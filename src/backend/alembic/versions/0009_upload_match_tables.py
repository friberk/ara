"""Upload-match state moves from prefixed settings rows into tables (ARA-092).

ARA-086 kept three kinds of state in `model_configurations`: `upload_match:<placeholder>`,
`paper_redirect:<placeholder>` and `pdf_doi_owner:<document>`. They become `upload_matches`,
`paper_redirects` and `documents.doi_owner_paper_id`, whose foreign keys remove state with the
rows it names. Rows that already point at something deleted, and malformed keys, are dropped.
The downgrade writes the prefixed rows back.

Revision ID: 0009_upload_match_tables
"""

import json
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision = "0009_upload_match_tables"
down_revision = "0008_library_embeddings"
branch_labels = None
depends_on = None

PENDING = "upload_match:"
REDIRECT = "paper_redirect:"
DOI_OWNER = "pdf_doi_owner:"


def uuid_of(value):
    try:
        return UUID(str(value))
    except ValueError:
        return None


def prefixed(connection, prefix):
    """(identifier, value) of each setting under the prefix whose identifier is a UUID."""
    rows = connection.execute(
        sa.text("SELECT key, value FROM model_configurations WHERE left(key, :n) = :prefix"),
        {"n": len(prefix), "prefix": prefix},
    ).all()
    return [(uuid_of(key[len(prefix) :]), value) for key, value in rows]


def existing(connection, table, ids):
    ids = [item for item in ids if item is not None]
    if not ids:
        return set()
    found = connection.execute(
        sa.text(f"SELECT id FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
    ).scalars()
    return set(found)


def upgrade():
    op.create_table(
        "upload_matches",
        sa.Column("placeholder_paper_id", sa.Uuid(), nullable=False),
        sa.Column("library_paper_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("matched_by", sa.String(10), nullable=False),
        sa.Column("found_by", sa.String(10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("matched_by IN ('doi','arxiv','title')", name="upload_match_matched_by"),
        sa.CheckConstraint("found_by IN ('ingest','lookup')", name="upload_match_found_by"),
        sa.ForeignKeyConstraint(["placeholder_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("placeholder_paper_id"),
    )
    op.create_index("ix_upload_matches_library_paper_id", "upload_matches", ["library_paper_id"])
    op.create_index("ix_upload_matches_document_id", "upload_matches", ["document_id"])
    op.create_table(
        "paper_redirects",
        sa.Column("old_paper_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("old_paper_id"),
    )
    op.create_index("ix_paper_redirects_paper_id", "paper_redirects", ["paper_id"])
    op.add_column("documents", sa.Column("doi_owner_paper_id", sa.Uuid()))
    op.create_foreign_key(
        "documents_doi_owner_paper_id_fkey",
        "documents",
        "papers",
        ["doi_owner_paper_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_doi_owner_paper_id", "documents", ["doi_owner_paper_id"])

    connection = op.get_bind()
    pending = [(key, value) for key, value in prefixed(connection, PENDING) if key is not None]
    redirects = [(key, value) for key, value in prefixed(connection, REDIRECT) if key is not None]
    owners = [(key, value) for key, value in prefixed(connection, DOI_OWNER) if key is not None]

    def target(value, name="paper_id"):
        return uuid_of(value.get(name)) if isinstance(value, dict) else None

    papers = existing(
        connection,
        "papers",
        [key for key, _ in pending]
        + [target(value) for _, value in pending]
        + [target(value) for _, value in redirects]
        + [target(value) for _, value in owners],
    )
    documents = existing(
        connection,
        "documents",
        [target(value, "document_id") for _, value in pending] + [key for key, _ in owners],
    )
    for placeholder, value in pending:
        library, document = target(value), target(value, "document_id")
        if placeholder not in papers or library not in papers or document not in documents:
            continue
        matched = value.get("matched_by")
        found = value.get("found_by")
        connection.execute(
            sa.text(
                "INSERT INTO upload_matches (placeholder_paper_id, library_paper_id, document_id,"
                " matched_by, found_by) VALUES (:placeholder, :library, :document, :matched,"
                " :found) ON CONFLICT DO NOTHING"
            ),
            {
                "placeholder": placeholder,
                "library": library,
                "document": document,
                "matched": matched if matched in ("doi", "arxiv", "title") else "doi",
                "found": found if found in ("ingest", "lookup") else "ingest",
            },
        )
    for old, value in redirects:
        if target(value) in papers:
            connection.execute(
                sa.text(
                    "INSERT INTO paper_redirects (old_paper_id, paper_id)"
                    " VALUES (:old, :paper) ON CONFLICT DO NOTHING"
                ),
                {"old": old, "paper": target(value)},
            )
    for document, value in owners:
        if document in documents and target(value) in papers:
            connection.execute(
                sa.text("UPDATE documents SET doi_owner_paper_id = :owner WHERE id = :id"),
                {"owner": target(value), "id": document},
            )
    connection.execute(
        sa.text(
            "DELETE FROM model_configurations WHERE left(key, :a) = :pending"
            " OR left(key, :b) = :redirect OR left(key, :c) = :owner"
        ),
        {
            "a": len(PENDING),
            "pending": PENDING,
            "b": len(REDIRECT),
            "redirect": REDIRECT,
            "c": len(DOI_OWNER),
            "owner": DOI_OWNER,
        },
    )


def downgrade():
    connection = op.get_bind()
    setting = sa.text(
        "INSERT INTO model_configurations (key, value) VALUES (:key, CAST(:value AS jsonb))"
        " ON CONFLICT (key) DO NOTHING"
    )
    for row in connection.execute(
        sa.text(
            "SELECT placeholder_paper_id, library_paper_id, document_id, matched_by, found_by"
            " FROM upload_matches"
        )
    ).all():
        value = {
            "paper_id": str(row.library_paper_id),
            "document_id": str(row.document_id),
            "matched_by": row.matched_by,
            "found_by": row.found_by,
        }
        connection.execute(
            setting, {"key": f"{PENDING}{row.placeholder_paper_id}", "value": json.dumps(value)}
        )
    for row in connection.execute(sa.text("SELECT old_paper_id, paper_id FROM paper_redirects")):
        connection.execute(
            setting,
            {
                "key": f"{REDIRECT}{row.old_paper_id}",
                "value": json.dumps({"paper_id": str(row.paper_id)}),
            },
        )
    for row in connection.execute(
        sa.text("SELECT id, doi_owner_paper_id FROM documents WHERE doi_owner_paper_id IS NOT NULL")
    ):
        connection.execute(
            setting,
            {
                "key": f"{DOI_OWNER}{row.id}",
                "value": json.dumps({"paper_id": str(row.doi_owner_paper_id)}),
            },
        )
    op.drop_index("ix_documents_doi_owner_paper_id", table_name="documents")
    op.drop_constraint("documents_doi_owner_paper_id_fkey", "documents", type_="foreignkey")
    op.drop_column("documents", "doi_owner_paper_id")
    op.drop_table("paper_redirects")
    op.drop_table("upload_matches")
