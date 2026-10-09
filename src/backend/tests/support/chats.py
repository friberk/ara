"""Chats with completed turns in a fixed order, for memory tests (ARA-077)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.models.research import ChatMessage, ChatSession
from tests.support.papers import seed_paper


@dataclass(frozen=True)
class Turn:
    question: UUID
    answer: UUID


async def seed_chat(resources, **paper_options) -> tuple[UUID, UUID, UUID]:
    paper_id, document_id = await seed_paper(resources, **paper_options)
    async with resources.sessions() as session, session.begin():
        chat = ChatSession(paper_id=paper_id, document_id=document_id, title="Discussion")
        session.add(chat)
        await session.flush()
        return paper_id, document_id, chat.id


async def add_turns(resources, chat_id: UUID, turns, *, model="gpt-5.6-luna") -> list[Turn]:
    """Append (question, answer[, citations]) turns one second apart, after any existing ones."""
    added = []
    async with resources.sessions() as session, session.begin():
        latest = await session.scalar(
            select(func.max(ChatMessage.created_at)).where(ChatMessage.session_id == chat_id)
        )
        clock = (latest or datetime.now(UTC)) + timedelta(seconds=1)
        for question, answer, *rest in turns:
            ids = []
            for role, content in (("user", question), ("assistant", answer)):
                message = ChatMessage(
                    id=uuid4(),
                    session_id=chat_id,
                    role=role,
                    content=content,
                    state="completed",
                    model=model if role == "assistant" else None,
                    reasoning_effort="low" if role == "assistant" else None,
                    citations=list(rest[0]) if rest and role == "assistant" else [],
                    request_id=uuid4(),
                    created_at=clock,
                )
                session.add(message)
                ids.append(message.id)
                clock += timedelta(seconds=1)
            added.append(Turn(*ids))
    return added


async def snapshot(resources, chat_id: UUID) -> list[tuple]:
    async with resources.sessions() as session:
        rows = await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return [(m.id, m.role, m.content, m.state, m.citations) for m in rows]
