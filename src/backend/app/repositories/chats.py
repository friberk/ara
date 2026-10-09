from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, true

from app.models.memory import ChatMemory
from app.models.research import ChatMessage, ChatSession, Paper
from app.schemas.ai import Chat, ChatSummary
from app.schemas.usage import ChatCost
from app.services.costs import Spend, message_spend

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


def dollars(amount) -> str:
    return format(amount.quantize(Decimal("0.00000001")), "f")


async def chat_spend(session, chat_id: UUID) -> tuple[ChatCost, int | None]:
    """What the chat has cost so far, and the tokens its latest completed answer sent."""
    messages = await session.execute(
        select(
            ChatMessage.state,
            ChatMessage.model,
            ChatMessage.usage,
            ChatMessage.retrieval["billed"],
            ChatMessage.context["input_tokens"],
        )
        .where(ChatMessage.session_id == chat_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    spend, sent = Spend(), None
    for state, model, usage, billed, input_tokens in messages:
        message_spend(spend, state, model, usage, billed)
        if state == "completed":
            sent = input_tokens if isinstance(input_tokens, int) else None
    for memory in await session.execute(
        select(ChatMemory.model, ChatMemory.usage).where(ChatMemory.session_id == chat_id)
    ):
        spend.chat_call("compaction", memory.model, memory.usage)
    cost = ChatCost(
        total=dollars(spend.total),
        answers=dollars(spend.answers),
        planning=dollars(spend.planning),
        compaction=dollars(spend.compaction),
        embeddings=dollars(spend.embeddings),
        reranking=dollars(spend.reranking),
        local=spend.local and not spend.hosted,
        unrecorded_turns=spend.unrecorded_turns,
    )
    return cost, sent
