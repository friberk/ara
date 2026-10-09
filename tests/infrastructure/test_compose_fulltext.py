"""The operator's PDF-host policy reaches every process that owns a downloader."""

import json
import os
import subprocess
import unittest
from pathlib import Path


class FullTextComposeTests(unittest.TestCase):
    def test_host_policy_reaches_api_and_workers(self):
        policy = '["arxiv.org","aclanthology.org"]'
        env = {**os.environ, "FULLTEXT_ALLOWED_HOSTS": policy, "POSTGRES_PASSWORD": "fixture-only", "REDIS_PASSWORD": "fixture-only", "MINIO_ROOT_PASSWORD": "fixture-only"}
        result = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, check=True)
        services = json.loads(result.stdout)["services"]
        for name in ("api", "worker", "model-worker"):
            self.assertEqual(services[name]["environment"].get("FULLTEXT_ALLOWED_HOSTS"), policy)
