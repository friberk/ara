"""A chat covers one or more library papers, each with its own pinned PDF (ARA-088).

`chat_papers` replaces `chat_sessions.paper_id` and `document_id`. Each existing chat becomes a
one-paper chat at ordinal 0 with the PDF it already used, so history and citations are
unchanged. A trigger deletes a chat once its last paper link is gone, so deleting a paper still
deletes the chats about only that paper, as the old cascade did. The downgrade restores both
columns from each chat's first paper by ordinal.

Revision ID: 0010_chat_papers
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_chat_papers"
down_revision = "0009_upload_match_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_papers",
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("chat_id", "paper_id"),
        sa.UniqueConstraint("chat_id", "ordinal", name="uq_chat_paper_ordinal"),
    )
    op.create_index("ix_chat_papers_paper_id", "chat_papers", ["paper_id"])
    op.create_index("ix_chat_papers_document_id", "chat_papers", ["document_id"])
    op.execute(
        "INSERT INTO chat_papers (chat_id, paper_id, document_id, ordinal, added_at) "
        "SELECT id, paper_id, document_id, 0, created_at FROM chat_sessions"
    )
    op.drop_column("chat_sessions", "paper_id")
    op.drop_column("chat_sessions", "document_id")
    op.execute(
        "CREATE FUNCTION drop_chat_without_papers() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN DELETE FROM chat_sessions WHERE id = OLD.chat_id AND NOT EXISTS "
        "(SELECT 1 FROM chat_papers WHERE chat_id = OLD.chat_id); RETURN NULL; END $$"
    )
    op.execute(
        "CREATE TRIGGER chat_papers_last_paper AFTER DELETE ON chat_papers "
        "FOR EACH ROW EXECUTE FUNCTION drop_chat_without_papers()"
    )


def downgrade():
    op.execute("DROP TRIGGER chat_papers_last_paper ON chat_papers")
    op.execute("DROP FUNCTION drop_chat_without_papers()")
    op.add_column("chat_sessions", sa.Column("paper_id", sa.Uuid()))
    op.add_column("chat_sessions", sa.Column("document_id", sa.Uuid()))
    op.execute(
        "UPDATE chat_sessions AS chat SET paper_id = first.paper_id, "
        "document_id = first.document_id FROM ("
        "SELECT DISTINCT ON (chat_id) chat_id, paper_id, document_id FROM chat_papers "
        "ORDER BY chat_id, ordinal) AS first WHERE first.chat_id = chat.id"
    )
    op.alter_column("chat_sessions", "paper_id", nullable=False)
    op.alter_column("chat_sessions", "document_id", nullable=False)
    op.create_foreign_key(
        "chat_sessions_paper_id_fkey",
        "chat_sessions",
        "papers",
        ["paper_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "chat_sessions_document_id_fkey", "chat_sessions", "documents", ["document_id"], ["id"]
    )
    op.drop_index("ix_chat_papers_document_id", table_name="chat_papers")
    op.drop_index("ix_chat_papers_paper_id", table_name="chat_papers")
    op.drop_table("chat_papers")
