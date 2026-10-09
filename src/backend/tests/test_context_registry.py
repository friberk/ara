"""Every model gets a real context profile instead of a byte budget (ARA-076)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings

THINKING_OFF_BY_DEFAULT = {"values": [False, True], "default": False}
THINKING_ON_BY_DEFAULT = {"values": [False, True], "default": True}


def resources(**overrides):
    return SimpleNamespace(settings=Settings(_env_file=None, **overrides))


def test_given_hosted_luna_when_profiling_then_working_cap_bounds_real_tokens():
    from app.integrations.context_registry import context_profile

    profile = context_profile(resources(), "gpt-5.6-luna", "low")
    assert profile.provider == "openai"
    assert (profile.window, profile.max_output, profile.thinking_allowance, profile.safety) == (
        1_050_000,
        4000,
        0,
        512,
    )
    assert profile.input_budget == 64000
    assert profile.counter.count("hello world") == 2
    narrow = resources(hosted_working_context_tokens=20000)
    assert context_profile(narrow, "gpt-5.6-luna", "low").input_budget == 20000


def test_given_local_model_without_thinking_when_profiling_then_output_and_safety_are_reserved():
    from app.integrations.context_registry import context_profile

    wide = resources(ollama_context_window=16384, local_input_budget_tokens=100000)
    profile = context_profile(wide, "ifm-k2-horizon-7b", "none", thinking=THINKING_OFF_BY_DEFAULT)
    assert profile.provider == "ollama" and profile.window == 16384
    assert profile.thinking_allowance == 0
    assert profile.input_budget == 16384 - 2048 - 512
    capped = context_profile(resources(ollama_context_window=16384), "ifm-k2-horizon-7b", "none")
    # Interactive default: CPU prefill runs at tens of tokens per second (ARA-070 S1).
    assert capped.input_budget == 3072


def test_given_local_thinking_effort_when_profiling_then_thinking_has_its_own_allowance():
    from app.integrations.context_registry import context_profile

    wide = resources(ollama_context_window=16384, local_input_budget_tokens=100000)
    off = context_profile(wide, "ifm-k2-horizon-7b", "none", thinking=THINKING_OFF_BY_DEFAULT)
    on = context_profile(wide, "ifm-k2-horizon-7b", "on", thinking=THINKING_OFF_BY_DEFAULT)
    assert on.thinking_allowance == 1024 and on.max_output == off.max_output
    assert on.input_budget == off.input_budget - 1024


@pytest.mark.parametrize(
    ("thinking", "allowance"),
    [(None, 0), (THINKING_OFF_BY_DEFAULT, 0), (THINKING_ON_BY_DEFAULT, 1024)],
)
def test_given_default_effort_when_profiling_then_model_default_decides_thinking(
    thinking, allowance
):
    from app.integrations.context_registry import context_profile

    profile = context_profile(resources(), "ifm-k2-horizon-7b", "default", thinking=thinking)
    assert profile.thinking_allowance == allowance


def test_given_local_model_when_counting_then_calibrated_factor_is_applied():
    from app.integrations.context_registry import context_profile

    default = context_profile(resources(), "ifm-k2-horizon-7b", "none")
    assert default.counter.count(" word" * 1000) == 1050
    custom = context_profile(resources(local_token_factor=1.2), "ifm-k2-horizon-7b", "none")
    assert custom.counter.count(" word" * 1000) == 1200


def test_given_registry_when_limiting_then_model_limits_delegates():
    from app.integrations.llm import model_limits

    assert model_limits(resources(), "ifm-k2-horizon-7b") == (3072, 2048)
    assert model_limits(resources(), "gpt-5.6-luna") == (64000, 4000)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ollama_context_window": 4096, "ollama_thinking_tokens": 2048},
        {"local_token_factor": 0.9},
        {"local_input_budget_tokens": 0},
        {"hosted_working_context_tokens": 0},
    ],
)
def test_given_invalid_context_settings_when_configuring_then_reject(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


async def test_given_hosted_model_when_recording_configuration_then_budget_is_explicit():
    from app.integrations.llm import generation_configuration

    configuration = await generation_configuration(resources(), "gpt-5.6-luna", "low")
    assert {
        key: configuration[key]
        for key in (
            "window",
            "max_output",
            "thinking_allowance",
            "safety_tokens",
            "input_budget",
            "tokenizer",
            "token_factor",
        )
    } == {
        "window": 1_050_000,
        "max_output": 4000,
        "thinking_allowance": 0,
        "safety_tokens": 512,
        "input_budget": 64000,
        "tokenizer": "o200k_base",
        "token_factor": 1.0,
    }


def local_adapter(
    client, *, efforts=("default", "none", "on"), thinking=THINKING_OFF_BY_DEFAULT, **settings
):
    from app.integrations.ollama_llm import OllamaLLM

    return OllamaLLM(
        Settings(openai_api_key=None, _env_file=None, **settings),
        "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
        http_client=client,
        reasoning_efforts=efforts,
        thinking=thinking,
    )


def completed(request):
    return httpx.Response(
        200, json={"message": {"content": "Answer"}, "done": True, "done_reason": "stop"}
    )


@pytest.mark.parametrize(("effort", "num_predict"), [("none", 2048), ("on", 2048 + 1024)])
async def test_given_local_thinking_when_generating_then_answer_keeps_its_output_allowance(
    effort, num_predict
):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return completed(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await local_adapter(client).complete("ifm-k2-horizon-7b", effort, "System", "Paper")
        await local_adapter(client).complete(
            "ifm-k2-horizon-7b", effort, "System", "Paper", max_output_tokens=128
        )
    assert [r["options"]["num_predict"] for r in requests] == [num_predict, num_predict - 1920]


async def test_given_local_prompt_when_budgeting_then_real_tokens_decide_the_limit():
    from app.integrations.llm import LLMError

    requests = []

    def provider(request):
        requests.append(request)
        return completed(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        # 12,000 bytes but about 1,500 tokens: byte counting wrongly rejected this.
        await local_adapter(client).complete("ifm-k2-horizon-7b", "none", "System", "x" * 12000)
        assert len(requests) == 1
        with pytest.raises(LLMError) as failure:
            # About 3,150 counted tokens exceed the 3,072-token interactive default.
            await local_adapter(client).complete(
                "ifm-k2-horizon-7b", "none", "System", " word" * 3000
            )
        assert failure.value.code == "CONTEXT_LIMIT" and len(requests) == 1
        # Without the interactive cap, the window decides: 5,632 tokens, or 4,608 with thinking.
        wide = {"local_input_budget_tokens": 8192}
        with pytest.raises(LLMError) as failure:
            await local_adapter(client, **wide).complete(
                "ifm-k2-horizon-7b", "none", "System", " word" * 6000
            )
        assert failure.value.code == "CONTEXT_LIMIT" and len(requests) == 1
        with pytest.raises(LLMError) as failure:
            # Fits without thinking, but not once thinking takes its allowance.
            await local_adapter(client, **wide).complete(
                "ifm-k2-horizon-7b", "on", "System", " word" * 5000
            )
        assert failure.value.code == "CONTEXT_LIMIT" and len(requests) == 1
        await local_adapter(client, **wide).complete(
            "ifm-k2-horizon-7b", "none", "System", " word" * 5000
        )
        assert len(requests) == 2


def test_given_hosted_prompt_when_budgeting_then_real_tokens_decide_the_limit():
    import asyncio

    from app.integrations.llm import HostedLLM, LLMError

    adapter = HostedLLM(Settings(openai_api_key="fixture", _env_file=None))
    try:
        # 40,000 bytes but 5,000 tokens: byte counting wrongly rejected this.
        adapter.parameters("gpt-5.6-luna", "low", "instructions", "x" * 40000)
        with pytest.raises(LLMError, match="context"):
            adapter.parameters("gpt-5.6-luna", "low", "instructions", " word" * 64000)
    finally:
        asyncio.run(adapter.close())
