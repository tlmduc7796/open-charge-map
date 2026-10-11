"""Điểm vào dòng lệnh. Chạy từ thư mục `simulator/`:

    python -m script pull   # DB (chỉ đọc) -> data/catalog_snapshot.json (+ config nếu chưa có)
    python -m script run    # snapshot + config -> sinh lượt đến, phiên sạc, kiểm tra -> data/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from script.config import CONFIG_PATH, DATA_DIR, ConfigError, new_user_config

SNAPSHOT_NAME = "catalog_snapshot.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_pull(args: argparse.Namespace) -> int:
    from script import db

    snapshot = db.pull_snapshot(db.find_database_url(args.database_url))
    path = args.data_dir / SNAPSHOT_NAME
    db.write_snapshot(snapshot, path)
    counts = snapshot["counts"]
    print(
        f"Snapshot: {counts['stations']} trạm, {counts['ports']} cổng, "
        f"{counts['vehicles']} xe -> {path}"
    )
    if not args.config.exists():
        text = json.dumps(new_user_config(snapshot), ensure_ascii=False, indent=2)
        args.config.write_text(text + "\n", encoding="utf-8")
        print(f"Đã tạo {args.config.name}, station_factor liệt kê sẵn các trạm; sửa để đổi.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from script import config as config_module
    from script import db, validate
    from script.arrivals import FIELDS as ARRIVAL_FIELDS
    from script.arrivals import generate_arrivals
    from script.sessions import (
        PORT_FIELDS,
        QUEUE_LOG_FIELDS,
        SESSION_FIELDS,
        simulate_sessions,
        write_csv,
    )

    snapshot_path = args.data_dir / SNAPSHOT_NAME
    snapshot = db.read_snapshot(snapshot_path)
    inputs = config_module.resolve(config_module.load_user_config(args.config), snapshot)

    arrivals = generate_arrivals(inputs.config, inputs.stations, inputs.vehicles)
    result = simulate_sessions(inputs.config, inputs.stations, inputs.vehicles, arrivals)

    data_dir = args.data_dir
    write_csv(arrivals, ARRIVAL_FIELDS, data_dir / "debug" / "arrivals.csv")
    write_csv(result["queue_log"], QUEUE_LOG_FIELDS, data_dir / "debug" / "queue_log.csv")
    write_csv(result["sessions"], SESSION_FIELDS, data_dir / "sessions.csv")
    write_csv(result["ports"], PORT_FIELDS, data_dir / "ports.csv")

    errors, report = validate.check_dir(data_dir, inputs.vehicles)
    (data_dir / "validation_report.md").write_text(report, encoding="utf-8")

    served = len(result["sessions"])
    manifest = {
        "seed": inputs.config["seed"],
        "window": [inputs.config["start_date"], inputs.config["end_date"]],
        "snapshot_sha256": sha256_file(snapshot_path),
        "config_sha256": hashlib.sha256(
            json.dumps(inputs.config, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "sessions_sha256": sha256_file(data_dir / "sessions.csv"),
        "counts": {
            "stations": len(inputs.stations),
            "ports": len(result["ports"]),
            "arrivals": len(arrivals),
            "sessions": served,
            "reneged": len(arrivals) - served,
        },
        "validation": "PASS" if not errors else "FAIL",
        "data_source": "synthetic",
        "is_synthetic": True,
    }
    (data_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"{len(arrivals)} lượt đến -> {served} phiên, {len(arrivals) - served} bỏ đi.")
    print(f"Kiểm tra bất biến: {manifest['validation']}. Đầu ra: {data_dir}")
    for message in errors[: validate.MAX_REPORTED_ERRORS]:
        print(f"  - {message}", file=sys.stderr)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m script", description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="file config của bạn")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="nơi lưu snapshot, đầu ra")
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("pull", help="kéo trạm, cổng, xe từ DB về snapshot (chỉ đọc)")
    pull.add_argument("--database-url", help="mặc định: DATABASE_URL hoặc .env ở gốc repo")
    pull.set_defaults(handler=cmd_pull)
    run = commands.add_parser("run", help="sinh lượt đến và phiên sạc từ snapshot + config")
    run.set_defaults(handler=cmd_run)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # console Windows mặc định không phải UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.handler(args)
    except (ConfigError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
