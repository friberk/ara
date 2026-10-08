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


if __name__ == "__main__":
    unittest.main()
