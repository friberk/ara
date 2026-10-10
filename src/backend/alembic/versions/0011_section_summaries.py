"""Section summaries: one short cited summary per top-level section, searched beside chunks
(ARA-079, ARA-094).

A summary belongs to a section of the document's current chunk set, so re-reading a PDF, which
replaces its sections, removes the summaries and their vectors with them. `content` keeps the
summary's canonical `[source:<chunk-uuid>]` markers; its keyword index leaves them out.

Revision ID: 0011_section_summaries
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0011_section_summaries"
down_revision = "0010_chat_papers"
branch_labels = None
depends_on = None

SEARCH_VECTOR = (
    "setweight(to_tsvector('english', title), 'A') || setweight(to_tsvector('english', "
    "regexp_replace(content, '\\[source:[^]]*\\]', ' ', 'g')), 'B')"
)


def created_at():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade():
    op.create_table(
        "section_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.Uuid(),
            sa.ForeignKey("document_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_set", sa.String(80), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", JSONB(), nullable=False, server_default="[]"),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("reasoning_effort", sa.String(20), nullable=False),
        sa.Column("usage", JSONB(), nullable=False, server_default="{}"),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id", ondelete="SET NULL")),
        created_at(),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
        ),
        sa.UniqueConstraint("section_id", name="uq_section_summary_section"),
    )
    op.create_index(
        "ix_section_summary_document", "section_summaries", ["document_id", "chunk_set"]
    )
    op.create_index(
        "ix_section_summary_search",
        "section_summaries",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_table(
        "section_summary_embeddings",
        sa.Column(
            "summary_id",
            sa.Uuid(),
            sa.ForeignKey("section_summaries.id", ondelete="CASCADE"),
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
    op.create_index(
        "ix_summary_embedding_document_profile",
        "section_summary_embeddings",
        ["document_id", "profile"],
    )


def downgrade():
    op.drop_table("section_summary_embeddings")
    op.drop_table("section_summaries")
