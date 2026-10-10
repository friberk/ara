"""Document structure, embeddings and versioned retrieval indexes (ARA-070)."""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_set", "ordinal", name="uq_section_ordinal"),
        CheckConstraint("role IN ('front_matter','body','references')", name="section_role"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_set: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    level: Mapped[int]
    path: Mapped[list] = mapped_column(JSONB, default=list)
    role: Mapped[str] = mapped_column(String(20), default="body")
    page: Mapped[int]
    page_end: Mapped[int]


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (Index("ix_embedding_document_profile", "document_id", "profile"),)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    profile: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Dimensions vary by profile; retrieval is document-scoped, so exact scans need no ANN index.
    embedding: Mapped[list[float]] = mapped_column(HALFVEC())
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetrievalIndex(Base):
    __tablename__ = "retrieval_indexes"
    __table_args__ = (
        UniqueConstraint("document_id", "profile", "chunk_set", name="uq_retrieval_index"),
        CheckConstraint(
            "state IN ('queued','embedding','ready','failed','unavailable')",
            name="retrieval_index_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    profile: Mapped[str] = mapped_column(String(40))
    chunk_set: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    embedded: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    model_digest: Mapped[str | None] = mapped_column(String(80))
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SectionSummary(Base):
    """A short cited summary of one top-level section, searched beside chunks (ARA-079).

    `content` keeps canonical `[source:<chunk-uuid>]` markers to the section's own chunks
    (`sources`); answers cite those chunks through their handles, never the summary itself.
    """

    __tablename__ = "section_summaries"
    __table_args__ = (
        UniqueConstraint("section_id", name="uq_section_summary_section"),
        Index("ix_section_summary_document", "document_id", "chunk_set"),
        Index("ix_section_summary_search", "search_vector", postgresql_using="gin"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    section_id: Mapped[UUID] = mapped_column(ForeignKey("document_sections.id", ondelete="CASCADE"))
    chunk_set: Mapped[str] = mapped_column(String(80))
    # The section's path, as chunk headings join it.
    title: Mapped[str] = mapped_column(Text)
    page: Mapped[int]
    page_end: Mapped[int]
    # The section's first chunk, which places the summary in page order.
    ordinal: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    context_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]
    model: Mapped[str] = mapped_column(String(80))
    reasoning_effort: Mapped[str] = mapped_column(String(20))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Source markers are left out of the keyword index.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', title), 'A') || setweight(to_tsvector('english', "
            "regexp_replace(content, '\\[source:[^]]*\\]', ' ', 'g')), 'B')",
            persisted=True,
        ),
    )


class SectionSummaryEmbedding(Base):
    __tablename__ = "section_summary_embeddings"
    __table_args__ = (Index("ix_summary_embedding_document_profile", "document_id", "profile"),)
    summary_id: Mapped[UUID] = mapped_column(
        ForeignKey("section_summaries.id", ondelete="CASCADE"), primary_key=True
    )
    profile: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    embedding: Mapped[list[float]] = mapped_column(HALFVEC())
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
