"""The OpenAlex key reaches every process that owns a downloader; no host policy remains."""

import json
import os
import subprocess
import unittest
from pathlib import Path


class FullTextComposeTests(unittest.TestCase):
    def test_browser_stack_uses_explicit_fixture_factory_and_pdf_mount(self):
        env = {
            **os.environ,
            "POSTGRES_PASSWORD": "fixture-only",
            "REDIS_PASSWORD": "fixture-only",
            "MINIO_ROOT_PASSWORD": "fixture-only",
        }
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.test.yaml",
                "-f",
                "compose.e2e.yaml",
                "config",
                "--format",
                "json",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        services = json.loads(result.stdout)["services"]
        for name in ("api", "worker"):
            self.assertIn("/fixtures/fulltext_runtime.py", services[name]["command"])
            self.assertIn("/fixtures", services[name]["environment"].get("PYTHONPATH", ""))
            # The browser stack downloads from the fixture's content endpoint (ARA-087).
            self.assertTrue(
                bool(services[name]["environment"].get("OPENALEX_API_KEY")),
                f"{name} has no OpenAlex key",
            )
        self.assertTrue(
            any(
                volume["target"] == "/fulltext-fixtures/research.pdf"
                for volume in services["external-fixtures"]["volumes"]
            )
        )

    def test_openalex_key_reaches_api_and_workers_without_a_host_policy(self):
        env = {
            **os.environ,
            "OPENALEX_API_KEY": "fixture-only-key",
            "POSTGRES_PASSWORD": "fixture-only",
            "REDIS_PASSWORD": "fixture-only",
            "MINIO_ROOT_PASSWORD": "fixture-only",
        }
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        services = json.loads(result.stdout)["services"]
        for name in ("api", "worker", "model-worker"):
            environment = services[name]["environment"]
            self.assertEqual(environment.get("OPENALEX_API_KEY"), "fixture-only-key")
            # Compare names only, so a failure never prints configured secrets.
            self.assertFalse(
                "FULLTEXT_ALLOWED_HOSTS" in environment, f"{name} still gets a host policy"
            )
