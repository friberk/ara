"""The local Qwen3 reranker is a pinned catalog artifact, verified by a logprob probe (ARA-074)."""

import json
import math
import re

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec
from tests.support.providers import overlap_relevance

RERANKER = "qwen3-reranker-0.6b"
RERANK = re.compile(r"<Query>: (.*?)\n<Document>: (.*?)<\|im_end\|>", re.S)


def test_given_catalog_then_the_local_reranker_is_pinned_to_the_measured_artifact():
    from app.integrations.reranker_catalog import RERANKERS

    spec = local_spec(RERANKER)
    assert (spec.kind, spec.quantization) == ("reranker", "Q8_0")
    # Ollama lists untagged pulls as ":latest", and inventory matching is exact.
    assert spec.model_id == "fanyx/Qwen3-Reranker-0.6B-Q8_0:latest"
    assert spec.expected_digest == (
        "fd021d86a15e539ac1b4f3bec2d1c6b15a3e158f316adb0d1325c713240103b3"
    )
    assert spec.download_bytes == 639152466
    profile = next(p for p in RERANKERS.values() if p.provider == "ollama")
    assert profile.local_model_key == RERANKER
    assert spec.model_id.removesuffix(":latest") == profile.model_id


def logprobs(p_yes: float, *, yes="yes", no="no") -> dict:
    return {
        "response": yes if p_yes >= 0.5 else no,
        "done": True,
        "done_reason": "length",
        "logprobs": [
            {
                "token": yes if p_yes >= 0.5 else no,
                "logprob": math.log(max(p_yes, 1 - p_yes)),
                "top_logprobs": [
                    {"token": yes, "logprob": math.log(p_yes)},
                    {"token": no, "logprob": math.log(1 - p_yes)},
                ],
            }
        ],
    }


def test_given_top_logprobs_when_scoring_then_yes_and_no_match_case_insensitively():
    from app.integrations.ollama import relevance_score

    data = {
        "logprobs": [
            {
                "token": "No",
                "logprob": math.log(0.6),
                "top_logprobs": [
                    {"token": "No", "logprob": math.log(0.6)},
                    {"token": " yes", "logprob": math.log(0.2)},
                    {"token": "YES", "logprob": math.log(0.1)},
                    {"token": "maybe", "logprob": math.log(0.05)},
                ],
            }
        ]
    }
    assert math.isclose(relevance_score(data), 0.3 / 0.9)
    assert math.isclose(relevance_score(logprobs(0.8, yes="Yes", no=" NO")), 0.8)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"logprobs": []},
        {"logprobs": [{"token": "x", "top_logprobs": [{"token": "maybe", "logprob": -0.1}]}]},
        {"logprobs": [{"token": "yes", "top_logprobs": [{"token": "yes", "logprob": "high"}]}]},
        {"logprobs": [{"token": "yes", "top_logprobs": None}]},
        {"logprobs": "yes"},
    ],
)
def test_given_unusable_logprobs_when_scoring_then_there_is_no_score(data):
    from app.integrations.ollama import relevance_score

    assert relevance_score(data) is None


def reranker_runtime(
    spec,
    requests,
    *,
    capabilities=("tools", "thinking", "completion"),
    relevance=overlap_relevance,
    context_length=40960,
):
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            item = {"name": spec.model_id, "model": spec.model_id, "digest": spec.expected_digest}
            return httpx.Response(200, json={"models": [item]})
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "template": "{{ .Prompt }}",
                    "capabilities": list(capabilities),
                    "model_info": {"qwen3.context_length": context_length},
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.1-ara.fixture"})
        if request.url.path == "/api/generate":
            body = json.loads(request.content)
            requests.append(body)
            score = relevance(*RERANK.search(body["prompt"]).groups())
            return httpx.Response(200, json=logprobs(score) if score is not None else {})
        return httpx.Response(404, json={"error": "unexpected probe"})

    return httpx.MockTransport(handler)


async def test_given_reranker_when_verifying_then_a_logprob_probe_runs_without_chat():
    from app.integrations.ollama import OllamaRuntime

    spec, requests = local_spec(RERANKER), []
    async with httpx.AsyncClient(transport=reranker_runtime(spec, requests)) as client:
        validation = await OllamaRuntime(client, "http://runtime", probe_threads=3).verify(
            spec, context_window=8192
        )
    assert validation == {
        "kind": "reranker",
        "digest": spec.expected_digest,
        "runtime_version": "0.40.1-ara.fixture",
        "context_window": 8192,
        "thinking_schema": 1,
        "reasoning_efforts": ["default"],
        "supports_streaming": False,
        "supports_structured_output": False,
    }
    assert "/api/chat" not in requests
    probes = [item for item in requests if isinstance(item, dict)]
    assert len(probes) == 2
    for probe in probes:
        assert probe["model"] == spec.model_id
        assert (probe["raw"], probe["stream"], probe["logprobs"]) == (True, False, True)
        assert probe["top_logprobs"] == 20 and probe["keep_alive"] == 0
        assert probe["options"] == {
            "temperature": 0,
            "num_predict": 1,
            "num_ctx": 2048,
            "num_thread": 3,
        }


@pytest.mark.parametrize(
    "relevance",
    [
        lambda query, document: 0.5,  # uniform logits: the broken dengcao Q8_0 artifact
        lambda query, document: 0.6 if "datasets" in document else 0.35,  # margin below 0.3
        lambda query, document: None,  # no logprobs at all
    ],
)
async def test_given_uninformative_reranker_when_verifying_then_validation_fails(relevance):
    from app.integrations.ollama import OllamaRuntime

    spec = local_spec(RERANKER)
    transport = reranker_runtime(spec, [], relevance=relevance)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
    assert (error.value.status_code, error.value.code) == (409, "MODEL_VALIDATION_FAILED")


@pytest.mark.parametrize(
    ("capabilities", "context_length", "code"),
    [
        (("embedding",), 40960, "MODEL_VALIDATION_FAILED"),
        (("completion",), 1024, "MODEL_CONTEXT_UNSUPPORTED"),
    ],
)
async def test_given_unsuitable_reranker_runtime_when_verifying_then_it_is_rejected(
    capabilities, context_length, code
):
    from app.integrations.ollama import OllamaRuntime

    spec, requests = local_spec(RERANKER), []
    transport = reranker_runtime(
        spec, requests, capabilities=capabilities, context_length=context_length
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
    assert error.value.code == code
    assert "/api/generate" not in requests
