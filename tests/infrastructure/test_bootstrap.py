"""Bootstrap acceptance checks use temporary directories, never development secrets."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/bootstrap.py"


class BootstrapTests(unittest.TestCase):
    def run_bootstrap(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--env-file", str(path)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_given_missing_env_when_bootstrapped_then_private_random_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (
                Path(directory) / "first.env",
                Path(directory) / "second.env",
            )
            result = self.run_bootstrap(first)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.run_bootstrap(second).returncode, 0)
            values = dict(
                line.split("=", 1)
                for line in first.read_text().splitlines()
                if line and not line.startswith("#")
            )
            other = dict(
                line.split("=", 1)
                for line in second.read_text().splitlines()
                if line and not line.startswith("#")
            )
            for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "MINIO_ROOT_PASSWORD"):
                self.assertGreaterEqual(len(values[key]), 32)
                self.assertNotEqual(values[key], other[key])
                self.assertNotIn(values[key], result.stdout + result.stderr)
            if os.name == "posix":
                self.assertEqual(first.stat().st_mode & 0o777, 0o600)

    def test_given_existing_env_when_bootstrapped_then_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OPENAI_API_KEY=example-existing-value\n")
            result = self.run_bootstrap(path)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                path.read_text(), "OPENAI_API_KEY=example-existing-value\n"
            )
            self.assertNotIn("example-existing-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
