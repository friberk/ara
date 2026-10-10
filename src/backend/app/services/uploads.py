import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.core.errors import AppError
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document, DocumentUploadRequest, Paper
from app.repositories.jobs import enqueue, fence, now
from app.repositories.papers import identity_locks
from app.schemas.research import UploadAccepted

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class AttachmentGuard:
    job_id: UUID
    generation: int
    lease_token: UUID
    expected_active_document_id: UUID | None


class AttachmentLeaseLost(Exception):
    pass


class AttachmentSuperseded(Exception):
    pass


async def check_storage_owner(session, guard: AttachmentGuard | None):
    if (
        guard
        and await session.scalar(
            select(BackgroundJob)
            .where(*fence(guard.job_id, guard.generation, guard.lease_token))
            .with_for_update()
        )
        is None
    ):
        raise AttachmentLeaseLost


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
    return await ingest_pdf_bytes(
        resources,
        data=bytes(data),
        filename=file.filename or "paper.pdf",
        request_id=request_id,
        paper_id=paper_id,
    )


async def ingest_pdf_bytes(
    resources,
    *,
    data: bytes,
    filename: str,
    request_id: UUID,
    paper_id: UUID | None,
    guard: AttachmentGuard | None = None,
    acquisition: dict | None = None,
) -> UploadAccepted:
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(413, "PDF_SIZE_LIMIT", "Upload a PDF smaller than 25 MiB.")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise AppError(415, "INVALID_PDF_SIGNATURE", "Upload a valid PDF file.")
    digest = hashlib.sha256(data).hexdigest()
    async with resources.sessions() as session, session.begin():
        if guard:
            owned = await session.scalar(
                select(BackgroundJob)
                .where(*fence(guard.job_id, guard.generation, guard.lease_token))
                .with_for_update()
            )
            if owned is None:
                raise AttachmentLeaseLost
        await identity_locks(session, [f"pdf:{digest}", f"upload:{request_id}"])
        binding = await session.get(DocumentUploadRequest, request_id)
        existing = (
            await session.get(Document, binding.document_id)
            if binding
            else await session.scalar(select(Document).where(Document.sha256 == digest))
        )
        paper = None
        if paper_id:
            paper = await session.scalar(
                select(Paper).where(Paper.id == paper_id).with_for_update()
            )
            if paper is None:
                raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        if guard and (
            paper is None
            or (
                paper.active_document_id != guard.expected_active_document_id
                and (binding is None or paper.active_document_id != binding.document_id)
            )
        ):
            raise AttachmentSuperseded
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
                    details=[{"paper_id": str(existing.paper_id)}],
                )
            if guard and paper:
                paper.active_document_id = existing.id
            revived = False
            if binding is None and not guard and existing.status == "ready":
                # A PDF kept for older chats after Remove PDF, or an earlier version, uploaded
                # again becomes its paper's current PDF; from the home page only when the paper
                # has none (ARA-097).
                owner = paper or await session.scalar(
                    select(Paper).where(Paper.id == existing.paper_id).with_for_update()
                )
                revived = owner.active_document_id != existing.id and (
                    paper is not None or owner.active_document_id is None
                )
                if revived:
                    owner.active_document_id = existing.id
            if binding is None:
                session.add(DocumentUploadRequest(request_id=request_id, document_id=existing.id))
            job = await session.get(BackgroundJob, existing.ingest_job_id)
            interrupted_owned_upload = guard and binding and existing.status == "uploading"
            if not interrupted_owned_upload and (
                job is None
                or job.state != "failed"
                or job.error_code not in {"STORAGE_UPLOAD_FAILED", "STORAGE_OBJECT_MISSING"}
            ):
                # A new request for bytes already stored opens that paper; a replay is not new.
                return references(existing).model_copy(
                    update={"duplicate": binding is None and not revived}
                )
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
            if paper is None:
                paper = Paper(metadata_provenance={})
                session.add(paper)
                await session.flush()
            document_id = uuid4()
            document = Document(
                id=document_id,
                paper_id=paper.id,
                object_key=f"originals/{document_id}.pdf",
                sha256=digest,
                original_filename=PurePath(filename.replace("\\", "/")).name[:160],
                byte_size=len(data),
                request_id=request_id,
                status="uploading",
                warnings=[],
                acquisition=acquisition,
            )
            session.add(document)
            await session.flush()
            payload = {"document_id": str(document.id)}
            if paper_id is None:
                # Created for this upload: ingestion may find it is a library paper (ARA-086).
                payload["new_paper"] = True
            job = await enqueue(session, kind="ingest", payload=payload)
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
            await check_storage_owner(session, guard)
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
    await activate_ingestion(resources, accepted, generation, guard)
    return accepted


async def activate_ingestion(
    resources, accepted: UploadAccepted, generation: int, guard: AttachmentGuard | None = None
):
    async with resources.sessions() as session, session.begin():
        await check_storage_owner(session, guard)
        await session.execute(
            update(Document)
            .where(Document.id == accepted.document_id, Document.status == "uploading")
            .values(status="processing")
        )
        await session.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == accepted.job_id,
                BackgroundJob.generation == generation,
                BackgroundJob.state == "queued",
            )
            .values(available_at=func.now())
        )
        await session.execute(
            update(JobOutbox)
            .where(JobOutbox.job_id == accepted.job_id, JobOutbox.generation == generation)
            .values(available_at=func.now())
        )
