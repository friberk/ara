"""One hosted catalog entry per model; budgets derive from its window (ARA-093).

The design table is docs/plans/retrieval-orchestration.md, "Budget" and "Window sizes".
"""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations import llm
from app.integrations.tokens import PromptMessage, TiktokenCounter, count_messages

MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
MILLION = Decimal(1_000_000)
# (input, cached input, output) in USD per million tokens, from each model page.
DOCUMENTED = {
    "gpt-5.6-sol": ("4", "0.4", "20"),
    "gpt-5.6-terra": ("2", "0.2", "12"),
    "gpt-5.6-luna": ("0.2", "0.02", "1.2"),
}
# What each model is for, in one sentence from its model page's tagline (read 2026-10-10, ARA-109).
PURPOSES = {
    "gpt-5.6-sol": "Flagship model for complex professional work.",
    "gpt-5.6-terra": "Balances intelligence and cost.",
    "gpt-5.6-luna": "Built for cost-sensitive, high-volume work.",
}


def catalog():
    from app.integrations import hosted_catalog

    return hosted_catalog


def synthetic(monkeypatch, window: int, key: str | None = None):
    """A catalog entry of any window; it shares Luna's prices, tier and reserve policy."""
    entry = replace(catalog().HOSTED_MODELS["gpt-5.6-luna"], key=key or f"synthetic-{window}")
    entry = replace(entry, window=window)
    monkeypatch.setitem(catalog().HOSTED_MODELS, entry.key, entry)
    return entry


def test_given_the_catalog_when_read_then_each_model_has_one_complete_entry():
    models = catalog().HOSTED_MODELS
    assert tuple(models) == MODELS
    for key, entry in models.items():
        assert entry.key == key and entry.display_name == "GPT-5.6 " + key[8:].capitalize()
        assert (entry.window, entry.max_output, entry.price_tier_tokens) == (
            1_050_000,
            128_000,
            272_000,
        )
        assert entry.answer_reserve == 4000
        assert entry.reasoning_efforts == ("none", "low", "medium", "high", "xhigh", "max")
        assert entry.encoding == "o200k_base"
        base, cached, output = (Decimal(price) for price in DOCUMENTED[key])
        assert (entry.input_price, entry.cached_input_price, entry.output_price) == (
            base,
            cached,
            output,
        )
        # OpenAI bills prompt-cache writes at 1.25x the uncached input rate.
        assert entry.cache_write_price == base * Decimal("1.25")
        assert entry.source.startswith("https://developers.openai.com/api/docs/models/")


def test_given_the_catalog_when_read_then_each_model_says_what_it_is_for():
    for key, entry in catalog().HOSTED_MODELS.items():
        assert entry.description == PURPOSES[key]


async def test_given_the_models_route_when_listing_then_hosted_models_carry_purpose_and_prices(
    monkeypatch,
):
    from app.routes import ai

    async def nothing(resources):
        return []

    async def hosted_default(resources):
        return ai.Defaults()

    monkeypatch.setattr(ai, "list_local_models", nothing)
    monkeypatch.setattr(ai, "saved_defaults", hosted_default)
    resources = SimpleNamespace(settings=Settings(_env_file=None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resources=resources)))
    page = await ai.models(request)
    listed = {item.key: item for item in page.items}
    for key, entry in catalog().HOSTED_MODELS.items():
        item = listed[key]
        assert item.description == PURPOSES[key]
        assert item.input_price_per_million == float(entry.input_price)
        assert item.output_price_per_million == float(entry.output_price)


def test_given_a_local_model_when_selected_then_it_has_no_purpose_or_price():
    item = llm.validate_selection("ifm-k2-horizon-7b", "default")
    assert item.provider == "ollama"
    assert (item.description, item.input_price_per_million, item.output_price_per_million) == (
        None,
        None,
        None,
    )


def test_given_the_catalog_when_selecting_then_unknown_models_raise_as_before():
    assert catalog().hosted_model("gpt-9") is None
    with pytest.raises(llm.LLMError) as failure:
        llm.validate_selection("gpt-9", "low")
    assert failure.value.code == "INVALID_MODEL"
    with pytest.raises(llm.LLMError) as failure:
        llm.reservation_amount("gpt-9", 10)
    assert failure.value.code == "INVALID_MODEL"


def test_given_the_catalog_when_scanning_code_then_no_parallel_model_tables_remain():
    from app.integrations import context_registry

    for name in ("PRICES", "HOSTED_REASONING_EFFORTS", "OUTPUT_LIMIT"):
        assert not hasattr(llm, name)
    for name in ("HOSTED_WINDOW", "HOSTED_OUTPUT_TOKENS"):
        assert not hasattr(context_registry, name)
    assert not hasattr(Settings(_env_file=None), "hosted_working_context_tokens")


