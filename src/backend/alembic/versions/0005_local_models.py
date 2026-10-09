"""Durable model installations, request identity and global inference leases."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0005_local_models"
down_revision = "0004_workspace_history"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("job_state", "background_jobs", type_="check")
    op.create_check_constraint(
        "job_state",
        "background_jobs",
        "state IN ('queued','processing','paused','completed','failed')",
    )
    op.add_column("background_jobs", sa.Column("model_key", sa.String(80)))
    op.add_column("background_jobs", sa.Column("completed_bytes", sa.BigInteger()))
    op.add_column("background_jobs", sa.Column("total_bytes", sa.BigInteger()))
    op.add_column("background_jobs", sa.Column("runtime_operation_id", sa.Uuid()))
    op.create_unique_constraint(
        "uq_job_runtime_operation", "background_jobs", ["runtime_operation_id"]
    )
    op.create_table(
        "model_installations",
        sa.Column("model_key", sa.String(80), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("desired_state", sa.String(20), nullable=False),
        sa.Column("weights_present", sa.Boolean(), nullable=False),
        sa.Column("completed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger()),
        sa.Column("digest", sa.String(80)),
        sa.Column(
            "active_job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id", ondelete="SET NULL")
        ),
        sa.Column("validation", JSONB()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(400)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('missing','queued','downloading','pausing','paused',"
            "'verifying','ready','deleting','failed')",
            name="model_installation_state",
        ),
    )
    op.create_table(
        "model_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("model_key", sa.String(80), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("background_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "model_uses",
        sa.Column("slot", sa.String(40), primary_key=True),
        sa.Column("model_key", sa.String(80), nullable=False),
        sa.Column("token", sa.Uuid(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("model_uses")
    op.drop_table("model_requests")
    op.drop_table("model_installations")
    op.drop_constraint("uq_job_runtime_operation", "background_jobs", type_="unique")
    for name in ["runtime_operation_id", "total_bytes", "completed_bytes", "model_key"]:
        op.drop_column("background_jobs", name)
    op.execute(
        "UPDATE background_jobs SET state = 'failed', stage = 'failed' WHERE state = 'paused'"
    )
    op.drop_constraint("job_state", "background_jobs", type_="check")
    op.create_check_constraint(
        "job_state", "background_jobs", "state IN ('queued','processing','completed','failed')"
    )
