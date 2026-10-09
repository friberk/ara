"""Durable request identities and immutable candidate outcomes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FullTextRequest(Base):
    __tablename__ = "fulltext_requests"
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("background_jobs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_fulltext_request_paper", "paper_id", "created_at"),)


class FullTextAttempt(Base):
    __tablename__ = "fulltext_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "generation", "ordinal", name="uq_fulltext_attempt"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("background_jobs.id", ondelete="CASCADE"))
    generation: Mapped[int]
    ordinal: Mapped[int]
    provider: Mapped[str] = mapped_column(String(40))
    candidate: Mapped[dict] = mapped_column(JSONB)
    response_status: Mapped[int | None]
    outcome: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(400))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
