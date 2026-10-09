from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class CanaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="pipeline-ok", max_length=200)


class ModelOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class JobRetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None


class JobError(BaseModel):
    code: str
    message: str


class JobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    state: Literal["queued", "processing", "paused", "completed", "failed"]
    stage: str
    progress: int
    attempts: int
    generation: int
    result: dict | None
    error_code: str | None
    error_message: str | None
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    model_operation: Literal["download", "verify", "delete"] | None = None
    model_key: str | None = None
    completed_bytes: int | None = None
    total_bytes: int | None = None
    paper_id: UUID | None = None
    paper_title: str | None = None

    @computed_field
    @property
    def error(self) -> JobError | None:
        if self.error_code is None:
            return None
        return JobError(code=self.error_code, message=self.error_message or "Job failed.")


class JobPage(BaseModel):
    items: list[JobStatus]
