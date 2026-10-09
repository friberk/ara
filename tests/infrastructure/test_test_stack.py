"""The test helper must refuse destructive resets without an explicit opt-in."""

from pathlib import Path
import subprocess
import sys
import unittest


class TestStackTests(unittest.TestCase):
    def test_given_reset_without_flag_when_requested_then_no_docker_action(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        result = subprocess.run(
            [sys.executable, str(script), "reset"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--reset-data", result.stderr)

    def test_given_project_name_when_config_then_compose_uses_it(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        result = subprocess.run(
            [sys.executable, str(script), "config", "--project-name", "ara-rag-a-test", "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--project-name ara-rag-a-test", result.stdout)

    def test_given_default_project_when_dry_run_then_ara_test_is_used(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        result = subprocess.run(
            [sys.executable, str(script), "config", "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--project-name ara-test ", result.stdout)

    def test_given_unsafe_project_name_when_requested_then_refused(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        for name in ("ara", "ara-feature", "ara-rag", "Ara-Test"):
            result = subprocess.run(
                [sys.executable, str(script), "config", "--project-name", name, "--dry-run"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("project name", result.stderr)


if __name__ == "__main__":
    unittest.main()
