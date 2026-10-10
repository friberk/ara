"""The library papers a chat covers (ARA-088).

Each paper pins the PDF that was active when it joined, as a single-paper chat always did, so a
newer upload never changes what an existing chat reads. The lowest ordinal is the chat's first
paper, whose page is the chat's URL. A chat always keeps at least one paper: removal refuses the
last one, and a database trigger deletes a chat whose last paper is deleted (migration 0010).
"""

import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update

from app.core.errors import AppError
from app.models.research import ChatPaper, ChatSession, Document, Paper
from app.schemas.ai import ChatCreate
from app.services.context import PaperHeader

# A title shorter than this ("Go") would match ordinary words, so it never names a paper.
MIN_TITLE_CHARS = 4


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


async def ready_documents(session, paper_ids: Sequence[UUID]) -> list[Document]:
    """Each paper's active PDF, in order, read in one query; it must be ready."""
    rows = await session.execute(
        select(Paper, Document)
        .outerjoin(Document, Document.id == Paper.active_document_id)
        .where(Paper.id.in_(list(paper_ids)))
    )
    found = {paper.id: (paper, document) for paper, document in rows}
    documents = []
    for paper_id in paper_ids:
        if paper_id not in found:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        paper, document = found[paper_id]
        if document is None or document.status != "ready":
            name = f"“{paper.title}”" if paper.title else "This paper"
            raise AppError(
                409, "PAPER_NOT_READY", f"{name} needs a processed PDF before you can ask about it."
            )
        documents.append(document)
    return documents


async def create_chat(session, body: ChatCreate) -> ChatSession:
    chat = ChatSession(
        title=body.title,
        title_source="manual" if "title" in body.model_fields_set else "default",
    )
    documents = await ready_documents(session, body.paper_ids)
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
    (document,) = await ready_documents(session, [paper_id])
    if any(link.paper_id == paper_id for link in links):
        return chat
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


def normalized(text: str) -> str:
    return " " + " ".join(re.findall(r"[^\W_]+", text.casefold())) + " "


def surname(name: str) -> str:
    name = name.strip()
    return name.split(",")[0].strip() if "," in name else (name.split() or [""])[-1]


def named_papers(question: str, papers: Sequence[PaperHeader]) -> list[int]:
    """Indexes of the papers a question names: by full title, or as citation chips name them,
    "Surname Year" (ARA-088). Named papers are always kept in a multi-paper answer."""
    asked = normalized(question)
    found = []
    for index, paper in enumerate(papers):
        names = []
        if paper.title and len(paper.title.strip()) >= MIN_TITLE_CHARS:
            names.append(paper.title)
        if paper.authors and paper.year:
            names.append(f"{surname(paper.authors[0])} {paper.year}")
        if any(normalized(name) in asked for name in names if normalized(name).strip()):
            found.append(index)
    return found
