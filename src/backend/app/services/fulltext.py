"""PDF retrieval from OpenAlex's stored copies (ARA-087), stored and ingested like an upload."""

import asyncio
from uuid import UUID

from minio.error import S3Error
from sqlalchemy import select, update

from app.core.errors import AppError
from app.integrations.openalex_content import api_key, stored_work
from app.models.jobs import BackgroundJob
from app.models.research import Document, DocumentUploadRequest, Paper, PaperSource
from app.repositories.fulltext import enqueue_request
from app.repositories.jobs import fence, now
from app.schemas.fulltext import FullTextAccepted
from app.services.deletion import PAPER_DELETED, STOPPED
from app.services.uploads import (
    AttachmentGuard,
    AttachmentLeaseLost,
    AttachmentSuperseded,
    activate_ingestion,
    ingest_pdf_bytes,
)

JOB_SECONDS = 420


async def request_fulltext(resources, paper_id: UUID, request_id: UUID) -> FullTextAccepted:
    if api_key(resources.settings) is None:
        raise AppError(
            409,
            "OPENALEX_API_KEY_REQUIRED",
            "Add an OpenAlex API key to download PDFs automatically.",
        )
    async with resources.sessions() as session, session.begin():
        return await enqueue_request(session, paper_id, request_id)


async def current_document(resources, paper_id):
    async with resources.sessions() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        return (
            await session.get(Document, paper.active_document_id)
            if paper.active_document_id
            else None
        )


def document_result(document, outcome):
    return {
        "outcome": outcome,
        "document_id": str(document.id) if document else None,
        "ingest_job_id": str(document.ingest_job_id)
        if document and document.ingest_job_id
        else None,
    }


async def finish(resources, job_id, generation, token, result, *, reason=None):
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return
        if result["outcome"] in {"downloaded", "already_attached"}:
            paper = await session.scalar(
                select(Paper).where(Paper.id == UUID(job.payload["paper_id"])).with_for_update()
            )
            if paper is None:
                result, reason = {"outcome": "paper_deleted"}, STOPPED
            elif str(paper.active_document_id) != result.get("document_id"):
                document = (
                    await session.get(Document, paper.active_document_id)
                    if paper.active_document_id
                    else None
                )
                result = document_result(document, "superseded")
        success = result["outcome"] in {"downloaded", "already_attached", "superseded"}
        job.state, job.stage = ("completed", "completed") if success else ("failed", "failed")
        job.progress = 100 if success else job.progress
        job.result = result
        if success:
            job.error_code = None
        elif result["outcome"] == "paper_deleted":
            job.error_code = PAPER_DELETED
        else:
            job.error_code = f"FULLTEXT_{result['outcome'].upper()}"
        job.error_message = None if success else (reason or "The PDF could not be retrieved.")[:400]
        job.lease_token, job.lease_expires_at = None, None
        job.updated_at = now()


async def checkpoint(resources, job_id, generation, token, payload, stage, progress):
    async with resources.sessions() as session, session.begin():
        return (
            await session.scalar(
                update(BackgroundJob)
                .where(*fence(job_id, generation, token))
                .values(payload=dict(payload), stage=stage, progress=progress, updated_at=now())
                .returning(BackgroundJob.id)
            )
            is not None
        )


async def lookup_work(resources, paper_id):
    """The paper's OpenAlex work: its saved OpenAlex record, else its DOI (a free lookup)."""
    async with resources.sessions() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        work_id = await session.scalar(
            select(PaperSource.external_id).where(
                PaperSource.paper_id == paper_id, PaperSource.provider == "openalex"
            )
        )
        doi = paper.normalized_doi
    return await stored_work(resources.http, resources.settings, work_id=work_id, doi=doi)


