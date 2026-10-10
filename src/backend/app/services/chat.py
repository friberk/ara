"""Persisted streaming chat. A request UUID records one attempt, including failures.

`prepare()` admits a question in short transactions with no network call under the chat lock.
`stream_answer()` then plans, retrieves and generates, persisting the retrieval trace before the
provider call (ARA-073). Answers carry the running summary, recalled turns and the unsummarized
recent turns, and a completed turn queues memory upkeep (ARA-077).
"""

import asyncio
import json
from contextlib import AsyncExitStack, nullcontext, suppress
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.integrations.context_registry import ContextProfile, context_profile
from app.integrations.llm import (
    LLMError,
    create_llm,
    generation_configuration,
    generation_slots,
    reserve,
    thinking_controls,
    validate_model_available,
)
from app.integrations.model_catalog import local_spec
from app.integrations.open_models import offered_reranker
from app.models.research import (
    ChatMessage,
    ChatSession,
    Document,
    ModelConfiguration,
    Paper,
    PaperAuthor,
)
from app.rag.citations import (
    HandleMap,
    HandleTransducer,
    normalize_source_markers,
    passage_citations,
)
from app.rag.indexing import effective_profile
from app.rag.pipeline import evidence_ceiling, retrieve_evidence
from app.repositories.jobs import now
from app.repositories.local_models import use_held
from app.schemas.ai import Message
from app.schemas.retrieval import RetrievalSettings
from app.services import memory
from app.services.context import (
    INSTRUCTIONS_VERSION,
    RECALL_SHARE,
    SUMMARY_SHARE,
    PaperHeader,
    assemble_answer_prompt,
)
from app.services.memory import AnswerMemory, QueryPlan

LEASE = timedelta(seconds=60)
# Background local work (a conversation or paper summary) may hold the local runtime; a
# question waits this long for it, polling the slot's lease, then fails busy as before.
LOCAL_ADMISSION_WAIT_SECONDS = 60
ADMISSION_POLL_SECONDS = 1


# Clause punctuation only: closing brackets, quotes and percent signs carry meaning.
TITLE_TRAILING = " .,;:!?…-–—。，；：！？、"


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def title_from_question(text: str, limit: int = 60) -> str:
    """Deterministic chat title: collapsed whitespace, word-boundary cut, "…" if shortened."""
    collapsed = " ".join(text.split())
    shortened = len(collapsed) > limit
    cut = collapsed
    if shortened:
        cut = collapsed[: limit - 1]
        if collapsed[limit - 1] != " " and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
    title = cut.rstrip(TITLE_TRAILING) or cut
    return title + "…" if shortened else title


async def expire(session, chat_id):
    await session.execute(
        update(ChatMessage)
        .where(
            ChatMessage.session_id == chat_id,
            ChatMessage.role == "assistant",
            ChatMessage.state == "processing",
            ChatMessage.lease_expires_at <= func.now(),
        )
        .values(state="interrupted", lease_expires_at=None)
    )


async def replayed(session, chat_id: UUID, body) -> tuple[ChatSession, ChatMessage | None]:
    """Lock the chat; return the stored answer when this request UUID was already used."""
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == chat_id).with_for_update()
    )
    if chat is None:
        raise HTTPException(404, "Chat not found")
    await expire(session, chat_id)
    replay = await session.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == chat_id,
            ChatMessage.role == "assistant",
            ChatMessage.request_id == body.request_id,
        )
    )
    if replay is None:
        return chat, None
    user = await session.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == chat_id,
            ChatMessage.role == "user",
            ChatMessage.request_id == body.request_id,
        )
    )
    if (
        user is None
        or user.content != body.content
        or replay.model != body.model
        or replay.reasoning_effort != body.reasoning_effort
    ):
        raise HTTPException(409, "Request UUID was already used for a different message")
    if replay.state == "processing":
        raise HTTPException(409, "This request is already processing")
    return chat, replay


