#!/usr/bin/env python3
"""Run deterministic backend checks in a separate Compose project and data volumes."""

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "test", "down", "reset", "config"))
    parser.add_argument(
        "--reset-data", action="store_true", help="Delete test volumes only."
    )
    args = parser.parse_args()
    if args.action == "reset" and not args.reset_data:
        parser.error(
            "reset requires --reset-data; only ara-test volumes will be removed"
        )
    root = Path(__file__).resolve().parents[1]
    compose = [
        "docker",
        "compose",
        "--project-name",
        "ara-test",
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
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode:
            sys.exit(result.returncode)


if __name__ == "__main__":
    main()
