"""Uploads that turn out to be papers already in the library (ARA-086).

A PDF uploaded without a target paper first gets a placeholder paper. When ingestion finds that
it is a library paper (same DOI, arXiv DOI, or a title matched by the strict lookup rule), the
upload joins that paper instead of duplicating it:
- if the library paper has no usable PDF, ingestion attaches the upload to it in the same
  commit that makes the PDF ready, so processing and the automatic summary continue there;
- otherwise ingestion stops before persisting pages, so nothing paid (model metadata, embeddings,
  the automatic summary) starts, and records a pending match for the user to resolve: Replace
  makes the upload that paper's active PDF and re-ingests it there; Cancel discards the
  placeholder, the document and its stored original.
A match the catalog lookup finds later is recorded the same way and asks the same question.

State lives in tables whose foreign keys remove it with the rows it names (ARA-092):
- `upload_matches`, keyed by the placeholder paper: the pending match. Placeholders with one are
  hidden from the library listing (a NOT EXISTS on the key) and listed by GET /uploads/matches
  instead. Deleting the placeholder, the library paper or the document deletes the match.
- `paper_redirects`, keyed by the retired placeholder's ID: where an attached or replaced upload
  went, so an open link to the placeholder still reaches its paper. The old ID has no row to
  reference, so only the target is a foreign key; deleting the target deletes the redirect.
- `documents.doi_owner_paper_id`: an upload into a chosen paper whose DOI belongs to another
  paper. Deleting the owner clears it.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations.academic import normalized_doi
from app.models.research import (
    Document,
    Paper,
    PaperAuthor,
    PaperRedirect,
    PaperSummary,
    UploadMatch,
)
from app.repositories.jobs import enqueue
from app.repositories.papers import identity_locks
from app.schemas.research import SearchResult
from app.services.chat_papers import move_paper
from app.services.metadata import Clues, acceptable, title_score


@dataclass(frozen=True)
class LibraryMatch:
    paper_id: UUID
    has_pdf: bool
    matched_by: str


def pending_papers():
    """Filter for placeholder papers whose upload waits for the user's decision."""
    return exists().where(UploadMatch.placeholder_paper_id == Paper.id)


def library_papers():
    """Filter for papers that are in the library, not held placeholders."""
    return ~pending_papers()


def pending_lock_key(placeholder_id: UUID) -> str:
    return f"upload_match:{placeholder_id}"


async def has_pdf(session, paper: Paper) -> bool:
    """A paper has a PDF unless it has none or its active one failed to process."""
    if paper.active_document_id is None:
        return False
    status = await session.scalar(
        select(Document.status).where(Document.id == paper.active_document_id)
    )
    return status is not None and status != "failed"


async def find_library_match(
    session, placeholder_id: UUID, metadata: dict, first_pages: str
) -> LibraryMatch | None:
    """The library paper this upload is: by DOI, arXiv DOI, then the strict title rule."""
    doi = normalized_doi(metadata.get("doi")) if isinstance(metadata.get("doi"), str) else None
    arxiv = metadata.get("arxiv_id")
    identities = [(doi, "doi")]
    if isinstance(arxiv, str) and arxiv:
        identities.append((f"10.48550/arxiv.{arxiv.lower()}", "arxiv"))
    for value, by in identities:
        if not value:
            continue
        paper = await session.scalar(
            select(Paper).where(
                Paper.normalized_doi == value, Paper.id != placeholder_id, library_papers()
            )
        )
        if paper is not None:
            return LibraryMatch(paper.id, await has_pdf(session, paper), by)
    clues = Clues.from_payload(metadata)
    longest = max((w for w in (clues.title or "").split() if w.isalpha()), key=len, default="")
    if len(longest) < 4:
        return None
    candidates = (
        await session.scalars(
            select(Paper)
            .where(Paper.title.ilike(f"%{longest}%"), Paper.id != placeholder_id, library_papers())
            .limit(25)
        )
    ).all()
    best = None
    for paper in candidates:
        authors = (
            await session.scalars(
                select(PaperAuthor.name)
                .where(PaperAuthor.paper_id == paper.id)
                .order_by(PaperAuthor.ordinal)
            )
        ).all()
        record = SearchResult(
            provider="openalex",
            external_id=str(paper.id),
            title=paper.title,
            authors=list(authors),
            year=paper.year,
        )
        score = title_score(clues.title, paper.title)
        if acceptable(record, clues, first_pages, by="title") and (not best or score > best[0]):
            best = (score, paper)
    if best is None:
        return None
    return LibraryMatch(best[1].id, await has_pdf(session, best[1]), "title")


async def hold(
    session, *, placeholder_id: UUID, document_id: UUID, match: LibraryMatch, found_by: str
) -> dict:
    """Record a pending match; a repeat keeps the first record."""
    await session.execute(
        insert(UploadMatch)
        .values(
            placeholder_paper_id=placeholder_id,
            library_paper_id=match.paper_id,
            document_id=document_id,
            matched_by=match.matched_by,
            found_by=found_by,
        )
        .on_conflict_do_nothing()
    )
    return {"paper_id": str(match.paper_id), "outcome": "pending", "matched_by": match.matched_by}


