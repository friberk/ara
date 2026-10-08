import hashlib
import io
from datetime import timedelta
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.core.errors import AppError
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document, DocumentUploadRequest, Paper
from app.repositories.jobs import enqueue, now
from app.repositories.papers import identity_locks
from app.schemas.research import UploadAccepted

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def references(document: Document) -> UploadAccepted:
    if document.ingest_job_id is None:
        raise AppError(
            409, "UPLOAD_IN_PROGRESS", "The original upload is still being recorded.", retry_after=2
        )
    return UploadAccepted(
        paper_id=document.paper_id, document_id=document.id, job_id=document.ingest_job_id
    )


async def upload(resources, file, request_id: UUID, paper_id: UUID | None) -> UploadAccepted:
    data = bytearray()
    while block := await file.read(1024 * 1024):
        data.extend(block)
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppError(413, "PDF_SIZE_LIMIT", "Upload a PDF smaller than 25 MiB.")
    if file.content_type not in {"application/pdf", "application/octet-stream"} or not data[
        :1024
    ].lstrip().startswith(b"%PDF-"):
        raise AppError(415, "INVALID_PDF_SIGNATURE", "Upload a valid PDF file.")
    digest = hashlib.sha256(data).hexdigest()
    async with resources.sessions() as session, session.begin():
        await identity_locks(session, [f"pdf:{digest}", f"upload:{request_id}"])
        binding = await session.get(DocumentUploadRequest, request_id)
        existing = (
            await session.get(Document, binding.document_id)
            if binding
            else await session.scalar(select(Document).where(Document.sha256 == digest))
        )
        grace = now() + timedelta(seconds=120)
        if existing:
            if binding and existing.sha256 != digest:
                raise AppError(
                    409,
                    "UPLOAD_REQUEST_CONFLICT",
                    "This request ID was already used for a different file.",
                )
            if paper_id and existing.paper_id != paper_id:
                raise AppError(
                    409,
                    "DOCUMENT_ALREADY_ATTACHED",
                    "This PDF belongs to another paper. Open that paper to reconcile it.",
                )
            if binding is None:
                session.add(DocumentUploadRequest(request_id=request_id, document_id=existing.id))
            job = await session.get(BackgroundJob, existing.ingest_job_id)
            if (
                job is None
                or job.state != "failed"
                or job.error_code not in {"STORAGE_UPLOAD_FAILED", "STORAGE_OBJECT_MISSING"}
            ):
                return references(existing)
            # Same bytes can resume an interrupted upload using the retained object key.
            existing.status, existing.warnings = "uploading", []
            job.state, job.stage, job.progress = "queued", "queued", 0
            job.attempts, job.generation = 0, job.generation + 1
            job.error_code, job.error_message, job.result = None, None, None
            job.lease_token, job.lease_expires_at = None, None
            job.available_at = grace
            job.updated_at = now()
            session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=grace))
            document_id, key = existing.id, existing.object_key
            accepted = references(existing)
        else:
            if paper_id:
                paper = await session.get(Paper, paper_id)
                if paper is None:
                    raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
            else:
                paper = Paper(metadata_provenance={})
                session.add(paper)
                await session.flush()
            document_id = uuid4()
            document = Document(
                id=document_id,
                paper_id=paper.id,
                object_key=f"originals/{document_id}.pdf",
                sha256=digest,
                original_filename=PurePath((file.filename or "paper.pdf").replace("\\", "/")).name[
                    :160
                ],
                byte_size=len(data),
                request_id=request_id,
                status="uploading",
                warnings=[],
            )
            session.add(document)
            await session.flush()
            job = await enqueue(session, kind="ingest", payload={"document_id": str(document.id)})
            # The delayed durable job recovers a crash between DB commit and S3 completion.
            job.available_at = grace
            await session.execute(
                update(JobOutbox).where(JobOutbox.job_id == job.id).values(available_at=grace)
            )
            document.ingest_job_id = job.id
            session.add(DocumentUploadRequest(request_id=request_id, document_id=document.id))
            paper.active_document_id = document.id
            accepted, key = references(document), document.object_key
        generation = job.generation
    try:
        await resources.storage_call(
            resources.storage.put_object,
            resources.settings.minio_bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type="application/pdf",
        )
    except Exception:
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(Document).where(Document.id == document_id).values(status="failed")
            )
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == accepted.job_id, BackgroundJob.generation == generation)
                .values(
                    state="failed",
                    stage="failed",
                    error_code="STORAGE_UPLOAD_FAILED",
                    error_message="The original PDF could not be stored. Try the upload again.",
                    updated_at=func.now(),
                )
            )
        raise AppError(
            503, "STORAGE_UNAVAILABLE", "PDF storage is unavailable. Try again shortly."
        ) from None
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == "uploading")
            .values(status="processing")
        )
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == accepted.job_id, BackgroundJob.generation == generation)
            .values(available_at=func.now())
        )
        await session.execute(
            update(JobOutbox)
            .where(JobOutbox.job_id == accepted.job_id, JobOutbox.generation == generation)
            .values(available_at=func.now())
        )
    return accepted
