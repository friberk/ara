"""Readiness must require the Alembic head, or a migrated stack never becomes ready."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_given_the_migrations_then_readiness_expects_the_single_alembic_head():
    from app.services.health import SCHEMA_REVISION

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == [SCHEMA_REVISION]


async def test_given_a_freshly_migrated_database_then_readiness_reports_the_database_ok(resources):
    from app.services.health import readiness

    assert (await readiness(resources))["database"] == "ok"
