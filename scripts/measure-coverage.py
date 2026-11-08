#!/usr/bin/env python3
"""Measure backend and frontend coverage in an isolated project, with the HW2 source scope."""

import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evidence/generated/coverage"
CONFIG = ROOT / "scripts/coverage/backend.coveragerc"
FRONTEND = ROOT / "src/frontend"
RCFILE = "--rcfile=/coverage/backend-docker.coveragerc"
VITEST = [
    "npx", "--no-install", "vitest", "run", "--coverage", "--coverage.provider=v8",
    "--coverage.include=src/**/*.{ts,tsx}",
    "--coverage.exclude=src/**/*.{test,spec}.{ts,tsx}",
    "--coverage.exclude=src/test/**",
    "--coverage.exclude=src/**/*.d.ts",
    "--coverage.exclude=src/api/generated.ts",
    "--coverage.reportsDirectory=../../docs/evidence/generated/coverage/frontend",
    "--coverage.reporter=text", "--coverage.reporter=json-summary", "--coverage.reporter=html",
    "--coverage.reportOnFailure",
]


def percent(covered: int, total: int) -> str:
    return f"{covered:,}/{total:,} ({covered / total * 100:.2f}%)"


def setup_steps(project: str) -> list[str]:
    planned = subprocess.run(
        [sys.executable, str(ROOT / "scripts/test-stack.py"), "test", "--project-name", project, "--dry-run"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if planned.returncode:
        sys.stderr.write(planned.stderr)
        raise SystemExit(planned.returncode)
    return planned.stdout.splitlines()[:-1]


def coverage_command(project: str, *arguments: str) -> list[str]:
    return [
        "docker", "compose", "--project-name", project, "--file", "compose.yaml", "--file", "compose.test.yaml",
        "run", "--rm", "--no-deps", "-e", "ARA_INTEGRATION=1", "-v", f"{OUTPUT}:/coverage", "api",
        "uv", "run", "--frozen", "--with", "coverage==7.17.1", "--with", "greenlet==3.5.6",
        "python", "-m", "coverage", *arguments,
    ]


def backend(project: str, dry_run: bool) -> int:
    setup = setup_steps(project)
    tests = coverage_command(project, "run", RCFILE, "-m", "pytest", "-q")
    reports = [
        coverage_command(project, "combine", "--keep", RCFILE),
        coverage_command(project, "json", "-o", "/coverage/backend-full.json", RCFILE),
        coverage_command(project, "html", "-d", "/coverage/backend-html", RCFILE),
        coverage_command(project, "report", RCFILE),
    ]
    if dry_run:
        print("\n".join([*setup, *(shlex.join(step) for step in (tests, *reports))]))
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob(".coverage*"):
        stale.unlink()
    shutil.copyfile(CONFIG, OUTPUT / "backend-docker.coveragerc")
    for step in setup:
        subprocess.run(shlex.split(step), cwd=ROOT, check=True)
    result = subprocess.run(tests, cwd=ROOT, check=False)
    for step in reports:
        subprocess.run(step, cwd=ROOT, check=True)
    totals = json.loads((OUTPUT / "backend-full.json").read_text())["totals"]
    print(f"Backend lines {percent(totals['covered_lines'], totals['num_statements'])}")
    print(f"Backend branches {percent(totals['covered_branches'], totals['num_branches'])}")
    return result.returncode


def frontend(dry_run: bool) -> int:
    install = ["npm", "ci", "--ignore-scripts"]
    tool_packages = ["--ignore-scripts", "--save-exact", "@vitest/coverage-v8@5.0.3", "vitest@5.0.3"]
    if dry_run:
        print(shlex.join(install))
        print(shlex.join(["npm", "install", "--prefix", "<temporary tools directory>", *tool_packages]))
        print(shlex.join(VITEST))
        return 0
    subprocess.run(install, cwd=FRONTEND, check=True)
    with tempfile.TemporaryDirectory() as tools:
        subprocess.run(["npm", "install", "--prefix", tools, *tool_packages], cwd=FRONTEND, check=True)
        link = FRONTEND / "node_modules/@vitest/coverage-v8"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(Path(tools) / "node_modules/@vitest/coverage-v8")
        try:
            result = subprocess.run(VITEST, cwd=FRONTEND, check=False)
        finally:
            link.unlink()
    totals = json.loads((OUTPUT / "frontend/coverage-summary.json").read_text())["total"]
    for name, key in (("lines", "lines"), ("branches", "branches")):
        total = totals[key]
        print(f"Frontend {name} {total['covered']:,}/{total['total']:,} ({total['pct']:.2f}%)")
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", choices=("all", "backend", "frontend"), default="all")
    parser.add_argument("--project-name", default="ara-test", help="isolated Compose project for the backend")
    parser.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    args = parser.parse_args()
    code = backend(args.project_name, args.dry_run) if args.target != "frontend" else 0
    if args.target != "backend":
        code = frontend(args.dry_run) or code
    raise SystemExit(code)


if __name__ == "__main__":
    main()
