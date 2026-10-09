"""Alembic owns full-text schema; a new database protects all existing test data."""

import asyncio
import os
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def test_fulltext_migration_preserves_local_model_installation(resources):
    """Given the previous schema and a paused model, then upgrade preserves user intent."""
    name = f"ara019_migration_test_{uuid4().hex[:12]}"
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

    try:
        await migrate("0005_local_models")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO model_installations "
                    "(model_key,state,desired_state,weights_present,completed_bytes) "
                    "VALUES ('ifm-k2-horizon-7b','paused','paused',true,123)"
                )
            )
        await migrate("head")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            assert "fulltext_requests" in tables and "fulltext_attempts" in tables
            columns = await connection.run_sync(
                lambda conn: [item["name"] for item in inspect(conn).get_columns("documents")]
            )
            assert "acquisition" in columns
            retained = (
                await connection.execute(
                    text(
                        "SELECT state, desired_state, completed_bytes FROM model_installations "
                        "WHERE model_key='ifm-k2-horizon-7b'"
                    )
                )
            ).one()
            assert tuple(retained) == ("paused", "paused", 123)
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
