"""Migration 0008 drops the per-paper embedding override; papers follow the library model."""

import asyncio
import os
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def test_given_papers_with_overrides_when_upgrading_from_0007_then_column_is_dropped(
    resources,
):
    """Given 0007 data with a per-paper override, then upgrade keeps the paper and its index."""
    name = f"ara091_migration_test_{uuid4().hex[:12]}"
    admin = create_async_engine(
        resources.settings.database_url.get_secret_value(), isolation_level="AUTOCOMMIT"
    )
    url = make_url(resources.settings.database_url.get_secret_value()).set(database=name)
    engine = create_async_engine(url)
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))

    async def migrate(revision):
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
            "upgrade",
            revision,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()

    pinned, following = uuid4(), uuid4()
    try:
        await migrate("0007_feature_merge")
        async with engine.begin() as connection:
            for paper, profile in ((pinned, "qwen3-embed-4b"), (following, None)):
                await connection.execute(
                    text(
                        "INSERT INTO papers (id, title, retrieval_profile, metadata_provenance) "
                        "VALUES (:id, 'P', :p, '{}')"
                    ),
                    {"id": paper, "p": profile},
                )
            await connection.execute(
                text(
                    "INSERT INTO model_configurations (key, value) "
                    "VALUES ('retrieval', '{\"embedding_profile\": \"openai-3-small\"}')"
                )
            )
        await migrate("head")
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda conn: [item["name"] for item in inspect(conn).get_columns("papers")]
            )
            assert "retrieval_profile" not in columns
            rows = (await connection.execute(text("SELECT id FROM papers"))).scalars().all()
            assert sorted(map(str, rows)) == sorted(map(str, (pinned, following)))
            setting = await connection.scalar(
                text(
                    "SELECT value->>'embedding_profile' FROM model_configurations "
                    "WHERE key = 'retrieval'"
                )
            )
            assert setting == "openai-3-small"
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0009_upload_match_tables"
            )
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()
