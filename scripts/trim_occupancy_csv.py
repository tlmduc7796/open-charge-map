#!/usr/bin/env python3
"""Cắt station_occupancy_5m.csv của simulator xuống vài tháng (mặc định: tháng 9 và 10/2026).

File simulator phủ cả năm (~960 nghìn dòng, ~67 MB). Database nạp NGUYÊN file đầu ra này
(database/docker/sql/load_history.sql) làm dữ liệu demo, nên chỉ giữ tháng cần xem và đủ nhỏ để
commit vào git.

Tháng được tính theo múi giờ của chính cột `bucket_at` quy về giờ VN (UTC+7), cùng quy ước với
database/docker/sql/load_history.sql. Dòng được chép nguyên văn theo thứ tự gốc.

    python scripts/trim_occupancy_csv.py
    python scripts/trim_occupancy_csv.py --months 9 10 --year 2026 --output out.csv

Chỉ dùng thư viện chuẩn.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "simulator" / "data" / "station_occupancy_5m.csv"
DEFAULT_OUTPUT = ROOT / "database" / "fixtures" / "simulator" / "station_occupancy_5m.csv"
VN_TZ = timezone(timedelta(hours=7))


def trim(source: Path, target: Path, year: int, months: set[int]) -> dict:
    """Ghi các dòng thuộc (year, months) vào `target`; trả về thống kê."""
    tmp = target.with_name(target.name + ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    rows_in = rows_out = 0
    per_month: Counter[str] = Counter()
    stations: set[str] = set()
    first = last = None

    try:
        with (
            source.open("r", encoding="utf-8", newline="") as reader,
            tmp.open("w", encoding="utf-8", newline="") as writer,
        ):
            header = reader.readline()
            columns = header.rstrip("\r\n").split(",")
            for name in ("station_id", "bucket_at"):
                if name not in columns:
                    raise ValueError(f"{source} thiếu cột `{name}` (header: {columns})")
            id_idx, at_idx = columns.index("station_id"), columns.index("bucket_at")
            writer.write(header)

            for line in reader:
                if not line.strip():
                    continue
                rows_in += 1
                fields = line.rstrip("\r\n").split(",")
                if len(fields) != len(columns):
                    raise ValueError(
                        f"{source}:{rows_in + 1}: {len(fields)} cột, cần {len(columns)}"
                    )
                bucket = datetime.fromisoformat(fields[at_idx])
                if bucket.tzinfo is None:
                    raise ValueError(f"{source}:{rows_in + 1}: bucket_at không có múi giờ")
                local = bucket.astimezone(VN_TZ)
                if local.year != year or local.month not in months:
                    continue
                writer.write(line)
                rows_out += 1
                per_month[f"{local.year}-{local.month:02d}"] += 1
                stations.add(fields[id_idx])
                first = local if first is None or local < first else first
                last = local if last is None or local > last else last

        if rows_out == 0:
            raise ValueError(
                f"Không có dòng nào thuộc năm {year}, tháng {sorted(months)} trong {source}"
            )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "per_month": dict(sorted(per_month.items())),
        "stations": len(stations),
        "first": first,
        "last": last,
        "bytes": target.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    # Console Windows mặc định cp1252 không in được tiếng Việt.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT, help=f"mặc định: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help=f"mặc định: {DEFAULT_OUTPUT}"
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--months", type=int, nargs="+", default=[9, 10], metavar="M", help="mặc định: 9 10"
    )
    args = parser.parse_args(argv)

    if bad := [m for m in args.months if not 1 <= m <= 12]:
        parser.error(f"tháng không hợp lệ: {bad}")
    if not args.input.is_file():
        parser.error(f"không thấy file nguồn: {args.input}")
    if args.output.resolve() == args.input.resolve():
        parser.error("--output không được trùng --input")

    try:
        stats = trim(args.input, args.output, args.year, set(args.months))
    except ValueError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"Nguồn : {args.input}  ({stats['rows_in']:,} dòng)")
    print(f"Đích  : {args.output}  ({stats['rows_out']:,} dòng, {stats['bytes'] / 1e6:.1f} MB)")
    print(f"Tháng : {', '.join(f'{k}: {v:,}' for k, v in stats['per_month'].items())}")
    print(f"Trạm  : {stats['stations']}")
    print(f"Phủ   : {stats['first'].isoformat()} -> {stats['last'].isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
