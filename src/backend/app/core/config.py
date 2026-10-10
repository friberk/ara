import ipaddress
import re
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://ara:development@localhost:5432/ara")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    broker_namespace: str = "dramatiq"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("development")
    minio_secret_key: SecretStr = SecretStr("development-secret")
    minio_bucket: str = "research-pdfs"
    minio_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    openai_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None
    semantic_scholar_api_key: SecretStr | None = None
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    openalex_base_url: str = "https://api.openalex.org"
    openai_base_url: str = "https://api.openai.com/v1"
    fulltext_allowed_hosts: list[str] = [
        "arxiv.org",
        "export.arxiv.org",
        "aclanthology.org",
        "pmc.ncbi.nlm.nih.gov",
        "europepmc.org",
        "proceedings.neurips.cc",
        "openaccess.thecvf.com",
        "pdfs.semanticscholar.org",
        "link.springer.com",
        "www.nature.com",
        "nature.com",
        "static-content.springer-cdn.com",
        "ieeexplore.ieee.org",
        "dl.acm.org",
    ]
    ollama_base_url: str = "http://ollama:11434"
    ollama_context_window: int = Field(default=8192, ge=1024, le=131072)
    ollama_max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    # Ollama counts thinking against num_predict, so thinking efforts get their own allowance.
    ollama_thinking_tokens: int = Field(default=1024, ge=0, le=32768)
    # Interactive cap on local prompts: CPU prefill runs at tens of tokens per second, so
    # 3,072 tokens keep a local answer near one minute (ARA-070 S1).
    local_input_budget_tokens: int = Field(default=3072, ge=256, le=131072)
    # Local tokenizers measured 0.974-1.018x o200k (ARA-070 S1); counts round up from o200k.
    local_token_factor: float = Field(default=1.05, ge=1, le=2)
    hosted_working_context_tokens: int = Field(default=64000, ge=1024, le=1_000_000)
    # Compact older turns once unsummarized turns pass this share of the recent-turns budget.
    memory_compaction_ratio: float = Field(default=0.6, gt=0, le=1)
    ollama_num_threads: int = Field(default=4, ge=1, le=64)
    ollama_request_timeout_seconds: float = Field(default=900, gt=0, le=21600)
    ollama_pull_timeout_seconds: float = Field(default=21600, gt=0, le=21600)
    ollama_stall_seconds: float = Field(default=120, gt=0, le=3600)
    ollama_memory_limit: str = "12g"
    # Open (local) models are experimental and frozen (ARA-090): nothing of them exists unless on.
    experimental_open_models: bool = False
    default_model: str = "gpt-5.6-luna"
    default_reasoning_effort: str = "low"
    llm_daily_budget_usd: float = Field(default=5, gt=0)
    dispatch_interval_seconds: float = Field(default=2, ge=0.1)
    recovery_interval_seconds: float = Field(default=30, ge=1)
    lease_seconds: int = Field(default=60, ge=30)
    heartbeat_seconds: int = Field(default=10, ge=1)

    @field_validator("fulltext_allowed_hosts")
    @classmethod
    def public_hostnames(cls, values: list[str]) -> list[str]:
        result = []
        for value in values:
            host = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
            if not re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", host
            ):
                raise ValueError("FULLTEXT_ALLOWED_HOSTS must contain exact hostnames")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("FULLTEXT_ALLOWED_HOSTS cannot contain IP addresses")
            if host not in result:
                result.append(host)
        return result

    @field_validator("ollama_base_url")
    @classmethod
    def local_http_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("OLLAMA_BASE_URL must be an HTTP endpoint without credentials or path")
        try:
            _ = parts.port
        except ValueError as exc:
            raise ValueError("OLLAMA_BASE_URL has an invalid port") from exc
        return value.rstrip("/")

    @field_validator("ollama_memory_limit")
    @classmethod
    def memory_limit(cls, value: str) -> str:
        if not re.fullmatch(r"[1-9]\d*(?:[kKmMgG](?:[bB])?)?", value):
            raise ValueError("OLLAMA_MEMORY_LIMIT must be a positive Docker memory limit")
        return value

    @model_validator(mode="after")
    def local_context_reserves_output(self):
        reserved = self.ollama_max_output_tokens + self.ollama_thinking_tokens + 512
        if self.ollama_context_window <= reserved:
            raise ValueError("Local context must reserve output, thinking and 512 safety tokens")
        return self

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        return value

    @model_validator(mode="after")
    def fixture_overrides_are_test_only(self):
        defaults = {
            "semantic_scholar_base_url": "https://api.semanticscholar.org/graph/v1",
            "openalex_base_url": "https://api.openalex.org",
            "openai_base_url": "https://api.openai.com/v1",
        }
        if self.app_env != "test" and any(
            getattr(self, key).rstrip("/") != url for key, url in defaults.items()
        ):
            raise ValueError("Provider URL overrides are allowed only in APP_ENV=test")
        return self

    def secret_values(self) -> list[str]:
        return [
            value.get_secret_value()
            for value in self.__dict__.values()
            if isinstance(value, SecretStr) and value.get_secret_value()
        ]
