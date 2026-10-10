"""Resumable per-document embedding indexes with blue/green serving (ARA-072).

An index is keyed by (document, profile, chunk set). Questions use `ready_index()`, which
returns only a fully embedded index, so a switch or rebuild never exposes a half-built one.
A rebuild of a ready index embeds into a staging row (`<chunk set>#r`, vectors under
`<profile>#r`) and swaps the vectors in one transaction when it completes.
"""

import hashlib
import time
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations.embedding_catalog import DEFAULT_PROFILE, PROFILES, embedding_profile
from app.integrations.embeddings import create_embedder
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.models.research import Document, DocumentChunk, ModelConfiguration
from app.models.retrieval import ChunkEmbedding, RetrievalIndex
from app.repositories.jobs import continue_locked, enqueue, fence, now, payload_uuid

# A job yields its lease after this much work, so long local embeddings never hit
# the actor time limit and never spend retry attempts.
WORK_SECONDS = 240
BUSY_WAIT_SECONDS = 10
REBUILD = "#r"
# Configuration or installation problems that retries cannot fix. Keyword search continues.
UNAVAILABLE = {
    "MODEL_NOT_CONFIGURED",
    "MODEL_UNAVAILABLE",
    "DAILY_BUDGET_EXCEEDED",
    "INVALID_EMBEDDING_PROFILE",
    "LOCAL_MODEL_NOT_FOUND",
    "LOCAL_MODEL_NOT_READY",
    "LOCAL_MODEL_REVALIDATION_REQUIRED",
    "MODEL_WEIGHTS_MISSING",
    "MODEL_DIGEST_MISMATCH",
}


async def default_profile(session) -> str:
    from app.schemas.retrieval import RetrievalSettings

    row = await session.get(ModelConfiguration, "retrieval")
    if row is None:
        return DEFAULT_PROFILE
    try:
        key = RetrievalSettings.from_stored(row.value).embedding_profile
    except ValidationError:
        return DEFAULT_PROFILE
    return key if key in PROFILES else DEFAULT_PROFILE


async def profile_status(session, settings, profile) -> tuple[str, str | None]:
    """Embedding and reranker profiles: a hosted key, or a ready, verified local install."""
    from app.integrations.llm import configured
    from app.integrations.model_catalog import local_spec
    from app.services.local_models import model_dto

    if profile.provider == "openai":
        if configured(settings):
            return "available", None
        return "unavailable", "Add an OpenAI API key on the server."
    spec = local_spec(profile.local_model_key)
    if spec is None:
        return "unavailable", f"Download {profile.display_name} in Settings."
    download = f"Download {spec.display_name} in Settings."
    row = await session.get(ModelInstallation, spec.key)
    model = model_dto(spec, row, context_window=settings.ollama_context_window)
    if model.status == "available":
        return "available", None
    if row is None or row.state == "missing":
        return "unavailable", download
    return "unavailable", model.unavailable_reason


