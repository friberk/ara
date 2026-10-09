from uuid import uuid4

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec


async def test_pull_progress_counts_each_layer_once_and_requires_success():
    from app.integrations.ollama import OllamaRuntime, PullProgress

    progress = PullProgress()
    assert progress.apply({"digest": "a", "total": 10, "completed": 4}) == (4, 10)
    assert progress.apply({"digest": "b", "total": 20, "completed": 8}) == (12, 30)
    assert progress.apply({"digest": "a", "total": 10, "completed": 7}) == (15, 30)
    assert progress.apply({"digest": "b", "total": 20, "completed": 8}) == (15, 30)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text='{"status":"pulling","digest":"a","total":10,"completed":10}\n'
            )
        )
    ) as client:
        runtime = OllamaRuntime(client, "http://runtime")
        with pytest.raises(AppError, match="did not finish"):
            async for _ in runtime.pull("model", "operation", controlled=True):
                pass


async def test_inventory_rejects_known_digest_drift_and_validation_checks_actual_response():
    from app.integrations.ollama import OllamaRuntime

    spec = local_spec("ifm-k2-horizon-3.7b")

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": spec.model_id, "digest": "bad"}]})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runtime = OllamaRuntime(client, "http://runtime")
        with pytest.raises(AppError) as error:
            await runtime.artifact(spec)
        assert error.value.code == "MODEL_DIGEST_MISMATCH"

    def valid_inventory_bad_probe(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "template": "{{ .Messages }}",
                    "capabilities": ["completion"],
                    "model_info": {"llama.context_length": 32768},
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        return httpx.Response(200, json={"done": True, "message": {"content": ""}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(valid_inventory_bad_probe)
    ) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
        assert error.value.code == "MODEL_VALIDATION_FAILED"


async def test_stock_runtime_explicitly_refuses_pause():
    from app.integrations.ollama import OllamaRuntime

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404))
    ) as client:
        runtime = OllamaRuntime(client, "http://runtime")
        assert not await runtime.supports_pause()
        with pytest.raises(AppError) as error:
            await runtime.pause("operation")
        assert error.value.code == "MODEL_PAUSE_UNSUPPORTED"


async def test_delete_unloads_and_confirms_removal_even_for_drifted_weights():
    from app.integrations.ollama import OllamaRuntime

    spec = local_spec("ifm-k2-horizon-3.7b")
    present = True
    calls = []

    def handler(request):
        nonlocal present
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": spec.model_id, "digest": "drift"}] if present else []},
            )
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/delete":
            present = False
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await OllamaRuntime(client, "http://runtime").delete(spec)
        assert calls == ["/api/tags", "/api/generate", "/api/ps", "/api/delete", "/api/tags"]
        calls.clear()
        await OllamaRuntime(client, "http://runtime").delete(spec)
        assert calls == ["/api/tags"]


async def test_runtime_memory_error_has_safe_explicit_code():
    from app.integrations.ollama import OllamaRuntime

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                500, json={"error": "model requires more system memory /private/user/file.secret"}
            )
        )
    ) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").request("POST", "/api/chat", json={})
        assert error.value.code == "MODEL_MEMORY_LIMIT"
        assert "/private" not in error.value.message


async def test_validation_rejects_truncated_probe_even_with_visible_content():
    from app.integrations.ollama import OllamaRuntime

    spec = local_spec("ifm-k2-horizon-3.7b")

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        return httpx.Response(
            200, json={"done": True, "done_reason": "length", "message": {"content": "OK"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
        assert error.value.code == "MODEL_VALIDATION_FAILED"


async def test_validation_proves_json_schema_support_and_uses_configured_output_budget():
    import json

    from app.integrations.ollama import OllamaRuntime, local_model_reasoning

    spec = local_spec("ifm-k2-horizon-3.7b")
    probes = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "template": "{{ .Messages }}",
                    "capabilities": ["completion"],
                    "thinking": {"values": [False, "low", "high", "xhigh"], "default": "high"},
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        body = json.loads(request.content)
        probes.append(body)
        content = json.dumps({"ok": True}) if "format" in body else "OK"
        return httpx.Response(
            200,
            text=json.dumps({"done": True, "done_reason": "stop", "message": {"content": content}})
            + "\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OllamaRuntime(client, "http://runtime", probe_output_tokens=256).verify(
            spec, context_window=8192
        )
        assert result["supports_structured_output"] is True
        assert all(probe["options"]["num_predict"] == 256 for probe in probes)
        assert all(probe["options"]["num_thread"] == 4 for probe in probes)
        assert any(isinstance(probe.get("format"), dict) for probe in probes)
        assert result["reasoning_efforts"] == ["default", "none", "low", "high", "xhigh"]
    assert local_model_reasoning(
        {"thinking": {"values": [False, "xhigh"], "default": "xhigh"}}
    ) == [
        "default",
        "none",
        "xhigh",
    ]


@pytest.mark.parametrize("default_thinking", ["private reasoning", ""])
async def test_none_reasoning_is_discovered_by_actual_boolean_probe_without_show_levels(
    default_thinking,
):
    import json

    from app.integrations.ollama import OllamaRuntime

    spec = local_spec("ifm-k2-horizon-3.7b")

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": "OK",
                    "thinking": "" if body.get("think") is False else default_thinking,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
        assert result["reasoning_efforts"] == (
            ["default", "none"] if default_thinking else ["default"]
        )


def test_resumed_progress_reconciles_partial_rollback_then_counts_monotonically():
    from app.integrations.ollama import PullProgress

    progress = PullProgress(layers={"a": [90, 100], "b": [50, 100]})
    assert progress.apply({"digest": "a", "completed": 20, "total": 100}) == (20, 200)
    assert progress.apply({"digest": "b", "completed": 10, "total": 100}) == (30, 200)
    assert progress.apply({"digest": "a", "completed": 19, "total": 100}) == (30, 200)


def test_invalid_layer_totals_fail_safely_instead_of_negative_progress():
    from app.integrations.ollama import PullProgress

    with pytest.raises(AppError) as error:
        PullProgress().apply({"digest": "layer", "completed": 1, "total": -1})
    assert error.value.code == "MODEL_PROTOCOL_ERROR"


async def test_non_object_runtime_response_is_a_safe_protocol_error():
    from app.integrations.ollama import OllamaRuntime

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    ) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").request("GET", "/api/tags")
        assert error.value.code == "MODEL_PROTOCOL_ERROR"


async def test_unknown_operation_404_requires_settlement_and_stays_retryable():
    from app.integrations.ollama import OllamaRuntime

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        return httpx.Response(404, json={"error": "unknown operation_id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").pause(str(uuid4()))
        assert error.value.code == "MODEL_PAUSE_UNCONFIRMED"
        assert error.value.status_code == 503
