#!/usr/bin/env python3
"""Create, verify, and prune managed custom-format PostgreSQL backups."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data_platform.backup import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_COMPOSE_FILE,
    DEFAULT_ENV_FILE,
    create_backup,
    prune_backups,
    verify_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("create", help="dump and validate a backup")
    backup.add_argument("--database", default="smart_ev_data")
    backup.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    backup.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    backup.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    backup.add_argument("--age-recipient", required=True)
    backup.add_argument("--age-identity-file", type=Path, required=True)

    verify = commands.add_parser("verify", help="check manifest, checksum, and pg_restore listing")
    verify.add_argument("archive", type=Path)
    verify.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    verify.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    verify.add_argument("--age-identity-file", type=Path)

    prune = commands.add_parser("prune", help="remove only managed backups past retention")
    prune.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    prune.add_argument("--older-than-days", type=int, required=True)
    prune.add_argument("--keep-last", type=int, default=2)

    args = parser.parse_args()
    try:
        if args.command == "create":
            archive = create_backup(
                output_dir=args.output_dir,
                database=args.database,
                env_file=args.env_file,
                compose_file=args.compose_file,
                age_recipient=args.age_recipient,
                age_identity_file=args.age_identity_file,
            )
            print(f"Backup PASS: {archive}")
        elif args.command == "verify":
            record = verify_backup(
                args.archive,
                env_file=args.env_file,
                compose_file=args.compose_file,
                age_identity_file=args.age_identity_file,
            )
            print(json.dumps(record, ensure_ascii=False, indent=2))
            print("Backup verification PASS")
        else:
            removed = prune_backups(
                args.output_dir,
                older_than_days=args.older_than_days,
                keep_last=args.keep_last,
            )
            for archive in removed:
                print(f"Removed expired backup: {archive}")
            print(f"Retention PASS: removed {len(removed)} backup(s)")
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, OSError) as exc:
        print(f"Backup operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
