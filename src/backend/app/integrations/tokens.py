"""Real token counts. Hosted models use their own encoding; local models scale o200k."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import tiktoken

# Role framing per message plus reply priming. The Responses token-count endpoint measured
# o200k + 6 per request (ARA-070 S1), so this stays conservative for short lists.
MESSAGE_OVERHEAD = 4
REPLY_PRIMING = 3


@dataclass(frozen=True)
class PromptMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class TiktokenCounter:
    """Exact for hosted o200k models; `factor` covers local tokenizers measured against o200k."""

    def __init__(self, encoding: str = "o200k_base", factor: float = 1.0):
        self.encoding = tiktoken.get_encoding(encoding)
        self.factor = factor

    def count(self, text: str) -> int:
        return math.ceil(len(self.encoding.encode(text, disallowed_special=())) * self.factor)


def count_messages(counter: TokenCounter, messages: Sequence[PromptMessage]) -> int:
    return sum(counter.count(m.content) + MESSAGE_OVERHEAD for m in messages) + REPLY_PRIMING


def keep_head(counter: TokenCounter, text: str, limit: int) -> str:
    """Longest prefix within `limit` tokens; slicing by code point keeps characters whole."""
    if counter.count(text) <= limit:
        return text
    fits, over = 0, len(text)
    while over - fits > 1:
        middle = (fits + over) // 2
        if counter.count(text[:middle]) <= limit:
            fits = middle
        else:
            over = middle
    return text[:fits]


def keep_tail(counter: TokenCounter, text: str, limit: int) -> str:
    """Longest suffix within `limit` tokens."""
    if counter.count(text) <= limit:
        return text
    over, fits = 0, len(text)
    while fits - over > 1:
        middle = (fits + over) // 2
        if counter.count(text[middle:]) <= limit:
            fits = middle
        else:
            over = middle
    return text[fits:]
