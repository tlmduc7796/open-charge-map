#!/usr/bin/env python3
"""Download an immutable ACN-Data session export for offline ML experiments.

The ACN API token is read only from an environment variable.  The resulting
raw JSON retains the source session fields and optional charging-rate series;
normalization belongs to ``prepare_acn_data.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "ml" / "data" / "external" / "acn" / "raw"
# The API returns no Caltech sessions for 2025; 2021 is the most recent
# confirmed non-empty year at the time this collector was added.
DEFAULT_OUTPUT = RAW_DIR / "acn_caltech_2021.json"
DEFAULT_START = "2021-01-01T00:00:00Z"
DEFAULT_END = "2022-01-01T00:00:00Z"


def parse_utc(value: str) -> datetime:
    """Parse a user-supplied ISO-8601 instant and require a timezone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--start and --end require an explicit timezone, for example ...Z")
    return parsed.astimezone(UTC)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def read_token(name: str) -> str:
    """Read a secret from the process environment or the ignored root .env file."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, candidate = line.split("=", maxsplit=1)
        if key.strip() == name:
            return candidate.strip().strip("\"'")
    return ""


def acquire(
    *,
    token: str,
    site: str,
    start: datetime,
    end: datetime,
    output: Path,
    timeseries: bool,
    force: bool,
) -> dict[str, object]:
    """Fetch one time-bounded ACN export and persist it with provenance."""
    if end <= start:
        raise ValueError("--end must be later than --start")
    if output.exists() and not force:
        raise FileExistsError(f"Raw export already exists: {output}; pass --force to replace it")
    try:
        from acnportal import acndata
    except ImportError as exc:
        raise RuntimeError("Install ml/requirements.txt before acquiring ACN-Data") from exc

    client = acndata.DataClient(token)
    records = list(
        client.get_sessions_by_time(
            site=site,
            start=start,
            end=end,
            timeseries=timeseries,
        )
    )
    payload = {
        "_meta": {
            "site": site,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeseries_requested": timeseries,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "source": "ACN-Data API",
        },
        "_items": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "dataset": "ACN-Data",
        "source": "ACN-Data API",
        "raw_export": output.name,
        "site": site,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timeseries_requested": timeseries,
        "records": len(records),
        "size_bytes": output.stat().st_size,
        "sha256": sha256(output),
        "acquired_at": datetime.now(UTC).isoformat(),
        "token_storage": "environment variable only; token is not stored in this manifest",
        "usage": "offline research/pipeline validation; not Vietnamese production ground truth",
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"output": str(output), "manifest": str(manifest_path), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=("caltech", "jpl"), default="caltech")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--token-env", default="ACNDATA_API_TOKEN")
    parser.add_argument(
        "--with-timeseries",
        action="store_true",
        help=(
            "Include charging-current/pilot-signal series. Download a small date batch: "
            "the ACN API returns these one session at a time."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing raw export")
    args = parser.parse_args()
    token = read_token(args.token_env)
    if not token:
        raise RuntimeError(
            f"Set {args.token_env} in the environment; do not put API tokens in code"
        )
    result = acquire(
        token=token,
        site=args.site,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        output=args.output,
        timeseries=args.with_timeseries,
        force=args.force,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
