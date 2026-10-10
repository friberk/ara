from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import String, and_, cast, or_, select

from app.core.errors import AppError
from app.integrations.open_models import MODEL_OPERATIONS
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document
from app.repositories.jobs import enqueue, job_statuses, now
from app.schemas.jobs import CanaryInput, JobPage, JobRetryInput, JobStatus, ModelOperationInput
from app.services.local_models import transition_job
from app.services.pdf_removal import PDF_REMOVED


def router(development: bool, *, open_models: bool = True) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    def hidden(job: BackgroundJob | None) -> bool:
        # Model operations do not exist while open models are off (ARA-090).
        return job is not None and not open_models and job.kind in MODEL_OPERATIONS

    @routes.get("", response_model=JobPage)
    async def list_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        paper_id: UUID | None = None,
        kind: Literal[
            "ingest",
            "summary",
            "section_summaries",
            "fulltext",
            "metadata",
            "model_download",
            "model_delete",
        ]
        | None = None,
        active: bool | None = None,
    ):
        statement = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
        if kind is not None:
            statement = statement.where(BackgroundJob.kind == kind)
        if not open_models:
            statement = statement.where(BackgroundJob.kind.not_in(MODEL_OPERATIONS))
        if active is not None:
            # retry_wait is a stage of the queued state, so active jobs include it.
            states = ["queued", "processing", "paused"] if active else ["completed", "failed"]
            statement = statement.where(BackgroundJob.state.in_(states))
        if paper_id is not None:
            documents = select(cast(Document.id, String)).where(Document.paper_id == paper_id)
            statement = statement.where(
                or_(
                    and_(
                        BackgroundJob.kind.in_(
                            ["summary", "section_summaries", "fulltext", "embed", "metadata"]
                        ),
                        BackgroundJob.payload["paper_id"].astext == str(paper_id),
                    ),
                    and_(
                        BackgroundJob.kind == "ingest",
                        BackgroundJob.payload["document_id"].astext.in_(documents),
                    ),
                )
            )
        async with request.app.state.resources.sessions() as session:
            jobs = (await session.scalars(statement)).all()
            return JobPage(items=await job_statuses(session, list(jobs)))

    if development:

        @routes.post("/canary", response_model=JobStatus, status_code=202)
        async def canary(body: CanaryInput, request: Request):
            async with request.app.state.resources.sessions() as session, session.begin():
                job = await enqueue(session, kind="canary", payload=body.model_dump())
                return JobStatus.model_validate(job)

    else:

        @routes.post("/canary", include_in_schema=False)
        async def disabled_canary():
            raise HTTPException(status_code=404, detail="Not found")

    @routes.post("/{job_id}/retry", response_model=JobStatus, status_code=202)
    async def retry_job(job_id: UUID, request: Request, body: JobRetryInput | None = None):
        async with request.app.state.resources.sessions() as lookup:
            local_job = await lookup.get(BackgroundJob, job_id)
            if hidden(local_job):
                raise AppError(404, "JOB_NOT_FOUND", "Job not found.")
            if local_job and local_job.kind in {"model_download", "model_delete"}:
                if body is None or body.request_id is None:
                    raise AppError(
                        422,
                        "MODEL_REQUEST_ID_REQUIRED",
                        "Local model retries require a request UUID.",
                    )
                return await transition_job(
                    request.app.state.resources, job_id, "retry", body.request_id
                )
        async with request.app.state.resources.sessions() as session, session.begin():
            job = await session.scalar(
                select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update()
            )
            if job is None:
                raise AppError(404, "JOB_NOT_FOUND", "Job not found.")
            if job.kind == "fulltext":
                raise AppError(
                    409,
                    "NEW_FULLTEXT_REQUEST_REQUIRED",
                    "Start a new PDF retrieval request to retry access.",
                )
            if job.state != "failed":
                raise AppError(
                    409, "JOB_NOT_RETRYABLE", "Only eligible failed jobs can be retried."
                )
            if job.kind in {"summary", "section_summaries"}:
                raise AppError(
                    409,
                    "NEW_GENERATION_REQUEST_REQUIRED",
                    "Start a new summary request to avoid replaying uncertain paid inference.",
                )
            if job.kind == "ingest":
                removed = await session.get(Document, UUID(job.payload["document_id"]))
                if removed is not None and removed.removed:
                    raise AppError(
                        409, PDF_REMOVED, "This PDF was removed. Upload it again instead."
                    )
            if job.error_code not in {
                "JOB_EXECUTION_FAILED",
                "LEASE_EXPIRED",
                "STORAGE_UNAVAILABLE",
                "PDF_PARSE_TIMEOUT",
                "PDF_PARSE_FAILED",
                # A metadata lookup that ran out of attempts while sources were busy (ARA-086).
                "PROVIDER_RATE_LIMITED",
                "PROVIDER_UNAVAILABLE",
            }:
                raise AppError(
                    409, "JOB_NOT_RETRYABLE", "This failure needs a corrected upload or request."
                )
            job.state, job.stage, job.progress = "queued", "queued", 0
            job.attempts, job.generation = 0, job.generation + 1
            job.error_code, job.error_message = None, None
            job.lease_token, job.lease_expires_at = None, None
            job.available_at = job.updated_at = now()
            session.add(
                JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at)
            )
            if job.kind == "ingest":
                document = await session.get(Document, UUID(job.payload["document_id"]))
                if document:
                    document.status, document.warnings = "processing", []
            await session.flush()
            return (await job_statuses(session, [job]))[0]

    if open_models:

        @routes.post("/{job_id}/pause", response_model=JobStatus, status_code=202)
        async def pause_job(job_id: UUID, body: ModelOperationInput, request: Request):
            return await transition_job(
                request.app.state.resources, job_id, "pause", body.request_id
            )

        @routes.post("/{job_id}/resume", response_model=JobStatus, status_code=202)
        async def resume_job(job_id: UUID, body: ModelOperationInput, request: Request):
            return await transition_job(
                request.app.state.resources, job_id, "resume", body.request_id
            )

    @routes.get("/{job_id}", response_model=JobStatus)
    async def get_job(job_id: UUID, request: Request):
        async with request.app.state.resources.sessions() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None or hidden(job):
                raise HTTPException(status_code=404, detail="Job not found")
            return (await job_statuses(session, [job]))[0]

    return routes
