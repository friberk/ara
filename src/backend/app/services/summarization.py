"""Full-document summaries with durable paid-call checkpoints and fenced final writes."""

from uuid import UUID, uuid4

from sqlalchemy import select, update

from app.integrations.llm import (
    INPUT_LIMIT,
    HostedLLM,
    LLMError,
    ensure_configured,
    estimate_tokens,
    reserve,
    validate_selection,
)
from app.models.jobs import BackgroundJob
from app.repositories.jobs import fence, now
from app.services.retrieval import INSTRUCTIONS, passage, validate_citations


def supported_citations(content, chunks, document_id):
    try:
        return validate_citations(content, chunks, document_id)
    except ValueError:
        raise LLMError(
            "UNGROUNDED_OUTPUT", "The summary cited unavailable source evidence."
        ) from None


def batches(chunks, budget=24000):
    groups, current, used = [], [], 0
    for chunk in chunks:
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
        ensure_configured(resources.settings)
        model, effort = payload["model"], payload["reasoning_effort"]
        validate_selection(model, effort)
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
        groups = batches(chunks)
        partials = list(payload.get("partials", []))
        client = HostedLLM(resources.settings)
        total_usage = dict(payload.get("usage", {}))

        async def generate(prompt, stage, progress):
            nonlocal total_usage
            await reserve(resources, model, estimate_tokens(INSTRUCTIONS) + estimate_tokens(prompt))
            payload["paid_call_inflight"] = True
            await checkpoint(resources, job_id, generation, lease_token, payload, stage, progress)
            async with resources.llm_slots:
                result = await client.complete(model, effort, INSTRUCTIONS, prompt)
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                total_usage[key] = total_usage.get(key, 0) + result.usage.get(key, 0)
            payload["usage"] = total_usage
            payload["paid_call_inflight"] = False
            return result.content

        for index, group in enumerate(groups):
            if index < len(partials):
                continue
            prompt = (
                "Summarize the supplied paper passages, including objectives, methods, "
                "results, limitations, and conclusions when present. Retain source markers.\n\n"
                + "\n".join(passage(chunk) for chunk in group)
            )
            content = await generate(prompt, "summarizing", int(80 * index / len(groups)))
            if not supported_citations(content, group, document_id):
                raise LLMError("UNGROUNDED_OUTPUT", "The summary did not cite its source evidence.")
            partials.append(content)
            payload["partials"] = partials
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
        while len(reduced) > 1:
            new, batch, used = [], [], 0
            reduction_groups = []
            for item in reduced:
                cost = estimate_tokens(item) + 2
                if batch and used + cost > 23000:
                    reduction_groups.append(batch)
                    batch, used = [], 0
                batch.append(item)
                used += cost
            if batch:
                reduction_groups.append(batch)
            if len(reduction_groups) >= len(reduced):
                raise LLMError(
                    "CONTEXT_LIMIT", "Summary sections cannot fit the reduction budget.", 413
                )
            for group in reduction_groups:
                prompt = (
                    "Combine every section below into one coherent summary of the complete "
                    "paper. Cover its objective, methods, findings and limitations. Preserve "
                    "supported source markers; omit unsupported claims.\n\n" + "\n\n".join(group)
                )
                assert estimate_tokens(prompt) + estimate_tokens(INSTRUCTIONS) < INPUT_LIMIT
                new.append(await generate(prompt, "combining", 90))
            reduced = new
            payload["reduced"] = reduced
            await checkpoint(resources, job_id, generation, lease_token, payload, "combining", 95)
        content = reduced[0]
        citations = supported_citations(content, chunks, document_id)
        if not citations:
            raise LLMError("UNGROUNDED_OUTPUT", "The summary did not cite its source evidence.")
        summary_id = uuid4()
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
                    configuration={
                        "prompt_version": "1",
                        "input_limit": INPUT_LIMIT,
                        "output_limit": 4000,
                        "covered_chunks": len(chunks),
                    },
                    usage=total_usage,
                )
            )
            job.state, job.stage, job.progress = "completed", "completed", 100
            job.result = {"summary_id": str(summary_id)}
            job.lease_token, job.lease_expires_at = None, None
            job.error_code, job.error_message = None, None
            job.updated_at = now()
    except Exception as exc:
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
