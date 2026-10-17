"""Download the real street network of the nine pilot wards from OpenStreetMap (Overpass API).

Writes a compact GeoJSON used by prepare_gap_analysis_demo.py to cut the area into street blocks.
Standard library only. The result is committed, so this only needs re-running to refresh the roads.

    python scripts/collect_osm_roads.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENT = ROOT / "data_platform" / "station_planning" / "demo_hcmc_v3" / "pilot_extent.geojson"
OUTPUT = ROOT / "raw_data" / "osm_roads"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HIGHWAY_PATTERN = "^(motorway|trunk|primary|secondary|tertiary|unclassified|residential)(_link)?$"
KEPT_TAGS = ("highway", "name", "lanes", "oneway", "ref")


def extent_bbox(path: Path) -> tuple[float, float, float, float]:
    """(south, west, north, east) of the pilot extent."""
    collection = json.loads(path.read_text(encoding="utf-8"))
    lons: list[float] = []
    lats: list[float] = []

    def walk(coordinates: list) -> None:
        if coordinates and isinstance(coordinates[0], int | float):
            lons.append(coordinates[0])
            lats.append(coordinates[1])
        else:
            for item in coordinates:
                walk(item)

    features = collection["features"] if "features" in collection else [collection]
    for feature in features:
        walk(feature["geometry"]["coordinates"])
    return min(lats), min(lons), max(lats), max(lons)


def fetch(bbox: tuple[float, float, float, float]) -> dict:
    south, west, north, east = bbox
    query = (
        f'[out:json][timeout:120];way["highway"~"{HIGHWAY_PATTERN}"]'
        f"({south},{west},{north},{east});out geom;"
    )
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "smart-ev-planner-data-prep/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read())


def to_geojson(payload: dict) -> dict:
    features = []
    for element in sorted(payload["elements"], key=lambda item: item["id"]):
        points = [[round(p["lon"], 6), round(p["lat"], 6)] for p in element.get("geometry", [])]
        if element.get("type") != "way" or len(points) < 2:
            continue
        tags = element.get("tags", {})
        properties = {"osm_id": element["id"]}
        properties.update({key: tags[key] for key in KEPT_TAGS if key in tags})
        features.append(
            {"type": "Feature", "properties": properties,
             "geometry": {"type": "LineString", "coordinates": points}}
        )
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args(argv)
    bbox = extent_bbox(EXTENT)
    collection = to_geojson(fetch(bbox))
    arguments.output.mkdir(parents=True, exist_ok=True)
    path = arguments.output / "hcm_nine_wards_roads.geojson"
    encoded = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    path.write_text(encoded, encoding="utf-8")
    counts: dict[str, int] = {}
    for feature in collection["features"]:
        highway = feature["properties"]["highway"]
        counts[highway] = counts.get(highway, 0) + 1
    manifest = {
        "source": "OpenStreetMap via Overpass API",
        "licence": "ODbL 1.0, (c) OpenStreetMap contributors",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bbox_south_west_north_east": bbox,
        "highway_filter": HIGHWAY_PATTERN,
        "ways": len(collection["features"]),
        "ways_by_highway": dict(sorted(counts.items())),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (arguments.output / "collection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["ways_by_highway"], ensure_ascii=False))
    print(f"Wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
