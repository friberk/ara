from pydantic import BaseModel, ConfigDict

from app.schemas.research import Provider


class MetadataSettings(BaseModel):
    """Which catalog uploaded PDFs are looked up in first (ARA-086)."""

    model_config = ConfigDict(extra="forbid")
    source: Provider = "openalex"
