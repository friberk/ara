"""Versioned running summaries and embedded turns for long conversations (ARA-070)."""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatMemory(Base):
    __tablename__ = "chat_memories"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_chat_memory_version"),
        UniqueConstraint("session_id", "through_message_id", name="uq_chat_memory_through"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    version: Mapped[int]
    through_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE")
    )
    summary: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatTurnEmbedding(Base):
    __tablename__ = "chat_turn_embeddings"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True
    )
    profile: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    embedding: Mapped[list[float]] = mapped_column(HALFVEC())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
