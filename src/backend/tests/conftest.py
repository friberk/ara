import os
from uuid import uuid4

import pytest
from sqlalchemy import delete


@pytest.fixture
async def resources():
    if os.environ.get("ARA_INTEGRATION") != "1":
        pytest.skip("ARA_INTEGRATION=1 and ARA_TEST_DATABASE_URL are required")
    from urllib.parse import urlsplit, urlunsplit

    from app.core.config import Settings
    from app.core.resources import Resources

    url = os.environ.get("ARA_TEST_DATABASE_URL")
    assert url and "test" in url.rsplit("/", 1)[-1], "use an isolated migrated test database"
    settings = Settings(database_url=url, minio_bucket=f"ara-test-{uuid4().hex}", app_env="test")
    redis_parts = urlsplit(settings.redis_url.get_secret_value())
    test_redis_url = urlunsplit(redis_parts._replace(path="/15"))
    # Revalidate secrets after assignment; use a unique broker namespace per fixture.
    settings = Settings(
        **{
            **settings.model_dump(),
            "redis_url": test_redis_url,
            "broker_namespace": f"ara-test-{uuid4().hex}",
        }
    )
    resources = Resources(settings)
    from app.models.jobs import BackgroundJob
    from app.models.research import GenerationReservation, ModelConfiguration, Paper

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Paper))
        await session.execute(delete(ModelConfiguration))
        await session.execute(delete(GenerationReservation))
        await session.execute(delete(BackgroundJob))
    await resources.storage_call(resources.storage.make_bucket, settings.minio_bucket)
    try:
        yield resources
    finally:
        objects = await resources.storage_call(
            lambda: list(resources.storage.list_objects(settings.minio_bucket, recursive=True))
        )
        for obj in objects:
            await resources.storage_call(
                resources.storage.remove_object, settings.minio_bucket, obj.object_name
            )
        await resources.storage_call(resources.storage.remove_bucket, settings.minio_bucket)
        async with resources.sessions() as session, session.begin():
            await session.execute(delete(Paper))
            await session.execute(delete(ModelConfiguration))
            await session.execute(delete(GenerationReservation))
            await session.execute(delete(BackgroundJob))
        await resources.close()
