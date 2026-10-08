"""Workspace history: search history, chat title source and chat activity index."""

import sqlalchemy as sa

from alembic import op

revision = "0004_workspace_history"
down_revision = "0003_upload_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.String(900), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_searched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "normalized_query", name="uq_search_history_query"),
    )
    op.create_index("ix_search_history_recent", "search_history", ["last_searched_at"])
    op.add_column(
        "chat_sessions",
        sa.Column("title_source", sa.String(20), server_default="default", nullable=False),
    )
    op.create_check_constraint(
        "chat_title_source", "chat_sessions", "title_source IN ('default','auto','manual')"
    )
    # Existing chats with a non-default title were named explicitly at creation.
    op.execute("UPDATE chat_sessions SET title_source = 'manual' WHERE title <> 'Paper discussion'")
    op.create_index("ix_chat_message_activity", "chat_messages", ["session_id", "created_at"])


def downgrade():
    op.drop_index("ix_chat_message_activity", table_name="chat_messages")
    op.drop_constraint("chat_title_source", "chat_sessions", type_="check")
    op.drop_column("chat_sessions", "title_source")
    op.drop_index("ix_search_history_recent", table_name="search_history")
    op.drop_table("search_history")
