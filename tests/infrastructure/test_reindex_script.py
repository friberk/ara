"""The reindex wrapper only queues jobs inside the running api service (ARA-071)."""

from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/reindex.py"


def dry_run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ReindexScriptTests(unittest.TestCase):
    def test_given_dry_run_then_it_execs_the_module_in_the_api_service(self):
        result = dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        root = SCRIPT.parents[1]
        self.assertEqual(
            result.stdout.strip(),
            f"docker compose --file {root / 'compose.yaml'} exec api "
            "python -m app.services.reindex",
        )

    def test_given_project_name_then_compose_targets_it(self):
        result = dry_run("--project-name", "ara-feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docker compose --project-name ara-feature --file ", result.stdout)


if __name__ == "__main__":
    unittest.main()
