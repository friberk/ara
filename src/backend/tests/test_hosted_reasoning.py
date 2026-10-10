"""Hosted capabilities are selected independently for each model."""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations import llm
from app.routes.ai import models


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
@pytest.mark.parametrize("effort", ["xhigh", "max"])
async def test_given_each_hosted_model_when_requesting_deep_reasoning_then_preserve_effort(
    model, effort
):
    selection = llm.validate_selection(model, effort)
    assert selection.reasoning_efforts == ["none", "low", "medium", "high", "xhigh", "max"]
    adapter = llm.HostedLLM(Settings(openai_api_key="fixture", _env_file=None))
    payload = adapter.parameters(model, effort, "System", "Paper")
    assert payload["model"] == model
    assert payload["reasoning"] == {"effort": effort}
    await adapter.close()


@pytest.mark.parametrize("effort", ["on", "default", "deliberate"])
@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
def test_given_native_only_control_when_selecting_hosted_then_reject(model, effort):
    with pytest.raises(llm.LLMError) as failure:
        llm.validate_selection(model, effort)
    assert failure.value.code == "INVALID_REASONING"


async def test_given_one_hosted_capability_change_when_listing_then_other_models_are_independent(
    monkeypatch,
):
    from app.routes import ai

    monkeypatch.setitem(llm.HOSTED_REASONING_EFFORTS, "gpt-5.6-sol", ("none", "low"))
    assert llm.validate_selection("gpt-5.6-sol", "low").reasoning_efforts == ["none", "low"]
    with pytest.raises(llm.LLMError):
        llm.validate_selection("gpt-5.6-sol", "max")
    for model in ("gpt-5.6-terra", "gpt-5.6-luna"):
        assert "max" in llm.validate_selection(model, "max").reasoning_efforts

    async def local_models(resources):
        return []

    async def hosted_default(resources):
        return ai.Defaults()

    monkeypatch.setattr(ai, "list_local_models", local_models)
    monkeypatch.setattr(ai, "saved_defaults", hosted_default)
    resources = SimpleNamespace(settings=Settings(_env_file=None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resources=resources)))
    page = await models(request)
    assert {model.key: model.reasoning_efforts for model in page.items} == {
        "gpt-5.6-sol": ["none", "low"],
        "gpt-5.6-terra": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
    }
