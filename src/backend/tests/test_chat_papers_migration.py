"""Migration 0010 moves each chat's paper and PDF into `chat_papers` (ARA-088)."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

PAPER = "INSERT INTO papers (id, title, metadata_provenance) VALUES (:id, 'P', '{}')"
DOCUMENT = (
    "INSERT INTO documents (id, paper_id, status, object_key, sha256, original_filename, "
    "byte_size, request_id, warnings) "
    "VALUES (:id, :paper, 'ready', :key, :key, 'a.pdf', 1, :request, '[]')"
)
CHAT = (
    "INSERT INTO chat_sessions (id, paper_id, document_id, title, title_source, created_at) "
    "VALUES (:id, :paper, :document, 'Chat', 'manual', :created)"
)
MESSAGE = (
    "INSERT INTO chat_messages (id, session_id, role, content, state, citations, configuration, "
    "usage, retrieval, context) VALUES (:id, :chat, :role, :content, 'completed', "
    "CAST(:citations AS jsonb), '{}', '{}', '{}', '{}')"
)


async def test_given_single_paper_chats_when_upgrading_then_each_becomes_a_one_paper_chat(
    resources,
):
    """Backfill keeps each chat's paper, PDF and history; a downgrade restores the columns."""
    name = f"ara088_migration_test_{uuid4().hex[:12]}"
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

    first, second = uuid4(), uuid4()
    earlier, current, other = uuid4(), uuid4(), uuid4()
    old_chat, new_chat, other_chat = uuid4(), uuid4(), uuid4()
    created = datetime(2026, 10, 1, 12, tzinfo=UTC)
    citation = f'[{{"chunk_id": "{uuid4()}", "document_id": "{earlier}", "page": 2}}]'
    try:
        await alembic("upgrade", "0009_upload_match_tables")
        async with engine.begin() as connection:
            for paper in (first, second):
                await connection.execute(text(PAPER), {"id": paper})
            for document, paper in ((earlier, first), (current, first), (other, second)):
                await connection.execute(
                    text(DOCUMENT),
                    {"id": document, "paper": paper, "key": str(document), "request": uuid4()},
                )
            # A chat on an earlier PDF keeps that PDF; the paper's newer one is not pinned.
            for chat, paper, document in (
                (old_chat, first, earlier),
                (new_chat, first, current),
                (other_chat, second, other),
            ):
                await connection.execute(
                    text(CHAT),
                    {"id": chat, "paper": paper, "document": document, "created": created},
                )
            for role, content, cited in (
                ("user", "What was measured?", "[]"),
                ("assistant", "Recall [source:x].", citation),
            ):
                await connection.execute(
                    text(MESSAGE),
                    {
                        "id": uuid4(),
                        "chat": old_chat,
                        "role": role,
                        "content": content,
                        "citations": cited,
                    },
                )
            history = (
                await connection.execute(
                    text("SELECT id, role, content, citations FROM chat_messages ORDER BY role")
                )
            ).all()

        await alembic("upgrade", "head")
        async with engine.connect() as connection:
            links = (
                await connection.execute(
                    text(
                        "SELECT chat_id, paper_id, document_id, ordinal, added_at "
                        "FROM chat_papers ORDER BY paper_id, document_id"
                    )
                )
            ).all()
            assert sorted(tuple(row) for row in links) == sorted(
                [
                    (old_chat, first, earlier, 0, created),
                    (new_chat, first, current, 0, created),
                    (other_chat, second, other, 0, created),
                ]
            )
            columns = await connection.run_sync(
                lambda conn: [item["name"] for item in inspect(conn).get_columns("chat_sessions")]
            )
            assert "paper_id" not in columns and "document_id" not in columns
            unchanged = (
                await connection.execute(
                    text("SELECT id, role, content, citations FROM chat_messages ORDER BY role")
                )
            ).all()
            assert unchanged == history

        # A second paper joins one chat; the downgrade keeps the first paper by ordinal.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO chat_papers (chat_id, paper_id, document_id, ordinal) "
                    "VALUES (:chat, :paper, :document, 1)"
                ),
                {"chat": new_chat, "paper": second, "document": other},
            )
        await alembic("downgrade", "0009_upload_match_tables")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            assert "chat_papers" not in tables
            restored = (
                await connection.execute(
                    text("SELECT id, paper_id, document_id FROM chat_sessions")
                )
            ).all()
            assert sorted(tuple(row) for row in restored) == sorted(
                [
                    (old_chat, first, earlier),
                    (new_chat, first, current),
                    (other_chat, second, other),
                ]
            )

        await alembic("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM chat_papers")) == 3
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()
