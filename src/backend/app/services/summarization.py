"""Full-document summaries with durable paid-call checkpoints and fenced final writes."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select, update

from app.integrations.llm import (
    LLMError,
    create_llm,
    estimate_tokens,
    generation_configuration,
    generation_slots,
    model_limits,
    reserve,
    validate_model_available,
)
from app.models.jobs import BackgroundJob
from app.repositories.jobs import fence, now
from app.services.retrieval import (
    INSTRUCTIONS,
    normalize_source_markers,
    passage,
    validate_citations,
)


def supported_citations(content, chunks, document_id):
    try:
        return validate_citations(content, chunks, document_id)
    except ValueError:
        raise LLMError(
            "UNGROUNDED_OUTPUT", "The summary cited unavailable source evidence."
        ) from None


def canonical_summary_content(content, chunks, document_id):
    if not supported_citations(content, chunks, document_id):
        raise LLMError("UNGROUNDED_OUTPUT", "The summary did not cite its source evidence.")
    return normalize_source_markers(content)


PART_PREFIX = (
    "Summarize the supplied paper passages, including objectives, methods, "
    "results, limitations, and conclusions when present. Retain source markers.\n\n"
)
REDUCE_PREFIX = (
    "Combine every section below into one coherent summary of the complete "
    "paper. Cover its objective, methods, findings and limitations. Preserve "
    "supported source markers; omit unsupported claims.\n\n"
)


def batches(chunks, budget=24000, *, split_oversize=False):
    groups, current, used = [], [], 0
    pending = []
    for chunk in chunks:
        if split_oversize and estimate_tokens(passage(chunk)) > budget:
            header = SimpleNamespace(id=chunk.id, page=chunk.page, text="")
            capacity = budget - estimate_tokens(passage(header))
            if capacity < 4:
                raise LLMError("CONTEXT_LIMIT", "Source markers exceed the summary budget.", 413)
            remaining = chunk.text.encode("utf-8")
            while remaining:
                text = remaining[:capacity].decode("utf-8", errors="ignore")
                if not text:
                    raise LLMError(
                        "CONTEXT_LIMIT", "A source passage cannot fit the summary budget.", 413
                    )
                pending.append(
                    SimpleNamespace(
                        id=chunk.id, document_id=chunk.document_id, page=chunk.page, text=text
                    )
                )
                remaining = remaining[len(text.encode("utf-8")) :]
        else:
            pending.append(chunk)
    for chunk in pending:
        cost = estimate_tokens(passage(chunk))
        if cost > budget:
            raise LLMError("CONTEXT_LIMIT", "A source passage exceeds the summary budget.", 413)
        if current and used + cost > budget:
            groups.append(current)
            current, used = [], 0
        current.append(chunk)
        used += cost
    if current:
        groups.append(current)
    return groups


async def checkpoint(resources, job_id, generation, token, payload, stage, progress):
    async with resources.sessions() as session, session.begin():
        saved = await session.scalar(
            update(BackgroundJob)
            .where(*fence(job_id, generation, token))
            .values(payload=payload, stage=stage, progress=progress, updated_at=now())
            .returning(BackgroundJob.id)
        )
        if saved is None:
            raise LLMError("LEASE_LOST", "The summary worker lease expired.")


async def run_summary_job(resources, job_id, generation, lease_token, payload):
    from app.models.research import Document, DocumentChunk, PaperSummary

    client = None
    try:
        async with resources.sessions() as session:
            owned = await session.scalar(
                select(BackgroundJob).where(*fence(job_id, generation, lease_token))
            )
            if owned is None:
                return
            payload = dict(owned.payload)
        model, effort = payload["model"], payload["reasoning_effort"]
        selection = await validate_model_available(resources, model, effort)
        input_limit, _ = model_limits(resources, model)
        # An unknown paid outcome is never automatically resubmitted by job recovery.
        if payload.get("paid_call_inflight"):
            raise LLMError(
                "GENERATION_OUTCOME_UNKNOWN",
                "Previous inference was interrupted; start a new request.",
            )
        document_id = UUID(payload["document_id"])
        async with resources.sessions() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status != "ready":
                raise LLMError("DOCUMENT_NOT_READY", "The selected document is not ready.", 409)
            chunks = list(
                (
                    await session.scalars(
                        select(DocumentChunk)
                        .where(DocumentChunk.document_id == document_id)
                        .order_by(DocumentChunk.ordinal)
                    )
                ).all()
            )
        if not chunks:
            raise LLMError("NO_EVIDENCE", "The document has no extracted passages.", 409)
        local = selection.provider == "ollama"
        batch_budget = input_limit - estimate_tokens(INSTRUCTIONS + PART_PREFIX) if local else 24000
        groups = batches(chunks, budget=batch_budget, split_oversize=local)
        partials = list(payload.get("partials", []))
        if (partials or payload.get("reduced")) and not payload.get("_generation_configuration"):
            raise LLMError(
                "GENERATION_PROVENANCE_UNKNOWN",
                "Previous summary sections lack model provenance. Start a new summary request.",
            )
        # Only an owned processing job reaches this point. Reused completed
        # sections must satisfy the same source contract as new output before
        # entering another prompt or durable checkpoint.
        partials = [
            canonical_summary_content(
                content, groups[index] if index < len(groups) else chunks, document_id
            )
            for index, content in enumerate(partials)
        ]
        payload["partials"] = partials
        for key in ("reduced", "reduction_results"):
            if key in payload:
                payload[key] = [
                    canonical_summary_content(content, chunks, document_id)
                    for content in payload[key]
                ]
        if payload.get("compression"):
            payload["compression"] = {
                **payload["compression"],
                "candidate": canonical_summary_content(
                    payload["compression"]["candidate"], chunks, document_id
                ),
            }
        client = create_llm(resources, model, selection=selection)
        total_usage = dict(payload.get("usage", {}))

        async def generate(prompt, stage, progress, *, save_completed, max_output_tokens=None):
            nonlocal total_usage
            await reserve(resources, model, estimate_tokens(INSTRUCTIONS) + estimate_tokens(prompt))
            async with generation_slots(resources, model):
                configuration = await generation_configuration(resources, model, effort)
                previous = payload.get("_generation_configuration")
                if previous is not None and previous != configuration:
                    raise LLMError(
                        "MODEL_CONFIGURATION_CHANGED",
                        "Model settings changed during this summary. Start a new summary request.",
                    )
                # Capture under admission, before weights or runtime validation can change.
                # The same checkpoint as the in-flight flag makes this durable across retries.
                payload["_generation_configuration"] = configuration
                # This flag records an uncertain generation for either provider.
                payload["paid_call_inflight"] = True
                await checkpoint(
                    resources, job_id, generation, lease_token, payload, stage, progress
                )
                try:
                    options = {"max_output_tokens": max_output_tokens} if max_output_tokens else {}
                    result = await client.complete(model, effort, INSTRUCTIONS, prompt, **options)
                except LLMError as exc:
                    if exc.code == "LOCAL_MODEL_BUSY":
                        # An explicit admission rejection means no generation started.
                        payload["paid_call_inflight"] = False
                        await checkpoint(
                            resources, job_id, generation, lease_token, payload, stage, progress
                        )
                    raise
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    total_usage[key] = total_usage.get(key, 0) + result.usage.get(key, 0)
                payload["usage"] = total_usage
                content = canonical_summary_content(result.content, chunks, document_id)
                save_completed(content)
                payload["paid_call_inflight"] = False
                # Commit the completed result and cursor before releasing admission.
                await checkpoint(
                    resources, job_id, generation, lease_token, payload, stage, progress
                )
            return content

        for index, group in enumerate(groups):
            if index < len(partials):
                continue
            prompt = PART_PREFIX + "".join(passage(chunk) for chunk in group)

            def save_partial(content, group=group):
                if not supported_citations(content, group, document_id):
                    raise LLMError(
                        "UNGROUNDED_OUTPUT", "The summary did not cite its source evidence."
                    )
                partials.append(content)
                payload["partials"] = partials

            await generate(
                prompt, "summarizing", int(80 * index / len(groups)), save_completed=save_partial
            )
            await checkpoint(
                resources,
                job_id,
                generation,
                lease_token,
                payload,
                "summarizing",
                int(80 * (index + 1) / len(groups)),
            )
        # Recursive ordered reductions keep all sections represented under the application cap.
        reduced = list(payload.get("reduced", partials))
        reduction_budget = (
            input_limit - estimate_tokens(INSTRUCTIONS + REDUCE_PREFIX) if local else 23000
        )
        while len(reduced) > 1:
            payload["reduced"] = reduced
            new = list(payload.get("reduction_results", []))
            batch, used = [], 0
            reduction_groups = []
            for item in reduced:
                cost = estimate_tokens(item) + 2
                if batch and used + cost > reduction_budget:
                    reduction_groups.append(batch)
                    batch, used = [], 0
                batch.append(item)
                used += cost
            if batch:
                reduction_groups.append(batch)
            if len(reduction_groups) >= len(reduced):
                if not local:
                    raise LLMError(
                        "CONTEXT_LIMIT", "Summary sections cannot fit the reduction budget.", 413
                    )
                # Bound individual sections so a following round can combine at least two.
                byte_limit = (reduction_budget - 4) // 2
                for index, item in enumerate(reduced):
                    if estimate_tokens(item) <= byte_limit:
                        continue
                    state = payload.get("compression", {})
                    candidate = (
                        state.get("candidate", item) if state.get("index") == index else item
                    )
                    attempts = state.get("attempts", 0) if state.get("index") == index else 0
                    required = {c.chunk_id for c in supported_citations(item, chunks, document_id)}
                    while estimate_tokens(candidate) > byte_limit:
                        if attempts >= 3:
                            raise LLMError(
                                "SUMMARY_COMPRESSION_FAILED",
                                "The model could not fit these sections into the reduction budget.",
                            )
                        attempts += 1
                        allocation = min(
                            resources.settings.ollama_max_output_tokens,
                            max(1, byte_limit // (8 * attempts)),
                        )
                        prompt = (
                            f"Compress this complete section into at most "
                            f"{max(1, allocation // 4)} words and {byte_limit} UTF-8 bytes. "
                            "Retain every section's main "
                            "finding, methods, numbers and limitations. Preserve every source "
                            "marker verbatim. Do not add claims.\n\n" + candidate
                        )
                        if estimate_tokens(INSTRUCTIONS + prompt) > input_limit:
                            raise LLMError(
                                "SUMMARY_COMPRESSION_FAILED",
                                "A generated summary section exceeds the compression input budget.",
                            )

                        def save_compression(
                            content, index=index, attempts=attempts, required=required
                        ):
                            actual = {
                                c.chunk_id
                                for c in supported_citations(content, chunks, document_id)
                            }
                            if actual != required:
                                raise LLMError(
                                    "UNGROUNDED_OUTPUT",
                                    "Compression did not preserve the section's sources.",
                                )
                            payload["compression"] = {
                                "index": index,
                                "attempts": attempts,
                                "candidate": content,
                            }

                        await generate(
                            prompt,
                            "compressing",
                            90,
                            save_completed=save_compression,
                            max_output_tokens=allocation,
                        )
                        candidate = payload["compression"]["candidate"]
                    reduced[index] = candidate
                    payload["reduced"] = list(reduced)
                    payload.pop("compression", None)
                    await checkpoint(
                        resources, job_id, generation, lease_token, payload, "compressing", 90
                    )
                continue
            for index, group in enumerate(reduction_groups):
                if index < len(new):
                    continue
                prompt = REDUCE_PREFIX + "\n\n".join(group)
                if estimate_tokens(prompt) + estimate_tokens(INSTRUCTIONS) > input_limit:
                    raise LLMError(
                        "CONTEXT_LIMIT", "Summary sections exceed the reduction budget.", 413
                    )

                def save_reduction(content, new=new):
                    new.append(content)
                    payload["reduction_results"] = new

                await generate(prompt, "combining", 90, save_completed=save_reduction)
            reduced = new
            payload["reduced"] = reduced
            payload.pop("reduction_results", None)
            await checkpoint(resources, job_id, generation, lease_token, payload, "combining", 95)
        citations = supported_citations(reduced[0], chunks, document_id)
        content = normalize_source_markers(reduced[0])
        if not citations:
            raise LLMError("UNGROUNDED_OUTPUT", "The summary did not cite its source evidence.")
        summary_id = uuid4()
        configuration = dict(payload["_generation_configuration"])
        configuration["covered_chunks"] = len(chunks)
        async with resources.sessions() as session, session.begin():
            job = await session.scalar(
                select(BackgroundJob)
                .where(*fence(job_id, generation, lease_token))
                .with_for_update()
            )
            if job is None:
                return
            session.add(
                PaperSummary(
                    id=summary_id,
                    paper_id=UUID(payload["paper_id"]),
                    document_id=document_id,
                    model=model,
                    reasoning_effort=effort,
                    content=content,
                    citations=[c.model_dump(mode="json") for c in citations],
                    configuration=configuration,
                    usage=total_usage,
                )
            )
            job.state, job.stage, job.progress = "completed", "completed", 100
            job.result = {"summary_id": str(summary_id)}
            job.lease_token, job.lease_expires_at = None, None
            job.error_code, job.error_message = None, None
            job.updated_at = now()
    except Exception as exc:
        if isinstance(exc, LLMError) and exc.code == "LOCAL_MODEL_BUSY":
            raise
        safe = (
            exc
            if isinstance(exc, LLMError)
            else LLMError("SUMMARY_FAILED", "The summary could not be generated.")
        )
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(BackgroundJob)
                .where(*fence(job_id, generation, lease_token))
                .values(
                    state="failed",
                    stage="failed",
                    error_code=safe.code,
                    error_message=safe.message,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now(),
                )
            )
    finally:
        if client is not None:
            await client.close()
