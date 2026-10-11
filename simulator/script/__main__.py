"""Điểm vào dòng lệnh. Chạy từ thư mục `simulator/`:

    python -m script pull   # DB (chỉ đọc) -> data/catalog_snapshot.json (+ config nếu chưa có)
    python -m script run    # snapshot + config -> sinh lượt đến, phiên sạc, kiểm tra -> data/
    python -m script occupancy   # sessions.csv + ports.csv -> data/station_occupancy_5m.csv
    python -m script feed   # phát lại station_occupancy_5m.csv vào backend mỗi 5 phút
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from script.config import CONFIG_PATH, DATA_DIR, ROOT, ConfigError, new_user_config

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


def cmd_occupancy(args: argparse.Namespace) -> int:
    from script import occupancy

    data_dir = args.data_dir
    output = args.output or data_dir / "station_occupancy_5m.csv"
    result = occupancy.convert_files(
        sessions_path=args.sessions or data_dir / "sessions.csv",
        ports_path=args.ports or data_dir / "ports.csv",
        stations_sql=args.stations_sql,
        output_path=output,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(
        f"{result['rows']} dòng ({result['stations']} trạm, "
        f"{result['start'].isoformat()} -> {result['end'].isoformat()}), "
        f"occupied tối đa {result['occupied_max']} cổng -> {output}"
    )
    return 0


def cmd_feed(args: argparse.Namespace) -> int:
    from script import feed

    replay = feed.load_replay(
        args.csv or args.data_dir / "station_occupancy_5m.csv", args.stations_sql
    )
    url = feed.resolve_api_url(args.api_url)
    api_key = feed.resolve_api_key(args.api_key, ROOT.parent / ".env")
    if args.at is not None and args.at.tzinfo is None:
        raise ValueError("--at phải có múi giờ, ví dụ 2026-10-12T16:05:00+07:00")
    span = f"{replay.start.isoformat()} -> {replay.end.isoformat()}"
    if args.once or args.dry_run or args.at is not None:
        feed.feed_once(
            replay,
            at=args.at or datetime.now(UTC),
            url=url,
            api_key=api_key,
            dry_run=args.dry_run,
        )
        return 0
    print(f"Phát lại {len(replay.readings)} trạm ({span}) -> {url}; mỗi 5 phút, Ctrl+C để dừng.")
    try:
        feed.run_loop(replay, url=url, api_key=api_key, delay_s=args.delay_s)
    except KeyboardInterrupt:
        print("Đã dừng.")
    return 0


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
    occupancy = commands.add_parser(
        "occupancy", help="đổi sessions.csv thành occupancy 5 phút (bảng station_occupancy_5m)"
    )
    occupancy.add_argument("--sessions", type=Path, help="mặc định: <data-dir>/sessions.csv")
    occupancy.add_argument("--ports", type=Path, help="mặc định: <data-dir>/ports.csv")
    occupancy.add_argument(
        "--stations-sql",
        type=Path,
        default=ROOT.parent / "database" / "data" / "catalog" / "stations.sql",
        help="nguồn ánh xạ mã trạm -> UUID",
    )
    occupancy.add_argument(
        "--output", type=Path, help="mặc định: <data-dir>/station_occupancy_5m.csv"
    )
    occupancy.add_argument(
        "--start-date", type=date.fromisoformat, help="ngày đầu (trọn ngày); mặc định theo phiên"
    )
    occupancy.add_argument(
        "--end-date", type=date.fromisoformat, help="ngày cuối (trọn ngày); mặc định theo phiên"
    )
    occupancy.set_defaults(handler=cmd_occupancy)
    feed = commands.add_parser(
        "feed", help="phát lại station_occupancy_5m.csv vào backend, mỗi 5 phút một batch"
    )
    feed.add_argument("--csv", type=Path, help="mặc định: <data-dir>/station_occupancy_5m.csv")
    feed.add_argument(
        "--stations-sql",
        type=Path,
        default=ROOT.parent / "database" / "data" / "catalog" / "stations.sql",
        help="nguồn ánh xạ UUID -> mã trạm",
    )
    feed.add_argument(
        "--api-url", help="mặc định: FEED_API_URL hoặc http://127.0.0.1:8000"
    )
    feed.add_argument(
        "--api-key", help="mặc định: INTERNAL_API_KEY (môi trường hoặc .env gốc repo)"
    )
    feed.add_argument("--once", action="store_true", help="gửi đúng một batch rồi thoát")
    feed.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="giả lập thời điểm gửi (có múi giờ); ngụ ý --once",
    )
    feed.add_argument(
        "--dry-run", action="store_true", help="chỉ in batch sẽ gửi, không gọi backend"
    )
    feed.add_argument(
        "--delay-s",
        type=float,
        default=15.0,
        help="chờ bao nhiêu giây sau mỗi mốc 5 phút rồi mới gửi (mặc định 15)",
    )
    feed.set_defaults(handler=cmd_feed)
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
