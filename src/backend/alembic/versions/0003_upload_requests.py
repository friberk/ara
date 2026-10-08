"""Bind every deduplicated upload request to its retained original."""

import sqlalchemy as sa

from alembic import op

revision = "0003_upload_requests"
down_revision = "0002_research"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_upload_requests",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.execute(
        "INSERT INTO document_upload_requests (request_id, document_id, created_at) "
        "SELECT request_id, id, created_at FROM documents"
    )


def downgrade():
    op.drop_table("document_upload_requests")
