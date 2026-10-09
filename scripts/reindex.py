#!/usr/bin/env python3
"""Queue re-ingestion of ready documents whose chunks predate the current chunk set.

Runs `python -m app.services.reindex` in the running api service; the API also does this at
startup. It only enqueues ingest jobs (idempotent while they are queued) and never resets data.
Papers with older chunks serve them until each job replaces them; papers from before migration
0006 have no chunks and cannot be asked about until their job finishes.
"""

import argparse
from pathlib import Path
import shlex
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-name", help="Compose project to target (default: the name in compose.yaml)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command without running it."
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    command = [
        "docker",
        "compose",
        *(["--project-name", args.project_name] if args.project_name else []),
        "--file",
        str(root / "compose.yaml"),
        "exec",
        "api",
        "python",
        "-m",
        "app.services.reindex",
    ]
    if args.dry_run:
        print(shlex.join(command))
        return
    sys.exit(subprocess.run(command, cwd=root, check=False).returncode)


if __name__ == "__main__":
    main()
