"""Re-ingest ready documents whose chunks predate the current chunk set (ARA-071).

The API queues this at startup; `docker compose exec api python -m app.services.reindex` does
the same by hand. A document with older chunks serves them until its ingest job replaces them
in one transaction. A document from before migration 0006 has no chunks (`chunk_set` is NULL),
so questions about it are refused until its re-ingest finishes.
"""

import asyncio
import logging

from sqlalchemy import or_, select

from app.models.jobs import BackgroundJob
from app.models.research import Document
from app.rag.chunking import CHUNK_SET
from app.rag.indexing import reconcile_indexes
from app.repositories.jobs import enqueue

logger = logging.getLogger(__name__)
# Reuse the original job's metadata inference so re-ingestion never repeats a paid call.
CARRIED_PAYLOAD = ("metadata_attempted", "metadata_result")


async def enqueue_reindex(resources) -> int:
    async with resources.sessions() as session, session.begin():
        # Lock first, then look for active jobs, so concurrent runs queue each document once.
        documents = (
            await session.scalars(
                select(Document)
                .where(
                    Document.status == "ready",
                    or_(Document.chunk_set.is_(None), Document.chunk_set != CHUNK_SET),
                )
                .order_by(Document.created_at, Document.id)
                .with_for_update()
            )
        ).all()
        active = set(
            (
                await session.scalars(
                    select(BackgroundJob.payload["document_id"].astext).where(
                        BackgroundJob.kind == "ingest",
                        BackgroundJob.state.in_(("queued", "processing")),
                    )
                )
            ).all()
        )
        queued = 0
        for document in documents:
            if str(document.id) in active:
                continue
            previous = (
                await session.get(BackgroundJob, document.ingest_job_id)
                if document.ingest_job_id
                else None
            )
            payload = {"document_id": str(document.id)}
            for key in CARRIED_PAYLOAD:
                if previous is not None and key in previous.payload:
                    payload[key] = previous.payload[key]
            job = await enqueue(session, kind="ingest", payload=payload)
            document.ingest_job_id = job.id
            queued += 1
        return queued


async def prepare_search(resources) -> None:
    """API startup: queue the one-time metadata refresh (ARA-095), re-ingest outdated documents,
    then queue missing or unavailable indexes.

    Retries until the database answers; every step is idempotent under concurrent runs. The
    refresh goes first, so a re-ingest finds its lookup already queued and asks no provider.
    """
    from app.services.metadata import queue_backfill

    while True:
        try:
            await queue_backfill(resources)
            await enqueue_reindex(resources)
            await reconcile_indexes(resources)
            return
        except Exception:
            logger.warning("Search preparation unavailable; retrying later")
            await asyncio.sleep(resources.settings.recovery_interval_seconds)


async def main() -> None:
    from app.core.config import Settings
    from app.core.resources import Resources

    resources = Resources(Settings())
    try:
        print(f"Queued {await enqueue_reindex(resources)} document(s) for re-indexing.")
    finally:
        await resources.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
