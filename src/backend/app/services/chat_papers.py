"""The library papers a chat covers (ARA-088).

Each paper pins the PDF that was active when it joined, as a single-paper chat always did, so a
newer upload never changes what an existing chat reads. The lowest ordinal is the chat's first
paper, whose page is the chat's URL. A chat always keeps at least one paper: removal refuses the
last one, and a database trigger deletes a chat whose last paper is deleted (migration 0010).
"""

from uuid import UUID

from sqlalchemy import delete, select, update

from app.core.errors import AppError
from app.models.research import ChatPaper, ChatSession, Document, Paper
from app.schemas.ai import MAX_CHAT_PAPERS, ChatCreate


async def locked_chat(session, chat_id: UUID) -> ChatSession:
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == chat_id).with_for_update()
    )
    if chat is None:
        raise AppError(404, "CHAT_NOT_FOUND", "Chat not found.")
    return chat


async def pinned(session, chat_id: UUID) -> list[ChatPaper]:
    """The chat's papers by ordinal."""
    return list(
        (
            await session.scalars(
                select(ChatPaper).where(ChatPaper.chat_id == chat_id).order_by(ChatPaper.ordinal)
            )
        ).all()
    )


async def library_paper(session, paper_id: UUID) -> Paper:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    return paper


async def ready_document(session, paper: Paper) -> Document:
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    if document is None or document.status != "ready":
        name = f"“{paper.title}”" if paper.title else "This paper"
        raise AppError(
            409, "PAPER_NOT_READY", f"{name} needs a processed PDF before you can ask about it."
        )
    return document


async def create_chat(session, body: ChatCreate) -> ChatSession:
    chat = ChatSession(
        title=body.title,
        title_source="manual" if "title" in body.model_fields_set else "default",
    )
    documents = [
        await ready_document(session, await library_paper(session, paper_id))
        for paper_id in body.paper_ids
    ]
    session.add(chat)
    await session.flush()
    session.add_all(
        ChatPaper(chat_id=chat.id, paper_id=document.paper_id, document_id=document.id, ordinal=n)
        for n, document in enumerate(documents)
    )
    await session.flush()
    return chat


async def add_paper(session, chat_id: UUID, paper_id: UUID) -> ChatSession:
    """Add a paper with its active PDF; adding an included paper changes nothing."""
    chat = await locked_chat(session, chat_id)
    links = await pinned(session, chat_id)
    paper = await library_paper(session, paper_id)
    if any(link.paper_id == paper_id for link in links):
        return chat
    if len(links) >= MAX_CHAT_PAPERS:
        raise AppError(
            409,
            "CHAT_PAPER_LIMIT",
            f"A chat can include up to {MAX_CHAT_PAPERS} papers. Remove one to add another.",
        )
    document = await ready_document(session, paper)
    session.add(
        ChatPaper(
            chat_id=chat_id,
            paper_id=paper_id,
            document_id=document.id,
            ordinal=links[-1].ordinal + 1,
        )
    )
    await session.flush()
    return chat


async def remove_paper(session, chat_id: UUID, paper_id: UUID) -> ChatSession:
    """Remove a paper; earlier answers keep their citations to it."""
    chat = await locked_chat(session, chat_id)
    links = await pinned(session, chat_id)
    link = next((link for link in links if link.paper_id == paper_id), None)
    if link is None:
        raise AppError(404, "CHAT_PAPER_NOT_FOUND", "This paper is not in the chat.")
    if len(links) == 1:
        raise AppError(409, "LAST_CHAT_PAPER", "A chat needs at least one paper.")
    await session.delete(link)
    await session.flush()
    return chat


async def move_paper(session, old_paper_id: UUID, new_paper_id: UUID) -> None:
    """Chats follow a placeholder's PDF into its library paper. A chat that already covers the
    library paper keeps that paper's pinned PDF."""
    covered = select(ChatPaper.chat_id).where(ChatPaper.paper_id == new_paper_id)
    await session.execute(
        delete(ChatPaper).where(ChatPaper.paper_id == old_paper_id, ChatPaper.chat_id.in_(covered))
    )
    await session.execute(
        update(ChatPaper).where(ChatPaper.paper_id == old_paper_id).values(paper_id=new_paper_id)
    )
