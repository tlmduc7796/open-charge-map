#!/usr/bin/env python3
"""Fetch important demo routes from public OSRM and store normalized cache files."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_CONFIG = ROOT / "config" / "demo_routes.json"
STATIONS_FILE = ROOT / "data_platform" / "data" / "static" / "stations.geojson"
ROUTES_DIR = ROOT / "data_platform" / "data" / "routes"
OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving"


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def request_osrm(points: list[dict]) -> dict:
    coordinate_path = ";".join(f"{point['lon']},{point['lat']}" for point in points)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    url = f"{OSRM_BASE_URL}/{coordinate_path}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "SmartEVJourney/0.1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RuntimeError(f"OSRM failed: {payload.get('code')} {payload.get('message', '')}")
    return payload["routes"][0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Replace existing route caches")
    args = parser.parse_args()

    config = read_json(ROUTE_CONFIG)
    stations = read_json(STATIONS_FILE)
    station_by_id = {
        feature["properties"]["station_id"]: feature for feature in stations["features"]
    }
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)

    origin = config["origin"]
    destination = config["destination"]
    for definition in config["routes"]:
        output = ROUTES_DIR / f"{definition['route_id'].lower()}.json"
        if output.exists() and not args.force:
            print(f"Keep existing {output.name}")
            continue
        waypoints = []
        for station_id in definition["waypoint_station_ids"]:
            feature = station_by_id[station_id]
            lon, lat = feature["geometry"]["coordinates"]
            waypoints.append(
                {
                    "station_id": station_id,
                    "lat": lat,
                    "lon": lon,
                    "label": feature["properties"]["name"],
                }
            )
        points = [origin, *waypoints, destination]
        route = request_osrm(points)
        request_key = json.dumps(
            {"provider": "osrm", "points": [[point["lat"], point["lon"]] for point in points]},
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized = {
            "route_id": definition["route_id"],
            "provider": "osrm",
            "origin": origin,
            "destination": destination,
            "waypoints": waypoints,
            "geometry": route["geometry"],
            "distance_m": route["distance"],
            "duration_s": route["duration"],
            "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "request_hash": hashlib.sha256(request_key.encode("utf-8")).hexdigest(),
            "data_source": "routing_api",
        }
        output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Cached {definition['route_id']}: {route['distance']:.0f} m, {route['duration']:.0f} s")


if __name__ == "__main__":
    main()
