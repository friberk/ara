import os
from uuid import uuid4

import httpx
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
    # Answers rerank with OpenAI Decisions by default (ARA-074); tests that set a fixture key
    # get the in-process Decisions fixture instead of the real API.
    from tests.support.providers import OfflineOpenAI

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=OfflineOpenAI(settings.openai_base_url, []), timeout=httpx.Timeout(20, connect=5)
    )
    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation, ModelRequest, ModelUse
    from app.models.research import (
        GenerationReservation,
        ModelConfiguration,
        Paper,
        SearchHistory,
    )

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(ModelUse))
        await session.execute(delete(ModelRequest))
        await session.execute(delete(ModelInstallation))
        await session.execute(delete(Paper))
        await session.execute(delete(ModelConfiguration))
        await session.execute(delete(GenerationReservation))
        await session.execute(delete(BackgroundJob))
        await session.execute(delete(SearchHistory))
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
            await session.execute(delete(ModelUse))
            await session.execute(delete(ModelRequest))
            await session.execute(delete(ModelInstallation))
            await session.execute(delete(Paper))
            await session.execute(delete(ModelConfiguration))
            await session.execute(delete(GenerationReservation))
            await session.execute(delete(BackgroundJob))
            await session.execute(delete(SearchHistory))
        await resources.close()


def external(host: str) -> bool:
    """Compose services ("ollama"), fixture hosts and loopback stay local; dotted hosts do not."""
    return "." in host and host not in {"127.0.0.1", "::1"} and not host.startswith("127.")


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """No test reaches a real external provider such as api.openai.com (ARA-074).

    In-process transports never get here. A real request to an external host is refused, and
    the test fails at teardown even when the code under test swallowed the error.
    """
    attempts = []
    send_async = httpx.AsyncHTTPTransport.handle_async_request
    send = httpx.HTTPTransport.handle_request

    def refuse(request):
        attempts.append(str(request.url))
        raise httpx.ConnectError("Tests never reach external providers.", request=request)

    async def guarded_async(self, request):
        if external(request.url.host):
            refuse(request)
        return await send_async(self, request)

    def guarded(self, request):
        if external(request.url.host):
            refuse(request)
        return send(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)
    yield attempts
    assert attempts == [], f"Tests must not reach external providers: {attempts}"
