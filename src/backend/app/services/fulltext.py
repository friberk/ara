"""Full-text request orchestration; worker downloading is added independently."""

import asyncio
from urllib.parse import urlsplit
from uuid import UUID

from minio.error import S3Error
from sqlalchemy import select, update

from app.core.errors import AppError
from app.models.jobs import BackgroundJob
from app.models.research import Document, DocumentUploadRequest, Paper
from app.repositories.fulltext import enqueue_request, record_attempt
from app.repositories.jobs import fence, now
from app.schemas.fulltext import DownloadResult, FullTextAccepted
from app.services.fulltext_discovery import LABELS, discover_fulltext
from app.services.uploads import (
    AttachmentGuard,
    AttachmentLeaseLost,
    AttachmentSuperseded,
    activate_ingestion,
    ingest_pdf_bytes,
)

JOB_SECONDS = 420


async def request_fulltext(resources, paper_id: UUID, request_id: UUID) -> FullTextAccepted:
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
            if paper and str(paper.active_document_id) != result.get("document_id"):
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
        job.error_code = None if success else f"FULLTEXT_{result['outcome'].upper()}"
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


def unchecked(discovery) -> DownloadResult:
    """Why discovery found no candidate: a provider's reported wait outranks an outage."""
    if discovery.rate_limited:
        names = [LABELS[provider] for provider in discovery.rate_limited]
        verb = "are" if len(names) > 1 else "is"
        return DownloadResult(
            "rate_limited",
            reason=f"{' and '.join(names)} {verb} limiting lookups; some copies went unchecked.",
            retry_after=min(300, max(discovery.rate_limited.values())),
        )
    if discovery.warnings:
        return DownloadResult("unavailable", reason="Paper lookup is temporarily unavailable.")
    return DownloadResult(
        "no_pdf_link",
        reason="No direct PDF link was found. Open the paper in your browser or upload a PDF.",
    )


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
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "discovering_fulltext", 10
            ):
                return
            discovery = await discover_fulltext(resources, paper_id)
            payload["discovery_warnings"] = discovery.warnings[:4]
            if not await checkpoint(
                resources, job_id, generation, lease_token, payload, "discovering_fulltext", 30
            ):
                return
            failures = []
            for ordinal, candidate in enumerate(discovery.candidates):
                payload["source_host"] = urlsplit(candidate.url).hostname
                if not await checkpoint(
                    resources, job_id, generation, lease_token, payload, "fetching_pdf", 40
                ):
                    return
                downloaded = await resources.pdf_downloader.fetch(candidate)
                async with resources.sessions() as session, session.begin():
                    if not await record_attempt(
                        session,
                        job_id=job_id,
                        generation=generation,
                        lease_token=lease_token,
                        ordinal=ordinal,
                        candidate=candidate,
                        result=downloaded,
                    ):
                        return
                if downloaded.outcome != "downloaded":
                    failures.append(downloaded)
                    continue
                if not await checkpoint(
                    resources, job_id, generation, lease_token, payload, "storing_pdf", 75
                ):
                    return
                accepted = await ingest_pdf_bytes(
                    resources,
                    data=downloaded.data or b"",
                    filename="retrieved-paper.pdf",
                    request_id=UUID(payload["attachment_request_id"]),
                    paper_id=paper_id,
                    guard=AttachmentGuard(job_id, generation, lease_token, expected),
                    acquisition={
                        "method": "provider_download",
                        "provider": candidate.provider,
                        "candidate_url": candidate.url,
                        "final_url": downloaded.final_url,
                        "is_oa": candidate.location.is_oa,
                        "license": candidate.location.license,
                        "version": candidate.location.version,
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
                return
            priority = [
                "access_required",
                "blocked",
                "rate_limited",
                "unavailable",
                "invalid_pdf",
                "not_found",
                "unsupported_source",
                "unsafe_url",
            ]
            failure = (
                min(failures, key=lambda item: priority.index(item.outcome))
                if failures
                else unchecked(discovery)
            )
            await finish(
                resources,
                job_id,
                generation,
                lease_token,
                {"outcome": failure.outcome, "retry_after": failure.retry_after},
                reason=failure.reason,
            )
    except AttachmentLeaseLost:
        return
    except AttachmentSuperseded:
        await finish(
            resources,
            job_id,
            generation,
            lease_token,
            document_result(await current_document(resources, paper_id), "superseded"),
        )
    except TimeoutError:
        await finish(
            resources,
            job_id,
            generation,
            lease_token,
            {"outcome": "unavailable"},
            reason="PDF retrieval exceeded its time limit. Try again or upload the PDF.",
        )
    except AppError as error:
        if error.status_code >= 500:
            raise
        await finish(
            resources,
            job_id,
            generation,
            lease_token,
            {"outcome": "invalid_pdf"},
            reason=error.message,
        )
