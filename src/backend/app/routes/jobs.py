from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.core.errors import AppError
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document
from app.repositories.jobs import enqueue, now
from app.schemas.jobs import CanaryInput, JobPage, JobStatus


def router(development: bool) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    @routes.get("", response_model=JobPage)
    async def list_jobs(request: Request, limit: int = Query(default=50, ge=1, le=100)):
        async with request.app.state.resources.sessions() as session:
            jobs = (
                await session.scalars(
                    select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
                )
            ).all()
            return JobPage(items=[JobStatus.model_validate(job) for job in jobs])

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
    async def retry_job(job_id: UUID, request: Request):
        async with request.app.state.resources.sessions() as session, session.begin():
            job = await session.scalar(
                select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update()
            )
            if job is None:
                raise AppError(404, "JOB_NOT_FOUND", "Job not found.")
            if job.state != "failed":
                raise AppError(
                    409, "JOB_NOT_RETRYABLE", "Only eligible failed jobs can be retried."
                )
            if job.kind == "summary":
                raise AppError(
                    409,
                    "NEW_GENERATION_REQUEST_REQUIRED",
                    "Start a new summary request to avoid replaying uncertain paid inference.",
                )
            if job.error_code not in {
                "JOB_EXECUTION_FAILED",
                "LEASE_EXPIRED",
                "STORAGE_UNAVAILABLE",
                "PDF_PARSE_TIMEOUT",
                "PDF_PARSE_FAILED",
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
            return JobStatus.model_validate(job)

    @routes.get("/{job_id}", response_model=JobStatus)
    async def get_job(job_id: UUID, request: Request):
        async with request.app.state.resources.sessions() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return JobStatus.model_validate(job)

    return routes
