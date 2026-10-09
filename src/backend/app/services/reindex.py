"""Re-ingest ready documents whose chunks predate the current chunk set (ARA-071).

Run with `docker compose exec api python -m app.services.reindex`. Documents keep serving
their previous chunks until the new ingest job replaces them in one transaction.
"""

from sqlalchemy import or_, select

from app.models.jobs import BackgroundJob
from app.models.research import Document
from app.rag.chunking import CHUNK_SET
from app.repositories.jobs import enqueue

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
