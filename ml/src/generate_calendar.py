"""
Generate Vietnam calendar/event feature dataset.

Creates a temporal feature table with:
- Vietnamese public holidays (Tết, 30/4, 2/9, etc.)
- Extended holiday periods (Tết holiday week)
- Season markers (rainy/dry for South VN, cold/hot for North)
- Tourism season flags
- School semester periods
- Payday cycle (~25th of month)
- Rush hour flags
- Weekend/workday classification

Output: ml/data/derived/calendar/calendar_features_<region>.parquet

Note: While UrbanEV data is from Germany, we generate BOTH German and
Vietnamese calendars. German calendar aligns with UrbanEV for training.
Vietnamese calendar is prepared for future deployment on VN stations.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# German Public Holidays (for UrbanEV alignment)
# NRW (Nordrhein-Westfalen) where Paderborn is located
# ──────────────────────────────────────────────────────────
GERMAN_HOLIDAYS_NRW = {
    # 2022
    "2022-10-03": "Tag der Deutschen Einheit",
    "2022-11-01": "Allerheiligen",
    "2022-12-25": "1. Weihnachtstag",
    "2022-12-26": "2. Weihnachtstag",
    # 2023
    "2023-01-01": "Neujahr",
    "2023-02-20": "Rosenmontag (regional)",
}

# Extended holiday periods in Germany
GERMAN_HOLIDAY_PERIODS = [
    ("2022-12-23", "2023-01-02", "Weihnachtsferien"),  # Christmas break
    ("2022-10-04", "2022-10-15", "Herbstferien NRW"),    # Autumn break
]

# ──────────────────────────────────────────────────────────
# Vietnamese Public Holidays
# ──────────────────────────────────────────────────────────
VN_HOLIDAYS = {
    # Yearly fixed dates (representative year)
    "01-01": ("Tết Dương lịch", "new_year"),
    "04-30": ("Ngày Giải phóng", "liberation_day"),
    "05-01": ("Quốc tế Lao động", "labor_day"),
    "09-02": ("Quốc khánh", "national_day"),
    "09-03": ("Quốc khánh (nghỉ bù)", "national_day_ext"),
    # Lunar-based (approximate for 2023, 2024, 2025, 2026)
    # Tết Nguyên Đán 2023: Jan 22
    # Tết Nguyên Đán 2024: Feb 10
    # Tết Nguyên Đán 2025: Jan 29
    # Tết Nguyên Đán 2026: Feb 17
    # Giỗ Tổ Hùng Vương 2023: Apr 29 (10/3 Âm lịch)
}

# Tết Nguyên Đán extended periods (biggest travel event of the year)
TET_PERIODS = {
    2023: ("2023-01-20", "2023-01-29"),  # Tết Quý Mão
    2024: ("2024-02-08", "2024-02-14"),  # Tết Giáp Thìn
    2025: ("2025-01-27", "2025-02-02"),  # Tết Ất Tỵ
    2026: ("2026-02-15", "2026-02-22"),  # Tết Bính Ngọ
}

# Vietnam seasonal patterns
VN_SEASONS = {
    # South Vietnam (HCM, Mekong Delta)
    "south": {
        "rainy": list(range(5, 12)),   # May-November
        "dry": [12, 1, 2, 3, 4],       # December-April
    },
    # North Vietnam (Hanoi)
    "north": {
        "cold": [11, 12, 1, 2, 3],     # November-March
        "hot": [4, 5, 6, 7, 8, 9, 10], # April-October
    },
}

# Tourism seasons
VN_TOURISM_HIGH = [1, 2, 6, 7, 8, 12]  # Tết, summer, Christmas

# German seasons (for UrbanEV)
GERMAN_SEASONS = {
    "winter": [12, 1, 2],
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "autumn": [9, 10, 11],
}


def generate_temporal_features(
    start_date: str,
    end_date: str,
    freq: str = "5min",
    region: str = "germany",
) -> pd.DataFrame:
    """Generate a complete temporal feature table."""
    timestamps = pd.date_range(start=start_date, end=end_date, freq=freq)
    df = pd.DataFrame({"timestamp": timestamps})

    # ── Basic temporal ──────────────────────────────────
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["day_of_week"] = df["timestamp"].dt.dayofweek  # 0=Mon, 6=Sun
    df["day_of_month"] = df["timestamp"].dt.day
    df["month"] = df["timestamp"].dt.month
    df["week_of_year"] = df["timestamp"].dt.isocalendar().week.astype(int)

    # ── Cyclical encoding ───────────────────────────────
    # Hour sin/cos (24-hour cycle)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

    # Day-of-week sin/cos (7-day cycle)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    # Month sin/cos (12-month cycle)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    # Minute-of-day (for finer granularity)
    df["minute_of_day"] = df["hour"] * 60 + df["minute"]
    df["mod_sin"] = np.sin(2 * np.pi * df["minute_of_day"] / 1440)
    df["mod_cos"] = np.cos(2 * np.pi * df["minute_of_day"] / 1440)

    # ── Weekend / Workday ───────────────────────────────
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    # ── Rush hour flags ─────────────────────────────────
    df["is_morning_rush"] = (
        (df["hour"] >= 7) & (df["hour"] <= 9) & (df["is_weekend"] == 0)
    ).astype(int)
    df["is_evening_rush"] = (
        (df["hour"] >= 17) & (df["hour"] <= 19) & (df["is_weekend"] == 0)
    ).astype(int)
    df["is_rush_hour"] = (df["is_morning_rush"] | df["is_evening_rush"]).astype(int)

    # ── Time-of-day bucket ──────────────────────────────
    # 0=night(0-5), 1=morning(6-11), 2=afternoon(12-17), 3=evening(18-23)
    df["time_bucket"] = pd.cut(
        df["hour"],
        bins=[-1, 5, 11, 17, 23],
        labels=[0, 1, 2, 3],
    ).astype(int)

    # ── Payday proxy ────────────────────────────────────
    # Most companies pay on 25th-28th
    df["is_near_payday"] = (
        (df["day_of_month"] >= 25) | (df["day_of_month"] <= 3)
    ).astype(int)

    # ── Holidays ────────────────────────────────────────
    date_str = df["timestamp"].dt.strftime("%Y-%m-%d")

    if region == "germany":
        df["is_public_holiday"] = date_str.isin(GERMAN_HOLIDAYS_NRW).astype(int)

        # Extended holiday periods
        df["is_holiday_period"] = 0
        for start, end, name in GERMAN_HOLIDAY_PERIODS:
            mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
            df.loc[mask, "is_holiday_period"] = 1

        # Season
        df["season"] = df["month"].map(
            {m: s for s, months in GERMAN_SEASONS.items() for m in months}
        )
        season_map = {"winter": 0, "spring": 1, "summer": 2, "autumn": 3}
        df["season_code"] = df["season"].map(season_map)

    elif region == "vietnam":
        # Fixed holidays
        mmdd = df["timestamp"].dt.strftime("%m-%d")
        df["is_public_holiday"] = mmdd.isin(VN_HOLIDAYS).astype(int)

        # Tết period
        df["is_tet_period"] = 0
        for year, (start, end) in TET_PERIODS.items():
            mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
            df.loc[mask, "is_tet_period"] = 1
            df.loc[mask, "is_public_holiday"] = 1

        df["is_holiday_period"] = (
            (df["is_public_holiday"] == 1) | (df["is_tet_period"] == 1)
        ).astype(int)

        # Rainy season (South VN)
        df["is_rainy_season_south"] = df["month"].isin(
            VN_SEASONS["south"]["rainy"]
        ).astype(int)

        # Tourism season
        df["is_tourism_high"] = df["month"].isin(VN_TOURISM_HIGH).astype(int)

        # Season code (South VN: 0=dry, 1=rainy)
        df["season"] = df["is_rainy_season_south"].map({0: "dry", 1: "rainy"})
        df["season_code"] = df["is_rainy_season_south"]

    # ── Composite flags ─────────────────────────────────
    # "Non-working" time = weekend OR holiday
    df["is_non_working"] = (
        (df["is_weekend"] == 1) | (df["is_public_holiday"] == 1)
    ).astype(int)

    return df


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate calendar feature dataset")
    parser.add_argument(
        "--start", default="2022-09-01",
        help="Start date (default: matching UrbanEV)",
    )
    parser.add_argument(
        "--end", default="2023-02-28",
        help="End date (default: matching UrbanEV)",
    )
    parser.add_argument(
        "--region", default="germany", choices=["germany", "vietnam"],
        help="Calendar region (default: germany for UrbanEV alignment)",
    )
    parser.add_argument(
        "--output-dir", default="ml/data/derived/calendar",
        help="Output directory",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # Generate for specified region
    df = generate_temporal_features(
        start_date=args.start,
        end_date=args.end,
        freq="5min",
        region=args.region,
    )

    elapsed = time.time() - t0

    # Save
    region_tag = args.region
    parquet_path = out_dir / f"calendar_features_{region_tag}.parquet"
    df.to_parquet(parquet_path, index=False)

    csv_sample_path = out_dir / f"calendar_features_{region_tag}_sample.csv"
    df.head(500).to_csv(csv_sample_path, index=False)

    # Metadata
    meta = {
        "version": "1.0.0",
        "created_at": datetime.utcnow().isoformat() + "+00:00",
        "elapsed_seconds": round(elapsed, 2),
        "region": region_tag,
        "time_range": {"start": args.start, "end": args.end},
        "resolution": "5 minutes",
        "total_records": len(df),
        "columns": list(df.columns),
        "holiday_count": int(df["is_public_holiday"].sum()),
        "holiday_period_days": int(
            df.loc[df["is_holiday_period"] == 1, "timestamp"]
            .dt.date.nunique()
        ),
        "weekend_ratio": round(float(df["is_weekend"].mean()), 4),
        "parquet_file": parquet_path.name,
        "parquet_size_bytes": parquet_path.stat().st_size,
    }

    meta_path = out_dir / f"calendar_meta_{region_tag}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("Calendar features generation COMPLETE (%s)", region_tag)
    logger.info("  Records: %d", len(df))
    logger.info("  Columns: %d", len(df.columns))
    logger.info("  Holidays: %d timestamps", meta["holiday_count"])
    logger.info("  Holiday periods: %d days", meta["holiday_period_days"])
    logger.info("  Parquet: %s (%.2f MB)", parquet_path, parquet_path.stat().st_size / 1e6)
    logger.info("  Elapsed: %.2fs", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
