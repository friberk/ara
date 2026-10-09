"""Durable full-text requests, candidate attempts and document acquisition provenance."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0006_fulltext"
down_revision = "0005_local_models"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("acquisition", JSONB(), nullable=True))
    op.create_table(
        "fulltext_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "paper_id", sa.Uuid(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("background_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_fulltext_request_paper", "fulltext_requests", ["paper_id", "created_at"])
    op.create_table(
        "fulltext_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("background_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("candidate", JSONB(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(400), nullable=False),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("job_id", "generation", "ordinal", name="uq_fulltext_attempt"),
    )


def downgrade():
    op.drop_table("fulltext_attempts")
    op.drop_table("fulltext_requests")
    op.drop_column("documents", "acquisition")
