"""
Collect historical weather data from Open-Meteo API.

Aligns weather data with UrbanEV time range (2022-09-01 to 2023-02-28).
UrbanEV dataset is from Paderborn, Germany area — we use representative
coordinates for weather retrieval.

Output: ml/artifacts/weather_historical.parquet
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger(__name__)

# UrbanEV dataset location: Paderborn, Germany region
# Using representative coordinate for the study area
DEFAULT_LATITUDE = 51.7189
DEFAULT_LONGITUDE = 8.7575

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

# Hourly variables to retrieve
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "pressure_msl",
    "is_day",
]


def fetch_weather_data(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    timezone: str = "Europe/Berlin",
) -> pd.DataFrame:
    """Fetch hourly weather data from Open-Meteo Archive API."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": timezone,
    }

    logger.info(
        "Fetching weather: lat=%.4f lon=%.4f, %s → %s",
        latitude, longitude, start_date, end_date,
    )

    resp = requests.get(OPEN_METEO_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if "hourly" not in data:
        raise ValueError(f"No hourly data in response: {list(data.keys())}")

    hourly = data["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"])
    df = df.rename(columns={"time": "timestamp"})

    logger.info("Fetched %d hourly records", len(df))
    return df


def resample_to_5min(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample hourly weather to 5-minute intervals using interpolation.
    
    For continuous variables (temperature, humidity, etc.): linear interpolation.
    For categorical (weather_code, is_day): forward-fill.
    """
    df = df.set_index("timestamp").sort_index()

    # Create 5-minute index
    idx_5min = pd.date_range(
        start=df.index.min(),
        end=df.index.max(),
        freq="5min",
    )

    # Reindex and interpolate
    df_5min = df.reindex(idx_5min)

    # Continuous variables: linear interpolation
    continuous_cols = [
        "temperature_2m", "relative_humidity_2m", "precipitation", "rain",
        "snowfall", "cloud_cover", "wind_speed_10m", "wind_gusts_10m",
        "pressure_msl",
    ]
    for col in continuous_cols:
        if col in df_5min.columns:
            df_5min[col] = df_5min[col].interpolate(method="linear")

    # Categorical variables: forward-fill
    categorical_cols = ["weather_code", "is_day"]
    for col in categorical_cols:
        if col in df_5min.columns:
            df_5min[col] = df_5min[col].ffill()

    df_5min = df_5min.reset_index().rename(columns={"index": "timestamp"})

    logger.info("Resampled to %d records at 5-min resolution", len(df_5min))
    return df_5min


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived weather features useful for ML."""
    # Is it raining? (binary)
    if "precipitation" in df.columns:
        df["is_raining"] = (df["precipitation"] > 0.1).astype(int)

    # Rain intensity bucket
    if "precipitation" in df.columns:
        df["rain_intensity"] = pd.cut(
            df["precipitation"],
            bins=[-np.inf, 0.0, 0.5, 2.0, 10.0, np.inf],
            labels=[0, 1, 2, 3, 4],  # none, light, moderate, heavy, extreme
        ).astype(float)

    # Temperature comfort bucket
    if "temperature_2m" in df.columns:
        df["temp_bucket"] = pd.cut(
            df["temperature_2m"],
            bins=[-np.inf, 0, 10, 20, 30, np.inf],
            labels=[0, 1, 2, 3, 4],  # freezing, cold, mild, warm, hot
        ).astype(float)

    # Wind chill (simplified) — affects EV battery performance
    if "temperature_2m" in df.columns and "wind_speed_10m" in df.columns:
        df["feels_like"] = df["temperature_2m"] - 0.4 * df["wind_speed_10m"]

    return df


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect historical weather data")
    parser.add_argument(
        "--lat", type=float, default=DEFAULT_LATITUDE,
        help="Latitude (default: Paderborn area)",
    )
    parser.add_argument(
        "--lon", type=float, default=DEFAULT_LONGITUDE,
        help="Longitude (default: Paderborn area)",
    )
    parser.add_argument(
        "--start", default="2022-09-01",
        help="Start date (default: 2022-09-01, matching UrbanEV)",
    )
    parser.add_argument(
        "--end", default="2023-02-28",
        help="End date (default: 2023-02-28, matching UrbanEV)",
    )
    parser.add_argument(
        "--output-dir", default="ml/artifacts",
        help="Output directory for weather parquet",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch hourly weather
    t0 = time.time()
    df_hourly = fetch_weather_data(
        latitude=args.lat,
        longitude=args.lon,
        start_date=args.start,
        end_date=args.end,
    )

    # Step 2: Resample to 5-minute intervals
    df_5min = resample_to_5min(df_hourly)

    # Step 3: Add derived features
    df_5min = add_derived_features(df_5min)

    elapsed = time.time() - t0

    # Step 4: Save
    parquet_path = out_dir / "weather_historical.parquet"
    df_5min.to_parquet(parquet_path, index=False)

    csv_sample_path = out_dir / "weather_historical_sample.csv"
    df_5min.head(500).to_csv(csv_sample_path, index=False)

    # Step 5: Generate metadata
    meta = {
        "version": "1.0.0",
        "created_at": datetime.utcnow().isoformat() + "+00:00",
        "elapsed_seconds": round(elapsed, 2),
        "source": "Open-Meteo Archive API",
        "source_url": OPEN_METEO_URL,
        "coordinates": {"latitude": args.lat, "longitude": args.lon},
        "time_range": {"start": args.start, "end": args.end},
        "original_resolution": "1 hour",
        "output_resolution": "5 minutes",
        "total_records": len(df_5min),
        "columns": list(df_5min.columns),
        "variables": HOURLY_VARIABLES,
        "derived_features": ["is_raining", "rain_intensity", "temp_bucket", "feels_like"],
        "parquet_file": parquet_path.name,
        "parquet_size_bytes": parquet_path.stat().st_size,
        "nulls_per_column": df_5min.isnull().sum().to_dict(),
    }

    meta_path = out_dir / "weather_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("Weather data collection COMPLETE")
    logger.info("  Records: %d", len(df_5min))
    logger.info("  Range: %s → %s", args.start, args.end)
    logger.info("  Parquet: %s (%.2f MB)", parquet_path, parquet_path.stat().st_size / 1e6)
    logger.info("  Metadata: %s", meta_path)
    logger.info("  Elapsed: %.2fs", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
