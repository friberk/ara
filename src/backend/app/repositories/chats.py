from uuid import UUID

from sqlalchemy import func, select, true

from app.models.research import ChatMessage, ChatSession, Paper
from app.schemas.ai import Chat, ChatSummary

PREVIEW_LIMIT = 140


def preview(text: str | None, limit: int = PREVIEW_LIMIT) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


async def chat_summaries(
    session, *, paper_id: UUID | None, limit: int, offset: int
) -> list[ChatSummary]:
    """One query; per-chat activity and the latest question both use the activity index."""
    stats = (
        select(
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .where(ChatMessage.session_id == ChatSession.id)
        .lateral("stats")
    )
    latest_question = (
        select(
            func.left(func.regexp_replace(ChatMessage.content, r"\s+", " ", "g"), PREVIEW_LIMIT + 1)
        )
        .where(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    activity = func.coalesce(stats.c.last_message_at, ChatSession.created_at).label(
        "last_activity_at"
    )
    statement = (
        select(ChatSession, Paper.title, stats.c.message_count, activity, latest_question)
        .join(Paper, Paper.id == ChatSession.paper_id)
        .join(stats, true())
        .order_by(activity.desc(), ChatSession.id)
        .limit(limit)
        .offset(offset)
    )
    if paper_id is not None:
        statement = statement.where(ChatSession.paper_id == paper_id)
    rows = (await session.execute(statement)).all()
    return [
        ChatSummary(
            **Chat.model_validate(chat).model_dump(),
            paper_title=paper_title,
            last_activity_at=last_activity_at,
            message_count=message_count,
            last_question_preview=preview(question),
        )
        for chat, paper_title, message_count, last_activity_at, question in rows
    ]
