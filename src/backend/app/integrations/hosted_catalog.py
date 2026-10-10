"""The hosted chat models and every limit, price and control that belongs to each (ARA-093).

One entry per model is the only source of its window, output allowance, prices, price tier,
reasoning levels and token encoding; budgets and costs read it and never repeat a model ID.
"""

from dataclasses import dataclass
from decimal import Decimal

# tiktoken.encoding_for_model("gpt-5.6-luna") resolves to o200k_base, and OpenAI's
# token-count endpoint matched it exactly (ARA-070 S1).
HOSTED_ENCODING = "o200k_base"
# Verified 2026-10-10 on each model page below: reasoning levels none to max, a 1,050,000 token
# window, 128,000 maximum output, and cache writes billed at 1.25x the uncached input rate.
# Prompts over 272K input tokens are billed at 2x input and 1.5x output for the whole request,
# so the application never sends more than the tier boundary (see context_registry).
# Prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
SOURCE = "https://developers.openai.com/api/docs/models/"


@dataclass(frozen=True)
class HostedModel:
    key: str
    display_name: str
    # Native context window and the model's own maximum output, both in tokens.
    window: int
    max_output: int
    # Output the application allows an answer; a policy, distinct from `max_output`.
    answer_reserve: int
    # USD per million tokens.
    input_price: Decimal
    cached_input_price: Decimal
    cache_write_price: Decimal
    output_price: Decimal
    # Input beyond this many tokens is billed at a higher tier.
    price_tier_tokens: int
    reasoning_efforts: tuple[str, ...]
    encoding: str
    source: str


def entry(name: str, input_price: str, cached_price: str, output_price: str) -> HostedModel:
    return HostedModel(
        key=f"gpt-5.6-{name}",
        display_name=f"GPT-5.6 {name.capitalize()}",
        window=1_050_000,
        max_output=128_000,
        answer_reserve=4000,
        input_price=Decimal(input_price),
        cached_input_price=Decimal(cached_price),
        cache_write_price=Decimal(input_price) * CACHE_WRITE_MULTIPLIER,
        output_price=Decimal(output_price),
        price_tier_tokens=272_000,
        reasoning_efforts=EFFORTS,
        encoding=HOSTED_ENCODING,
        source=f"{SOURCE}gpt-5.6-{name}",
    )


HOSTED_MODELS: dict[str, HostedModel] = {
    model.key: model
    for model in (
        entry("sol", "4", "0.4", "20"),
        entry("terra", "2", "0.2", "12"),
        entry("luna", "0.2", "0.02", "1.2"),
    )
}


def hosted_model(key: str) -> HostedModel | None:
    return HOSTED_MODELS.get(key)
