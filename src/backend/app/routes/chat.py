from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.errors import AppError
from app.integrations.llm import LLMError, validate_selection
from app.models.research import ChatMessage, ChatSession, Document, Paper
from app.schemas.ai import Chat, ChatCreate, ChatInput, ChatPage, Message, MessagePage
from app.services.chat import expire, prepare, stream_answer

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/papers/{paper_id}/chats", response_model=Chat, status_code=201)
async def create_chat(paper_id: UUID, body: ChatCreate, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(404, "Paper not found")
        document = (
            await session.get(Document, paper.active_document_id)
            if paper.active_document_id
            else None
        )
        if document is None or document.status != "ready":
            raise HTTPException(409, "Upload and process a paper PDF before starting a chat")
        chat = ChatSession(paper_id=paper_id, document_id=document.id, title=body.title)
        session.add(chat)
        await session.flush()
        return Chat.model_validate(chat)


@router.get("/papers/{paper_id}/chats", response_model=ChatPage)
async def list_chats(paper_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        if await session.get(Paper, paper_id) is None:
            raise HTTPException(404, "Paper not found")
        items = (
            await session.scalars(
                select(ChatSession)
                .where(ChatSession.paper_id == paper_id)
                .order_by(ChatSession.created_at.desc())
            )
        ).all()
        return ChatPage(items=[Chat.model_validate(item) for item in items])


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
        return MessagePage(items=[Message.model_validate(item) for item in items])


@router.post("/chats/{chat_id}/messages/stream", response_class=StreamingResponse)
async def answer(chat_id: UUID, body: ChatInput, request: Request):
    resources = request.app.state.resources
    try:
        validate_selection(body.model, body.reasoning_effort)
        assistant, prompt, chunks, replay = await prepare(resources, chat_id, body)
    except LLMError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None
    return StreamingResponse(
        stream_answer(resources, request, assistant, prompt, chunks, replay),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
