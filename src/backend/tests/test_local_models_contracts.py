from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.ai import Model
from app.schemas.jobs import JobStatus


def test_local_catalog_has_exact_pinned_artifacts():
    from app.integrations.model_catalog import LOCAL_MODELS, local_spec

    assert set(LOCAL_MODELS) == {"ifm-k2-horizon-3.7b", "ifm-k2-horizon-7b", "qwen3.8-27b"}
    assert local_spec("qwen3.8-27b").model_id == "qwen3.8:27b-q4_K_M"
    assert local_spec("ifm-k2-horizon-3.7b").download_bytes == 3156599066
    assert (
        local_spec("ifm-k2-horizon-7b").expected_digest
        == "3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278"
    )
    assert local_spec("unknown") is None


def test_local_contract_preserves_pause_and_artifact_information():
    stamp = datetime.now(UTC)
    job = JobStatus(
        id=uuid4(),
        kind="model_download",
        state="paused",
        stage="paused",
        progress=17,
        attempts=0,
        generation=2,
        result=None,
        error_code=None,
        error_message=None,
        available_at=stamp,
        created_at=stamp,
        updated_at=stamp,
        model_key="local",
        completed_bytes=17,
        total_bytes=100,
    )
    assert job.model_dump()["completed_bytes"] == 17
    model = Model(
        key="local",
        provider="ollama",
        model_id="local:q4",
        display_name="Local",
        status="unavailable",
        reasoning_efforts=["default"],
        installation={
            "state": "paused",
            "weights_present": False,
            "quantization": "Q4_K_M",
            "download_bytes": 100,
            "completed_bytes": 17,
            "total_bytes": None,
            "job_id": job.id,
            "digest": None,
            "updated_at": stamp,
            "error": None,
        },
    )
    assert model.installation.state == "paused"
    assert model.unavailable_code is None


def test_direct_model_worker_import_registers_with_configured_broker_and_resources():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from app.jobs import model_actors, actors
assert model_actors.execute_model_job.broker is actors.broker
assert model_actors.execute_local_summary.broker is actors.broker
assert any(isinstance(m, actors.WorkerResources) for m in actors.broker.middleware)
print("configured-broker-and-resources")
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "configured-broker-and-resources"


async def test_model_actor_failure_logs_safe_class_and_job_identity_without_exception_text(
    monkeypatch, caplog
):
    from types import SimpleNamespace

    from app.core.logging import JsonFormatter
    from app.jobs import model_actors
    from app.services import local_models

    async def raising_attempt(*args):
        raise RuntimeError("fixture-private-secret https://private.invalid/token")

    monkeypatch.setattr(model_actors, "worker_resources", lambda: SimpleNamespace())
    monkeypatch.setattr(local_models, "execute_model_attempt", raising_attempt)
    job_id = str(uuid4())
    await model_actors.execute_model_job.fn.__wrapped__(job_id, 1)
    record = caplog.records[-1]
    rendered = JsonFormatter().format(record)
    assert record.job_id == job_id
    assert "error_type=RuntimeError" in rendered
    assert "error_code=UNEXPECTED_MODEL_ERROR" in rendered
    assert "function=raising_attempt" in rendered
    assert "fixture-private-secret" not in rendered and "https://" not in rendered
