"""Malformed managed-runtime fields fail at the HTTP boundary, without inference."""

import asyncio
import json

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec
from app.integrations.ollama import OllamaRuntime

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = pytest.mark.open_models

KEY = "ifm-k2-horizon-7b"
MALFORMED = [
    ("tags", "models", None),
    ("tags", "models", {}),
    ("tags", "models", [None]),
    ("tags", "models", ["private malformed inventory"]),
    ("show", "template", True),
    ("show", "capabilities", None),
    ("show", "capabilities", "completion"),
    ("show", "capabilities", ["completion", {}]),
    ("show", "model_info", None),
    ("show", "model_info", []),
    ("show", "model_info", {"fixture.context_length": None}),
    ("show", "model_info", {"fixture.context_length": "32768"}),
    ("show", "model_info", {"fixture.context_length": True}),
    ("show", "model_info", {"fixture.context_length": -1}),
    ("probe", "message", None),
    ("probe", "message", []),
    ("probe", "message", {"content": {"private": "response"}}),
    ("probe", "message", {"content": "OK", "thinking": None}),
    ("thinking_probe", "message", None),
    ("thinking_probe", "message", {"content": True}),
    ("stream", None, None),
    ("stream", None, []),
    ("stream", "message", None),
    ("stream", "message", "private malformed stream"),
    ("stream", "message", {"content": None}),
    ("stream", "message", {"content": "OK", "thinking": {}}),
    ("schema", "message", None),
    ("schema", "message", {"content": {"ok": True}}),
    ("version", "version", None),
    ("version", "version", " "),
    ("version", "version", {"private": "version"}),
]


def protocol_transport(case=None):
    """The integration tests reuse the exact 7B boundary responses tested here."""
    state, calls = {"case": case}, []
    spec = local_spec(KEY)

    def provider(request):
        calls.append(request.url.path)
        path = request.url.path
        if path == "/api/tags":
            target = "tags"
            data = {"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
        elif path == "/api/version":
            target, data = "version", {"version": "fixture-current"}
        elif path == "/api/show":
            target = "show"
            data = {
                "template": "{{ .Messages }}",
                "capabilities": ["completion"],
                "model_info": {"fixture.context_length": 32768},
                "thinking": {"values": [False, True], "default": True},
            }
        elif path == "/api/chat":
            body = json.loads(request.content)
            target = (
                "stream"
                if body["stream"]
                else "schema"
                if "format" in body
                else "thinking_probe"
                if "think" in body
                else "probe"
            )
            data = {
                "done": True,
                "done_reason": "stop",
                "message": {"content": '{"ok":true}' if target == "schema" else "OK"},
            }
        else:
            raise AssertionError(f"Verification reached unexpected path {path}")
        malformed = state["case"]
        if malformed and malformed[0] == target:
            _, field, value = malformed
            data = {**data, field: value} if field is not None else value
        # NDJSON and ordinary JSON use the same deterministic response body.
        return httpx.Response(200, text=json.dumps(data) + "\n")

    return state, calls, httpx.MockTransport(provider)


@pytest.mark.parametrize("case", MALFORMED)
async def test_given_malformed_runtime_fields_when_verifying_then_safe_protocol_error(case):
    _, calls, transport = protocol_transport(case)
    async with httpx.AsyncClient(transport=transport) as client:
        control = OllamaRuntime(client, "http://fixture")
        with pytest.raises(AppError) as failed:
            await control.verify(local_spec(KEY), context_window=8192)
    assert failed.value.code == "MODEL_PROTOCOL_ERROR"
    assert failed.value.message == "The runtime returned an invalid response."
    assert not any("pull" in path for path in calls)


async def test_given_valid_native_protocol_when_verifying_then_capabilities_are_preserved():
    _, _, transport = protocol_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        result = await OllamaRuntime(client, "http://fixture").verify(
            local_spec(KEY), context_window=8192
        )
    assert result["runtime_version"] == "fixture-current"
    assert result["think_mapping"] == {"none": False, "on": True}
    assert result["supports_streaming"] and result["supports_structured_output"]


@pytest.mark.parametrize(
    "case,code",
    [
        (("show", "template", ""), "MODEL_VALIDATION_FAILED"),
        (("show", "capabilities", []), "MODEL_VALIDATION_FAILED"),
        (("show", "model_info", {"fixture.context_length": 4096}), "MODEL_CONTEXT_UNSUPPORTED"),
        (("probe", "message", {"content": ""}), "MODEL_VALIDATION_FAILED"),
    ],
)
async def test_given_valid_but_unusable_protocol_when_verifying_then_original_error(case, code):
    _, _, transport = protocol_transport(case)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as failed:
            await OllamaRuntime(client, "http://fixture").verify(
                local_spec(KEY), context_window=8192
            )
    assert failed.value.code == code


async def test_given_schema_content_invalid_json_when_verifying_then_structured_is_false():
    _, _, transport = protocol_transport(("schema", "message", {"content": "plain text"}))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await OllamaRuntime(client, "http://fixture").verify(
            local_spec(KEY), context_window=8192
        )
    assert result["supports_structured_output"] is False


async def test_given_cancelled_http_when_verifying_then_cancellation_propagates():
    def cancelled(request):
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(cancelled)) as client:
        with pytest.raises(asyncio.CancelledError):
            await OllamaRuntime(client, "http://fixture").verify(
                local_spec(KEY), context_window=8192
            )
