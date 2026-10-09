import asyncio
import logging
from contextlib import suppress
from uuid import UUID

import dramatiq
from dramatiq.asyncio import get_event_loop_thread
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO, Middleware
from sqlalchemy import select

from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.resources import Resources
from app.models.jobs import BackgroundJob
from app.repositories.jobs import claim, complete, fail, heartbeat

settings = Settings()
broker = RedisBroker(
    url=settings.redis_url.get_secret_value(),
    namespace=settings.broker_namespace,
    socket_timeout=5,
    socket_connect_timeout=5,
)
broker.add_middleware(AsyncIO())
dramatiq.set_broker(broker)
_resources: Resources | None = None
logger = logging.getLogger(__name__)


async def start_resources() -> None:
    global _resources
    configure_logging(settings.secret_values())
    _resources = Resources(settings)


async def stop_resources() -> None:
    global _resources
    if _resources is not None:
        await _resources.close()
        _resources = None


class WorkerResources(Middleware):
    def after_worker_boot(self, broker, worker):
        get_event_loop_thread().run_coroutine(start_resources())

    def after_worker_shutdown(self, broker, worker):
        # after_* hooks run in reverse registration order: close before AsyncIO stops.
        get_event_loop_thread().run_coroutine(stop_resources())


broker.add_middleware(WorkerResources())


async def keep_alive(resources, job_id, generation, token):
    while True:
        await asyncio.sleep(resources.settings.heartbeat_seconds)
        if not await heartbeat(
            resources.sessions, job_id, generation, token, resources.settings.lease_seconds
        ):
            return


@dramatiq.actor(max_retries=0, time_limit=660_000)
async def execute_job(job_id: str, generation: int) -> None:
    resources = _resources
    if resources is None:
        raise RuntimeError("Worker resources are not initialized")
    identifier = UUID(job_id)
    token = await claim(
        resources.sessions, identifier, generation, resources.settings.lease_seconds
    )
    if token is None:
        return
    heartbeats = asyncio.create_task(keep_alive(resources, identifier, generation, token))
    try:
        async with resources.sessions() as session:
            job = await session.scalar(select(BackgroundJob).where(BackgroundJob.id == identifier))
            kind, payload = job.kind, job.payload
        if kind == "ingest":
            from app.services.ingestion import run_ingest_job

            await run_ingest_job(resources, identifier, generation, token, payload)
        elif kind == "fulltext":
            from app.services.fulltext import run_fulltext_job

            running = asyncio.create_task(
                run_fulltext_job(resources, identifier, generation, token, payload)
            )
            try:
                done, _ = await asyncio.wait(
                    (running, heartbeats), return_when=asyncio.FIRST_COMPLETED
                )
                if running not in done:
                    running.cancel()
                    with suppress(asyncio.CancelledError):
                        await running
                    await heartbeats
                else:
                    await running
            finally:
                if not running.done():
                    running.cancel()
                    with suppress(asyncio.CancelledError):
                        await running
        elif kind == "summary":
            from app.services.summarization import run_summary_job

            await run_summary_job(resources, identifier, generation, token, payload)
        elif kind == "canary":
            await complete(
                resources.sessions,
                identifier,
                generation,
                token,
                {"message": payload.get("message", "pipeline-ok")},
            )
        else:
            await fail(resources.sessions, identifier, generation, token, permanent=True)

    except Exception:
        logger.error("Job execution failed", extra={"job_id": identifier})
        await fail(resources.sessions, identifier, generation, token)
    finally:
        heartbeats.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeats


# Register dedicated actors when Dramatiq imports this module as its worker entrypoint.
from app.jobs import model_actors  # noqa: E402,F401
