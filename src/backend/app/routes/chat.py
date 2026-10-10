from contextlib import AsyncExitStack
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from starlette.background import BackgroundTask

from app.core.errors import AppError
from app.integrations import open_models
from app.integrations.context_registry import context_profile
from app.integrations.llm import (
    LLMError,
    generation_slots,
    thinking_controls,
    validate_selection,
)
from app.integrations.model_catalog import local_spec
from app.models.research import ChatMessage, ChatPaper, ChatSession, Paper
from app.repositories.chats import (
    chat_dto,
    chat_spend,
    chat_summaries,
    chat_view,
    included_papers,
    includes,
    with_cited_papers,
)
from app.schemas.ai import (
    Chat,
    ChatCreate,
    ChatInput,
    ChatPage,
    ChatPaperAdd,
    ChatRename,
    ChatSummary,
    ChatSummaryPage,
    Message,
    MessagePage,
)
from app.schemas.usage import ChatContext, ChatUsage
from app.services.chat import expire, held_by_background, prepare, stream_answer
from app.services.chat_papers import add_paper, create_chat, locked_chat, remove_paper
from app.services.local_models import list_local_models
from app.services.pdf_removal import delete_detached, lock_pdfs

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chats", response_model=Chat, status_code=201)
async def new_chat(body: ChatCreate, request: Request):
    """A chat over one or more ready library papers, each pinned to its active PDF."""
    async with request.app.state.resources.sessions() as session, session.begin():
        return await chat_view(session, await create_chat(session, body))


