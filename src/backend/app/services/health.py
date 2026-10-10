import asyncio

from sqlalchemy import text

SCHEMA_REVISION = "0011_section_summaries"


async def readiness(resources) -> dict[str, str]:
    async def database():
        async with resources.sessions() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            if version != SCHEMA_REVISION:
                raise ValueError("Migrations are not current")
            await session.execute(text("SELECT id FROM background_jobs LIMIT 0"))
            await session.execute(text("SELECT id FROM job_outbox LIMIT 0"))

    async def storage():
        if not await resources.storage_call(
            resources.storage.bucket_exists, resources.settings.minio_bucket
        ):
            raise ValueError("Storage bucket is missing")

    async def redis():
        await resources.redis.ping()

    checks = await asyncio.gather(database(), storage(), redis(), return_exceptions=True)
    return {
        name: "unavailable" if isinstance(result, BaseException) else "ok"
        for name, result in zip(("database", "storage", "redis"), checks, strict=True)
    }
