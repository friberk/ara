"""Pinned, opt-in local artifacts. These names must never resolve to substitute models."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LocalModelSpec:
    key: str
    model_id: str
    display_name: str
    expected_digest: str
    download_bytes: int
    quantization: str = "Q4_K_M"
    boolean_enabled_effort: str | None = None
    kind: Literal["chat", "embedding", "reranker"] = "chat"
    embedding_dimensions: int | None = None


LOCAL_MODELS = {
    spec.key: spec
    for spec in (
        LocalModelSpec(
            "ifm-k2-horizon-3.7b",
            "hf.co/IFM/K2-Horizon-3.7B-GGUF:Q4_K_M",
            "IFM K2 Horizon 3.7B",
            "2e334d42ac17a07fb7e6447dd5c98d0c501d4f90bef900cc57fd3f6cd067dd2c",
            3156599066,
            boolean_enabled_effort="high",
        ),
        LocalModelSpec(
            "ifm-k2-horizon-7b",
            "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
            "IFM K2 Horizon 7B",
            "3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278",
            5592218900,
            boolean_enabled_effort="high",
        ),
        LocalModelSpec(
            "qwen3.8-27b",
            "qwen3.8:27b-q4_K_M",
            "Qwen 3.8 27B",
            "25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e",
            17741872132,
        ),
        # Embedding models use native dimensions; digests from the Phase 0 S1 pull.
        LocalModelSpec(
            "qwen3-embedding-4b",
            "qwen3-embedding:4b-q4_K_M",
            "Qwen3 Embedding 4B",
            "df5bd2e3c74cd8d069d21dc038f1b359fcdc9458fce1c99bd43c9eb1518ff907",
            2496704041,
            kind="embedding",
            embedding_dimensions=2560,
        ),
        LocalModelSpec(
            "qwen3-embedding-8b",
            "qwen3-embedding:8b-q4_K_M",
            "Qwen3 Embedding 8B",
            "64b933495768fbd3b87c20583d379728a07471e0c66733a9df87cd1901b3c44b",
            4676805193,
            kind="embedding",
            embedding_dimensions=4096,
        ),
        # Not the broken dengcao Q8_0 file (uniform logits); measured 12/12 by the lead.
        # Ollama lists the untagged pull as ":latest", and inventory matching is exact.
        LocalModelSpec(
            "qwen3-reranker-0.6b",
            "fanyx/Qwen3-Reranker-0.6B-Q8_0:latest",
            "Qwen3 Reranker 0.6B",
            "fd021d86a15e539ac1b4f3bec2d1c6b15a3e158f316adb0d1325c713240103b3",
            639152466,
            quantization="Q8_0",
            kind="reranker",
        ),
    )
}


def local_spec(key: str) -> LocalModelSpec | None:
    return LOCAL_MODELS.get(key)