@router.post("/chats/{chat_id}/papers", response_model=Chat)
async def include_paper(chat_id: UUID, body: ChatPaperAdd, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        return await chat_view(session, await add_paper(session, chat_id, body.paper_id))


@router.delete("/chats/{chat_id}/papers/{paper_id}", response_model=Chat)
async def exclude_paper(chat_id: UUID, paper_id: UUID, request: Request):
    """The response's `paper_id` is the chat's first paper after the removal. A PDF the chat was
    the last to use, and that is not its paper's current PDF, goes with it (ARA-097)."""
    async with request.app.state.resources.sessions() as session, session.begin():
        pinned = (
            await session.scalars(
                select(ChatPaper.document_id).where(
                    ChatPaper.chat_id == chat_id, ChatPaper.paper_id == paper_id
                )
            )
        ).all()
        await lock_pdfs(session, pinned)
        chat = await remove_paper(session, chat_id, paper_id)
        await delete_detached(session, pinned)
        return await chat_view(session, chat)


@router.get("/papers/{paper_id}/chats", response_model=ChatPage)
async def list_chats(paper_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        if await session.get(Paper, paper_id) is None:
            raise HTTPException(404, "Paper not found")
        chats = (
            await session.scalars(
                select(ChatSession)
                .where(includes(paper_id))
                .order_by(ChatSession.created_at.desc())
            )
        ).all()
        papers = await included_papers(session, [chat.id for chat in chats])
        return ChatPage(items=[Chat(**chat_dto(chat, papers[chat.id])) for chat in chats])


@router.get("/chats", response_model=ChatSummaryPage)
async def recent_chats(
    request: Request,
    paper_id: UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    async with request.app.state.resources.sessions() as session:
        items = await chat_summaries(session, paper_id=paper_id, limit=limit, offset=offset)
        return ChatSummaryPage(items=items)


@router.get("/chats/{chat_id}", response_model=ChatSummary)
async def read_chat(chat_id: UUID, request: Request):
    """One chat with its papers; its URL is /papers/{paper_id}/chats/{id}."""
    async with request.app.state.resources.sessions() as session:
        found = await chat_summaries(session, paper_id=None, chat_id=chat_id, limit=1, offset=0)
    if not found:
        raise AppError(404, "CHAT_NOT_FOUND", "Chat not found.")
    return found[0]


@router.patch("/chats/{chat_id}", response_model=Chat)
async def rename_chat(chat_id: UUID, body: ChatRename, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        chat = await locked_chat(session, chat_id)
        chat.title, chat.title_source = body.title, "manual"
        await session.flush()
        return await chat_view(session, chat)


@router.delete("/chats/{chat_id}", status_code=204, response_class=Response)
async def delete_chat(chat_id: UUID, request: Request):
    """PDFs this chat was the last to use, and that are not their paper's current PDF, go with
    it (ARA-097)."""
    async with request.app.state.resources.sessions() as session, session.begin():
        pinned = (
            await session.scalars(select(ChatPaper.document_id).where(ChatPaper.chat_id == chat_id))
        ).all()
        await lock_pdfs(session, pinned)
        chat = await locked_chat(session, chat_id)
        await expire(session, chat_id)
        if await session.scalar(
            select(ChatMessage.id).where(
                ChatMessage.session_id == chat_id,
                ChatMessage.role == "assistant",
                ChatMessage.state == "processing",
            )
        ):
            raise AppError(
                409, "CHAT_BUSY", "Wait for the current answer to finish before deleting."
            )
        # Messages go with the chat through the session_id ON DELETE CASCADE foreign key.
        await session.delete(chat)
        await delete_detached(session, pinned)
    return Response(status_code=204)


@router.get("/chats/{chat_id}/messages", response_model=MessagePage)
async def list_messages(chat_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        if (
            await session.scalar(
                select(ChatSession).where(ChatSession.id == chat_id).with_for_update()
            )
            is None
        ):
            raise HTTPException(404, "Chat not found")
        await expire(session, chat_id)
        items = (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
        messages = [Message.model_validate(item) for item in items]
        return MessagePage(items=await with_cited_papers(session, messages))


@router.get("/chats/{chat_id}/usage", response_model=ChatUsage)
async def chat_usage(chat_id: UUID, model: str, reasoning_effort: str, request: Request):
    """Context used by the latest answer against the selected model's input budget, and spend.

    The budget is computed for `model` and `reasoning_effort` exactly as an answer sizes its
    prompt, so the meter follows the composer's selection; no runtime call is made.
    """
    resources = request.app.state.resources
    try:
        selection = validate_selection(model, reasoning_effort)
    except LLMError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None
    if open_models.open_chat_model(resources.settings, model):
        raise open_models.disabled()
    if local_spec(model):
        selection = next(
            item
            for item in await list_local_models(resources, inspect_runtime=False)
            if item.key == model
        )
    profile = context_profile(
        resources, model, reasoning_effort, thinking=thinking_controls(selection)
    )
    async with resources.sessions() as session:
        if await session.get(ChatSession, chat_id) is None:
            raise AppError(404, "CHAT_NOT_FOUND", "Chat not found.")
        cost, used = await chat_spend(session, chat_id)
    return ChatUsage(
        context=ChatContext(
            used_tokens=used,
            input_budget=profile.input_budget,
            window=profile.window,
            model=model,
        ),
        cost=cost,
    )


@router.post("/chats/{chat_id}/messages/stream", response_class=StreamingResponse)
async def answer(chat_id: UUID, body: ChatInput, request: Request):
    resources = request.app.state.resources
    slots = AsyncExitStack()
    wait_for_slot = False
    try:
        validate_selection(body.model, body.reasoning_effort)
        # With open models off, a local model is refused below unless this is a replay (ARA-090).
        if local_spec(body.model) and open_models.enabled(resources.settings):
            async with resources.sessions() as session:
                replay_id = await session.scalar(
                    select(ChatMessage.id).where(
                        ChatMessage.session_id == chat_id,
                        ChatMessage.role == "assistant",
                        ChatMessage.request_id == body.request_id,
                    )
                )
            if replay_id is None:
                # Admission happens before returning HTTP headers; busy is actionable 429.
                # Background work, which the reader cannot see, is waited out in the stream.
                try:
                    await slots.enter_async_context(generation_slots(resources, body.model))
                except LLMError as exc:
                    if exc.code != "LOCAL_MODEL_BUSY" or not await held_by_background(resources):
                        raise
                    wait_for_slot = True
        prepared = await prepare(resources, chat_id, body)
    except LLMError as exc:
        await slots.aclose()
        raise AppError(exc.status, exc.code, exc.message) from None
    except BaseException:
        await slots.aclose()
        raise
    return StreamingResponse(
        stream_answer(
            resources,
            request,
            prepared,
            inference_slot=slots if local_spec(body.model) and not prepared.replay else None,
            wait_for_slot=wait_for_slot and not prepared.replay,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(slots.aclose),
    )
