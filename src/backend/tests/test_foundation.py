import io
import json
import logging

import httpx
import pytest


def test_environment_overrides_dotenv_and_secrets_are_redacted(tmp_path, monkeypatch):
    """Given dotenv defaults, when environment overrides them, then no secret is exposed."""
    from app.core.config import Settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_ENV=production\nMINIO_SECRET_KEY=dotenv-secret\n")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
    settings = Settings(_env_file=dotenv)
    assert settings.app_env == "development"
    assert settings.minio_secret_key.get_secret_value() == "dotenv-secret"
    assert "dotenv-secret" not in repr(settings)
    assert "dotenv-secret" not in settings.model_dump_json()


def test_json_logging_redacts_configured_secrets():
    from app.core.logging import JsonFormatter

    record = logging.LogRecord("test", logging.ERROR, "", 0, "failure top-secret", (), None)
    rendered = JsonFormatter(secrets=["top-secret"]).format(record)
    assert json.loads(rendered)["message"] == "failure [REDACTED]"
    assert "top-secret" not in rendered


async def test_liveness_without_external_credentials_and_structured_errors():
    """Given no live dependencies, when liveness is requested, then it succeeds."""
    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/health/live", headers={"X-Request-ID": "unsafe\nrequest"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert "\n" not in response.headers["x-request-id"]
        error = await c.get("/api/v1/jobs/not-a-uuid")
        assert error.status_code == 422
        assert error.json()["code"] == "VALIDATION_ERROR"
        assert error.json()["request_id"] == error.headers["x-request-id"]
        assert "message" in error.json() and "details" in error.json()
        missing = await c.get("/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"


async def test_production_canary_is_unavailable():
    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(app_env="production", _env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/api/v1/jobs/canary", json={})
    assert response.status_code == 404
    assert "/api/v1/jobs/canary" not in app.openapi()["paths"]


def test_bucket_initializer_creates_private_bucket_without_policy():
    from app.core.storage_init import initialize_bucket

    class Storage:
        def __init__(self):
            self.exists = False
            self.created = []

        def bucket_exists(self, bucket):
            return self.exists

        def make_bucket(self, bucket):
            self.exists = True
            self.created.append(bucket)

        def delete_bucket_policy(self, bucket):
            self.policy_deleted = bucket

    storage = Storage()
    initialize_bucket(storage, "private")
    initialize_bucket(storage, "private")
    assert storage.created == ["private"]
    assert storage.policy_deleted == "private"


def test_storage_roundtrip_verifies_bytes_and_always_releases_response():
    from app.integrations.storage import read_object

    class Response(io.BytesIO):
        released = False

        def release_conn(self):
            self.released = True

    class Storage:
        def get_object(self, bucket, key):
            self.response = Response(b"known-original")
            return self.response

    storage = Storage()
    assert read_object(storage, "private", "object", 100) == b"known-original"
    assert storage.response.closed and storage.response.released
    with pytest.raises(ValueError, match="size limit"):
        read_object(storage, "private", "object", 2)
    assert storage.response.closed and storage.response.released


def test_job_error_contract_is_safe_nullable_object():
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.schemas.jobs import JobStatus

    job = JobStatus(
        id=uuid4(),
        kind="canary",
        state="failed",
        stage="failed",
        progress=0,
        attempts=3,
        generation=3,
        result=None,
        error_code="LEASE_EXPIRED",
        error_message="Worker lease expired; recovering.",
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert job.model_dump()["error"] == {
        "code": "LEASE_EXPIRED",
        "message": "Worker lease expired; recovering.",
    }
    job.error_code = None
    job.error_message = None
    assert job.model_dump()["error"] is None
