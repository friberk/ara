"""Authoritative metadata for uploaded PDFs from OpenAlex or Semantic Scholar (ARA-086).

Ingestion keeps what the PDF says and, in the same commit, queues one lookup for a paper that
has no provider record yet. The lookup asks the chosen source first and the other one second:
by DOI, then arXiv ID, then title. A title hit is used only when the titles agree closely and
an author or the year agrees too; an identifier hit must be the paper printed on the first
pages, since a DOI in the text can belong to a cited reference. Fields the user edited, and
values already taken from a provider, are never replaced.

A lookup never blocks reading, summaries or questions: the document is ready before it runs.
The chosen source's own "no match" is final, even if the other source is busy. When the chosen
source is rate limited or unreachable and the other cannot supply a match, the job waits for
the longest Retry-After (at least 60 s, then 120 s, at most 30 minutes) and gives up after its
third attempt, keeping the PDF's values. PostgreSQL job state is authoritative and lease fences
make a duplicate delivery a no-op.
"""

import asyncio
import random
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import exists, func, or_, select, update

from app.core.errors import AppError
from app.integrations.academic import AcademicSearch, normalized_doi
from app.jobs.pdf_parser import squashed
from app.models.jobs import BackgroundJob
from app.models.research import DocumentPage, ModelConfiguration, Paper, PaperSource
from app.repositories.jobs import enqueue, fence, now, payload_uuid, retry_locked
from app.repositories.papers import identity_locks, replace_authors
from app.schemas.research import SearchResult
from app.services.deletion import settle_deleted_locked

SETTING_KEY = "metadata"
SOURCES = ("openalex", "semantic_scholar")
# Normalized-title similarity (difflib ratio) that counts as the same title.
TITLE_AGREEMENT = 0.9
# A local title cut short by a line break still matches when it keeps this many words.
PREFIX_WORDS = 5
RETRY_BASE_SECONDS = 60
RETRY_CAP_SECONDS = 1800
LOOKUP_DEADLINE_SECONDS = 45
# Provenance that a provider value may replace; manual and provider values stay.
LOCAL_SOURCES = {"pdf", "pdf_metadata", "extraction", "llm"}
# Values read from the PDF itself, which reading the PDF again may replace (ARA-095).
PDF_SOURCES = {"pdf", "pdf_metadata", "extraction"}
# "again" (Look up again) replaces every value that is not manual. "backfill", the one-time
# refresh of papers read before ARA-086, also fills values the provider had none for before.
REFRESH_MODES = ("again", "backfill")
BACKFILL_KEY = "metadata_backfill"
# The startup refresh spaces its jobs out, so the catalogs see a trickle rather than a burst.
BACKFILL_SPACING_SECONDS = 3
CLUE_KEYS = ("title", "authors", "year", "doi", "arxiv_id", "venue")


@dataclass
class Clues:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    # From XMP prism:publicationName; it only breaks ties between equally good title matches.
    venue: str | None = None

    @classmethod
    def from_payload(cls, value) -> "Clues":
        value = value if isinstance(value, dict) else {}

        def text(key):
            item = value.get(key)
            return item if isinstance(item, str) and item.strip() else None

        authors = value.get("authors")
        year = value.get("year")
        return cls(
            title=text("title"),
            authors=[a for a in authors if isinstance(a, str)] if isinstance(authors, list) else [],
            year=year if isinstance(year, int) and not isinstance(year, bool) else None,
            doi=normalized_doi(text("doi")),
            arxiv_id=text("arxiv_id"),
            venue=text("venue"),
        )


