"""Current native thinking discovery and exact wire values; no real inference."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.integrations.llm import LLMError, create_llm, validate_model_available, validate_selection
from app.integrations.model_catalog import local_spec
from app.integrations.ollama import OllamaRuntime, local_model_reasoning
from app.integrations.ollama_llm import OllamaLLM


@pytest.mark.parametrize(
    ("thinking", "expected"),
    [
        ({"values": [True, False], "default": True}, ["default", "on", "none"]),
        ({"values": [False], "default": False}, ["default", "none"]),
        (
            {"values": ["quick", "deliberate"], "default": "deliberate"},
            ["default", "quick", "deliberate"],
        ),
        (
            {"values": [False, True, "low", "balanced", "high"], "default": "balanced"},
            ["default", "none", "on", "low", "balanced", "high"],
        ),
    ],
)
def test_given_current_show_metadata_when_discovering_then_preserve_native_controls(
    thinking, expected
):
    assert local_model_reasoning({"thinking": thinking}) == expected


@pytest.mark.parametrize(
    "show",
    [
        {},
        {"thinking_levels": [False, "low", "high"]},
        {"thinking_levels": [["bad"]]},
        {"thinking": None},
        {"thinking": {"values": [True]}},
        {"thinking": {"values": [], "default": False}},
        {"thinking": {"values": [True], "default": False}},
        {"thinking": {"values": [1], "default": 1}},
        {"thinking": {"values": [True, {}], "default": True}},
        {"thinking": {"values": "high", "default": "high"}},
        {"thinking": {"values": [""], "default": ""}},
        {"thinking": {"values": ["default"], "default": "default"}},
        {"thinking": {"values": [False, "none"], "default": False}},
        {"thinking": {"values": [True, "on"], "default": True}},
    ],
)
def test_given_absent_or_malformed_metadata_when_discovering_then_no_false_controls(show):
    assert local_model_reasoning(show) == ["default"]


async def verified_runtime(show):
    spec = local_spec("ifm-k2-horizon-7b")
    probes = []

    def provider(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"], **show}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "fixture"})
        body = json.loads(request.content)
        probes.append(body)
        result = {
            "message": {"content": '{"ok":true}' if "format" in body else "OK"},
            "done": True,
            "done_reason": "stop",
        }
        return httpx.Response(200, text=json.dumps(result) + "\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await OllamaRuntime(client, "http://fixture").verify(spec, context_window=8192)
    return result, probes


async def test_given_current_metadata_when_verifying_then_persist_exact_mapping_and_default():
    thinking = {"values": [False, True, "deliberate"], "default": "deliberate"}
    result, probes = await verified_runtime({"thinking": thinking})
    assert result["reasoning_efforts"] == ["default", "none", "on", "deliberate"]
    assert result["thinking"] == thinking
    assert result["think_mapping"] == {"none": False, "on": True, "deliberate": "deliberate"}
    assert [body["think"] for body in probes if "think" in body and "format" not in body] == [
        False,
        True,
        "deliberate",
    ]
    assert all(body["options"]["temperature"] == 0.0 for body in probes)


@pytest.mark.parametrize(
    "show", [{"thinking_levels": [False, "low", "xhigh"]}, {"thinking": {"values": [{}]}}]
)
async def test_given_legacy_names_and_http_success_when_verifying_then_no_named_level_is_inferred(
    show,
):
    result, probes = await verified_runtime(show)
    assert result["reasoning_efforts"] == ["default"]
    assert result.get("thinking") is None
    assert result["think_mapping"] == {}
    assert not any("think" in body for body in probes)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("effort", "expected"),
    [("default", None), ("none", False), ("on", True), ("deliberate", "deliberate")],
)
async def test_given_verified_controls_when_generating_then_complete_and_stream_use_exact_values(
    stream, effort, expected
):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        result = {"message": {"content": "Answer"}, "done": True, "done_reason": "stop"}
        return httpx.Response(200, text=json.dumps(result) + "\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        llm = OllamaLLM(
            Settings(_env_file=None),
            "fixture-model",
            http_client=client,
            reasoning_efforts=["default", "none", "on", "deliberate"],
        )
        if stream:
            assert [x async for x in llm.stream("local", effort, "System", "Paper")] == ["Answer"]
        else:
            assert (await llm.complete("local", effort, "System", "Paper")).content == "Answer"
    assert requests == [
        {
            "model": "fixture-model",
            "messages": [
                {"role": "system", "content": "System"},
                {"role": "user", "content": "Paper"},
            ],
            "stream": stream,
            "options": {"num_ctx": 8192, "num_predict": 2048, "num_thread": 4, "temperature": 0.0},
            **({"think": expected} if effort != "default" else {}),
        }
    ]


async def test_given_model_defined_name_when_validating_then_use_native_capabilities(monkeypatch):
    from app.services import local_models

    async def available(resources, model):
        selected = validate_selection(model, "default")
        selected.reasoning_efforts = ["default", "deliberate"]
        return selected

    monkeypatch.setattr(local_models, "ensure_local_available", available)
    async with httpx.AsyncClient() as client:
        resources = SimpleNamespace(
            settings=Settings(_env_file=None), ollama_generation_http=client
        )
        selected = await validate_model_available(resources, "ifm-k2-horizon-7b", "deliberate")
        llm = create_llm(resources, selected.key, selection=selected)
        assert (
            llm.parameters(selected.key, "deliberate", "System", "Paper")["think"] == "deliberate"
        )
        with pytest.raises(LLMError) as failure:
            await validate_model_available(resources, selected.key, "invented")
        assert failure.value.code == "INVALID_REASONING"
        with pytest.raises(LLMError):
            validate_selection("gpt-5.6-luna", "deliberate")
