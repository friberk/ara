#!/usr/bin/env python3
"""Run deterministic backend checks in a separate Compose project and data volumes."""

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys

# Only test projects may be targeted; development projects (ara, ara-feature, ...) never match.
PROJECT_NAME = re.compile(r"ara-test|ara-[a-z0-9]+(?:-[a-z0-9]+)*-test")
# Experimental open models run only under this Compose profile (ARA-090).
OPEN_MODEL_SERVICES = {"ollama", "model-worker"}


def check_open_model_profile(compose: list[str]) -> None:
    """The default stack leaves the open-model services out; the profile brings them back."""
    for profile, expected in (([], set()), (["--profile", "open-models"], OPEN_MODEL_SERVICES)):
        listed = subprocess.run(
            [*compose, *profile, "config", "--services"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        found = OPEN_MODEL_SERVICES & set(listed)
        if found != expected:
            sys.exit(f"open-models profile {profile or 'off'}: expected {expected}, got {found}")
    print("open-models profile: off by default, on with --profile open-models")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "test", "down", "reset", "config"))
    parser.add_argument(
        "--reset-data", action="store_true", help="Delete test volumes only."
    )
    parser.add_argument(
        "--project-name",
        default="ara-test",
        help="Isolated Compose project: ara-test or ara-<name>-test.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the commands without running them."
    )
    args = parser.parse_args()
    if not PROJECT_NAME.fullmatch(args.project_name):
        parser.error("project name must be ara-test or ara-<name>-test")
    if args.action == "reset" and not args.reset_data:
        parser.error(
            f"reset requires --reset-data; only {args.project_name} volumes will be removed"
        )
    root = Path(__file__).resolve().parents[1]
    compose = [
        "docker",
        "compose",
        "--project-name",
        args.project_name,
        "--file",
        str(root / "compose.yaml"),
        "--file",
        str(root / "compose.test.yaml"),
    ]
    if args.action == "config":
        commands = [[*compose, "config", "--quiet"]]
    elif args.action in ("down", "reset"):
        commands = [
            [*compose, "down", *(["--volumes"] if args.action == "reset" else [])]
        ]
    elif args.action == "up":
        commands = [[*compose, "up", "--detach", "--build", "--wait", "api", "worker"]]
    else:
        # Keep dispatchers and workers stopped while repository tests own job state.
        commands = [
            [*compose, "stop", "api", "worker"],
            [*compose, "build", "api"],
            [
                *compose,
                "up",
                "--detach",
                "--build",
                "--wait",
                "postgres",
                "redis",
                "minio",
            ],
            [*compose, "run", "--rm", "--no-deps", "migrate"],
            [*compose, "run", "--rm", "--no-deps", "storage-init"],
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "api",
                "uv",
                "run",
                "--frozen",
                "ruff",
                "check",
                ".",
            ],
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "-e",
                "ARA_INTEGRATION=1",
                "api",
                "uv",
                "run",
                "--frozen",
                "pytest",
            ],
        ]
    for command in commands:
        if args.dry_run:
            print(shlex.join(command))
            continue
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode:
            sys.exit(result.returncode)
    if args.action == "config" and not args.dry_run:
        check_open_model_profile(compose)


if __name__ == "__main__":
    main()
