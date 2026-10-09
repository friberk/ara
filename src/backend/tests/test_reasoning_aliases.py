"""Presentation aliases describe verified native controls without changing raw efforts."""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations import llm
from app.integrations.model_catalog import local_spec
from app.main import create_app
from app.schemas.ai import Model
from app.services.local_models import model_dto

KEY = "ifm-k2-horizon-7b"


def current_validation(key=KEY):
    return {
        "digest": local_spec(key).expected_digest,
        "context_window": 8192,
        "runtime_version": "fixture-current",
        "thinking_schema": 1,
        "thinking": {"values": [False, True, "low", "medium", "high"], "default": "high"},
        "think_mapping": {
            "none": False,
            "on": True,
            "low": "low",
            "medium": "medium",
            "high": "high",
        },
        "reasoning_efforts": ["default", "none", "on", "low", "medium", "high"],
    }


def selection(data, *, key=KEY):
    spec = local_spec(key)
    row = SimpleNamespace(
        validation=data,
        state="ready",
        weights_present=True,
        error_code=None,
        completed_bytes=0,
        total_bytes=None,
        active_job_id=None,
        digest=spec.expected_digest,
        updated_at=None,
    )
    return model_dto(spec, row)


@pytest.mark.parametrize("key", ["ifm-k2-horizon-3.7b", KEY])
def test_given_pinned_ifm_controls_when_listing_then_default_and_on_alias_verified_high(key):
    data = current_validation(key)
    model = selection(data, key=key)
    assert model.reasoning_aliases == {"default": "high", "on": "high"}
    assert model.reasoning_efforts == data["reasoning_efforts"]
    assert model.thinking.model_dump() == data["thinking"]


@pytest.mark.parametrize("key", ["ifm-k2-horizon-3.7b", KEY])
@pytest.mark.parametrize("default,expected", [(False, "none"), (True, "high")])
def test_given_full_ifm_boolean_default_when_listing_then_alias_targets_are_terminal(
    key, default, expected
):
    data = current_validation(key)
    data["thinking"]["default"] = default
    model = selection(data, key=key)
    assert model.reasoning_aliases == {"default": expected, "on": "high"}
    assert model.reasoning_efforts == data["reasoning_efforts"]
    assert model.thinking.default is default


@pytest.mark.parametrize("default,expected", [(False, "none"), (True, "on")])
def test_given_other_model_boolean_default_when_listing_then_no_ifm_equivalence(default, expected):
    data = current_validation("qwen3.8-27b")
    data["thinking"]["default"] = default
    assert selection(data, key="qwen3.8-27b").reasoning_aliases == {"default": expected}


@pytest.mark.parametrize("missing,expected", [("high", {"default": "on"}), ("on", {})])
def test_given_partial_ifm_boolean_default_when_listing_then_no_unproven_collapse(
    missing, expected
):
    data = current_validation()
    data["thinking"]["default"] = True
    data["think_mapping"].pop(missing)
    data["reasoning_efforts"].remove(missing)
    assert selection(data).reasoning_aliases == expected


@pytest.mark.parametrize(
    "missing,expected",
    [("high", {}), ("on", {"default": "high"})],
)
def test_given_unverified_ifm_equivalence_when_listing_then_no_control_is_invented(
    missing, expected
):
    data = current_validation()
    data["think_mapping"].pop(missing)
    data["reasoning_efforts"].remove(missing)
    assert selection(data).reasoning_aliases == expected


@pytest.mark.parametrize(
    "effort,value,expected",
    [("on", "true", {"default": "high"}), ("high", True, {})],
)
def test_given_wrong_verified_raw_type_when_listing_then_alias_requires_exact_value(
    effort, value, expected
):
    data = current_validation()
    data["think_mapping"][effort] = value
    assert selection(data).reasoning_aliases == expected


@pytest.mark.parametrize("default,expected", [(False, "none"), (True, "on")])
def test_given_boolean_only_default_when_listing_then_alias_resolves_verified_boolean(
    default, expected
):
    data = current_validation()
    data["thinking"] = {"values": [False, True], "default": default}
    data["think_mapping"] = {"none": False, "on": True}
    data["reasoning_efforts"] = ["default", "none", "on"]
    assert selection(data).reasoning_aliases == {"default": expected}


@pytest.mark.parametrize("default", [False, True])
def test_given_unverified_boolean_default_when_listing_then_no_default_alias(default):
    data = current_validation()
    data["thinking"] = {"values": [False, True], "default": default}
    data["think_mapping"] = {}
    assert selection(data).reasoning_aliases == {}


@pytest.mark.parametrize("key", [KEY, "qwen3.8-27b"])
def test_given_arbitrary_named_default_when_listing_then_preserve_exact_verified_name(key):
    data = current_validation(key)
    data["thinking"] = {"values": [False, True, "deliberate"], "default": "deliberate"}
    data["think_mapping"] = {"none": False, "on": True, "deliberate": "deliberate"}
    data["reasoning_efforts"] = ["default", "none", "on", "deliberate"]
    assert selection(data, key=key).reasoning_aliases == {"default": "deliberate"}


def test_given_other_model_with_same_named_controls_when_listing_then_on_is_not_assumed_high():
    data = current_validation("qwen3.8-27b")
    model = selection(data, key="qwen3.8-27b")
    assert model.reasoning_aliases == {"default": "high"}
    assert model.reasoning_efforts == data["reasoning_efforts"]


@pytest.mark.parametrize("marker", [None, "1", 0, True, 2])
def test_given_legacy_or_malformed_schema_when_listing_then_no_aliases(marker):
    data = current_validation()
    if marker is None:
        data.pop("thinking_schema")
    else:
        data["thinking_schema"] = marker
    assert selection(data).reasoning_aliases == {}


@pytest.mark.parametrize(
    "thinking",
    [
        None,
        [],
        {"values": [False, True, "high"]},
        {"values": [False, True, "high"], "default": 1},
        {"values": [False, True, "high"], "default": "unknown"},
        {"values": [True, "on", "high"], "default": "high"},
    ],
)
def test_given_malformed_thinking_when_listing_then_no_aliases(thinking):
    data = current_validation()
    data["thinking"] = thinking
    assert selection(data).reasoning_aliases == {}


@pytest.mark.parametrize("data", [None, ["malformed"], "malformed"])
def test_given_malformed_validation_when_listing_then_no_aliases(data):
    assert selection(data).reasoning_aliases == {}


@pytest.mark.parametrize("key", list(llm.HOSTED_REASONING_EFFORTS))
def test_given_hosted_model_when_listing_then_efforts_remain_individual_and_aliases_empty(key):
    model = llm.validate_selection(key, "max")
    assert model.reasoning_efforts == list(llm.HOSTED_REASONING_EFFORTS[key])
    assert model.reasoning_aliases == {}


def test_given_alias_metadata_when_serializing_then_optional_contract_roundtrips():
    model = selection(current_validation())
    dumped = model.model_dump(mode="json")
    assert dumped["reasoning_aliases"] == {"default": "high", "on": "high"}
    assert Model.model_validate(dumped).reasoning_aliases == model.reasoning_aliases
    dumped.pop("reasoning_aliases")
    restored = Model.model_validate(dumped)
    assert restored.reasoning_aliases == {}
    schema = create_app(Settings(_env_file=None)).openapi()["components"]["schemas"]["Model"]
    assert "reasoning_aliases" not in schema["required"]
    assert schema["properties"]["reasoning_aliases"]["additionalProperties"] == {"type": "string"}
