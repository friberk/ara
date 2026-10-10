from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import exists, func, select, true

from app.models.memory import ChatMemory
from app.models.research import ChatMessage, ChatPaper, ChatSession, Document, Paper, PaperAuthor
from app.schemas.ai import Chat, ChatSummary, IncludedPaper, Message
from app.schemas.usage import ChatCost
from app.services.costs import Spend, message_spend

PREVIEW_LIMIT = 140


def preview(text: str | None, limit: int = PREVIEW_LIMIT) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


async def included_papers(session, chat_ids: Sequence[UUID]) -> dict[UUID, list[IncludedPaper]]:
    """Each chat's papers by ordinal, with what a chip needs to name them (ARA-088) and whether
    the pinned PDF was removed (ARA-097)."""
    first_author = (
        select(PaperAuthor.name)
        .where(PaperAuthor.paper_id == Paper.id)
        .order_by(PaperAuthor.ordinal)
        .limit(1)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(ChatPaper, Paper.title, Paper.year, first_author, Document.removed)
        .join(Paper, Paper.id == ChatPaper.paper_id)
        .join(Document, Document.id == ChatPaper.document_id)
        .where(ChatPaper.chat_id.in_(list(chat_ids)))
        .order_by(ChatPaper.chat_id, ChatPaper.ordinal)
    )
    found: dict[UUID, list[IncludedPaper]] = {chat_id: [] for chat_id in chat_ids}
    for link, title, year, author, removed in rows:
        found[link.chat_id].append(
            IncludedPaper(
                paper_id=link.paper_id,
                document_id=link.document_id,
                title=title,
                first_author=author,
                year=year,
                added_at=link.added_at,
                pdf_removed=removed,
            )
        )
    return found


def chat_dto(chat: ChatSession, papers: list[IncludedPaper]) -> dict:
    return {
        "id": chat.id,
        "paper_id": papers[0].paper_id,
        "papers": papers,
        "title": chat.title,
        "title_source": chat.title_source,
        "created_at": chat.created_at,
    }


async def chat_view(session, chat: ChatSession) -> Chat:
    return Chat(**chat_dto(chat, (await included_papers(session, [chat.id]))[chat.id]))


def includes(paper_id: UUID):
    """Chats that cover the paper."""
    return exists().where(ChatPaper.chat_id == ChatSession.id, ChatPaper.paper_id == paper_id)


async def with_cited_papers(session, messages: list[Message]) -> list[Message]:
    """Name the paper of every cited PDF, including papers since removed from the chat."""
    documents = {citation.document_id for message in messages for citation in message.citations}
    if not documents:
        return messages
    owners = dict(
        (
            await session.execute(
                select(Document.id, Document.paper_id).where(Document.id.in_(documents))
            )
        ).all()
    )
    for message in messages:
        for citation in message.citations:
            citation.paper_id = owners.get(citation.document_id)
    return messages


async def chat_summaries(
    session, *, paper_id: UUID | None, limit: int, offset: int, chat_id: UUID | None = None
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
        select(ChatSession, stats.c.message_count, activity, latest_question)
        .join(stats, true())
        .order_by(activity.desc(), ChatSession.id)
        .limit(limit)
        .offset(offset)
    )
    if paper_id is not None:
        statement = statement.where(includes(paper_id))
    if chat_id is not None:
        statement = statement.where(ChatSession.id == chat_id)
    rows = (await session.execute(statement)).all()
    papers = await included_papers(session, [chat.id for chat, *_ in rows])
    return [
        ChatSummary(
            **chat_dto(chat, papers[chat.id]),
            last_activity_at=last_activity_at,
            message_count=message_count,
            last_question_preview=preview(question),
        )
        for chat, message_count, last_activity_at, question in rows
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
