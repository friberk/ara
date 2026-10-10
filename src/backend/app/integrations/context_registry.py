"""Per-model context windows, output and thinking allowances, and token counters (ARA-076)."""

from dataclasses import dataclass
from typing import Literal

from app.integrations.hosted_catalog import hosted_model
from app.integrations.tokens import TiktokenCounter

LOCAL_ENCODING = "o200k_base"
SAFETY_TOKENS = 512
# Conversation history (summary, recent turns, recalled turns) is capped at 32K tokens or a
# quarter of the working budget W, whichever is smaller; older turns are summarised. Small
# windows therefore summarise sooner and large ones keep up to 32K verbatim, in step with long
# prompts degrading answers (docs/plans/retrieval-orchestration.md, "Budget").
HISTORY_TARGET_TOKENS = 32_000
HISTORY_SHARE_PERCENT = 25
# Hosted reasoning tokens count against max_output_tokens, so an intermediate call that asks
# for a short answer at a high effort needs room above it or it ends incomplete.
HOSTED_REASONING_HEADROOM = {
    "none": 0,
    "low": 1024,
    "medium": 2048,
    "high": 4096,
    "xhigh": 8192,
    "max": 16384,
}


def hosted_reasoning_headroom(effort: str) -> int:
    return HOSTED_REASONING_HEADROOM.get(effort, 0)


@dataclass(frozen=True)
class ContextProfile:
    model: str
    provider: Literal["openai", "ollama"]
    window: int
    max_output: int
    thinking_allowance: int
    safety: int
    input_budget: int
    counter: TiktokenCounter

    @property
    def history_budget(self) -> int:
        """H = min(32K, 25% of W); the evidence ceiling is W - F - H."""
        return history_budget(self.input_budget)


def history_budget(input_budget: int) -> int:
    return min(HISTORY_TARGET_TOKENS, input_budget * HISTORY_SHARE_PERCENT // 100)


def local_thinks(effort: str, thinking: dict | None) -> bool:
    """Whether a local request may think; `default` follows the model's verified default."""
    if effort == "default":
        return bool(thinking) and thinking.get("default") is not False
    return effort != "none"


def hosted_profile(model: str, effort: str = "none") -> ContextProfile:
    """W = min(window - answer reserve - reasoning reserve - safety, price-tier cap)."""
    entry = hosted_model(model)
    if entry is None:
        raise KeyError(model)
    reserves = entry.answer_reserve + hosted_reasoning_headroom(effort) + SAFETY_TOKENS
    working = entry.window - reserves
    return ContextProfile(
        model=model,
        provider="openai",
        window=entry.window,
        max_output=entry.answer_reserve,
        thinking_allowance=0,
        safety=SAFETY_TOKENS,
        input_budget=max(0, min(working, entry.price_tier_tokens)),
        counter=TiktokenCounter(entry.encoding),
    )


def local_profile(
    settings, model: str, effort: str, *, thinking: dict | None = None
) -> ContextProfile:
    window, output = settings.ollama_context_window, settings.ollama_max_output_tokens
    allowance = settings.ollama_thinking_tokens if local_thinks(effort, thinking) else 0
    return ContextProfile(
        model=model,
        provider="ollama",
        window=window,
        max_output=output,
        thinking_allowance=allowance,
        safety=SAFETY_TOKENS,
        input_budget=min(
            window - output - allowance - SAFETY_TOKENS, settings.local_input_budget_tokens
        ),
        counter=TiktokenCounter(LOCAL_ENCODING, settings.local_token_factor),
    )


def context_profile(
    resources, model: str, effort: str, *, thinking: dict | None = None
) -> ContextProfile:
    """`thinking` is the local model's verified controls (`Model.thinking`), if any."""
    from app.integrations.model_catalog import local_spec

    if local_spec(model):
        return local_profile(resources.settings, model, effort, thinking=thinking)
    return hosted_profile(model, effort)
