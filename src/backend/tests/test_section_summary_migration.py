"""Migration 0011 adds section summaries and their vectors beside chunks (ARA-079, ARA-094)."""

import asyncio
import os
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

PAPER = "INSERT INTO papers (id, title, metadata_provenance) VALUES (:id, 'P', '{}')"
DOCUMENT = (
    "INSERT INTO documents (id, paper_id, status, object_key, sha256, original_filename, "
    "byte_size, request_id, warnings, chunk_set) "
    "VALUES (:id, :paper, 'ready', :key, :key, 'a.pdf', 1, :request, '[]', 'set')"
)
SECTION = (
    "INSERT INTO document_sections (id, document_id, chunk_set, ordinal, title, level, path, "
    "role, page, page_end) VALUES (:id, :document, 'set', 0, '2 Method', 1, "
    "'[\"2 Method\"]', 'body', 2, 4)"
)
SUMMARY = (
    "INSERT INTO section_summaries (id, document_id, section_id, chunk_set, title, page, "
    "page_end, ordinal, content, sources, context_text, token_count, model, reasoning_effort, "
    "usage) VALUES (:id, :document, :section, 'set', '2 Method', 2, 4, 3, :content, "
    "CAST(:sources AS jsonb), 'context', 12, 'gpt-5.6-luna', 'low', '{}')"
)


async def test_given_the_section_summary_migration_then_summaries_are_searchable_and_cascade(
    resources,
):
    name = f"ara079_migration_test_{uuid4().hex[:12]}"
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

    paper, document, section, summary, chunk = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    try:
        await alembic("upgrade", "0010_chat_papers")
        await alembic("upgrade", "head")
        async with engine.begin() as connection:
            await connection.execute(text(PAPER), {"id": paper})
            await connection.execute(
                text(DOCUMENT),
                {"id": document, "paper": paper, "key": str(document), "request": uuid4()},
            )
            await connection.execute(text(SECTION), {"id": section, "document": document})
            await connection.execute(
                text(SUMMARY),
                {
                    "id": summary,
                    "document": document,
                    "section": section,
                    "content": f"Terms use the Okapi weighting [source:{chunk}].",
                    "sources": f'["{chunk}"]',
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO section_summary_embeddings (summary_id, profile, document_id, "
                    "embedding, input_hash) VALUES (:summary, 'openai-3-small', :document, "
                    "'[0.1,0.2]'::halfvec, 'h')"
                ),
                {"summary": summary, "document": document},
            )
        async with engine.connect() as connection:
            # Keyword search reads the summary's words, never the hex of its source markers.
            found = await connection.scalar(
                text(
                    "SELECT count(*) FROM section_summaries WHERE search_vector @@ "
                    "websearch_to_tsquery('english', 'Okapi weighting')"
                )
            )
            marker = await connection.scalar(
                text(
                    "SELECT count(*) FROM section_summaries WHERE search_vector @@ "
                    "to_tsquery('english', :part)"
                ),
                {"part": chunk.hex[:8]},
            )
            assert (found, marker) == (1, 0)
        async with engine.begin() as connection:
            # Re-reading a PDF replaces its sections, and their summaries and vectors go too.
            await connection.execute(
                text("DELETE FROM document_sections WHERE id = :id"), {"id": section}
            )
            left = await connection.scalar(text("SELECT count(*) FROM section_summary_embeddings"))
            assert left == 0
        await alembic("downgrade", "0010_chat_papers")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            assert "section_summaries" not in tables
            assert "section_summary_embeddings" not in tables
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()
