"""Separate bounded worker lanes keep long local operations off PDF/hosted workers."""

import asyncio
import traceback
from contextlib import suppress
from datetime import timedelta
from uuid import UUID

import dramatiq
from sqlalchemy import select

from app.core.errors import AppError
from app.jobs import actors
from app.models.jobs import BackgroundJob, JobOutbox
from app.repositories.jobs import claim, fail, fence, heartbeat, now


def worker_resources():
    from app.jobs import actors

    if actors._resources is None:
        raise RuntimeError("Worker resources are not initialized")
    return actors._resources


@dramatiq.actor(
    broker=actors.broker, queue_name="local-models", max_retries=0, time_limit=21_660_000
)
async def execute_model_job(job_id: str, generation: int) -> None:
    from app.services.local_models import execute_model_attempt

    resources = worker_resources()
    try:
        await execute_model_attempt(resources, UUID(job_id), generation)
    except Exception as error:
        # Recovery only advances a stale lease. It preserves desired pause state and inventory.
        from app.jobs.actors import logger

        frame = traceback.extract_tb(error.__traceback__)[-1]
        code = error.code if isinstance(error, AppError) else "UNEXPECTED_MODEL_ERROR"
        logger.error(
            "Local model maintenance failed; durable lease recovery will reconcile it "
            "(error_type=%s, error_code=%s, function=%s, line=%s)",
            type(error).__name__,
            code,
            frame.name,
            frame.lineno,
            extra={"job_id": job_id},
        )


async def requeue_busy_summary(resources, job_id, generation, token):
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return
        job.state, job.stage = "queued", "local_runtime_wait"
        job.generation += 1
        job.attempts = max(0, job.attempts - 1)
        job.lease_token = job.lease_expires_at = None
        job.available_at = now() + timedelta(seconds=10)
        job.updated_at = now()
        session.add(
            JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at)
        )


@dramatiq.actor(
    broker=actors.broker, queue_name="local-generation", max_retries=0, time_limit=21_660_000
)
async def execute_local_summary(job_id: str, generation: int) -> None:
    from app.integrations.llm import LLMError
    from app.services.summarization import run_summary_job

    resources, identifier = worker_resources(), UUID(job_id)
    token = await claim(resources.sessions, identifier, generation, 60)
    if token is None:
        return
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
    if job.kind != "summary":
        await fail(resources.sessions, identifier, generation, token, permanent=True)
        return
    work = asyncio.create_task(
        run_summary_job(resources, identifier, generation, token, job.payload)
    )
    try:
        async with asyncio.timeout(21_600):
            while not work.done():
                done, _ = await asyncio.wait({work}, timeout=10)
                if done:
                    break
                if not await heartbeat(resources.sessions, identifier, generation, token, 60):
                    work.cancel()
                    break
            await work
    except (LLMError, AppError) as error:
        if error.code == "LOCAL_MODEL_BUSY":
            await requeue_busy_summary(resources, identifier, generation, token)
        else:
            await fail(resources.sessions, identifier, generation, token)
    except Exception:
        await fail(resources.sessions, identifier, generation, token)
    finally:
        work.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await work