async def absorb(session, *, placeholder_id: UUID, library: Paper, document: Document) -> None:
    """Make the upload the library paper's active PDF and retire the placeholder.

    Conversations and summaries made on the placeholder move with its PDF, earlier PDFs of the
    library paper stay its versions, and an open link to the placeholder redirects.
    """
    document.paper_id = library.id
    library.active_document_id = document.id
    library.updated_at = func.now()
    await move_paper(session, placeholder_id, library.id)
    await session.execute(
        update(PaperSummary)
        .where(PaperSummary.paper_id == placeholder_id)
        .values(paper_id=library.id)
    )
    await session.flush()
    # Deleting the placeholder also deletes its pending match.
    await session.execute(delete(Paper).where(Paper.id == placeholder_id))
    await session.execute(
        insert(PaperRedirect)
        .values(old_paper_id=placeholder_id, paper_id=library.id)
        .on_conflict_do_update(index_elements=["old_paper_id"], set_={"paper_id": library.id})
    )


async def note_doi_owner(session, document_id: UUID, paper: Paper, doi: str | None) -> None:
    """An upload into a chosen paper keeps its target; a DOI owned elsewhere is reported."""
    if not doi or doi == normalized_doi(paper.doi):
        return
    owner = await session.scalar(
        select(Paper.id).where(Paper.normalized_doi == doi, Paper.id != paper.id)
    )
    if owner is not None:
        # A repeat keeps the first owner.
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.doi_owner_paper_id.is_(None))
            .values(doi_owner_paper_id=owner)
        )


async def redirect_target(session, paper_id: UUID) -> UUID | None:
    return await session.scalar(
        select(PaperRedirect.paper_id).where(PaperRedirect.old_paper_id == paper_id)
    )


async def match_view(session, paper: Paper) -> tuple[dict | None, dict | None]:
    """The pending match and the DOI owner of the active PDF, as PaperDetail fields."""
    pending = await session.get(UploadMatch, paper.id)
    match = None
    if pending is not None:
        library = await session.get(Paper, pending.library_paper_id)
        match = {
            "paper_id": library.id,
            "title": library.title,
            "has_pdf": await has_pdf(session, library),
            "matched_by": pending.matched_by,
            "found_by": pending.found_by,
        }
    owner = None
    if paper.active_document_id is not None:
        other = await session.scalar(
            select(Paper)
            .join(Document, Document.doi_owner_paper_id == Paper.id)
            .where(Document.id == paper.active_document_id)
        )
        if other is not None:
            owner = {"paper_id": other.id, "title": other.title}
    return match, owner


async def continue_upload(session, resources, document: Document) -> None:
    """A held upload goes on as its paper's PDF: indexed and summarized once if it was already
    read, as when a PDF becomes ready, else read now."""
    from app.rag import hooks
    from app.services.summarization import queue_automatic_summary

    if document.status == "ready":
        await hooks.after_chunks_persisted(session, document_id=document.id)
        await queue_automatic_summary(session, resources, document)
    else:
        # Held before its pages were stored.
        job = await enqueue(session, kind="ingest", payload={"document_id": str(document.id)})
        document.ingest_job_id = job.id
        document.status = "processing"


async def resolve(resources, placeholder_id: UUID, decision: str) -> UUID | None:
    """Attach or discard a pending upload; returns the paper to show, or None once discarded.

    Repeats are safe: a second attach answers with the paper it went to, a second discard with
    nothing. A paper without a pending match is a conflict. Discarding deletes the placeholder
    as any paper deletion does, so its stored original is removed by a durable job (ARA-095).
    """
    from app.services.deletion import delete_papers

    async with resources.sessions() as session, session.begin():
        await identity_locks(session, [pending_lock_key(placeholder_id)])
        row = await session.get(UploadMatch, placeholder_id, with_for_update=True)
        if row is None:
            target = await redirect_target(session, placeholder_id)
            if decision == "attach" and target is not None:
                return target
            if decision == "discard" and target is None:
                if await session.get(Paper, placeholder_id) is None:
                    return None
            raise AppError(
                409, "NO_PENDING_MATCH", "This upload has no library match waiting for a choice."
            )
        library_id = row.library_paper_id
        document_id = row.document_id
        papers = {
            paper.id: paper
            for paper in (
                await session.scalars(
                    select(Paper)
                    .where(Paper.id.in_(sorted([placeholder_id, library_id])))
                    .order_by(Paper.id)
                    .with_for_update()
                )
            ).all()
        }
        document = await session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        library = papers.get(library_id)
        if decision == "discard":
            await delete_papers(session, resources, [placeholder_id])
            target = None
        elif document is None or document.paper_id != placeholder_id:
            raise AppError(409, "NO_PENDING_MATCH", "This upload is no longer waiting.")
        else:
            if library is None:
                # The library paper was deleted meanwhile: the upload becomes its own paper.
                await session.delete(row)
                target = placeholder_id
            else:
                await absorb(
                    session, placeholder_id=placeholder_id, library=library, document=document
                )
                target = library.id
            await session.flush()
            await continue_upload(session, resources, document)
    return target
