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
    default_model: str = "gpt-5.6-luna"
    default_reasoning_effort: str = "low"
    llm_daily_budget_usd: float = Field(default=5, gt=0)
    dispatch_interval_seconds: float = Field(default=2, ge=0.1)
    recovery_interval_seconds: float = Field(default=30, ge=1)
    lease_seconds: int = Field(default=60, ge=30)
    heartbeat_seconds: int = Field(default=10, ge=1)

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
