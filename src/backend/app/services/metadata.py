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

from sqlalchemy import func, select, update

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

    It needs a DOI or a provider record. A lookup already queued or running is returned rather
    than repeated, so repeated clicks ask no provider twice. Clues are read when the job runs,
    so edits made meanwhile count.
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
    if not paper.normalized_doi and linked is None:
        raise AppError(409, "LOOKUP_UNAVAILABLE", "Add the paper's DOI to look up its details.")
    return await enqueue(
        session,
        kind="metadata",
        payload={
            "paper_id": str(paper.id),
            "document_id": str(paper.active_document_id) if paper.active_document_id else None,
            "refresh": True,
        },
    )


async def refresh_clues(session, paper: Paper) -> tuple[Clues, dict[str, str], bool]:
    """The paper's current details as clues, its saved records, and whether its DOI is manual."""
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
        title=paper.title, authors=list(authors), year=paper.year, doi=paper.normalized_doi
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
    refresh=False,
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


async def merge(
    session,
    paper: Paper,
    found: SearchResult,
    doi: str | None,
    *,
    by="title",
    new_paper=False,
    refresh=False,
) -> dict:
    """Write provider values over local ones; link the record unless another paper owns it.

    A new upload whose record another library paper owns asks to join that paper instead of
    staying a duplicate (ARA-086); nothing is written to it meanwhile. A refresh ("Look up
    again") also replaces earlier provider values; manual ones always stay (ARA-095).
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

    def replaceable(name: str) -> bool:
        current = provenance.get(name)
        if not isinstance(current, dict):
            return True
        if refresh:
            return current.get("source") != "manual"
        return current.get("source") in LOCAL_SOURCES

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
    refresh = payload.get("refresh") is True
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
        records, trust_doi = {}, False
        if refresh and paper is not None:
            clues, records, trust_doi = await refresh_clues(session, paper)
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
