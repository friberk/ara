"""Retrieval must reuse the single Postgres and the single Ollama service (ARA-070)."""

import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


def compose_services(*files, **env):
    environment = {
        **os.environ,
        "POSTGRES_PASSWORD": "fixture-only-password",
        "REDIS_PASSWORD": "fixture-only-redis",
        "MINIO_ROOT_PASSWORD": "fixture-only-minio",
        **env,
    }
    arguments = [part for name in files for part in ("--file", name)]
    result = subprocess.run(
        ["docker", "compose", *arguments, "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["services"]


def images(services, *needles):
    return sorted(
        name
        for name, service in services.items()
        if any(needle in service.get("image", "") for needle in needles)
    )


class ComposeRetrievalTests(unittest.TestCase):
    def test_single_postgres_uses_pinned_pgvector_image(self):
        for files in (("compose.yaml",), ("compose.yaml", "compose.test.yaml")):
            services = compose_services(*files)
            self.assertEqual(images(services, "postgres", "pgvector"), ["postgres"], files)
            self.assertRegex(
                services["postgres"]["image"],
                r"^pgvector/pgvector:[\w.-]+@sha256:[0-9a-f]{64}$",
            )

    def test_single_ollama_with_configurable_residency(self):
        services = compose_services("compose.yaml", OLLAMA_MAX_LOADED_MODELS="3")
        self.assertEqual(images(services, "ollama"), ["ollama"])
        environment = services["ollama"]["environment"]
        self.assertEqual(environment["OLLAMA_MAX_LOADED_MODELS"], "3")


if __name__ == "__main__":
    unittest.main()