async def paper_header(session, paper: Paper) -> PaperHeader:
    authors = await session.scalars(
        select(PaperAuthor.name)
        .where(PaperAuthor.paper_id == paper.id)
        .order_by(PaperAuthor.ordinal)
    )
    return PaperHeader(title=paper.title, authors=list(authors), year=paper.year)


@dataclass
class Prepared:
    """An admitted question, or the stored answer when its request UUID is replayed."""

    assistant: ChatMessage
    replay: bool
    question: str = ""
    document_id: UUID | None = None
    chunk_set: str | None = None
    retrieval_profile: str | None = None
    reranker: str | None = None
    paper: PaperHeader | None = None
    history: list[ChatMessage] = field(default_factory=list)
    limits: ContextProfile | None = None
    evidence_budget: int = 0


async def prepare(resources, chat_id: UUID, body) -> Prepared:
    async with resources.sessions() as session, session.begin():
        _, replay = await replayed(session, chat_id, body)
    if replay is not None:
        return Prepared(replay, replay=True)
    # Local validation calls the runtime, so it never runs while the chat row is locked.
    selection = await validate_model_available(resources, body.model, body.reasoning_effort)
    configuration = await generation_configuration(resources, body.model, body.reasoning_effort)
    limits = context_profile(
        resources, body.model, body.reasoning_effort, thinking=thinking_controls(selection)
    )
    async with resources.sessions() as session, session.begin():
        chat, replay = await replayed(session, chat_id, body)
        if replay is not None:  # A concurrent duplicate committed first.
            return Prepared(replay, replay=True)
        if await session.scalar(
            select(ChatMessage.id).where(
                ChatMessage.session_id == chat_id, ChatMessage.state == "processing"
            )
        ):
            raise HTTPException(409, "Another answer is already processing in this chat")
        document = await session.get(Document, chat.document_id)
        if document is None or document.status != "ready" or document.chunk_set is None:
            raise HTTPException(
                409,
                "This paper is being prepared for the new search. Try again in a minute."
                if document is not None and document.status == "ready"
                else "The selected document is not ready",
            )
        history = list(
            (
                await session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == chat_id)
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                )
            ).all()
        )
        paper = await session.get(Paper, chat.paper_id)
        header = await paper_header(session, paper)
        profile, _ = await effective_profile(session, paper)
        stored = await session.get(ModelConfiguration, "retrieval")
        reranker = RetrievalSettings.from_stored(stored.value if stored else None).reranker
        reranker = offered_reranker(resources.settings, reranker)
        # Sizing without evidence raises CONTEXT_LIMIT (413) before anything is stored.
        sizing = assemble_answer_prompt(
            profile=limits,
            paper=header,
            history=history,
            memory_summary=None,
            recalled=[],
            evidence_block=lambda budget: "",
            question=body.content,
            retrieved_for=None,
        )
        ceiling = await evidence_ceiling(session, document.id, document.chunk_set, limits.counter)
        await reserve(resources, body.model, prompt_bound(limits, sizing, ceiling, body.content))
        await memory.defer_compaction(session, chat_id)
        user = ChatMessage(
            id=uuid4(),
            session_id=chat_id,
            role="user",
            content=body.content,
            state="completed",
            model=None,
            reasoning_effort=None,
            citations=[],
            request_id=body.request_id,
            created_at=now(),
        )
        assistant = ChatMessage(
            id=uuid4(),
            session_id=chat_id,
            role="assistant",
            content="",
            state="processing",
            model=body.model,
            reasoning_effort=body.reasoning_effort,
            citations=[],
            request_id=body.request_id,
            lease_expires_at=now() + LEASE,
            configuration={**configuration, "prompt_version": INSTRUCTIONS_VERSION},
            created_at=now(),
        )
        if chat.title_source == "default":
            # Same transaction as the user message; replays returned above never retitle.
            first = next((m.content for m in history if m.role == "user"), body.content)
            chat.title, chat.title_source = title_from_question(first), "auto"
        session.add_all([user, assistant])
        await session.flush()
        return Prepared(
            assistant,
            replay=False,
            question=body.content,
            document_id=chat.document_id,
            chunk_set=document.chunk_set,
            retrieval_profile=profile,
            reranker=reranker,
            paper=header,
            history=history,
            limits=limits,
            evidence_budget=sizing.allocation.evidence,
        )