@pytest.mark.parametrize(
    ("window", "effort", "working", "history"),
    [
        # The answer reserve (4,000), the effort's reasoning headroom and 512 safety tokens
        # come off the window; history is a quarter of W up to 32K.
        (16_384, "low", 16_384 - 4000 - 1024 - 512, (16_384 - 4000 - 1024 - 512) // 4),
        (128_000, "none", 128_000 - 4000 - 512, (128_000 - 4000 - 512) // 4),
        (128_000, "max", 128_000 - 4000 - 16_384 - 512, (128_000 - 4000 - 16_384 - 512) // 4),
        (400_000, "low", 272_000, 32_000),
        (1_050_000, "high", 272_000, 32_000),
    ],
)
def test_given_a_window_when_profiling_then_budget_and_history_follow_the_design(
    monkeypatch, window, effort, working, history
):
    from app.integrations.context_registry import context_profile

    entry = synthetic(monkeypatch, window)
    profile = context_profile(SimpleNamespace(settings=Settings(_env_file=None)), entry.key, effort)
    assert (profile.window, profile.input_budget) == (window, working)
    assert profile.history_budget == min(history, 32_000)
    assert profile.history_budget <= profile.input_budget // 4 or profile.history_budget == 32_000


def test_given_the_real_models_when_profiling_then_the_price_tier_caps_every_effort():
    from app.integrations.context_registry import hosted_profile

    for model in MODELS:
        for effort in catalog().HOSTED_MODELS[model].reasoning_efforts:
            profile = hosted_profile(model, effort)
            assert profile.input_budget == 272_000 and profile.window == 1_050_000
            assert profile.history_budget == 32_000 and profile.max_output == 4000


def test_given_a_window_smaller_than_its_reserves_when_profiling_then_nothing_is_negative(
    monkeypatch,
):
    from app.integrations.context_registry import hosted_profile

    entry = synthetic(monkeypatch, 3000)
    assert hosted_profile(entry.key, "max").input_budget == 0


def prompt_pieces(counter, n: int):
    turn = " ".join(f"detail{i}" for i in range(150))
    history = []
    for i in range(n):
        history += [
            SimpleNamespace(role="user", content=f"Question {i}? {turn}", state="completed"),
            SimpleNamespace(
                role="assistant", content=f"Answer {i}. {turn}", state="completed", citations=[]
            ),
        ]
    return history


class Passages:
    def __init__(self, counter):
        self.counter = counter

    def __call__(self, budget):
        from app.integrations.tokens import keep_head

        text = "".join(f"[S{i}] passage {i}\n" for i in range(60000))
        return keep_head(self.counter, text, budget)


@pytest.mark.parametrize("window", [16_384, 128_000, 1_050_000])
def test_given_synthetic_windows_when_assembling_answers_then_history_scales_and_fits(
    monkeypatch, window
):
    from app.integrations.context_registry import hosted_profile
    from app.services.context import PaperHeader, assemble_answer_prompt

    entry = synthetic(monkeypatch, window)
    profile = hosted_profile(entry.key, "low")
    history = prompt_pieces(profile.counter, 400)
    result = assemble_answer_prompt(
        profile=profile,
        papers=[PaperHeader("Title", ["Ada"], 2024)],
        history=history,
        memory_summary=(1, "word " * 20_000),
        recalled=[("old question " * 200, "old answer " * 200)] * 60,
        evidence_block=Passages(profile.counter),
        question="What changed?",
        retrieved_for=None,
    )
    shares = result.allocation
    assert shares.summary + shares.recent + shares.recall <= profile.history_budget
    assert count_messages(profile.counter, result.messages) <= profile.input_budget
    assert result.usage.input_tokens <= profile.input_budget
    # Evidence takes what history leaves, and history alone fills its share on a long chat.
    assert shares.evidence >= profile.input_budget - profile.history_budget - 2000
    assert shares.recent > 0.5 * profile.history_budget


@pytest.mark.parametrize("window", [16_384, 128_000, 1_050_000])
def test_given_synthetic_windows_when_sizing_memory_then_planner_and_compaction_derive_from_w(
    monkeypatch, window
):
    from app.integrations.context_registry import hosted_profile
    from app.services.memory import (
        PLANNER_CONTEXT_TOKENS,
        compaction_prompt,
        memory_shares,
        planner_prompt,
        turn_pairs,
    )

    entry = synthetic(monkeypatch, window)
    profile = hosted_profile(entry.key, "low")
    shares = memory_shares(profile)
    assert shares.summary + shares.recent + shares.recall <= profile.history_budget
    history = prompt_pieces(profile.counter, 300)
    pairs = turn_pairs(history)
    planner = planner_prompt(
        profile.counter, profile.input_budget, pairs, "summary " * 5000, "And then?"
    )
    assert count_messages(profile.counter, planner) <= profile.input_budget
    room = min(PLANNER_CONTEXT_TOKENS, profile.history_budget // 4)
    fixed = count_messages(
        profile.counter, [planner[0], PromptMessage("user", "\n\nFollow-up question: And then?")]
    )
    assert count_messages(profile.counter, planner) <= fixed + room + 8
    target = min(2000, shares.summary)
    prompt = compaction_prompt(
        profile.counter, profile.input_budget, "previous " * 40_000, pairs, target
    )
    assert count_messages(profile.counter, prompt) <= profile.input_budget


def test_given_small_and_large_windows_when_history_grows_then_compaction_starts_sooner_on_small(
    monkeypatch,
):
    from app.integrations.context_registry import hosted_profile
    from app.services.memory import compaction_boundary, turn_pairs

    small = hosted_profile(synthetic(monkeypatch, 16_384).key, "low")
    large = hosted_profile(synthetic(monkeypatch, 1_050_000).key, "low")
    history = []
    for i in range(30):
        history += [
            SimpleNamespace(
                id=f"u{i}", role="user", content="q " * 400, state="completed", citations=[]
            ),
            SimpleNamespace(
                id=f"a{i}", role="assistant", content="a " * 400, state="completed", citations=[]
            ),
        ]
    pairs = turn_pairs(history)
    first_small = next(n for n in range(2, 31) if compaction_boundary(pairs[:n], small, 0.6))
    first_large = next(n for n in range(2, 31) if compaction_boundary(pairs[:n], large, 0.6))
    assert first_small < first_large
    # A large window keeps well over 10K tokens verbatim before it compacts.
    assert first_large * 1600 > 10_000


def test_given_cached_input_when_priced_then_the_cached_rate_applies():
    from app.services.costs import call_cost

    usage = {
        "input_tokens": 20_000,
        "output_tokens": 500,
        "input_tokens_details": {"cached_tokens": 15_000},
    }
    luna = catalog().HOSTED_MODELS["gpt-5.6-luna"]
    expected = (
        luna.input_price * 5000 + luna.cached_input_price * 15_000 + luna.output_price * 500
    ) / MILLION
    assert call_cost("gpt-5.6-luna", usage) == expected
    plain = {"input_tokens": 20_000, "output_tokens": 500}
    uncached = (luna.input_price * 20_000 + luna.output_price * 500) / MILLION
    assert call_cost("gpt-5.6-luna", plain) == uncached


def test_given_cache_writes_when_priced_then_each_token_has_one_rate():
    from app.services.costs import call_cost

    usage = {
        "input_tokens": 10_000,
        "output_tokens": 0,
        "input_tokens_details": {"cached_tokens": 4000, "cache_write_tokens": 2000},
    }
    luna = catalog().HOSTED_MODELS["gpt-5.6-luna"]
    expected = (
        luna.input_price * 4000 + luna.cached_input_price * 4000 + luna.cache_write_price * 2000
    ) / MILLION
    assert call_cost("gpt-5.6-luna", usage) == expected
    # Reads and writes together cannot exceed the input; an impossible pair is priced uncached.
    usage["input_tokens_details"] = {"cached_tokens": 8000, "cache_write_tokens": 8000}
    assert call_cost("gpt-5.6-luna", usage) == luna.input_price * 10_000 / MILLION


@pytest.mark.parametrize("cached", [-1, 25_000, "many", True, None])
def test_given_implausible_cached_count_when_priced_then_it_is_ignored(cached):
    from app.services.costs import call_cost

    usage = {
        "input_tokens": 20_000,
        "output_tokens": 0,
        "input_tokens_details": {"cached_tokens": cached},
    }
    assert call_cost("gpt-5.6-luna", usage) == Decimal("0.2") * 20_000 / MILLION


def test_given_planner_usage_when_billed_then_cached_tokens_are_kept():
    from app.services.memory import billed_tokens

    usage = {
        "input_tokens": 900,
        "output_tokens": 30,
        "total_tokens": 930,
        "input_tokens_details": {"cached_tokens": 512},
    }
    assert billed_tokens(usage) == {
        "input_tokens": 900,
        "output_tokens": 30,
        "input_tokens_details": {"cached_tokens": 512},
    }
    assert billed_tokens({"input_tokens": 5, "output_tokens": 1}) == {
        "input_tokens": 5,
        "output_tokens": 1,
    }


def test_given_a_reservation_when_estimated_then_it_stays_an_uncached_upper_bound():
    luna = catalog().HOSTED_MODELS["gpt-5.6-luna"]
    amount = llm.reservation_amount("gpt-5.6-luna", 10_000)
    assert amount == (luna.input_price * 10_000 + luna.output_price * 4000) / MILLION


async def test_given_the_models_route_when_listing_then_each_reports_its_catalog_window(
    monkeypatch,
):
    from app.routes import ai

    async def nothing(resources):
        return []

    async def hosted_default(resources):
        return ai.Defaults()

    synthetic(monkeypatch, 128_000, "gpt-5.6-terra")
    monkeypatch.setattr(ai, "list_local_models", nothing)
    monkeypatch.setattr(ai, "saved_defaults", hosted_default)
    resources = SimpleNamespace(settings=Settings(_env_file=None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resources=resources)))
    page = await ai.models(request)
    assert {item.key: item.context_window for item in page.items} == {
        "gpt-5.6-sol": 1_050_000,
        "gpt-5.6-terra": 128_000,
        "gpt-5.6-luna": 1_050_000,
    }


def test_given_a_counter_when_hosted_then_the_catalog_encoding_is_used():
    from app.integrations.context_registry import hosted_profile

    assert isinstance(hosted_profile("gpt-5.6-luna", "low").counter, TiktokenCounter)