async def locked_index(session, document_id: UUID, profile: str, chunk_set: str):
    await session.execute(
        insert(RetrievalIndex)
        .values(document_id=document_id, profile=profile, chunk_set=chunk_set)
        .on_conflict_do_nothing(constraint="uq_retrieval_index")
    )
    return await session.scalar(
        select(RetrievalIndex)
        .where(
            RetrievalIndex.document_id == document_id,
            RetrievalIndex.profile == profile,
            RetrievalIndex.chunk_set == chunk_set,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def chunk_count(document_id: UUID, chunk_set: str):
    return (
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document_id, DocumentChunk.chunk_set == chunk_set)
    )


async def ensure_index(
    session, document_id: UUID, profile_key: str, *, rebuild: bool = False
) -> RetrievalIndex:
    """Queue embedding unless the index is ready (or a rebuild was requested) or queued."""
    embedding_profile(profile_key)
    document = await session.get(Document, document_id)
    if document is None or document.chunk_set is None:
        raise AppError(409, "DOCUMENT_NOT_INDEXABLE", "This paper has no processed text yet.")
    current = await locked_index(session, document_id, profile_key, document.chunk_set)
    target = current
    if current.state == "ready":
        if not rebuild:
            return current
        target = await locked_index(session, document_id, profile_key, document.chunk_set + REBUILD)
    owner = await session.get(BackgroundJob, target.job_id) if target.job_id else None
    if owner is not None and owner.state in {"queued", "processing"}:
        return target
    job = await enqueue(
        session,
        kind="embed",
        payload={
            "index_id": str(target.id),
            "document_id": str(document_id),
            # The paper link lets the Jobs API label and filter indexing work.
            "paper_id": str(document.paper_id),
            "profile": profile_key,
        },
    )
    target.job_id, target.state = job.id, "queued"
    target.total = await session.scalar(chunk_count(document_id, document.chunk_set))
    target.error_code = target.error_message = None
    target.updated_at = now()
    return target


async def prune_other_models(session, document_id: UUID, keep: str) -> None:
    """Drop the vectors and index rows of every other model once `keep` is the ready library model.

    A model whose embed job is still queued or running is left alone; its own finish (or the
    next reconcile) prunes it, so an in-flight job never writes into a deleted index.
    """
    rows = (
        await session.execute(
            select(RetrievalIndex.profile, BackgroundJob.state)
            .outerjoin(BackgroundJob, BackgroundJob.id == RetrievalIndex.job_id)
            .where(RetrievalIndex.document_id == document_id, RetrievalIndex.profile != keep)
        )
    ).all()
    busy = {profile for profile, state in rows if state in {"queued", "processing"}}
    kept = {keep, keep + REBUILD, *busy, *(profile + REBUILD for profile in busy)}
    await session.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.document_id == document_id, ChunkEmbedding.profile.not_in(kept)
        )
    )
    await session.execute(
        delete(RetrievalIndex).where(
            RetrievalIndex.document_id == document_id, RetrievalIndex.profile.not_in({keep, *busy})
        )
    )


async def reconcile_document(session, document_id: UUID, available: set[str]) -> bool:
    """Queue the library model's index when it is missing or was unavailable, and prune others."""
    # Lock first, then look for a re-ingest, so concurrent runs queue each index once.
    document = await session.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None or document.status != "ready" or document.chunk_set is None:
        return False
    # A queued re-ingest replaces the chunks and queues their index itself.
    if await session.scalar(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.kind == "ingest",
            BackgroundJob.state.in_(("queued", "processing")),
            BackgroundJob.payload["document_id"].astext == str(document_id),
        )
        .limit(1)
    ):
        return False
    profile = await default_profile(session)
    if profile not in available:
        return False
    index = await session.scalar(
        select(RetrievalIndex).where(
            RetrievalIndex.document_id == document_id,
            RetrievalIndex.profile == profile,
            RetrievalIndex.chunk_set == document.chunk_set,
        )
    )
    if index is not None and index.state == "ready":
        await prune_other_models(session, document_id, profile)
        return False
    if index is not None and (index.state == "failed" and index.error_code not in UNAVAILABLE):
        return False  # Provider failures are rebuilt from the paper's Details, not on every boot.
    owner = index.job_id if index else None
    return (await ensure_index(session, document_id, profile)).job_id != owner


async def reconcile_indexes(resources) -> int:
    """Queue missing or unavailable indexes whose library model can embed now.

    Runs at API startup (a key arrives with a restart), after the default profile changes and
    after a local embedding model verifies. Returns the number of embed jobs queued.
    """
    async with resources.sessions() as session:
        available = {
            key
            for key, profile in PROFILES.items()
            if (await profile_status(session, resources.settings, profile))[0] == "available"
        }
        if not available:
            return 0
        documents = (
            await session.scalars(
                select(Document.id)
                .where(Document.status == "ready", Document.chunk_set.is_not(None))
                .order_by(Document.created_at, Document.id)
            )
        ).all()
    queued = 0
    for document_id in documents:
        async with resources.sessions() as session, session.begin():
            queued += await reconcile_document(session, document_id, available)
    return queued


async def ready_index(session, document_id: UUID, preferred: str) -> RetrievalIndex | None:
    """The preferred ready index for the current chunk set, else the latest other ready one."""
    chunk_set = await session.scalar(select(Document.chunk_set).where(Document.id == document_id))
    if chunk_set is None:
        return None
    return await session.scalar(
        select(RetrievalIndex)
        .where(
            RetrievalIndex.document_id == document_id,
            RetrievalIndex.chunk_set == chunk_set,
            RetrievalIndex.state == "ready",
        )
        .order_by((RetrievalIndex.profile == preferred).desc(), RetrievalIndex.updated_at.desc())
        .limit(1)
    )


