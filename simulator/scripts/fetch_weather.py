"""Fetch hourly historical weather for the simulator from Open-Meteo (run once, needs network).

Writes inputs/weather_hcmc.json. The simulator only reads that file, so
simulation runs stay offline and reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "simulator.json"
OUTPUT_PATH = ROOT / "inputs" / "weather_hcmc.json"
API_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARIABLES = ["precipitation", "cloud_cover", "is_day", "temperature_2m"]
TIMEZONE = "Asia/Ho_Chi_Minh"


def default_window(config: dict) -> tuple[date, date]:
    return date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])


def fetch(latitude: float, longitude: float, start: date, end: date) -> dict:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": TIMEZONE,
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}", headers={"User-Agent": "smart-ev-journey-simulator"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def build_output(payload: dict, start: date, end: date) -> dict:
    hourly = payload["hourly"]
    rows = []
    for index, time in enumerate(hourly["time"]):
        rows.append(
            {
                "time": time,
                "precipitation_mm": hourly["precipitation"][index],
                "cloud_cover_pct": hourly["cloud_cover"][index],
                "is_day": hourly["is_day"][index],
                "temperature_c": hourly["temperature_2m"][index],
            }
        )
    return {
        "source": "Open-Meteo Historical Weather API (CC BY 4.0)",
        "source_url": API_URL,
        "queried_at": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"),
        "latitude": payload["latitude"],
        "longitude": payload["longitude"],
        "timezone": TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, help="default: start_date")
    parser.add_argument("--end", type=date.fromisoformat, help="default: end_date")
    parser.add_argument("--force", action="store_true", help="replace an existing file")
    args = parser.parse_args()

    if OUTPUT_PATH.exists() and not args.force:
        print(f"{OUTPUT_PATH} already exists; pass --force to fetch again.")
        return 0

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    default_start, default_end = default_window(config)
    start, end = args.start or default_start, args.end or default_end
    payload = fetch(config["weather"]["latitude"], config["weather"]["longitude"], start, end)
    output = build_output(payload, start, end)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(output['hourly'])} hourly rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
