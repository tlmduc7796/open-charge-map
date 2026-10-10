#!/usr/bin/env python3
"""Restore a verified backup into a new, empty PostgreSQL database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_platform.backup import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_ENV_FILE,
    restore_to_new_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--age-identity-file", type=Path)
    args = parser.parse_args()
    try:
        revision = restore_to_new_database(
            args.archive,
            args.target_database,
            env_file=args.env_file,
            compose_file=args.compose_file,
            age_identity_file=args.age_identity_file,
        )
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, OSError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"Restore PASS: database={args.target_database}, schema_revision={revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
