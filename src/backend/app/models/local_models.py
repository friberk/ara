from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelInstallation(Base):
    __tablename__ = "model_installations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('missing','queued','downloading','pausing','paused',"
            "'verifying','ready','deleting','failed')",
            name="model_installation_state",
        ),
    )
    model_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default="missing")
    desired_state: Mapped[str] = mapped_column(String(20), default="ready")
    weights_present: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    digest: Mapped[str | None] = mapped_column(String(80))
    active_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    validation: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(400))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRequest(Base):
    __tablename__ = "model_requests"
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    model_key: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(20))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("background_jobs.id", ondelete="CASCADE"))
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelUse(Base):
    __tablename__ = "model_uses"
    slot: Mapped[str] = mapped_column(String(40), primary_key=True)
    model_key: Mapped[str] = mapped_column(String(80))
    token: Mapped[UUID] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
