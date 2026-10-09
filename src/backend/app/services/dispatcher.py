import asyncio
import logging
from contextlib import suppress

from sqlalchemy import func, select

from app.models.jobs import BackgroundJob, JobOutbox
from app.repositories.jobs import now, recover

logger = logging.getLogger(__name__)


async def dispatch_once(sessions, publish, *, model_publish=None, local_publish=None) -> None:
    # Lock until publish and commit; a crash after publish produces safe redelivery.
    async with sessions() as session, session.begin():
        events = (
            await session.scalars(
                select(JobOutbox)
                .join(BackgroundJob, JobOutbox.job_id == BackgroundJob.id)
                .where(
                    JobOutbox.delivered_at.is_(None),
                    JobOutbox.available_at <= func.now(),
                    BackgroundJob.state == "queued",
                    BackgroundJob.generation == JobOutbox.generation,
                )
                .order_by(JobOutbox.created_at)
                .with_for_update(of=JobOutbox, skip_locked=True)
                .limit(20)
            )
        ).all()
        for event in events:
            try:
                # Redis client has a five-second socket deadline; dispatch calls are serial/bounded.
                from app.integrations.model_catalog import local_spec

                job = await session.get(BackgroundJob, event.job_id)
                publisher = publish
                if job.kind in {"model_download", "model_delete"} and model_publish:
                    publisher = model_publish
                elif (
                    job.kind == "summary" and local_spec(job.payload.get("model")) and local_publish
                ):
                    publisher = local_publish
                await asyncio.to_thread(publisher, str(event.job_id), event.generation)
            except Exception:
                logger.warning(
                    "Broker publication failed; durable event remains pending",
                    extra={"job_id": event.job_id},
                )
                break
            event.delivered_at = now()


async def dispatcher_loop(resources, publish, *, model_publish=None, local_publish=None) -> None:
    from app.services.local_models import reconcile_local_models

    recovered_at = prepared_at = 0.0
    preparation = None

    async def prepare():
        try:
            await reconcile_local_models(resources)
        except Exception:
            logger.warning("Automatic model preparation unavailable; retrying later")

    try:
        while True:
            try:
                loop = asyncio.get_running_loop()
                if loop.time() - recovered_at >= resources.settings.recovery_interval_seconds:
                    await recover(resources.sessions)
                    recovered_at = loop.time()
                if loop.time() - prepared_at >= resources.settings.recovery_interval_seconds and (
                    preparation is None or preparation.done()
                ):
                    preparation = asyncio.create_task(prepare())
                    prepared_at = loop.time()
                await dispatch_once(
                    resources.sessions,
                    publish,
                    model_publish=model_publish,
                    local_publish=local_publish,
                )
            except Exception:
                logger.error("Job dispatcher unavailable; retrying on next poll")
            await asyncio.sleep(resources.settings.dispatch_interval_seconds)
    finally:
        if preparation is not None:
            preparation.cancel()
            with suppress(asyncio.CancelledError):
                await preparation
