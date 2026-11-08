"""The coverage script must reproduce the HW2 measurement scope in an isolated project."""

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/measure-coverage.py"


def dry_run(*arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments, "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )


class MeasureCoverageTests(unittest.TestCase):
    def test_given_backend_when_dry_run_then_lint_precedes_the_instrumented_real_service_run(self):
        result = dry_run("backend", "--project-name", "ara-rag-a-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        lint = next(i for i, line in enumerate(lines) if "ruff check" in line)
        pytest = next(i for i, line in enumerate(lines) if "-m pytest" in line)
        self.assertLess(lint, pytest)
        self.assertIn("--project-name ara-rag-a-test", lines[lint])
        self.assertIn("ARA_INTEGRATION=1", lines[pytest])
        self.assertIn("--with coverage==7.17.1", lines[pytest])
        self.assertIn("--with greenlet==3.5.6", lines[pytest])
        self.assertEqual(sum("uv run --frozen pytest" in line for line in lines), 0)
        for step in ("coverage combine --keep", "coverage json", "coverage report"):
            self.assertTrue(any(step in line for line in lines), step)

    def test_given_committed_backend_config_then_it_traces_every_concurrency_model(self):
        config = (ROOT / "scripts/coverage/backend.coveragerc").read_text()
        self.assertIn("concurrency = multiprocessing,greenlet,thread", config)
        self.assertIn("patch = subprocess", config)
        self.assertIn("source = app", config)
        self.assertIn("branch = True", config)

    def test_given_frontend_when_dry_run_then_the_baseline_scope_is_measured(self):
        result = dry_run("frontend")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("npm ci --ignore-scripts", result.stdout)
        self.assertIn("@vitest/coverage-v8@5.0.3", result.stdout)
        for option in (
            "--coverage.include=src/**/*.{ts,tsx}",
            "--coverage.exclude=src/**/*.{test,spec}.{ts,tsx}",
            "--coverage.exclude=src/test/**",
            "--coverage.exclude=src/**/*.d.ts",
            "--coverage.exclude=src/api/generated.ts",
        ):
            self.assertIn(option, result.stdout)

    def test_given_the_development_project_when_requested_then_it_is_refused(self):
        result = dry_run("backend", "--project-name", "ara")
        self.assertEqual(result.returncode, 2)
        self.assertIn("project", result.stderr)


if __name__ == "__main__":
    unittest.main()
