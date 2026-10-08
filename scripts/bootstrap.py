#!/usr/bin/env python3
"""Create private local Compose configuration without replacing existing settings."""

import argparse
import os
from pathlib import Path
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="Configuration destination (default: repository .env).",
    )
    args = parser.parse_args()
    template = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    replacements = {
        "replace-with-random-postgres-password": secrets.token_hex(24),
        "replace-with-random-redis-password": secrets.token_hex(24),
        "replace-with-random-minio-password": secrets.token_hex(24),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    try:
        descriptor = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing configuration preserved; no values were changed.")
        return
    with os.fdopen(descriptor, "w") as destination:
        destination.write(template)
    print("Created private local configuration with generated internal passwords.")
    print("Start the application with: docker compose up --build")


if __name__ == "__main__":
    main()
