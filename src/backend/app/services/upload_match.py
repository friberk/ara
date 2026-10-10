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

State lives in `model_configurations`, keyed by the placeholder paper or document, so no
migration is needed:
- `upload_match:<placeholder>`: the pending match. Placeholders with one are hidden from the
  library listing and listed by GET /uploads/matches instead.
- `paper_redirect:<placeholder>`: where an attached or replaced upload went, so an open link to
  the placeholder still reaches its paper.
- `pdf_doi_owner:<document>`: an upload into a chosen paper whose DOI belongs to another paper.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import String, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations.academic import normalized_doi
from app.models.research import (
    ChatSession,
    Document,
    ModelConfiguration,
    Paper,
    PaperAuthor,
    PaperSummary,
)
from app.repositories.jobs import enqueue
from app.repositories.papers import identity_locks
from app.schemas.research import SearchResult
from app.services.metadata import Clues, acceptable, title_score

PENDING = "upload_match:"
REDIRECT = "paper_redirect:"
DOI_OWNER = "pdf_doi_owner:"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LibraryMatch:
    paper_id: UUID
    has_pdf: bool
    matched_by: str


def pending_paper_ids():
    """Placeholder paper IDs (as text) whose upload waits for the user's decision."""
    return select(func.substr(ModelConfiguration.key, len(PENDING) + 1)).where(
        ModelConfiguration.key.startswith(PENDING)
    )


def library_papers():
    return cast(Paper.id, String).not_in(pending_paper_ids())


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
    value = {
        "paper_id": str(match.paper_id),
        "document_id": str(document_id),
        "matched_by": match.matched_by,
        "found_by": found_by,
    }
    await session.execute(
        insert(ModelConfiguration)
        .values(key=f"{PENDING}{placeholder_id}", value=value)
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
    for model in (ChatSession, PaperSummary):
        await session.execute(
            update(model).where(model.paper_id == placeholder_id).values(paper_id=library.id)
        )
    await session.flush()
    await session.execute(delete(Paper).where(Paper.id == placeholder_id))
    await session.execute(
        delete(ModelConfiguration).where(ModelConfiguration.key == f"{PENDING}{placeholder_id}")
    )
    redirect = {"paper_id": str(library.id)}
    await session.execute(
        insert(ModelConfiguration)
        .values(key=f"{REDIRECT}{placeholder_id}", value=redirect)
        .on_conflict_do_update(index_elements=["key"], set_={"value": redirect})
    )


async def note_doi_owner(session, document_id: UUID, paper: Paper, doi: str | None) -> None:
    """An upload into a chosen paper keeps its target; a DOI owned elsewhere is reported."""
    if not doi or doi == normalized_doi(paper.doi):
        return
    owner = await session.scalar(
        select(Paper.id).where(Paper.normalized_doi == doi, Paper.id != paper.id)
    )
    if owner is not None:
        await session.execute(
            insert(ModelConfiguration)
            .values(key=f"{DOI_OWNER}{document_id}", value={"paper_id": str(owner)})
            .on_conflict_do_nothing()
        )


async def redirect_target(session, paper_id: UUID) -> UUID | None:
    row = await session.get(ModelConfiguration, f"{REDIRECT}{paper_id}")
    return UUID(row.value["paper_id"]) if row else None


async def match_view(session, paper: Paper) -> tuple[dict | None, dict | None]:
    """The pending match and the DOI owner of the active PDF, as PaperDetail fields."""
    pending = await session.get(ModelConfiguration, f"{PENDING}{paper.id}")
    match = None
    if pending is not None:
        library = await session.get(Paper, UUID(pending.value["paper_id"]))
        if library is not None:
            match = {
                "paper_id": library.id,
                "title": library.title,
                "has_pdf": await has_pdf(session, library),
                "matched_by": pending.value.get("matched_by", "doi"),
                "found_by": pending.value.get("found_by", "ingest"),
            }
    owner = None
    if paper.active_document_id is not None:
        row = await session.get(ModelConfiguration, f"{DOI_OWNER}{paper.active_document_id}")
        other = await session.get(Paper, UUID(row.value["paper_id"])) if row else None
        if other is not None:
            owner = {"paper_id": other.id, "title": other.title}
    return match, owner


async def resolve(resources, placeholder_id: UUID, decision: str) -> UUID | None:
    """Attach or discard a pending upload; returns the paper to show, or None once discarded.

    Repeats are safe: a second attach answers with the paper it went to, a second discard with
    nothing. A paper without a pending match is a conflict.
    """
    from app.rag import hooks
    from app.services.summarization import queue_automatic_summary

    discarded_key = None
    async with resources.sessions() as session, session.begin():
        await identity_locks(session, [f"{PENDING}{placeholder_id}"])
        row = await session.get(
            ModelConfiguration, f"{PENDING}{placeholder_id}", with_for_update=True
        )
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
        library_id = UUID(row.value["paper_id"])
        document_id = UUID(row.value["document_id"])
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
            discarded_key = document.object_key if document else None
            await session.delete(row)
            await session.execute(delete(Paper).where(Paper.id == placeholder_id))
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
            if document.status == "ready":
                # Found late: the PDF is already read; index it for its paper and summarize it
                # once, as when a PDF becomes ready.
                await hooks.after_chunks_persisted(session, document_id=document.id)
                await queue_automatic_summary(session, resources, document)
            else:
                # Held before its pages were stored: read it now, on its paper.
                job = await enqueue(
                    session, kind="ingest", payload={"document_id": str(document.id)}
                )
                document.ingest_job_id = job.id
                document.status = "processing"
    if discarded_key:
        try:
            await resources.storage_call(
                resources.storage.remove_object, resources.settings.minio_bucket, discarded_key
            )
        except Exception:
            # The rows are gone; an unreachable store only leaves an unreferenced object.
            logger.warning("Discarded upload original could not be removed from storage")
    return target
