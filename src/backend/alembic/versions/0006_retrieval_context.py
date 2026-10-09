"""Structured chunks, pgvector embeddings, retrieval indexes and conversation memory.

Existing chunks are discarded: documents are re-ingested into the new chunk set (ARA-071).
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0006_retrieval_context"
down_revision = "0005_local_models"
branch_labels = None
depends_on = None

SEARCH_VECTOR = (
    "setweight(to_tsvector('english', heading), 'A') || "
    "setweight(to_tsvector('english', text), 'B')"
)


def created_at():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("papers", sa.Column("retrieval_profile", sa.String(40)))
    op.add_column("documents", sa.Column("parser", sa.String(40)))
    op.add_column("documents", sa.Column("chunk_set", sa.String(80)))
    op.add_column(
        "chat_messages",
        sa.Column("retrieval", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "chat_messages",
        sa.Column("context", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column("chat_messages", sa.Column("grounding", sa.String(20)))
    op.create_check_constraint(
        "message_grounding", "chat_messages", "grounding IN ('supported','insufficient')"
    )

    op.create_table(
        "document_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_set", sa.String(80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("path", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_set", "ordinal", name="uq_section_ordinal"),
        sa.CheckConstraint("role IN ('front_matter','body','references')", name="section_role"),
    )

    op.drop_table("document_chunks")
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_set", sa.String(80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "section_id", sa.Uuid(), sa.ForeignKey("document_sections.id", ondelete="SET NULL")
        ),
        sa.Column("section_path", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("heading", sa.Text(), server_default="", nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("bboxes", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_set", "ordinal", name="uq_document_chunk_ordinal"
        ),
        sa.CheckConstraint(
            "kind IN ('front_matter','text','table','references')", name="chunk_kind"
        ),
    )
    op.create_index("ix_chunk_document", "document_chunks", ["document_id", "chunk_set", "ordinal"])
    op.create_index("ix_chunk_search", "document_chunks", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "chunk_embeddings",
        sa.Column(
            "chunk_id",
            sa.Uuid(),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("profile", sa.String(40), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", HALFVEC(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        created_at(),
    )
    op.create_index("ix_embedding_document_profile", "chunk_embeddings", ["document_id", "profile"])

    op.create_table(
        "retrieval_indexes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile", sa.String(40), nullable=False),
        sa.Column("chunk_set", sa.String(80), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("embedded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_digest", sa.String(80)),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id", ondelete="SET NULL")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(400)),
        created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "profile", "chunk_set", name="uq_retrieval_index"),
        sa.CheckConstraint(
            "state IN ('queued','embedding','ready','failed','unavailable')",
            name="retrieval_index_state",
        ),
    )

    op.create_table(
        "chat_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "through_message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("usage", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        created_at(),
        sa.UniqueConstraint("session_id", "version", name="uq_chat_memory_version"),
        sa.UniqueConstraint("session_id", "through_message_id", name="uq_chat_memory_through"),
    )

    op.create_table(
        "chat_turn_embeddings",
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("profile", sa.String(40), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", HALFVEC(), nullable=False),
        created_at(),
    )


def downgrade():
    op.drop_table("chat_turn_embeddings")
    op.drop_table("chat_memories")
    op.drop_table("retrieval_indexes")
    op.drop_table("chunk_embeddings")
    op.drop_table("document_chunks")
    op.drop_table("document_sections")
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_ordinal"),
    )
    op.create_index("ix_chunk_document", "document_chunks", ["document_id"])
    op.create_index("ix_chunk_search", "document_chunks", ["search_vector"], postgresql_using="gin")
    op.drop_constraint("message_grounding", "chat_messages", type_="check")
    for column in ("grounding", "context", "retrieval"):
        op.drop_column("chat_messages", column)
    op.drop_column("documents", "chunk_set")
    op.drop_column("documents", "parser")
    op.drop_column("papers", "retrieval_profile")
    # The vector extension stays installed; dropping it could affect other databases' objects.