def prompt_bound(limits: ContextProfile, sizing, evidence_ceiling: int, question: str) -> int:
    """Input tokens this answer can actually send, for the daily ledger.

    The prompt sized without evidence, plus the summary and recall shares that memory may still
    fill, the evidence packing can choose, and a label for a rewritten question of similar length.
    """
    shares = sizing.allocation
    available = shares.evidence + shares.summary + shares.recent + shares.recall
    remembered = available * (SUMMARY_SHARE + RECALL_SHARE) // 100
    rewritten = limits.counter.count(f' (retrieved for: "{question}")')
    evidence = min(shares.evidence, evidence_ceiling)
    bound = sizing.usage.input_tokens + remembered + evidence + rewritten
    return min(bound, limits.input_budget)


async def plan_for_answer(resources, prepared: Prepared, remembered: AnswerMemory) -> QueryPlan:
    """Standalone search queries for a follow-up; a local chat plans under its own admission."""
    return await memory.plan_query(
        resources,
        model=prepared.assistant.model,
        effort=prepared.assistant.reasoning_effort,
        history=remembered.history,
        memory_summary=remembered.summary[1] if remembered.summary else None,
        question=prepared.question,
    )


async def recalled_turns(resources, prepared: Prepared, remembered: AnswerMemory, plan, evidence):
    """Earlier turns similar to the first search query, outside the recent window."""
    if not evidence.vectors:
        return []
    window = assemble_answer_prompt(
        profile=prepared.limits,
        paper=prepared.paper,
        history=remembered.history,
        memory_summary=remembered.summary,
        recalled=[],
        evidence_block=lambda budget: "",
        question=prepared.question,
        retrieved_for=plan.standalone_question,
    )
    return await memory.recall_turns(
        resources,
        chat_id=prepared.assistant.session_id,
        profile=evidence.summary.profile,
        query_vector=evidence.vectors[0],
        exclude_ids=memory.recent_answer_ids(remembered.history, window.usage.recent_turns),
    )


async def leased(session, message_id) -> ChatMessage:
    message = await session.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == message_id, ChatMessage.state == "processing")
        .with_for_update()
    )
    if message is None or message.lease_expires_at is None or message.lease_expires_at <= now():
        raise LLMError("LEASE_LOST", "The answer was interrupted because its lease expired.")
    return message


async def save(
    resources,
    message_id,
    content,
    *,
    state="processing",
    citations=None,
    usage=None,
    grounding=None,
):
    async with resources.sessions() as session, session.begin():
        message = await leased(session, message_id)
        message.content, message.state = content, state
        message.lease_expires_at = now() + LEASE if state == "processing" else None
        if citations is not None:
            message.citations = [item.model_dump(mode="json") for item in citations]
        if usage is not None:
            message.usage = usage
        if grounding is not None:
            message.grounding = grounding
        await session.flush()
        return Message.model_validate(message).model_dump(mode="json")


async def record_evidence(resources, message_id, evidence, usage, planner=None) -> None:
    """How the evidence was found, stored before any provider call.

    `billed` keeps the tokens of the calls made for this answer besides the answer itself, which
    the chat's cost meter prices."""
    async with resources.sessions() as session, session.begin():
        message = await leased(session, message_id)
        billed = {**evidence.trace.get("billed", {}), **({"planner": planner} if planner else {})}
        message.retrieval = {
            **evidence.summary.model_dump(mode="json"),
            "trace": evidence.trace,
            "billed": billed,
        }
        message.context = usage.model_dump(mode="json")
        message.lease_expires_at = now() + LEASE