def words(text: str | None) -> str:
    """Lowercase words without accents or punctuation, one space apart."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.sub(r"[\W_]+", " ", plain.lower()).split())


def title_score(local: str | None, candidate: str | None) -> float:
    a, b = words(local), words(candidate)
    if not a or not b:
        return 0.0
    shorter, longer = sorted((a, b), key=len)
    if longer.startswith(shorter) and len(shorter.split()) >= PREFIX_WORDS:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def surname(name: str) -> str:
    parts = words(name).split()
    return parts[-1] if parts else ""


def authors_agree(candidate: SearchResult, clues: Clues, first_pages: str) -> bool:
    local = {surname(name) for name in clues.authors} - {""}
    printed = set(words(first_pages).split())
    for name in candidate.authors:
        family = surname(name)
        # Two-letter surnames are common words too, so only listed authors can confirm them.
        if family and (family in local or (len(family) >= 3 and family in printed)):
            return True
    return False


def year_agrees(candidate: SearchResult, clues: Clues, first_pages: str) -> bool:
    if candidate.year is None:
        return False
    return candidate.year == clues.year or str(candidate.year) in words(first_pages).split()


def acceptable(candidate: SearchResult, clues: Clues, first_pages: str, *, by: str) -> bool:
    """Whether a provider record is this paper (see the module docstring)."""
    if by in {"doi", "arxiv"}:
        printed = squashed(candidate.title or "")
        return (len(printed) >= 12 and printed in squashed(first_pages)) or (
            title_score(clues.title, candidate.title) >= TITLE_AGREEMENT
        )
    return title_score(clues.title, candidate.title) >= TITLE_AGREEMENT and (
        authors_agree(candidate, clues, first_pages) or year_agrees(candidate, clues, first_pages)
    )


async def metadata_source(session) -> str:
    row = await session.get(ModelConfiguration, SETTING_KEY)
    source = row.value.get("source") if row and isinstance(row.value, dict) else None
    return source if source in SOURCES else "openalex"


async def queue_lookup(
    session, paper: Paper, document_id: UUID, metadata: dict, *, new_paper: bool = False
) -> None:
    """Inside the ingest commit: one lookup per new document of a paper without a provider record.

    Saved search results already carry provider metadata, and a re-ingest reuses the earlier
    lookup, so neither asks a provider again.
    """
    clues = Clues.from_payload(metadata)
    if not (clues.title or clues.doi or clues.arxiv_id):
        return
    linked = await session.scalar(
        select(PaperSource.id).where(PaperSource.paper_id == paper.id).limit(1)
    )
    earlier = await session.scalar(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.kind == "metadata",
            BackgroundJob.payload["document_id"].astext == str(document_id),
        )
        .limit(1)
    )
    if linked or earlier:
        return
    await enqueue(
        session,
        kind="metadata",
        payload={
            "paper_id": str(paper.id),
            "document_id": str(document_id),
            # A new upload whose record belongs to a library paper asks to join it (ARA-086).
            "new_paper": new_paper,
            "clues": {
                "title": clues.title,
                "authors": clues.authors[:20],
                "year": clues.year,
                "doi": clues.doi,
                "arxiv_id": clues.arxiv_id,
                "venue": clues.venue,
            },
        },
    )


async def queue_refresh(session, paper_id: UUID) -> BackgroundJob:
    """Look a paper up again at the user's request, at any time (ARA-095).

    It needs a title, DOI or provider record. A lookup already queued or running is returned
    rather than repeated, so repeated clicks ask no provider twice. The paper's details are read
    when the job runs, so edits made meanwhile count; clues only the PDF had, such as an arXiv
    ID, are carried over from the paper's earlier lookup.
    """
    paper = await session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    running = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "metadata",
            BackgroundJob.payload["paper_id"].astext == str(paper.id),
            BackgroundJob.state.in_(("queued", "processing")),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    if running is not None:
        return running
    linked = await session.scalar(
        select(PaperSource.id).where(PaperSource.paper_id == paper.id).limit(1)
    )
    if not (paper.title or paper.normalized_doi or linked):
        raise AppError(
            409, "LOOKUP_UNAVAILABLE", "Add the paper's title or DOI to look up its details."
        )
    return await enqueue_refresh(session, paper.id, paper.active_document_id, "again")


async def enqueue_refresh(
    session, paper_id: UUID, document_id: UUID | None, mode: str, *, delay_seconds: float = 0
) -> BackgroundJob:
    """One refresh job; the clues of the paper's earlier lookup come along."""
    earlier = await session.scalar(
        select(BackgroundJob.payload["clues"])
        .where(
            BackgroundJob.kind == "metadata",
            BackgroundJob.payload["paper_id"].astext == str(paper_id),
            BackgroundJob.payload.has_key("clues"),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return await enqueue(
        session,
        kind="metadata",
        payload={
            "paper_id": str(paper_id),
            "document_id": str(document_id) if document_id else None,
            "refresh": mode,
            "clues": earlier or {},
        },
        delay_seconds=delay_seconds,
    )


async def queue_backfill(resources) -> int:
    """Queue the one-time refresh for every library paper with a provider record or a read PDF.

    Papers saved or read before ARA-086 have no venue, and an upload may still carry a junk title
    that the first-page rule now rejects. API startup calls this. The marker row commits with
    the jobs, so concurrent and later startups queue nothing, and papers added afterwards are
    looked up when they are saved or read. Returns the number of jobs queued.
    """
    from app.models.research import Document
    from app.services.upload_match import library_papers

    async with resources.sessions() as session, session.begin():
        await identity_locks(session, [BACKFILL_KEY])
        if await session.get(ModelConfiguration, BACKFILL_KEY) is not None:
            return 0
        linked = exists().where(PaperSource.paper_id == Paper.id)
        read = exists().where(Document.id == Paper.active_document_id, Document.status == "ready")
        papers = (
            await session.execute(
                select(Paper.id, Paper.active_document_id)
                .where(library_papers(), or_(linked, read))
                .order_by(Paper.created_at, Paper.id)
            )
        ).all()
        for index, (paper_id, document_id) in enumerate(papers):
            await enqueue_refresh(
                session,
                paper_id,
                document_id,
                "backfill",
                delay_seconds=index * BACKFILL_SPACING_SECONDS,
            )
        session.add(
            ModelConfiguration(
                key=BACKFILL_KEY, value={"queued": len(papers), "queued_at": now().isoformat()}
            )
        )
    return len(papers)


def refresh_mode(payload: dict) -> str | None:
    value = payload.get("refresh")
    return value if value in REFRESH_MODES else None


async def stored_pdf(session, paper: Paper) -> str | None:
    """The object key of the PDF to read again: only for a read upload without a record."""
    from app.models.research import Document

    if paper.active_document_id is None or await session.scalar(
        select(PaperSource.id).where(PaperSource.paper_id == paper.id).limit(1)
    ):
        return None
    return await session.scalar(
        select(Document.object_key).where(
            Document.id == paper.active_document_id, Document.status == "ready"
        )
    )


async def reread_pdf(resources, object_key: str) -> dict | None:
    """The stored PDF's own metadata, read again by the child-process parser (XMP, first-page
    title, DOI, arXiv ID). A missing object leaves the paper's details as the only clues."""
    from minio.error import S3Error

    from app.integrations.storage import read_object
    from app.services.ingestion import parse_in_child
    from app.services.uploads import MAX_UPLOAD_BYTES

    try:
        data = await resources.storage_call(
            read_object,
            resources.storage,
            resources.settings.minio_bucket,
            object_key,
            MAX_UPLOAD_BYTES,
        )
    except S3Error as error:
        if error.code == "NoSuchKey":
            return None
        raise AppError(503, "STORAGE_UNAVAILABLE", "The stored PDF could not be read.") from None
    except Exception:
        raise AppError(503, "STORAGE_UNAVAILABLE", "The stored PDF could not be read.") from None
    parsed = await parse_in_child(data, layout=False)
    return None if parsed.get("error") else parsed.get("metadata")


async def take_pdf_values(session, paper: Paper, metadata: dict) -> None:
    """Values read again from the PDF replace earlier PDF values and fill missing ones; manual,
    model and provider values stay."""
    from app.models.research import PaperAuthor

    provenance = dict(paper.metadata_provenance)

    def open_to(name: str, current) -> bool:
        source = (provenance.get(name) or {}).get("source")
        return source != "manual" and (current in (None, "") or source in PDF_SOURCES)

    for name in ("title", "year", "abstract"):
        value = metadata.get(name)
        if value and value != getattr(paper, name) and open_to(name, getattr(paper, name)):
            setattr(paper, name, value)
            provenance[name] = {"source": "pdf"}
    doi = normalized_doi(metadata.get("doi")) if isinstance(metadata.get("doi"), str) else None
    if doi and doi != paper.normalized_doi and open_to("doi", paper.doi):
        owner = await session.scalar(
            select(Paper.id).where(Paper.normalized_doi == doi, Paper.id != paper.id)
        )
        if owner is None:
            paper.doi = paper.normalized_doi = doi
            provenance["doi"] = {"source": "pdf"}
    authors = [name for name in metadata.get("authors") or [] if isinstance(name, str)]
    listed = await session.scalar(
        select(PaperAuthor.id).where(PaperAuthor.paper_id == paper.id).limit(1)
    )
    if authors and open_to("authors", listed):
        await replace_authors(session, paper.id, authors)
        provenance["authors"] = {"source": "pdf"}
    paper.metadata_provenance = provenance
    paper.updated_at = func.now()


async def save_reread(resources, job_id, generation, token, paper_id, metadata, payload) -> bool:
    """Write the re-read PDF's values and checkpoint its clues, so a retry never parses again.

    False when the lease was lost or the paper is gone (then the job is settled)."""
    doi = (
        normalized_doi(metadata.get("doi"))
        if metadata and isinstance(metadata.get("doi"), str)
        else None
    )
    async with resources.sessions() as session, session.begin():
        if doi:
            await identity_locks(session, [f"doi:{doi}"])
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        paper = await session.scalar(
            select(Paper)
            .where(Paper.id == paper_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if paper is None:
            settle_deleted_locked(job)
            return False
        if metadata:
            await take_pdf_values(session, paper, metadata)
            payload["clues"] = {
                **(payload.get("clues") or {}),
                **{key: metadata[key] for key in CLUE_KEYS if metadata.get(key)},
            }
        payload["reread"] = True
        job.payload = dict(payload)
        job.updated_at = now()
    return True


async def refresh_clues(
    session, paper: Paper, earlier: Clues
) -> tuple[Clues, dict[str, str], bool]:
    """The paper's current details as clues, its saved records, and whether its DOI is manual.

    The arXiv ID and venue only the PDF had come from the earlier lookup's clues."""
    from app.models.research import PaperAuthor

    authors = (
        await session.scalars(
            select(PaperAuthor.name)
            .where(PaperAuthor.paper_id == paper.id)
            .order_by(PaperAuthor.ordinal)
            .limit(20)
        )
    ).all()
    records = dict(
        (
            await session.execute(
                select(PaperSource.provider, PaperSource.external_id).where(
                    PaperSource.paper_id == paper.id
                )
            )
        ).all()
    )
    manual_doi = (paper.metadata_provenance.get("doi") or {}).get("source") == "manual"
    clues = Clues(
        title=paper.title,
        authors=list(authors),
        year=paper.year,
        doi=paper.normalized_doi,
        arxiv_id=earlier.arxiv_id,
        venue=earlier.venue,
    )
    return clues, records, manual_doi


def rank(candidate: SearchResult, clues: Clues) -> tuple[float, bool]:
    venue, wanted = words(candidate.venue), words(clues.venue)
    agrees = bool(venue and wanted and (venue in wanted or wanted in venue))
    return title_score(clues.title, candidate.title), agrees


async def find(
    search: AcademicSearch,
    provider: str,
    clues: Clues,
    first_pages: str,
    *,
    record: str | None = None,
    trust_doi: bool = False,
) -> tuple[SearchResult, str] | None:
    """`record` is the paper's saved record at this provider, read again first; `trust_doi`
    accepts a DOI the user entered without checking it against the printed title (ARA-095)."""
    if record:
        try:
            return await search.canonical(provider, record), "record"
        except AppError as error:
            if error.code not in {"PAPER_NOT_FOUND", "INVALID_PAPER_ID"}:
                raise
    if clues.doi:
        found = await search.by_doi(provider, clues.doi)
        if found and (trust_doi or acceptable(found, clues, first_pages, by="doi")):
            return found, "doi"
    if clues.arxiv_id:
        found = await search.by_arxiv(provider, clues.arxiv_id)
        if found and acceptable(found, clues, first_pages, by="arxiv"):
            return found, "arxiv"
    if clues.title:
        matches = [
            item
            for item in await search.match_title(provider, clues.title)
            if acceptable(item, clues, first_pages, by="title")
        ]
        if matches:
            return max(matches, key=lambda item: rank(item, clues)), "title"
    return None


async def settle(resources, job_id, generation, token, *, result=None, failure=None, delay=0):
    """Complete, schedule a retry of, or fail the fenced job; False when the lease was lost."""
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        if failure is None:
            job.state, job.stage, job.progress, job.result = "completed", "completed", 100, result
            job.error_code = job.error_message = None
            job.lease_token = job.lease_expires_at = None
            job.updated_at = now()
        else:
            retry_locked(session, job, code=failure[0], message=failure[1], delay_seconds=delay)
        return True


def retry_delay(job_attempts: int, failures: list[AppError]) -> float:
    waits = [error.retry_after for error in failures if error.retry_after]
    backoff = RETRY_BASE_SECONDS * 2 ** max(0, job_attempts - 1)
    return min(RETRY_CAP_SECONDS, max([backoff, *waits])) * random.uniform(1, 1.1)


def unavailable(failures: list[AppError]) -> tuple[str, str]:
    if any(error.code == "PROVIDER_RATE_LIMITED" for error in failures):
        return (
            "PROVIDER_RATE_LIMITED",
            "The metadata sources are rate limited, so the details read from the PDF were "
            "kept. Retry the lookup later.",
        )
    return (
        "PROVIDER_UNAVAILABLE",
        "The metadata sources could not be reached, so the details read from the PDF were "
        "kept. Retry the lookup later.",
    )


async def apply(
    resources,
    job_id,
    generation,
    token,
    paper_id,
    found: SearchResult,
    by: str,
    *,
    new_paper=False,
    refresh: str | None = None,
):
    doi = normalized_doi(found.doi)
    async with resources.sessions() as session, session.begin():
        await identity_locks(
            session,
            [f"source:{found.provider}:{found.external_id}"] + ([f"doi:{doi}"] if doi else []),
        )
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return
        paper = await session.scalar(
            select(Paper)
            .where(Paper.id == paper_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if paper is None:
            # Deleted while the provider answered (ARA-095).
            settle_deleted_locked(job)
            return
        result = {"outcome": "matched", "provider": found.provider, "matched_by": by}
        result |= await merge(
            session, paper, found, doi, by=by, new_paper=new_paper, refresh=refresh
        )
        job.state, job.stage, job.progress, job.result = "completed", "completed", 100, result
        job.error_code = job.error_message = None
        job.lease_token = job.lease_expires_at = None
        job.updated_at = now()


async def empty_fields(session, paper: Paper) -> set[str]:
    """Fields with no value, the venue counting as empty when no linked record names one."""
    from app.models.research import PaperAuthor

    empty = {name for name in ("title", "year", "abstract", "doi") if not getattr(paper, name)}
    if not await session.scalar(
        select(PaperAuthor.id).where(PaperAuthor.paper_id == paper.id).limit(1)
    ):
        empty.add("authors")
    venues = await session.scalars(
        select(PaperSource.metadata_snapshot["venue"].astext).where(
            PaperSource.paper_id == paper.id
        )
    )
    if not any(venues.all()):
        empty.add("venue")
    return empty


async def merge(
    session,
    paper: Paper,
    found: SearchResult,
    doi: str | None,
    *,
    by="title",
    new_paper=False,
    refresh: str | None = None,
) -> dict:
    """Write provider values over local ones; link the record unless another paper owns it.

    A new upload whose record another library paper owns asks to join that paper instead of
    staying a duplicate (ARA-086); nothing is written to it meanwhile. Look up again also
    replaces earlier provider values, and the one-time refresh fills values a provider had none
    for; manual values always stay (ARA-095).
    """
    source = await session.scalar(
        select(PaperSource).where(
            PaperSource.provider == found.provider, PaperSource.external_id == found.external_id
        )
    )
    owner = None
    if source is not None and source.paper_id != paper.id:
        owner = source.paper_id
    elif doi:
        from app.services.upload_match import library_papers

        owner = await session.scalar(
            select(Paper.id).where(
                Paper.normalized_doi == doi, Paper.id != paper.id, library_papers()
            )
        )
    if owner is not None and new_paper and paper.active_document_id is not None:
        from app.services.upload_match import LibraryMatch, has_pdf, hold

        library = await session.get(Paper, owner)
        match = LibraryMatch(owner, await has_pdf(session, library), by)
        pending = await hold(
            session,
            placeholder_id=paper.id,
            document_id=paper.active_document_id,
            match=match,
            found_by="lookup",
        )
        return {"outcome": "library_match", "external_id": found.external_id, "match": pending}
    provenance = dict(paper.metadata_provenance)
    origin = {"source": found.provider, "external_id": found.external_id}

    empty = await empty_fields(session, paper) if refresh == "backfill" else set()

    def replaceable(name: str) -> bool:
        current = provenance.get(name)
        source = current.get("source") if isinstance(current, dict) else None
        if source == "manual":
            return False
        if source is None or source in LOCAL_SOURCES or refresh == "again":
            return True
        return name in empty

    updated = []
    if found.title and replaceable("title"):
        # A record that confirms the printed title keeps the PDF's capitalisation.
        if words(paper.title) != words(found.title):
            paper.title = found.title
        updated.append("title")
    if found.authors and replaceable("authors"):
        await replace_authors(session, paper.id, found.authors)
        updated.append("authors")
    for name in ("year", "abstract"):
        value = getattr(found, name)
        if value is not None and replaceable(name):
            setattr(paper, name, value)
            updated.append(name)
    if owner is None:
        if doi and replaceable("doi"):
            paper.doi = paper.normalized_doi = doi
            updated.append("doi")
        if found.venue and replaceable("venue"):
            updated.append("venue")
        snapshot = found.model_dump(mode="json")
        if source is None:
            session.add(
                PaperSource(
                    paper_id=paper.id,
                    provider=found.provider,
                    external_id=found.external_id,
                    metadata_snapshot=snapshot,
                )
            )
        else:
            source.metadata_snapshot = snapshot
    for name in updated:
        provenance[name] = origin
    paper.metadata_provenance = provenance
    paper.updated_at = func.now()
    await session.flush()
    result = {"external_id": found.external_id, "updated_fields": updated}
    if owner is not None:
        result["duplicate_paper_id"] = str(owner)
    return result


async def run_metadata_job(resources, job_id, generation, token, payload) -> None:
    paper_id = payload_uuid(payload, "paper_id")
    document_id = payload_uuid(payload, "document_id")
    clues = Clues.from_payload(payload.get("clues"))
    refresh = refresh_mode(payload)
    async with resources.sessions() as session, session.begin():
        started = await session.scalar(
            update(BackgroundJob)
            .where(*fence(job_id, generation, token))
            .values(stage="finding_metadata", progress=50)
            .returning(BackgroundJob.attempts)
        )
        if started is None:
            return
        paper = await session.get(Paper, paper_id) if paper_id is not None else None
        if paper_id is not None and paper is None:
            # The paper was deleted before its lookup ran (ARA-095); no provider is asked.
            job = await session.scalar(
                select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
            )
            settle_deleted_locked(job)
            return
        # A refresh of an upload without a record reads its stored PDF again, once (ARA-095).
        reread = (
            await stored_pdf(session, paper)
            if refresh and paper is not None and not payload.get("reread")
            else None
        )
        attempts = started
        selected = await metadata_source(session)
        pages = (
            await session.scalars(
                select(DocumentPage.text)
                .where(DocumentPage.document_id == document_id, DocumentPage.page <= 2)
                .order_by(DocumentPage.page)
            )
        ).all()
    if paper_id is None:
        await settle(resources, job_id, generation, token, result={"outcome": "paper_missing"})
        return
    if reread:
        try:
            metadata = await reread_pdf(resources, reread)
        except AppError as error:
            await settle(
                resources,
                job_id,
                generation,
                token,
                failure=(error.code, error.message),
                delay=retry_delay(attempts, []),
            )
            return
        if not await save_reread(resources, job_id, generation, token, paper_id, metadata, payload):
            return
    records, trust_doi = {}, False
    if refresh:
        async with resources.sessions() as session:
            paper = await session.get(Paper, paper_id)
            if paper is not None:
                clues, records, trust_doi = await refresh_clues(
                    session, paper, Clues.from_payload(payload.get("clues"))
                )
    first_pages = "\n".join(pages)
    search = AcademicSearch(resources.http, resources.settings)
    failures: list[AppError] = []
    found = None
    # The chosen source's answer decides: its "no match" is final even when the fallback is busy.
    answered = False
    try:
        async with asyncio.timeout(LOOKUP_DEADLINE_SECONDS):
            for provider in (selected, *(item for item in SOURCES if item != selected)):
                try:
                    found = await find(
                        search,
                        provider,
                        clues,
                        first_pages,
                        record=records.get(provider),
                        trust_doi=trust_doi,
                    )
                except AppError as error:
                    failures.append(error)
                    continue
                answered = answered or provider == selected
                if found:
                    break
    except TimeoutError:
        failures.append(AppError(503, "PROVIDER_UNAVAILABLE", "The lookup timed out."))
    if found:
        await apply(
            resources,
            job_id,
            generation,
            token,
            paper_id,
            *found,
            new_paper=bool(payload.get("new_paper")),
            refresh=refresh,
        )
    elif failures and not answered:
        await settle(
            resources,
            job_id,
            generation,
            token,
            failure=unavailable(failures),
            delay=retry_delay(attempts, failures),
        )
    else:
        await settle(resources, job_id, generation, token, result={"outcome": "no_match"})
