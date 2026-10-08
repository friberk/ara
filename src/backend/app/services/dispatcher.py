import asyncio
import logging

from sqlalchemy import func, select

from app.models.jobs import BackgroundJob, JobOutbox
from app.repositories.jobs import now, recover

logger = logging.getLogger(__name__)


async def dispatch_once(sessions, publish) -> None:
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
                await asyncio.to_thread(publish, str(event.job_id), event.generation)
            except Exception:
                logger.warning(
                    "Broker publication failed; durable event remains pending",
                    extra={"job_id": event.job_id},
                )
                break
            event.delivered_at = now()


async def dispatcher_loop(resources, publish) -> None:
    recovered_at = 0.0
    while True:
        try:
            loop = asyncio.get_running_loop()
            if loop.time() - recovered_at >= resources.settings.recovery_interval_seconds:
                await recover(resources.sessions)
                recovered_at = loop.time()
            await dispatch_once(resources.sessions, publish)
        except Exception:
            logger.error("Job dispatcher unavailable; retrying on next poll")
        await asyncio.sleep(resources.settings.dispatch_interval_seconds)
