"""Retrieval settings, model profiles, paper indexes and conversation memory (ARA-072/074/077)."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations import open_models
from app.integrations.embedding_catalog import PROFILES, embedding_profile
from app.integrations.reranker_catalog import RERANKERS, reranker_profile
from app.models.research import Document, DocumentChunk, ModelConfiguration, Paper
from app.models.retrieval import DocumentSection, RetrievalIndex
from app.rag.indexing import (
    REBUILD,
    default_profile,
    ensure_index,
    profile_status,
    reconcile_indexes,
)
from app.schemas.jobs import JobError
from app.schemas.retrieval import (
    ChatMemoryState,
    EmbeddingProfileOut,
    EmbeddingProfilePage,
    PaperRetrieval,
    RebuildInput,
    ReindexEstimate,
    RerankerOut,
    RetrievalIndexOut,
    RetrievalSettings,
)

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


async def listed(session, settings, catalog: dict, saved: str | None) -> list:
    """The offered profiles, plus a saved open-model choice reported unavailable (ARA-090)."""
    shown = open_models.offered(settings, catalog)
    if saved in catalog and saved not in shown:
        shown[saved] = catalog[saved]
    return [
        (profile, *await profile_status(session, settings, profile)) for profile in shown.values()
    ]


@router.get("/retrieval/profiles", response_model=EmbeddingProfilePage)
async def profiles(request: Request):
    resources = request.app.state.resources
    settings = resources.settings
    async with resources.sessions() as session:
        default = await default_profile(session)
        row = await session.get(ModelConfiguration, "retrieval")
        saved = RetrievalSettings.from_stored(row.value if row else None).reranker
        items = []
        for profile, status, reason in await listed(session, settings, PROFILES, default):
            items.append(
                EmbeddingProfileOut(
                    key=profile.key,
                    provider=profile.provider,
                    model_id=profile.model_id,
                    display_name=profile.display_name,
                    dimensions=profile.dimensions,
                    status=status,
                    unavailable_reason=reason,
                    local_model_key=local_key(settings, profile),
                    price_per_million=float(profile.price_per_million),
                    description=profile.description,
                )
            )
        rerankers = []
        for profile, status, reason in await listed(session, settings, RERANKERS, saved):
            rerankers.append(
                RerankerOut(
                    key=profile.key,
                    provider=profile.provider,
                    model_id=profile.model_id,
                    display_name=profile.display_name,
                    status=status,
                    unavailable_reason=reason,
                    local_model_key=local_key(settings, profile),
                    candidates=profile.candidates,
                    price_per_million=float(profile.price_per_million_input),
                    description=profile.description,
                )
            )
        return EmbeddingProfilePage(items=items, default_profile=default, rerankers=rerankers)


def local_key(settings, profile) -> str | None:
    """The local model that would serve a profile; none to install while open models are off."""
    return None if open_models.open_profile(settings, profile) else profile.local_model_key


@router.get("/retrieval/settings", response_model=RetrievalSettings)
async def retrieval_settings(request: Request):
    async with request.app.state.resources.sessions() as session:
        row = await session.get(ModelConfiguration, "retrieval")
        return RetrievalSettings.from_stored(row.value if row else None)


@router.put("/retrieval/settings", response_model=RetrievalSettings)
async def update_retrieval_settings(body: RetrievalSettings, request: Request):
    # Availability is not required: a default can be chosen before its model is installed.
    embedder = embedding_profile(body.embedding_profile)
    reranker = reranker_profile(body.reranker) if body.reranker is not None else None
    resources = request.app.state.resources
    async with resources.sessions() as session, session.begin():
        previous = await default_profile(session)
        row = await session.get(ModelConfiguration, "retrieval")
        stored = RetrievalSettings.from_stored(row.value if row else None)
        # With open models off, a saved open-model choice is kept but never newly chosen.
        if (
            open_models.open_profile(resources.settings, embedder)
            and body.embedding_profile != previous
        ) or (
            reranker is not None
            and open_models.open_profile(resources.settings, reranker)
            and body.reranker != stored.reranker
        ):
            raise open_models.disabled(open_models.CHOOSE_SEARCH)
        await session.execute(
            insert(ModelConfiguration)
            .values(key="retrieval", value=body.model_dump())
            .on_conflict_do_update(index_elements=["key"], set_={"value": body.model_dump()})
        )
    if body.embedding_profile != previous:
        # Every paper moves to the new model once it can embed; ready indexes keep serving.
        await reconcile_indexes(resources)
    return body


@router.get("/retrieval/reindex-estimate", response_model=ReindexEstimate)
async def reindex_estimate(profile: str, request: Request):
    """Papers and tokens a switch to `profile` would embed, priced from stored chunk counts."""
    chosen = embedding_profile(profile)
    if open_models.open_profile(request.app.state.resources.settings, chosen):
        raise open_models.disabled(open_models.CHOOSE_SEARCH)
    ready = (
        select(RetrievalIndex.id)
        .where(
            RetrievalIndex.document_id == Document.id,
            RetrievalIndex.profile == profile,
            RetrievalIndex.chunk_set == Document.chunk_set,
            RetrievalIndex.state == "ready",
        )
        .exists()
    )
    async with request.app.state.resources.sessions() as session:
        documents = (
            select(Document.id, Document.chunk_set)
            .where(Document.status == "ready", Document.chunk_set.is_not(None), ~ready)
            .subquery()
        )
        papers = await session.scalar(select(func.count()).select_from(documents))
        tokens = await session.scalar(
            select(func.coalesce(func.sum(DocumentChunk.token_count), 0)).join(
                documents,
                (DocumentChunk.document_id == documents.c.id)
                & (DocumentChunk.chunk_set == documents.c.chunk_set),
            )
        )
    price = float(chosen.price_per_million)
    return ReindexEstimate(
        profile=profile,
        papers=papers,
        tokens=tokens,
        price_per_million=price,
        estimated_cost_usd=tokens * price / 1_000_000,
    )


def percent(index: RetrievalIndex) -> int:
    return index.embedded * 100 // index.total if index.total else 0


def index_out(index: RetrievalIndex) -> RetrievalIndexOut:
    return RetrievalIndexOut(
        profile=index.profile,
        state=index.state,
        embedded=index.embedded,
        total=index.total,
        updated_at=index.updated_at,
        error=JobError(code=index.error_code, message=index.error_message or "Indexing failed.")
        if index.error_code
        else None,
    )


def disabled_index(index: RetrievalIndex) -> RetrievalIndexOut:
    """An open-model index while open models are off: stored, but it cannot serve (ARA-090)."""
    out = index_out(index)
    out.state = "unavailable"
    out.error = JobError(code=open_models.DISABLED, message=open_models.SEARCH_NOTE)
    return out


def unready_note(index: RetrievalIndex | None) -> str:
    if index is None:
        return "Search index has not been built yet."
    if index.state == "unavailable":
        return f"Search index unavailable: {index.error_message}"
    if index.state == "failed":
        return f"Search index could not be built: {index.error_message}"
    return f"Search index is building ({percent(index)}%)."


async def paper_retrieval(session, paper_id: UUID, settings) -> PaperRetrieval:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    profile = await default_profile(session)
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    result = PaperRetrieval(
        paper_id=paper.id,
        document_id=document.id if document else None,
        effective_profile=profile,
        parser=document.parser if document else None,
        chunk_count=0,
        section_count=0,
        mode="unavailable",
        mode_note="Upload and process a PDF to search this paper.",
        indexes=[],
    )
    if document is not None and document.status in {"uploading", "processing"}:
        result.mode_note = "The PDF is still being processed."
    elif document is not None and document.status == "failed":
        result.mode_note = "The PDF could not be processed, so it cannot be searched."
    elif document is not None and document.chunk_set is None:
        # Ready before migration 0006: the startup re-ingest rebuilds its passages.
        result.mode_note = "This paper is being prepared for the new search."
    if document is None or document.status != "ready" or document.chunk_set is None:
        return result
    chunk_set = document.chunk_set
    for model, field in ((DocumentChunk, "chunk_count"), (DocumentSection, "section_count")):
        count = await session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.document_id == document.id, model.chunk_set == chunk_set)
        )
        setattr(result, field, count)
    rows = (
        await session.scalars(
            select(RetrievalIndex)
            .where(
                RetrievalIndex.document_id == document.id,
                RetrievalIndex.chunk_set.in_([chunk_set, chunk_set + REBUILD]),
            )
            .order_by(RetrievalIndex.created_at)
        )
    ).all()
    serving = {row.profile: row for row in rows if row.chunk_set == chunk_set}
    rebuilding = {row.profile: row for row in rows if row.chunk_set != chunk_set}
    # One entry per profile: an unfinished rebuild reports its own progress.
    shown = {**serving, **rebuilding}
    usable = open_models.offered(settings, PROFILES)
    result.indexes = [
        index_out(index) if index.profile in usable else disabled_index(index)
        for index in shown.values()
    ]
    if profile not in usable:
        result.mode, result.mode_note = "keyword", open_models.SEARCH_NOTE
        return result
    ready = sorted(
        (row for row in serving.values() if row.state == "ready" and row.profile in usable),
        key=lambda row: (row.profile == profile, row.updated_at),
        reverse=True,
    )
    wanted = shown.get(profile)
    if not ready:
        result.mode, result.mode_note = "keyword", unready_note(wanted)
        return result
    result.mode, result.mode_note = "hybrid", None
    if ready[0].profile != profile:
        result.mode_note = (
            f"Searching with {PROFILES[ready[0].profile].display_name} until "
            f"{PROFILES[profile].display_name} is ready ({percent(wanted) if wanted else 0}%)."
        )
    elif profile in rebuilding:
        rebuild = rebuilding[profile]
        result.mode_note = (
            f"Rebuild failed: {rebuild.error_message} The current index keeps serving."
            if rebuild.state in {"failed", "unavailable"}
            else f"Rebuilding the search index ({percent(rebuild)}%). "
            "The current index keeps serving."
        )
    return result


@router.get("/papers/{paper_id}/retrieval", response_model=PaperRetrieval)
async def read_paper_retrieval(paper_id: UUID, request: Request):
    resources = request.app.state.resources
    async with resources.sessions() as session:
        return await paper_retrieval(session, paper_id, resources.settings)


async def replayed(session, request_id: UUID, intent: dict) -> PaperRetrieval | None:
    """Claim a request UUID; a concurrent duplicate waits for the first to commit."""
    key = f"retrieval_request:{request_id}"
    claimed = await session.scalar(
        insert(ModelConfiguration)
        .values(key=key, value=intent)
        .on_conflict_do_nothing()
        .returning(ModelConfiguration.key)
    )
    if claimed is not None:
        return None
    previous = await session.get(ModelConfiguration, key)
    stored = {name: value for name, value in previous.value.items() if name != "response"}
    if stored != intent or "response" not in previous.value:
        raise AppError(
            409,
            "RETRIEVAL_REQUEST_CONFLICT",
            "This request UUID was already used for a different search index change.",
        )
    return PaperRetrieval.model_validate(previous.value["response"])


async def remember(session, request_id: UUID, intent: dict, response: PaperRetrieval) -> None:
    row = await session.get(ModelConfiguration, f"retrieval_request:{request_id}")
    row.value = {**intent, "response": response.model_dump(mode="json")}


async def indexable_document(session, paper: Paper) -> Document | None:
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    if document is None or document.status != "ready" or document.chunk_set is None:
        return None
    return document


@router.post("/papers/{paper_id}/retrieval/rebuild", response_model=PaperRetrieval, status_code=202)
async def rebuild_paper_retrieval(paper_id: UUID, body: RebuildInput, request: Request):
    intent = {"paper_id": str(paper_id), "action": "rebuild"}
    resources = request.app.state.resources
    async with resources.sessions() as session, session.begin():
        paper = await session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
        if paper is None:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        if previous := await replayed(session, body.request_id, intent):
            return previous
        document = await indexable_document(session, paper)
        if document is None:
            raise AppError(
                409, "DOCUMENT_NOT_INDEXABLE", "Upload and process a PDF before rebuilding."
            )
        profile = await default_profile(session)
        # A local library model while open models are off cannot embed (ARA-090).
        if open_models.open_profile(resources.settings, PROFILES[profile]):
            raise open_models.disabled(open_models.CHOOSE_SEARCH)
        await ensure_index(session, document.id, profile, rebuild=True)
        response = await paper_retrieval(session, paper_id, resources.settings)
        await remember(session, body.request_id, intent, response)
        return response


@router.get("/chats/{chat_id}/memory", response_model=ChatMemoryState)
async def chat_memory(chat_id: UUID, request: Request):
    from app.services.memory import memory_state

    async with request.app.state.resources.sessions() as session:
        return await memory_state(session, chat_id)
