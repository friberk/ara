"""Pinned, opt-in local artifacts. These names must never resolve to substitute models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalModelSpec:
    key: str
    model_id: str
    display_name: str
    expected_digest: str
    download_bytes: int
    quantization: str = "Q4_K_M"


LOCAL_MODELS = {
    spec.key: spec
    for spec in (
        LocalModelSpec(
            "ifm-k2-horizon-3.7b",
            "hf.co/IFM/K2-Horizon-3.7B-GGUF:Q4_K_M",
            "IFM K2 Horizon 3.7B",
            "2e334d42ac17a07fb7e6447dd5c98d0c501d4f90bef900cc57fd3f6cd067dd2c",
            3156599066,
        ),
        LocalModelSpec(
            "ifm-k2-horizon-7b",
            "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
            "IFM K2 Horizon 7B",
            "3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278",
            5592218900,
        ),
        LocalModelSpec(
            "qwen3.8-27b",
            "qwen3.8:27b-q4_K_M",
            "Qwen 3.8 27B",
            "25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e",
            17741872132,
        ),
    )
}


def local_spec(key: str) -> LocalModelSpec | None:
    return LOCAL_MODELS.get(key)