async def fenced_job(session, job_id, generation, token) -> BackgroundJob | None:
    return await session.scalar(
        select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
    )


def complete_locked(job: BackgroundJob, result: dict) -> None:
    job.state = job.stage = "completed"
    job.progress = 100
    job.result = result
    job.error_code = job.error_message = None
    job.lease_token = job.lease_expires_at = None
    job.updated_at = now()


class Run:
    """One fenced attempt of an embed job over one index row."""

    def __init__(self, resources, job_id, generation, token, index: RetrievalIndex):
        self.resources, self.job_id = resources, job_id
        self.generation, self.token = generation, token
        self.index_id, self.document_id, self.profile = index.id, index.document_id, index.profile
        self.rebuild = index.chunk_set.endswith(REBUILD)
        self.chunk_set = index.chunk_set.removesuffix(REBUILD)
        # Staged rebuild vectors coexist with the serving ones until the swap.
        self.key = self.profile + REBUILD if self.rebuild else self.profile

    def chunk_ids(self):
        return select(DocumentChunk.id).where(
            DocumentChunk.document_id == self.document_id,
            DocumentChunk.chunk_set == self.chunk_set,
        )

    def embedded_count(self):
        return (
            select(func.count())
            .select_from(ChunkEmbedding)
            .where(
                ChunkEmbedding.profile == self.key, ChunkEmbedding.chunk_id.in_(self.chunk_ids())
            )
        )

    async def pending(self, limit: int) -> list[tuple[UUID, str]]:
        async with self.resources.sessions() as session:
            rows = await session.execute(
                select(DocumentChunk.id, DocumentChunk.context_text)
                .where(
                    DocumentChunk.document_id == self.document_id,
                    DocumentChunk.chunk_set == self.chunk_set,
                    ~exists().where(
                        ChunkEmbedding.chunk_id == DocumentChunk.id,
                        ChunkEmbedding.profile == self.key,
                    ),
                )
                .order_by(DocumentChunk.ordinal)
                .limit(limit)
            )
            return [(row.id, row.context_text) for row in rows]

    async def save(self, embedder, batch, vectors) -> bool:
        async with self.resources.sessions() as session, session.begin():
            job = await fenced_job(session, self.job_id, self.generation, self.token)
            if job is None:
                return False
            await session.execute(
                insert(ChunkEmbedding)
                .values(
                    [
                        {
                            "chunk_id": chunk_id,
                            "profile": self.key,
                            "document_id": self.document_id,
                            "embedding": vector,
                            "input_hash": hashlib.sha256(
                                embedder.sent_text(text).encode()
                            ).hexdigest(),
                        }
                        for (chunk_id, text), vector in zip(batch, vectors, strict=True)
                    ]
                )
                .on_conflict_do_nothing(index_elements=["chunk_id", "profile"])
            )
            index = await session.get(RetrievalIndex, self.index_id, with_for_update=True)
            embedded = await session.scalar(self.embedded_count())
            total = await session.scalar(chunk_count(self.document_id, self.chunk_set))
            if index is not None:
                index.state, index.embedded, index.total = "embedding", embedded, total
                index.error_code = index.error_message = None
                index.updated_at = now()
            job.stage = "embedding"
            job.progress = min(99, embedded * 100 // total) if total else 0
            job.updated_at = now()
            return True

    async def pause(self, *, stage: str, delay_seconds: float = 0) -> None:
        async with self.resources.sessions() as session, session.begin():
            job = await fenced_job(session, self.job_id, self.generation, self.token)
            if job is not None:
                continue_locked(
                    session, job, stage=stage, progress=job.progress, delay_seconds=delay_seconds
                )

    async def finish(self) -> None:
        async with self.resources.sessions() as session, session.begin():
            job = await fenced_job(session, self.job_id, self.generation, self.token)
            if job is None:
                return
            # Lock the serving row before the rebuild row, in the same order as ensure_index.
            serving = (
                await locked_index(session, self.document_id, self.profile, self.chunk_set)
                if self.rebuild
                else None
            )
            index = await session.get(RetrievalIndex, self.index_id, with_for_update=True)
            if index is None:
                complete_locked(job, {"index_id": str(self.index_id), "skipped": True})
                return
            embedded = await session.scalar(self.embedded_count())
            if serving is None:
                serving = index
            else:
                # Swap atomically: readers see either every old vector or every new one.
                await session.execute(
                    delete(ChunkEmbedding).where(
                        ChunkEmbedding.profile == self.profile,
                        ChunkEmbedding.chunk_id.in_(self.chunk_ids()),
                    )
                )
                await session.execute(
                    update(ChunkEmbedding)
                    .where(
                        ChunkEmbedding.profile == self.key,
                        ChunkEmbedding.chunk_id.in_(self.chunk_ids()),
                    )
                    .values(profile=self.profile)
                )
                await session.delete(index)
            local_key = PROFILES[self.profile].local_model_key
            installation = await session.get(ModelInstallation, local_key) if local_key else None
            serving.state, serving.embedded = "ready", embedded
            serving.total = await session.scalar(chunk_count(self.document_id, self.chunk_set))
            serving.job_id = job.id
            serving.model_digest = installation.digest if installation else None
            serving.error_code = serving.error_message = None
            serving.updated_at = now()
            current = await session.scalar(
                select(Document.chunk_set).where(Document.id == self.document_id)
            )
            if (
                not self.rebuild
                and current == self.chunk_set
                and self.profile == await default_profile(session)
            ):
                # The library model is ready for this document, so older models can go.
                await prune_other_models(session, self.document_id, self.profile)
            complete_locked(job, {"index_id": str(serving.id), "embedded": embedded})

    async def settle_unavailable(self, error: AppError) -> None:
        async with self.resources.sessions() as session, session.begin():
            job = await fenced_job(session, self.job_id, self.generation, self.token)
            if job is None:
                return
            index = await session.get(RetrievalIndex, self.index_id, with_for_update=True)
            if index is not None:
                index.state = "unavailable"
                index.error_code, index.error_message = error.code, error.message[:400]
                index.updated_at = now()
            complete_locked(job, {"index_id": str(self.index_id), "unavailable": error.code})

    async def record_error(self, error: AppError) -> None:
        """Keep the provider's reason for the index; the actor's fail() decides on retry."""
        async with self.resources.sessions() as session, session.begin():
            if await fenced_job(session, self.job_id, self.generation, self.token) is None:
                return
            index = await session.get(RetrievalIndex, self.index_id, with_for_update=True)
            if index is not None:
                index.error_code, index.error_message = error.code, error.message[:400]
                index.updated_at = now()


async def run_embed_job(resources, job_id, generation, token, payload) -> None:
    index_id = payload_uuid(payload, "index_id")
    async with resources.sessions() as session:
        live = await session.scalar(
            select(BackgroundJob.id).where(*fence(job_id, generation, token))
        )
        index = await session.get(RetrievalIndex, index_id) if index_id else None
    if live is None:
        return  # A duplicate or stale delivery holds no lease and writes nothing.
    if index is None or index.job_id != job_id:
        async with resources.sessions() as session, session.begin():
            job = await fenced_job(session, job_id, generation, token)
            if job is not None:
                complete_locked(job, {"index_id": str(index_id), "skipped": True})
        return
    run = Run(resources, job_id, generation, token, index)
    started = time.monotonic()
    embedder = None
    try:
        embedder = create_embedder(resources, embedding_profile(run.profile))
        while batch := await run.pending(embedder.profile.batch_size):
            vectors = await embedder.embed_documents([text for _, text in batch])
            if not await run.save(embedder, batch, vectors):
                return
            if time.monotonic() - started >= WORK_SECONDS:
                await run.pause(stage="embedding")
                return
        await run.finish()
    except AppError as error:
        if error.code in UNAVAILABLE:
            await run.settle_unavailable(error)
        elif error.code == "LOCAL_MODEL_BUSY":
            await run.pause(stage="local_runtime_wait", delay_seconds=BUSY_WAIT_SECONDS)
        else:
            await run.record_error(error)
            raise
    finally:
        if embedder is not None:
            await embedder.close()
