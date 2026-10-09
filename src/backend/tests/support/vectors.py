"""Deterministic fixture embeddings; keep identical to tests/fixtures/vectors.py."""

import hashlib
import math
import re

WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    "a an and are as at be by did do does for how in is it its of on or the this to was were "
    "what which with".split()
)


def fixture_vector(text: str, dims: int) -> list[float]:
    """Words hash to signed buckets; shared vocabulary means nearby vectors. Unit length."""
    # Qwen query instructions precede "Query:"; only the query itself carries meaning.
    text = text.split("Query:", 1)[-1].lower()
    vector = [0.0] * dims
    for word in WORD.findall(text):
        if word in STOP:
            continue
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dims] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return [1.0] + [0.0] * (dims - 1)
    return [value / norm for value in vector]
