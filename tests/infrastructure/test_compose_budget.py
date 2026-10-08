"""Configuration should deliver the operator's cost cap to both generation processes."""

import json
import os
from pathlib import Path
import subprocess
import unittest


class ComposeBudgetTests(unittest.TestCase):
    def test_custom_daily_budget_reaches_api_and_worker(self):
        environment = {**os.environ, "LLM_DAILY_BUDGET_USD": "0.50"}
        environment.update(
            POSTGRES_PASSWORD="fixture-only-password",
            REDIS_PASSWORD="fixture-only-redis",
            MINIO_ROOT_PASSWORD="fixture-only-minio",
        )
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        configuration = json.loads(result.stdout)
        # Never emit the full resolved configuration; it contains internal credentials.
        for service in ("api", "worker"):
            self.assertEqual(
                configuration["services"][service]["environment"].get(
                    "LLM_DAILY_BUDGET_USD"
                ),
                "0.50",
            )
