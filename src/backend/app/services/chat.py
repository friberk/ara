"""Persisted streaming chat. A request UUID records one attempt, including failures."""

import asyncio
import json
from contextlib import nullcontext, suppress
from datetime import timedelta
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException
from sqlalchemy import func, select, update

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
from app.models.research import ChatMessage, ChatSession, Document
from app.repositories.jobs import now
from app.schemas.ai import Message
from app.services.retrieval import (
    INSTRUCTIONS,
    history_context,
    passage,
    retrieve,
    validate_citations,
)

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


async def prepare(resources, chat_id: UUID, body):
    async with resources.sessions() as session, session.begin():
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
        if replay is not None:
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
            return replay, None, [], True
        if await session.scalar(
            select(ChatMessage.id).where(
                ChatMessage.session_id == chat_id, ChatMessage.state == "processing"
            )
        ):
            raise HTTPException(409, "Another answer is already processing in this chat")
        await validate_model_available(resources, body.model, body.reasoning_effort)
        document = await session.get(Document, chat.document_id)
        if document is None or document.status != "ready":
            raise HTTPException(409, "The selected document is not ready")
        messages = list(
            (
                await session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == chat_id)
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                )
            ).all()
        )
        input_limit, _ = model_limits(resources, body.model)
        question = "\nCurrent question:\n" + body.content
        history_budget = 4000
        if input_limit < 32000:
            history_budget = min(
                4000, max(0, (input_limit - estimate_tokens(INSTRUCTIONS + question) - 64) // 3)
            )
        history = history_context(messages, budget=history_budget)
        base = "Conversation (context only):\n" + history + "\nPaper evidence:\n"
        safety = 512 if input_limit == 32000 else 0
        budget = input_limit - estimate_tokens(INSTRUCTIONS + base + question) - safety
        if budget < 0:
            raise LLMError("CONTEXT_LIMIT", "The question exceeds the context budget.", 413)
        chunks = await retrieve(
            session, chat.document_id, body.content, messages, budget=min(12000, budget)
        )
        # passage() already terminates each source with a newline counted by retrieval.
        prompt = base + "".join(passage(c) for c in chunks) + question
        if estimate_tokens(INSTRUCTIONS + prompt) > input_limit:
            raise LLMError(
                "CONTEXT_LIMIT", "The assembled question exceeds the context budget.", 413
            )
        await reserve(
            resources, body.model, estimate_tokens(prompt) + estimate_tokens(INSTRUCTIONS)
        )
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
            lease_expires_at=now() + timedelta(seconds=60),
            configuration=await generation_configuration(
                resources, body.model, body.reasoning_effort
            ),
            created_at=now(),
        )
        if chat.title_source == "default":
            # Same transaction as the user message; replays returned above never retitle.
            first = next((m.content for m in messages if m.role == "user"), body.content)
            chat.title, chat.title_source = title_from_question(first), "auto"
        session.add_all([user, assistant])
        await session.flush()
        return assistant, prompt, chunks, False


async def save(resources, message_id, content, *, state="processing", citations=None, usage=None):
    async with resources.sessions() as session, session.begin():
        message = await session.scalar(
            select(ChatMessage)
            .where(ChatMessage.id == message_id, ChatMessage.state == "processing")
            .with_for_update()
        )
        if message is None or message.lease_expires_at is None or message.lease_expires_at <= now():
            raise LLMError("LEASE_LOST", "The answer was interrupted because its lease expired.")
        message.content, message.state = content, state
        message.lease_expires_at = now() + timedelta(seconds=60) if state == "processing" else None
        if citations is not None:
            message.citations = [item.model_dump(mode="json") for item in citations]
        if usage is not None:
            message.usage = usage
        await session.flush()
        return Message.model_validate(message).model_dump(mode="json")


async def stream_answer(
    resources, request, assistant, prompt, chunks, replay=False, *, inference_slot=None
):
    if replay:
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
    queue = asyncio.Queue(maxsize=32)
    last_checkpoint = asyncio.get_running_loop().time()

    async def pump():
        try:
            async with (
                nullcontext() if inference_slot else generation_slots(resources, assistant.model)
            ):
                async for delta in client.stream(
                    assistant.model, assistant.reasoning_effort, INSTRUCTIONS, prompt
                ):
                    await queue.put(("delta", delta))
            await queue.put(("done", None))
        except Exception as exc:
            await queue.put(("error", exc))

    try:
        yield event("message.started", {"message_id": str(assistant.id)})
        selection = await validate_model_available(
            resources, assistant.model, assistant.reasoning_effort
        )
        client = create_llm(resources, assistant.model, selection=selection)
        task = asyncio.create_task(pump())
        while True:
            if await request.is_disconnected():
                return
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                await save(resources, assistant.id, content)
                last_checkpoint = asyncio.get_running_loop().time()
                yield ": heartbeat\n\n"
                continue
            if kind == "error":
                raise value
            if kind == "done":
                break
            content += value
            # Bound database writes while the final/disconnect paths always flush partial text.
            if asyncio.get_running_loop().time() - last_checkpoint >= 1:
                await save(resources, assistant.id, content)
                last_checkpoint = asyncio.get_running_loop().time()
            yield event("message.delta", {"text": value})
        try:
            citations = validate_citations(
                content, chunks, chunks[0].document_id if chunks else UUID(int=0)
            )
        except ValueError:
            raise LLMError(
                "UNGROUNDED_OUTPUT", "The answer cited unavailable source evidence."
            ) from None
        if not citations and "insufficient" not in content.lower():
            raise LLMError(
                "UNGROUNDED_OUTPUT", "The answer did not cite the supplied paper evidence."
            )
        final = await save(
            resources,
            assistant.id,
            content,
            state="completed",
            citations=citations,
            usage=client.usage,
        )
        completed = True
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
