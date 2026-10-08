"""Real service tests: explicit opt-in, isolated DB/bucket/Redis namespace, never SQLite."""

import asyncio
import hashlib
import io
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def test_real_health_schema_and_private_s3_checksum(resources):
    """Given real migrated dependencies, when original bytes roundtrip, then checksum matches."""
    from app.integrations.storage import read_object
    from app.services.health import readiness

    assert await readiness(resources) == {"database": "ok", "storage": "ok", "redis": "ok"}
    original = b"%PDF-1.7\nsynthetic checksum fixture\n%%EOF\n"
    key = uuid4().hex
    bucket = resources.settings.minio_bucket
    await resources.storage_call(
        resources.storage.put_object, bucket, key, io.BytesIO(original), len(original)
    )
    restored = await resources.storage_call(read_object, resources.storage, bucket, key, 1024)
    assert hashlib.sha256(restored).digest() == hashlib.sha256(original).digest()
    from minio.error import S3Error

    with pytest.raises(S3Error) as err:
        await resources.storage_call(resources.storage.get_bucket_policy, bucket)
    assert err.value.code == "NoSuchBucketPolicy"
    await resources.storage_call(resources.storage.remove_object, bucket, key)


async def test_durable_job_claim_duplicate_generation_and_final_write_fencing(resources):
    """Given one job, when duplicate and stale actors claim, then only one owns the result."""
    from app.models.jobs import BackgroundJob, JobOutbox
    from app.repositories.jobs import claim, complete, enqueue

    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="canary", payload={"message": "durable"})
        job_id = job.id
    async with resources.sessions() as session:
        event = await session.scalar(select(JobOutbox).where(JobOutbox.job_id == job_id))
        assert event is not None and event.delivered_at is None
    first, duplicate = await asyncio.gather(
        claim(resources.sessions, job_id, 1), claim(resources.sessions, job_id, 1)
    )
    assert sum(owner is not None for owner in [first, duplicate]) == 1
    owner = first or duplicate
    assert await claim(resources.sessions, job_id, 0) is None
    assert not await complete(resources.sessions, job_id, 1, uuid4(), {"wrong": True})
    assert await complete(resources.sessions, job_id, 1, owner, {"message": "durable"})
    assert not await complete(resources.sessions, job_id, 1, owner, {"overwrite": True})
    async with resources.sessions() as session:
        saved = await session.get(BackgroundJob, job_id)
        assert saved.state == "completed" and saved.attempts == 1
        assert saved.result == {"message": "durable"}


async def test_expired_lease_recovers_with_new_generation_and_total_attempt_cap(resources):
    """Given expired leases, when recovered, then attempts stop at three and stale writes fail."""
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim, complete, enqueue, recover

    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="canary", payload={})
        job_id = job.id
    for generation in range(1, 4):
        lease = await claim(resources.sessions, job_id, generation)
        assert lease is not None
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, job_id)
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert not await complete(resources.sessions, job_id, generation, lease, {})
        await recover(resources.sessions)
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, job_id)
            if generation < 3:
                assert job.state == "queued" and job.generation == generation + 1
                job.available_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                assert job.state == "failed" and job.attempts == 3


async def test_broker_outage_leaves_outbox_pending_and_redelivery_is_safe(resources):
    from app.models.jobs import JobOutbox
    from app.repositories.jobs import enqueue
    from app.services.dispatcher import dispatch_once

    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="canary", payload={})
        job_id = job.id

    def unavailable(job_id, generation):
        raise ConnectionError("fixture broker unavailable")

    await dispatch_once(resources.sessions, unavailable)
    async with resources.sessions() as session:
        event = await session.scalar(select(JobOutbox).where(JobOutbox.job_id == job_id))
        assert event.delivered_at is None
    published = []

    def publish(job_id, generation):
        published.append((job_id, generation))

    await dispatch_once(resources.sessions, publish)
    assert (str(job_id), 1) in published
    async with resources.sessions() as session:
        event = await session.scalar(select(JobOutbox).where(JobOutbox.job_id == job_id))
        assert event.delivered_at is not None


async def test_real_redis_worker_canary_end_to_end(resources):
    """Given a committed outbox, when Redis delivers, then a real worker persists the result."""
    import contextlib
    import sys

    from dramatiq import Message
    from dramatiq.brokers.redis import RedisBroker

    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import enqueue
    from app.services.dispatcher import dispatch_once

    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=resources.settings.database_url.get_secret_value(),
        REDIS_URL=resources.settings.redis_url.get_secret_value(),
        BROKER_NAMESPACE=resources.settings.broker_namespace,
        APP_ENV="test",
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "dramatiq",
        "app.jobs.actors",
        "--processes",
        "1",
        "--threads",
        "2",
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    broker = RedisBroker(
        url=resources.settings.redis_url.get_secret_value(),
        namespace=resources.settings.broker_namespace,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    try:
        async with resources.sessions() as session, session.begin():
            job = await enqueue(session, kind="canary", payload={"message": "real-redis-worker"})
            job_id = job.id

        def publish(job_id, generation):
            broker.enqueue(Message("default", "execute_job", (job_id, generation), {}, {}))

        await dispatch_once(resources.sessions, publish)
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            assert process.returncode is None, "Dramatiq worker exited before processing the canary"
            async with resources.sessions() as session:
                job = await session.get(BackgroundJob, job_id)
                if job.state == "completed":
                    assert job.result == {"message": "real-redis-worker"}
                    assert job.attempts == 1
                    break
            await asyncio.sleep(0.2)
        else:
            pytest.fail("Real Redis worker did not complete canary within 30 seconds")
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 15)
        except TimeoutError:
            process.kill()
            await process.wait()
        await asyncio.to_thread(broker.flush_all)
        await asyncio.to_thread(broker.close)
