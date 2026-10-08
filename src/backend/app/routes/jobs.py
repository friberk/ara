from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import String, and_, cast, or_, select

from app.core.errors import AppError
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document
from app.repositories.jobs import enqueue, job_statuses, now
from app.schemas.jobs import CanaryInput, JobPage, JobStatus


def router(development: bool) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    @routes.get("", response_model=JobPage)
    async def list_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        paper_id: UUID | None = None,
        kind: Literal["ingest", "summary"] | None = None,
        active: bool | None = None,
    ):
        statement = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
        if kind is not None:
            statement = statement.where(BackgroundJob.kind == kind)
        if active is not None:
            # retry_wait is a stage of the queued state, so active jobs include it.
            states = ["queued", "processing"] if active else ["completed", "failed"]
            statement = statement.where(BackgroundJob.state.in_(states))
        if paper_id is not None:
            documents = select(cast(Document.id, String)).where(Document.paper_id == paper_id)
            statement = statement.where(
                or_(
                    and_(
                        BackgroundJob.kind == "summary",
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
            return (await job_statuses(session, [job]))[0]

    @routes.get("/{job_id}", response_model=JobStatus)
    async def get_job(job_id: UUID, request: Request):
        async with request.app.state.resources.sessions() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return (await job_statuses(session, [job]))[0]

    return routes