def grounded(content: str, transducer: HandleTransducer, passages, document_id: UUID):
    """Canonical content, its citations and grounding; unsupported citations fail."""
    try:
        if transducer.unknown:
            raise ValueError("The answer cited a handle that was not supplied.")
        content = normalize_source_markers(content)
        citations = passage_citations(content, passages, document_id)
    except ValueError:
        raise LLMError(
            "UNGROUNDED_OUTPUT", "The answer cited unavailable source evidence."
        ) from None
    if not citations and not transducer.insufficient:
        raise LLMError("UNGROUNDED_OUTPUT", "The answer did not cite the supplied paper evidence.")
    return content, citations, "insufficient" if transducer.insufficient else "supported"


async def held_by_background(resources) -> bool:
    """Whether background work, not another local answer, holds the local generation slot."""
    async with resources.sessions() as session:
        answering = await session.scalars(
            select(ChatMessage.model).where(
                ChatMessage.role == "assistant",
                ChatMessage.state == "processing",
                ChatMessage.lease_expires_at > func.now(),
            )
        )
        if any(local_spec(model or "") for model in answering):
            return False
    return await use_held(resources.sessions)


async def admit_after_wait(resources, model: str, slots: AsyncExitStack, on_wait) -> None:
    """Enter the local generation slot into `slots`, waiting out background work.

    `on_wait` runs once, before the first wait. A wait that expires raises the busy error.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LOCAL_ADMISSION_WAIT_SECONDS
    waiting = False
    while True:
        try:
            await slots.enter_async_context(generation_slots(resources, model))
            return
        except LLMError as exc:
            if exc.code != "LOCAL_MODEL_BUSY" or loop.time() >= deadline:
                raise
        if not waiting:
            waiting = True
            await on_wait()
        # Admission checks the runtime too; only a free lease is worth another attempt.
        while loop.time() < deadline:
            await asyncio.sleep(ADMISSION_POLL_SECONDS)
            if not await use_held(resources.sessions):
                break


async def stream_answer(
    resources, request, prepared: Prepared, *, inference_slot=None, wait_for_slot=False
):
    """`wait_for_slot`: background work held the local slot at admission; take it into
    `inference_slot` before planning, telling the reader it is waiting."""
    assistant = prepared.assistant
    if prepared.replay:
        yield event("message.started", {"message_id": str(assistant.id)})
        if assistant.state == "completed":
            yield event(
                "message.completed", Message.model_validate(assistant).model_dump(mode="json")
            )
        else:
            yield event(
                "message.failed",
                {
                    "code": "PREVIOUS_GENERATION_INTERRUPTED",
                    "message": (
                        "This request ended without a complete answer. "
                        "Use a new request to try again."
                    ),
                    "message_id": str(assistant.id),
                },
            )
        return
    content, completed, client, task = "", False, None, None
    evidence, transducer = None, None
    queue = asyncio.Queue(maxsize=32)
    last_checkpoint = asyncio.get_running_loop().time()

    async def produce():
        """Plan, retrieve and generate; the consumer turns stages and deltas into events."""
        nonlocal client, evidence
        try:
            if wait_for_slot:
                await admit_after_wait(
                    resources,
                    assistant.model,
                    inference_slot,
                    lambda: queue.put(("status", "waiting")),
                )
            await queue.put(("status", "planning"))
            remembered = await memory.answer_memory(
                resources, assistant.session_id, prepared.history
            )
            plan = await plan_for_answer(resources, prepared, remembered)
            await queue.put(("status", "retrieving"))
            evidence = await retrieve_evidence(
                resources,
                document_id=prepared.document_id,
                chunk_set=prepared.chunk_set,
                preferred_profile=prepared.retrieval_profile,
                queries=plan.search_queries,
                question=plan.standalone_question,
                budget=prepared.evidence_budget,
                counter=prepared.limits.counter,
                reranker=prepared.reranker,
                on_stage=lambda stage: queue.put(("status", stage)),
            )
            if plan.standalone_question != prepared.question:
                evidence.summary.standalone_query = plan.standalone_question
            assembled = assemble_answer_prompt(
                profile=prepared.limits,
                paper=prepared.paper,
                history=remembered.history,
                memory_summary=remembered.summary,
                recalled=await recalled_turns(resources, prepared, remembered, plan, evidence),
                evidence_block=evidence.block,
                question=prepared.question,
                retrieved_for=plan.standalone_question,
            )
            await record_evidence(resources, assistant.id, evidence, assembled.usage, plan.billed)
            await queue.put(("evidence", HandleMap(evidence.passages)))
            selection = await validate_model_available(
                resources, assistant.model, assistant.reasoning_effort
            )
            client = create_llm(resources, assistant.model, selection=selection)
            await queue.put(("status", "generating"))
            async with (
                nullcontext() if inference_slot else generation_slots(resources, assistant.model)
            ):
                async for delta in client.stream_messages(
                    assistant.model, assistant.reasoning_effort, assembled.messages
                ):
                    await queue.put(("delta", delta))
            await queue.put(("done", None))
        except Exception as exc:
            await queue.put(("error", exc))

    try:
        yield event("message.started", {"message_id": str(assistant.id)})
        task = asyncio.create_task(produce())
        while True:
            if await request.is_disconnected():
                return
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                if task.done():
                    # Only a lost runtime lease cancels the producer before it reports.
                    raise LLMError(
                        "LOCAL_MODEL_LEASE_LOST", "Local generation lost its runtime lease.", 409
                    ) from None
                await save(resources, assistant.id, content)
                last_checkpoint = asyncio.get_running_loop().time()
                yield ": heartbeat\n\n"
                continue
            if kind == "error":
                raise value
            if kind == "done":
                break
            if kind == "status":
                yield event("message.status", {"message_id": str(assistant.id), "stage": value})
                continue
            if kind == "evidence":
                transducer = HandleTransducer(value)
                continue
            text = transducer.feed(value)
            if not text:
                continue
            content += text
            # Bound database writes while the final/disconnect paths always flush partial text.
            if asyncio.get_running_loop().time() - last_checkpoint >= 1:
                await save(resources, assistant.id, content)
                last_checkpoint = asyncio.get_running_loop().time()
            yield event("message.delta", {"text": text})
        if tail := transducer.flush():
            content += tail
            yield event("message.delta", {"text": tail})
        content, citations, grounding = grounded(
            content, transducer, evidence.passages, prepared.document_id
        )
        final = await save(
            resources,
            assistant.id,
            content,
            state="completed",
            citations=citations,
            usage=client.usage,
            grounding=grounding,
        )
        completed = True
        await memory.remember_turn(
            resources,
            assistant.session_id,
            assistant.id,
            assistant.model,
            assistant.reasoning_effort,
        )
        yield event("message.completed", final)
    except Exception as exc:
        safe = (
            exc
            if isinstance(exc, LLMError)
            else LLMError("ANSWER_FAILED", "The answer could not be completed.")
        )
        with suppress(LLMError):
            await save(resources, assistant.id, content, state="failed")
        completed = True
        yield event(
            "message.failed",
            {"code": safe.code, "message": safe.message, "message_id": str(assistant.id)},
        )
    finally:
        # Starlette disconnects cancel an AnyIO scope repeatedly at every await. Shield
        # the whole shutdown, including provider close, before flushing the partial answer.
        with anyio.CancelScope(shield=True):
            if task is not None:
                task.cancel()
                with anyio.move_on_after(2), suppress(asyncio.CancelledError):
                    await task
            try:
                if client is not None:
                    with anyio.move_on_after(2), suppress(Exception):
                        await client.close()
                if inference_slot is not None:
                    with anyio.move_on_after(5), suppress(Exception):
                        await inference_slot.__aexit__(None, None, None)
            finally:
                if not completed:
                    with anyio.move_on_after(5), suppress(LLMError):
                        await save(resources, assistant.id, content, state="interrupted")
