"""Migration 0009 moves ARA-086's prefixed settings rows into real tables (ARA-092)."""

import asyncio
import json
import os
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

PAPER = "INSERT INTO papers (id, title, metadata_provenance) VALUES (:id, 'P', '{}')"
DOCUMENT = (
    "INSERT INTO documents (id, paper_id, status, object_key, sha256, original_filename, "
    "byte_size, request_id, warnings) "
    "VALUES (:id, :paper, 'processing', :key, :key, 'a.pdf', 1, :request, '[]')"
)
SETTING = "INSERT INTO model_configurations (key, value) VALUES (:key, CAST(:value AS jsonb))"


async def test_given_prefixed_rows_when_upgrading_then_valid_rows_move_and_downgrade_restores(
    resources,
):
    """Valid rows move, orphans and malformed rows are dropped, and a downgrade restores them."""
    name = f"ara092_migration_test_{uuid4().hex[:12]}"
    admin = create_async_engine(
        resources.settings.database_url.get_secret_value(), isolation_level="AUTOCOMMIT"
    )
    url = make_url(resources.settings.database_url.get_secret_value()).set(database=name)
    engine = create_async_engine(url)
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))

    async def alembic(command, revision):
        env = {
            **os.environ,
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "APP_ENV": "test",
        }
        process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "--frozen",
            "alembic",
            command,
            revision,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()

    library, placeholder, orphan_library, orphan_doc, moved, gone = (uuid4() for _ in range(6))
    owner, target, orphan_owner = uuid4(), uuid4(), uuid4()
    held, held_orphan_library, held_orphan_doc, owned, owned_orphan = (uuid4() for _ in range(5))
    missing = uuid4()
    try:
        await alembic("upgrade", "0008_library_embeddings")
        async with engine.begin() as connection:
            for paper in (
                library,
                placeholder,
                orphan_library,
                orphan_doc,
                owner,
                target,
                orphan_owner,
            ):
                await connection.execute(text(PAPER), {"id": paper})
            for document, paper in (
                (held, placeholder),
                (held_orphan_library, orphan_library),
                (held_orphan_doc, orphan_doc),
                (owned, target),
                (owned_orphan, orphan_owner),
            ):
                await connection.execute(
                    text(DOCUMENT),
                    {"id": document, "paper": paper, "key": str(document), "request": uuid4()},
                )
            rows = {
                f"upload_match:{placeholder}": {
                    "paper_id": str(library),
                    "document_id": str(held),
                    "matched_by": "title",
                    "found_by": "lookup",
                },
                f"upload_match:{orphan_library}": {
                    "paper_id": str(missing),
                    "document_id": str(held_orphan_library),
                    "matched_by": "doi",
                    "found_by": "ingest",
                },
                f"upload_match:{orphan_doc}": {
                    "paper_id": str(library),
                    "document_id": str(missing),
                    "matched_by": "doi",
                    "found_by": "ingest",
                },
                "upload_match:not-a-uuid": {"paper_id": "x", "document_id": "y"},
                f"paper_redirect:{moved}": {"paper_id": str(library)},
                f"paper_redirect:{gone}": {"paper_id": str(missing)},
                f"pdf_doi_owner:{owned}": {"paper_id": str(owner)},
                f"pdf_doi_owner:{owned_orphan}": {"paper_id": str(missing)},
                f"pdf_doi_owner:{missing}": {"paper_id": str(owner)},
                "retrieval": {"embedding_profile": "openai-3-small"},
            }
            for key, value in rows.items():
                await connection.execute(text(SETTING), {"key": key, "value": json.dumps(value)})

        await alembic("upgrade", "head")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            assert {"upload_matches", "paper_redirects"} <= set(tables)
            matches = (
                await connection.execute(
                    text(
                        "SELECT placeholder_paper_id, library_paper_id, document_id, matched_by, "
                        "found_by FROM upload_matches"
                    )
                )
            ).all()
            assert [tuple(row) for row in matches] == [
                (placeholder, library, held, "title", "lookup")
            ]
            redirects = (
                await connection.execute(text("SELECT old_paper_id, paper_id FROM paper_redirects"))
            ).all()
            assert [tuple(row) for row in redirects] == [(moved, library)]
            owners = (
                await connection.execute(
                    text(
                        "SELECT id, doi_owner_paper_id FROM documents "
                        "WHERE doi_owner_paper_id IS NOT NULL"
                    )
                )
            ).all()
            assert [tuple(row) for row in owners] == [(owned, owner)]
            leftover = (
                (
                    await connection.execute(
                        text("SELECT key FROM model_configurations ORDER BY key")
                    )
                )
                .scalars()
                .all()
            )
            assert leftover == ["retrieval"]

        await alembic("downgrade", "0008_library_embeddings")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            assert "upload_matches" not in tables and "paper_redirects" not in tables
            columns = await connection.run_sync(
                lambda conn: [item["name"] for item in inspect(conn).get_columns("documents")]
            )
            assert "doi_owner_paper_id" not in columns
            restored = {
                key: value
                for key, value in (
                    await connection.execute(text("SELECT key, value FROM model_configurations"))
                ).all()
            }
            assert restored == {
                f"upload_match:{placeholder}": rows[f"upload_match:{placeholder}"],
                f"paper_redirect:{moved}": {"paper_id": str(library)},
                f"pdf_doi_owner:{owned}": {"paper_id": str(owner)},
                "retrieval": {"embedding_profile": "openai-3-small"},
            }
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0008_library_embeddings"
            )

        await alembic("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0009_upload_match_tables"
            )
            assert await connection.scalar(text("SELECT count(*) FROM upload_matches")) == 1
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()