async def run_fulltext_job(
    resources, job_id: UUID, generation: int, lease_token: UUID, payload: dict
) -> None:
    async with resources.sessions() as session:
        if (
            await session.scalar(
                select(BackgroundJob.id).where(*fence(job_id, generation, lease_token))
            )
            is None
        ):
            return
    paper_id = UUID(payload["paper_id"])
    expected = (
        UUID(payload["expected_active_document_id"])
        if payload.get("expected_active_document_id")
        else None
    )
    try:
        async with asyncio.timeout(JOB_SECONDS):
            document = await current_document(resources, paper_id)
            async with resources.sessions() as session:
                binding = await session.get(
                    DocumentUploadRequest, UUID(payload["attachment_request_id"])
                )
            owned_document = (
                binding is not None and document is not None and binding.document_id == document.id
            )
            if owned_document:
                try:
                    await resources.storage_call(
                        resources.storage.stat_object,
                        resources.settings.minio_bucket,
                        document.object_key,
                    )
                except S3Error as error:
                    if error.code != "NoSuchKey":
                        raise
                else:
                    async with resources.sessions() as session:
                        child = (
                            await session.get(BackgroundJob, document.ingest_job_id)
                            if document.ingest_job_id
                            else None
                        )
                    if child and document.status == "uploading":
                        from app.schemas.research import UploadAccepted

                        await activate_ingestion(
                            resources,
                            UploadAccepted(
                                paper_id=paper_id, document_id=document.id, job_id=child.id
                            ),
                            child.generation,
                            AttachmentGuard(job_id, generation, lease_token, expected),
                        )
                    await finish(
                        resources,
                        job_id,
                        generation,
                        lease_token,
                        document_result(document, "downloaded"),
                    )
                    return
            if (document.id if document else None) != expected and not owned_document:
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    document_result(document, "superseded"),
                )
                return
            if (
                document
                and not owned_document
                and document.status in {"ready", "uploading", "processing"}
            ):
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    document_result(document, "already_attached"),
                )
                return
            key = api_key(resources.settings)
            if key is None:
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    {"outcome": "api_key_required"},
                    reason="Add an OpenAlex API key to download PDFs automatically.",
                )
                return
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "discovering_fulltext", 10
            ):
                return
            try:
                work = await lookup_work(resources, paper_id)
            except AppError as error:
                if error.code == "PAPER_NOT_FOUND":
                    raise
                # A refused or failed lookup ends this attempt; retrying is the user's choice.
                limited = error.code == "PROVIDER_RATE_LIMITED"
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    {
                        "outcome": "rate_limited" if limited else "unavailable",
                        "retry_after": error.retry_after if limited else None,
                    },
                    reason=error.message,
                )
                return
            if work is None or not work.has_pdf:
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    {"outcome": "not_stored"},
                    reason="OpenAlex has no stored copy of this PDF.",
                )
                return
            payload["work_id"] = work.work_id
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "fetching_pdf", 40
            ):
                return
            downloaded = await resources.pdf_downloader.fetch(work.work_id, key)
            if downloaded.outcome != "downloaded":
                await finish(
                    resources,
                    job_id,
                    generation,
                    lease_token,
                    {"outcome": downloaded.outcome, "retry_after": downloaded.retry_after},
                    reason=downloaded.reason,
                )
                return
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "storing_pdf", 75
            ):
                return
            accepted = await ingest_pdf_bytes(
                resources,
                data=downloaded.data or b"",
                filename=f"{work.work_id}.pdf",
                request_id=UUID(payload["attachment_request_id"]),
                paper_id=paper_id,
                guard=AttachmentGuard(job_id, generation, lease_token, expected),
                acquisition={
                    "method": "provider_download",
                    "provider": "openalex",
                    "source": "content",
                    "work_id": work.work_id,
                    "retrieved_at": now().isoformat(),
                    "retrieval_job_id": str(job_id),
                },
            )
            result = {
                "outcome": "downloaded",
                "document_id": str(accepted.document_id),
                "ingest_job_id": str(accepted.job_id),
            }
            payload["accepted"] = result
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "storing_pdf", 90
            ):
                return
            await finish(resources, job_id, generation, lease_token, result)
    except AttachmentLeaseLost:
        return
    except AttachmentSuperseded:
        try:
            result = document_result(await current_document(resources, paper_id), "superseded")
        except AppError as error:
            if error.code != "PAPER_NOT_FOUND":
                raise
            result = {"outcome": "paper_deleted"}
        await finish(resources, job_id, generation, lease_token, result, reason=STOPPED)
    except TimeoutError:
        await finish(
            resources,
            job_id,
            generation,
            lease_token,
            {"outcome": "unavailable", "retry_after": None},
            reason="PDF retrieval exceeded its time limit. Try again or upload the PDF.",
        )
    except AppError as error:
        if error.status_code >= 500:
            raise
        # The paper was deleted while this ran (ARA-095).
        deleted = error.code == "PAPER_NOT_FOUND"
        await finish(
            resources,
            job_id,
            generation,
            lease_token,
            {"outcome": "paper_deleted" if deleted else "invalid_pdf"},
            reason=STOPPED if deleted else error.message,
        )
