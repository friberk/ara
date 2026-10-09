"""Per-model context windows, output and thinking allowances, and token counters (ARA-076)."""

from dataclasses import dataclass
from typing import Literal

from app.integrations.tokens import TiktokenCounter

HOSTED_WINDOW = 1_050_000
HOSTED_OUTPUT_TOKENS = 4000
# tiktoken.encoding_for_model("gpt-5.6-luna") resolves to o200k_base, and OpenAI's
# token-count endpoint matched it exactly (ARA-070 S1).
HOSTED_ENCODING = "o200k_base"
LOCAL_ENCODING = "o200k_base"
SAFETY_TOKENS = 512


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


def local_thinks(effort: str, thinking: dict | None) -> bool:
    """Whether a local request may think; `default` follows the model's verified default."""
    if effort == "default":
        return bool(thinking) and thinking.get("default") is not False
    return effort != "none"


def hosted_profile(settings, model: str) -> ContextProfile:
    return ContextProfile(
        model=model,
        provider="openai",
        window=HOSTED_WINDOW,
        max_output=HOSTED_OUTPUT_TOKENS,
        thinking_allowance=0,
        safety=SAFETY_TOKENS,
        input_budget=min(
            HOSTED_WINDOW - HOSTED_OUTPUT_TOKENS - SAFETY_TOKENS,
            settings.hosted_working_context_tokens,
        ),
        counter=TiktokenCounter(HOSTED_ENCODING),
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
    return hosted_profile(resources.settings, model)
