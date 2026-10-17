"""Generate the gap-analysis snapshot (grid cells, simulated flow/rent, simulated stations).

POI values come from the collected official POI/transport layers. Vehicle flow, rent and the
charging-station inventory (own network + competitors) are simulated and labelled `synthetic`.
Standard library only; output is deterministic for a given config seed.

    python scripts/prepare_gap_analysis_demo.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "gap_analysis_demo.json"
EARTH_M_PER_DEG_LAT = 110_540.0
EARTH_M_PER_DEG_LON_EQ = 111_320.0

CELL_FIELDS = [
    "cell_id", "unit_id", "unit_name", "center_lat", "center_lon",
    "lat_min", "lat_max", "lon_min", "lon_max", "cell_size_m",
    "poi_count", "poi_weighted", "poi_status",
    "flow_vph", "flow_status", "rent_kvnd_m2_month", "rent_status",
]
ROUTE_FIELDS = [
    "cell_id", "unit_id", "unit_name", "center_lat", "center_lon", "lat_min", "lat_max",
    "lon_min", "lon_max", "area_m2", "subdivided", "road_names", "road_count", "road_length_m",
    "road_type", "lanes", "poi_count", "poi_weighted", "poi_status", "flow_vph", "flow_status",
    "rent_kvnd_m2_month", "rent_status", "polygon",
]
ROAD_FIELDS = [
    "road_id", "road_name", "road_type", "lanes", "length_m", "flow_vph", "flow_status",
    "coordinates",
]
STATION_FIELDS = [
    "station_id", "operator_id", "operator_name", "relationship", "unit_id", "unit_name",
    "cell_id", "lat", "lon", "site_type", "opening_hours", "port_count", "dc_port_count",
    "ac_port_count", "total_power_kw", "max_port_power_kw", "source_type", "is_synthetic",
    "quality_status",
]
PORT_FIELDS = [
    "station_id", "charger_type", "connector_type", "port_count", "power_kw_per_port",
    "group_power_kw",
]


class Projection:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self.m_per_deg_lon = EARTH_M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_per_deg_lon, (lat - self.lat0) * EARTH_M_PER_DEG_LAT

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / EARTH_M_PER_DEG_LAT, self.lon0 + x / self.m_per_deg_lon


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_contains(rings: list[list[list[float]]], lon: float, lat: float) -> bool:
    if not ring_contains(rings[0], lon, lat):
        return False
    return not any(ring_contains(hole, lon, lat) for hole in rings[1:])


def geometry_polygons(geometry: dict) -> list[list[list[list[float]]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"Unsupported ward geometry: {geometry['type']}")


def percentile_rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    for position, index in enumerate(order):
        ranks[index] = position / max(len(values) - 1, 1)
    return ranks


def minmax(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    span = high - low
    return [0.0 if span == 0 else (value - low) / span for value in values]


def load_wards(path: Path) -> list[dict]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    wards = []
    for feature in collection["features"]:
        properties = feature["properties"]
        wards.append(
            {
                "unit_id": properties["unit_id"],
                "unit_name": properties["unit_name"],
                "polygons": geometry_polygons(feature["geometry"]),
            }
        )
    return wards


def locate_ward(wards: list[dict], lon: float, lat: float) -> dict | None:
    for ward in wards:
        if any(polygon_contains(polygon, lon, lat) for polygon in ward["polygons"]):
            return ward
    return None


def build_grid(config: dict, wards: list[dict], projection: Projection) -> list[dict]:
    size = float(config["grid"]["cell_size_m"])
    xs, ys = [], []
    for ward in wards:
        for polygon in ward["polygons"]:
            for lon, lat in polygon[0]:
                x, y = projection.to_xy(lat, lon)
                xs.append(x)
                ys.append(y)
    x0, y0 = math.floor(min(xs) / size) * size, math.floor(min(ys) / size) * size
    columns = int(math.ceil((max(xs) - x0) / size))
    rows = int(math.ceil((max(ys) - y0) / size))
    cells = []
    for row in range(rows):
        for column in range(columns):
            cx, cy = x0 + (column + 0.5) * size, y0 + (row + 0.5) * size
            lat, lon = projection.to_latlon(cx, cy)
            ward = locate_ward(wards, lon, lat)
            if ward is None:
                continue
            lat_min, lon_min = projection.to_latlon(cx - size / 2, cy - size / 2)
            lat_max, lon_max = projection.to_latlon(cx + size / 2, cy + size / 2)
            cells.append(
                {
                    "row": row, "column": column, "x": cx, "y": cy,
                    "unit_id": ward["unit_id"], "unit_name": ward["unit_name"],
                    "center_lat": lat, "center_lon": lon,
                    "lat_min": lat_min, "lat_max": lat_max,
                    "lon_min": lon_min, "lon_max": lon_max,
                }
            )
    cells.sort(key=lambda cell: (cell["unit_id"], cell["row"], cell["column"]))
    for index, cell in enumerate(cells, start=1):
        cell["cell_id"] = f"G{index:04d}"
    return cells


class CellIndex:
    """Constant-time lookup of the grid cell containing a projected point."""

    def __init__(self, cells: list[dict], size: float, projection: Projection) -> None:
        self.size, self.projection = size, projection
        self._by_key = {(cell["row"], cell["column"]): cell for cell in cells}
        self._origin_x = min(cell["x"] - (cell["column"] + 0.5) * size for cell in cells)
        self._origin_y = min(cell["y"] - (cell["row"] + 0.5) * size for cell in cells)

    def find(self, lat: float, lon: float) -> dict | None:
        x, y = self.projection.to_xy(lat, lon)
        column = int(math.floor((x - self._origin_x) / self.size))
        row = int(math.floor((y - self._origin_y) / self.size))
        return self._by_key.get((row, column))


def aggregate_poi(config: dict, root: Path, index: CellIndex) -> dict[str, dict]:
    sources = config["sources"]
    poi = json.loads((root / sources["poi"]).read_text(encoding="utf-8"))
    transport = json.loads((root / sources["transport"]).read_text(encoding="utf-8"))
    weights_by_feature: dict[str, float] = {}
    with (root / sources["poi_weights"]).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            weights_by_feature[row["feature_id"]] = float(row["modeling_weight"])
    category_weights = config["poi"]["category_weights"]
    default_weight = float(config["poi"]["default_category_weight"])
    transport_poi = set(config["poi"]["transport_poi_categories"])
    totals: dict[str, dict] = defaultdict(lambda: {"count": 0.0, "weighted": 0.0})
    points: list[dict] = []

    def add(feature: dict, category: str, modeling_weight: float) -> None:
        lon, lat = feature["geometry"]["coordinates"][:2]
        cell = index.find(lat, lon)
        if cell is None:
            return
        weight = float(category_weights.get(category, default_weight))
        entry = totals[cell["cell_id"]]
        entry["count"] += modeling_weight
        entry["weighted"] += weight * modeling_weight
        points.append(
            {"category": category, "lat": lat, "lon": lon, "cell_id": cell["cell_id"]}
        )

    for feature in poi["features"]:
        if feature["geometry"]["type"] != "Point":
            continue
        category = feature["properties"]["category"]
        add(feature, category, weights_by_feature.get(feature["properties"]["feature_id"], 1.0))
    for feature in transport["features"]:
        category = feature["properties"].get("category")
        if feature["geometry"]["type"] == "Point" and category in transport_poi:
            add(feature, category, 1.0)
    return {"totals": dict(totals), "points": points}


def infrastructure_counts(config: dict, root: Path, index: CellIndex) -> dict[str, float]:
    transport = json.loads((root / config["sources"]["transport"]).read_text(encoding="utf-8"))
    weights = config["flow_simulation"]["infrastructure_weights"]
    vertex_weight = float(weights["road_vertex"])
    totals: dict[str, float] = defaultdict(float)

    def add_point(lon: float, lat: float, weight: float) -> None:
        cell = index.find(lat, lon)
        if cell is not None:
            totals[cell["cell_id"]] += weight

    for feature in transport["features"]:
        category = feature["properties"].get("category")
        geometry = feature["geometry"]
        if geometry["type"] == "Point" and category in weights:
            add_point(*geometry["coordinates"][:2], float(weights[category]))
        elif category == "Đường" and geometry["type"] in {"LineString", "MultiLineString"}:
            lines = (
                [geometry["coordinates"]]
                if geometry["type"] == "LineString"
                else geometry["coordinates"]
            )
            for line in lines:
                for lon, lat, *_ in line:
                    add_point(lon, lat, vertex_weight)
    return dict(totals)


def simulate_flow_and_rent(
    config: dict, cells: list[dict], poi_weighted: list[float], infra: list[float],
    projection: Projection, rng: random.Random,
) -> None:
    center = config["grid"]["city_center"]
    cx, cy = projection.to_xy(center["lat"], center["lon"])
    flow_cfg, rent_cfg = config["flow_simulation"], config["rent_simulation"]
    phases = [(rng.uniform(0, math.tau), rng.uniform(0.0006, 0.0016)) for _ in range(3)]
    infra_rank = percentile_rank(infra)
    poi_rank = percentile_rank(poi_weighted)
    noise_raw = []
    for cell in cells:
        noise_raw.append(
            sum(math.sin(cell["x"] * freq + phase) * math.cos(cell["y"] * freq * 1.3 + phase)
                for phase, freq in phases)
        )
    noise = minmax(noise_raw)
    weights = flow_cfg["weights"]
    latent = []
    for position, cell in enumerate(cells):
        distance = math.hypot(cell["x"] - cx, cell["y"] - cy)
        cell["distance_to_center_m"] = distance
        radial = math.exp(-distance / float(flow_cfg["radial_scale_m"]))
        latent.append(
            weights["radial"] * radial + weights["infrastructure"] * infra_rank[position]
            + weights["smooth_noise"] * noise[position]
        )
    latent = minmax(latent)
    low, high = float(flow_cfg["min_vph"]), float(flow_cfg["max_vph"])
    for position, cell in enumerate(cells):
        jitter = math.exp(rng.gauss(0.0, float(flow_cfg["lognormal_sigma"])))
        flow = low + (high - low) * (latent[position] ** 1.3) * jitter
        cell["flow_vph"] = int(round(min(max(flow, low), high), -1))
        cell["flow_status"] = flow_cfg["status"]
        rent = (
            float(rent_cfg["base_kvnd"])
            + float(rent_cfg["central_premium_kvnd"])
            * math.exp(-cell["distance_to_center_m"] / float(rent_cfg["radial_scale_m"]))
            + float(rent_cfg["poi_premium_kvnd"]) * poi_rank[position]
        ) * math.exp(rng.gauss(0.0, float(rent_cfg["lognormal_sigma"])))
        rent = min(max(rent, float(rent_cfg["min_kvnd"])), float(rent_cfg["max_kvnd"]))
        cell["rent_kvnd_m2_month"] = int(round(rent / 5.0) * 5)
        cell["rent_status"] = rent_cfg["status"]


def pick_template(operator: dict, rng: random.Random) -> dict:
    roll, cumulative = rng.random(), 0.0
    for template in operator["templates"]:
        cumulative += float(template["probability"])
        if roll <= cumulative:
            return template
    return operator["templates"][-1]


def simulate_stations(
    config: dict, cells: list[dict], host_sites: list[dict], index: CellIndex,
    projection: Projection, rng: random.Random,
) -> tuple[list[dict], list[dict]]:
    sim = config["station_simulation"]
    spacing = float(sim["minimum_spacing_m"])
    host_types = sim["host_categories"]
    by_id = {cell["cell_id"]: cell for cell in cells}
    available = [site for site in host_sites if site["category"] in host_types]
    for site in available:
        site["x"], site["y"] = projection.to_xy(site["lat"], site["lon"])
    placed: list[tuple[float, float]] = []
    stations: list[dict] = []
    ports: list[dict] = []
    for operator in sim["operators"]:
        exponent = float(operator["demand_exponent"])
        counter = 0
        while counter < int(operator["station_count"]):
            candidates = [
                site for site in available
                if all(math.hypot(site["x"] - px, site["y"] - py) >= spacing for px, py in placed)
            ]
            if not candidates:
                raise RuntimeError("Not enough host sites to place the requested stations.")
            weights = [
                (0.05 + by_id[site["cell_id"]]["demand_hint"]) ** exponent for site in candidates
            ]
            site = rng.choices(candidates, weights=weights, k=1)[0]
            available.remove(site)
            jitter_x, jitter_y = rng.uniform(-12, 12), rng.uniform(-12, 12)
            lat, lon = projection.to_latlon(site["x"] + jitter_x, site["y"] + jitter_y)
            cell = index.find(lat, lon) or by_id[site["cell_id"]]
            placed.append((site["x"], site["y"]))
            counter += 1
            template = pick_template(operator, rng)
            station_id = f"{operator['operator_id']}-{counter:02d}"
            dc = sum(int(g[2]) for g in template["groups"] if g[0] == "DC")
            ac = sum(int(g[2]) for g in template["groups"] if g[0] == "AC")
            total_kw = sum(int(g[2]) * float(g[3]) for g in template["groups"])
            site_type = host_types[site["category"]]
            retail = site_type in {"mall", "supermarket"}
            stations.append(
                {
                    "station_id": station_id, "operator_id": operator["operator_id"],
                    "operator_name": operator["operator_name"],
                    "relationship": operator["relationship"],
                    "unit_id": cell["unit_id"], "unit_name": cell["unit_name"],
                    "cell_id": cell["cell_id"], "lat": round(lat, 6), "lon": round(lon, 6),
                    "site_type": site_type,
                    "opening_hours": "08:00-22:00" if retail else "24/7",
                    "port_count": dc + ac, "dc_port_count": dc, "ac_port_count": ac,
                    "total_power_kw": round(total_kw, 1),
                    "max_port_power_kw": max(float(g[3]) for g in template["groups"]),
                    "source_type": "synthetic", "is_synthetic": True,
                    "quality_status": "simulated_not_real_inventory",
                }
            )
            for charger, connector, count, power in template["groups"]:
                ports.append(
                    {
                        "station_id": station_id, "charger_type": charger,
                        "connector_type": connector, "port_count": int(count),
                        "power_kw_per_port": float(power),
                        "group_power_kw": round(int(count) * float(power), 1),
                    }
                )
    manual_stations, manual_ports = place_manual_stations(config, stations, by_id, index)
    return stations + manual_stations, ports + manual_ports


def place_manual_stations(
    config: dict, existing: list[dict], by_id: dict[str, dict], index: CellIndex,
) -> tuple[list[dict], list[dict]]:
    """Stations at fixed coordinates (config `manual_stations`); they consume no random numbers."""
    sim = config["station_simulation"]
    operators = {operator["operator_id"]: operator for operator in sim["operators"]}
    counters = Counter(station["operator_id"] for station in existing)
    stations: list[dict] = []
    ports: list[dict] = []
    for manual in sim.get("manual_stations", []):
        operator = operators[manual["operator_id"]]
        groups = manual["groups"]
        counters[operator["operator_id"]] += 1
        station_id = f"{operator['operator_id']}-{counters[operator['operator_id']]:02d}"
        cell = index.find(manual["lat"], manual["lon"])
        if cell is None:
            raise RuntimeError(f"Manual station {station_id} lies outside the nine wards.")
        dc = sum(int(g[2]) for g in groups if g[0] == "DC")
        ac = sum(int(g[2]) for g in groups if g[0] == "AC")
        stations.append(
            {
                "station_id": station_id, "operator_id": operator["operator_id"],
                "operator_name": operator["operator_name"],
                "relationship": operator["relationship"],
                "unit_id": cell["unit_id"], "unit_name": cell["unit_name"],
                "cell_id": cell["cell_id"], "lat": manual["lat"], "lon": manual["lon"],
                "site_type": manual.get("site_type", "other"),
                "opening_hours": manual.get("opening_hours", "24/7"),
                "port_count": dc + ac, "dc_port_count": dc, "ac_port_count": ac,
                "total_power_kw": round(sum(int(g[2]) * float(g[3]) for g in groups), 1),
                "max_port_power_kw": max(float(g[3]) for g in groups),
                "source_type": "synthetic", "is_synthetic": True,
                "quality_status": "simulated_not_real_inventory",
            }
        )
        for charger, connector, count, power in groups:
            ports.append(
                {
                    "station_id": station_id, "charger_type": charger,
                    "connector_type": connector, "port_count": int(count),
                    "power_kw_per_port": float(power),
                    "group_power_kw": round(int(count) * float(power), 1),
                }
            )
    return stations, ports


# --- Route division: street blocks bounded by the real road network -----------------------------

ROAD_CLASS_SCORE = {
    "motorway": 6.0, "trunk": 5.0, "primary": 4.0, "secondary": 3.0, "tertiary": 2.0,
    "unclassified": 1.0, "residential": 1.0,
}
ROAD_CLASS_ORDER = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
]


def load_shapely() -> dict:
    """Shapely is only needed here, to cut the area into blocks (requirements-station-planning)."""
    try:
        from shapely import STRtree
        from shapely.geometry import LineString, Point, Polygon, box
        from shapely.ops import unary_union
    except ImportError as exc:
        raise SystemExit(
            "Route blocks need shapely: pip install -r scripts/requirements-station-planning.txt "
            "or pass --dependency-dir <folder containing shapely>."
        ) from exc
    return {"STRtree": STRtree, "LineString": LineString, "Point": Point, "Polygon": Polygon,
            "box": box, "unary_union": unary_union}


def keep_road(properties: dict, route: dict) -> str | None:
    """Base class of an OSM way that counts as a street, or None for alleys and unnamed lanes."""
    base = properties["highway"].removesuffix("_link")
    if base not in route["road_half_width_m"]:
        return None
    if base == "residential":
        name = unicodedata.normalize("NFC", properties.get("name") or "").lower()
        if not name or name.startswith(tuple(route["alley_name_prefixes"])):
            return None
    return base


def load_osm_roads(config: dict, projection: Projection, shp: dict) -> list[dict]:
    route = config["route_division"]
    collection = json.loads((ROOT / config["sources"]["osm_roads"]).read_text(encoding="utf-8"))
    roads: list[dict] = []
    for feature in collection["features"]:
        properties = feature["properties"]
        base = keep_road(properties, route)
        if base is None:
            continue
        points = [projection.to_xy(lat, lon) for lon, lat in feature["geometry"]["coordinates"]]
        lanes = properties.get("lanes", "")
        roads.append(
            {
                "line": shp["LineString"](points), "base": base,
                "name": properties.get("name") or "Đường chưa đặt tên",
                "lanes": int(lanes) if str(lanes).isdigit() else None,
            }
        )
    return roads


def ward_geometry(ward: dict, projection: Projection, shp: dict):
    polygons = []
    for rings in ward["polygons"]:
        projected = [[projection.to_xy(lat, lon) for lon, lat in ring] for ring in rings]
        polygons.append(shp["Polygon"](projected[0], projected[1:]))
    return shp["unary_union"](polygons)


def polygon_parts(geometry) -> list:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in geometry.geoms if part.geom_type == "Polygon"]


def split_large(polygon, maximum_m2: float, shp: dict) -> list:
    """Cut an oversized open area in halves, across its longer side, until each piece is small."""
    if polygon.area <= maximum_m2:
        return [polygon]
    min_x, min_y, max_x, max_y = polygon.bounds
    centre = polygon.centroid
    box = shp["box"]
    if max_x - min_x >= max_y - min_y:
        halves = [box(min_x, min_y, centre.x, max_y), box(centre.x, min_y, max_x, max_y)]
    else:
        halves = [box(min_x, min_y, max_x, centre.y), box(min_x, centre.y, max_x, max_y)]
    pieces = []
    for half in halves:
        for part in polygon_parts(polygon.intersection(half)):
            pieces.extend(split_large(part, maximum_m2, shp))
    return pieces


def build_blocks(
    config: dict, wards: list[dict], projection: Projection, shp: dict, roads: list[dict]
) -> list[dict]:
    route = config["route_division"]
    half_width = route["road_half_width_m"]
    corridor = shp["unary_union"]([road["line"].buffer(half_width[road["base"]]) for road in roads])
    blocks = []
    for ward in wards:
        free = ward_geometry(ward, projection, shp).difference(corridor)
        for part in polygon_parts(free):
            if part.area < float(route["min_block_m2"]):
                continue
            pieces = split_large(part, float(route["max_block_m2"]), shp)
            for piece in pieces:
                if piece.area >= float(route["min_block_m2"]):
                    blocks.append({"polygon": piece, "unit_id": ward["unit_id"],
                                   "unit_name": ward["unit_name"], "subdivided": len(pieces) > 1})
    for block in blocks:
        block["point"] = block["polygon"].representative_point()
    blocks.sort(key=lambda b: (b["unit_id"], round(b["point"].y), round(b["point"].x)))
    for number, block in enumerate(blocks, start=1):
        block["cell_id"] = f"B{number:04d}"
    return blocks


def describe_boundary_roads(blocks: list[dict], roads: list[dict], route: dict, shp: dict) -> None:
    """Which streets bound each block: names, best class, and class-weighted length."""
    tree = shp["STRtree"]([road["line"] for road in roads])
    reach = float(route["adjacent_road_m"])
    minimum = float(route["min_adjacent_m"])
    labels = route["road_class_labels"]
    for block in blocks:
        zone = block["polygon"].buffer(reach)
        by_name: dict[str, float] = defaultdict(float)
        weighted = 0.0
        best = len(ROAD_CLASS_ORDER)
        lanes = None
        for index in sorted(tree.query(zone, predicate="intersects")):
            road = roads[int(index)]
            length = road["line"].intersection(zone).length
            if length < minimum:
                continue
            by_name[road["name"]] += length
            weighted += length * ROAD_CLASS_SCORE[road["base"]]
            best = min(best, ROAD_CLASS_ORDER.index(road["base"]))
            if road["lanes"]:
                lanes = max(lanes or 0, road["lanes"])
        ranked = sorted(by_name.items(), key=lambda item: (-item[1], item[0]))
        block.update(
            road_names=[name for name, _ in ranked[:3]], road_count=len(ranked),
            road_length_m=sum(by_name.values()), weighted_road=weighted, lanes=lanes,
            road_type=labels[ROAD_CLASS_ORDER[best]] if best < len(ROAD_CLASS_ORDER) else "",
            poi_count=0.0, poi_weighted=0.0, infra=0.0,
        )


def assign_points_to_blocks(
    config: dict, blocks: list[dict], projection: Projection, shp: dict
) -> None:
    """POI and traffic infrastructure count for their block, else the nearest one within reach."""
    sources = config["sources"]
    reach = float(config["route_division"]["nearest_block_m"])
    tree = shp["STRtree"]([block["polygon"] for block in blocks])
    poi = json.loads((ROOT / sources["poi"]).read_text(encoding="utf-8"))
    transport = json.loads((ROOT / sources["transport"]).read_text(encoding="utf-8"))
    weights_by_feature: dict[str, float] = {}
    with (ROOT / sources["poi_weights"]).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            weights_by_feature[row["feature_id"]] = float(row["modeling_weight"])
    category_weights = config["poi"]["category_weights"]
    default_weight = float(config["poi"]["default_category_weight"])
    transport_poi = set(config["poi"]["transport_poi_categories"])
    infra_weights = config["flow_simulation"]["infrastructure_weights"]

    def block_for(feature: dict) -> dict | None:
        lon, lat = feature["geometry"]["coordinates"][:2]
        point = shp["Point"](projection.to_xy(lat, lon))
        index = int(tree.nearest(point))
        return blocks[index] if blocks[index]["polygon"].distance(point) <= reach else None

    for feature in poi["features"]:
        if feature["geometry"]["type"] != "Point":
            continue
        block = block_for(feature)
        if block is None:
            continue
        share = weights_by_feature.get(feature["properties"]["feature_id"], 1.0)
        weight = float(category_weights.get(feature["properties"]["category"], default_weight))
        block["poi_count"] += share
        block["poi_weighted"] += weight * share
    for feature in transport["features"]:
        category = feature["properties"].get("category")
        if feature["geometry"]["type"] != "Point":
            continue
        if category not in transport_poi and category not in infra_weights:
            continue
        block = block_for(feature)
        if block is None:
            continue
        if category in transport_poi:
            block["poi_count"] += 1.0
            block["poi_weighted"] += float(category_weights.get(category, default_weight))
        if category in infra_weights:
            block["infra"] += float(infra_weights[category])


def simulate_block_flow_and_rent(
    config: dict, blocks: list[dict], projection: Projection, rng: random.Random
) -> None:
    center = config["grid"]["city_center"]
    cx, cy = projection.to_xy(center["lat"], center["lon"])
    flow_cfg, rent_cfg = config["flow_simulation"], config["rent_simulation"]
    weights = config["route_division"]["flow_weights"]
    capacity_rank = percentile_rank([b["weighted_road"] for b in blocks])
    infra_rank = percentile_rank([b["infra"] for b in blocks])
    poi_rank = percentile_rank([b["poi_weighted"] for b in blocks])
    phases = [(rng.uniform(0, math.tau), rng.uniform(0.0006, 0.0016)) for _ in range(3)]
    noise = minmax(
        [
            sum(math.sin(b["point"].x * freq + phase) * math.cos(b["point"].y * freq * 1.3 + phase)
                for phase, freq in phases)
            for b in blocks
        ]
    )
    latent = []
    for position, block in enumerate(blocks):
        distance = math.hypot(block["point"].x - cx, block["point"].y - cy)
        block["distance_to_center_m"] = distance
        radial = math.exp(-distance / float(flow_cfg["radial_scale_m"]))
        latent.append(
            weights["radial"] * radial + weights["capacity"] * capacity_rank[position]
            + weights["infrastructure"] * infra_rank[position]
            + weights["smooth_noise"] * noise[position]
        )
    latent = minmax(latent)
    low, high = float(flow_cfg["min_vph"]), float(flow_cfg["max_vph"])
    for position, block in enumerate(blocks):
        jitter = math.exp(rng.gauss(0.0, float(flow_cfg["lognormal_sigma"])))
        flow = low + (high - low) * (latent[position] ** 1.3) * jitter
        block["flow_vph"] = int(round(min(max(flow, low), high), -1))
        block["flow_status"] = flow_cfg["status"]
        rent = (
            float(rent_cfg["base_kvnd"])
            + float(rent_cfg["central_premium_kvnd"])
            * math.exp(-block["distance_to_center_m"] / float(rent_cfg["radial_scale_m"]))
            + float(rent_cfg["poi_premium_kvnd"]) * poi_rank[position]
        ) * math.exp(rng.gauss(0.0, float(rent_cfg["lognormal_sigma"])))
        rent = min(max(rent, float(rent_cfg["min_kvnd"])), float(rent_cfg["max_kvnd"]))
        block["rent_kvnd_m2_month"] = int(round(rent / 5.0) * 5)
        block["rent_status"] = rent_cfg["status"]


# --- Per-road traffic flow (simulated), drawn as a Google-Maps-like congestion layer ------------


def road_midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Point at half the length of a polyline given in metres."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:], strict=False)]
    half, walked = sum(lengths) / 2, 0.0
    for (ax, ay), (bx, by), length in zip(points, points[1:], lengths, strict=False):
        if walked + length >= half and length > 0:
            share = (half - walked) / length
            return ax + (bx - ax) * share, ay + (by - ay) * share
        walked += length
    return points[0]


def simulate_road_flows(
    config: dict, projection: Projection, index: CellIndex, infra_rank_by_cell: dict[str, float],
    rng: random.Random,
) -> list[dict]:
    """One row per street (OSM way kept by `keep_road`) with a simulated peak-hour flow.

    Same family of drivers as the block flow (distance to the centre, road class, nearby traffic
    infrastructure, smooth noise) but evaluated on the road itself, so a main road reads as busy
    along its whole length instead of being averaged into the surrounding land.
    """
    route = config["route_division"]
    sim = config["road_flow_simulation"]
    flow_cfg = config["flow_simulation"]
    center = config["grid"]["city_center"]
    cx, cy = projection.to_xy(center["lat"], center["lon"])
    collection = json.loads((ROOT / config["sources"]["osm_roads"]).read_text(encoding="utf-8"))
    roads: list[dict] = []
    for feature in collection["features"]:
        properties = feature["properties"]
        base = keep_road(properties, route)
        if base is None:
            continue
        coordinates: list[list[float]] = []
        for lon, lat in feature["geometry"]["coordinates"]:
            point = [round(lat, 5), round(lon, 5)]
            if not coordinates or coordinates[-1] != point:
                coordinates.append(point)
        if len(coordinates) < 2:
            continue
        points = [projection.to_xy(lat, lon) for lat, lon in coordinates]
        mid_x, mid_y = road_midpoint(points)
        mid_lat, mid_lon = projection.to_latlon(mid_x, mid_y)
        cell = index.find(mid_lat, mid_lon)
        lanes = properties.get("lanes", "")
        roads.append(
            {
                "road_name": properties.get("name") or "Đường chưa đặt tên", "road_type": base,
                "lanes": int(lanes) if str(lanes).isdigit() else "",
                "length_m": round(sum(math.dist(a, b) for a, b in zip(points, points[1:],
                                                                        strict=False)), 1),
                "coordinates": coordinates, "x": mid_x, "y": mid_y,
                "infra": infra_rank_by_cell.get(cell["cell_id"], 0.0) if cell else 0.0,
            }
        )
    phases = [
        (rng.uniform(0, math.tau), rng.uniform(*sim["noise_frequency_range"])) for _ in range(4)
    ]
    noise = minmax(
        [
            sum(math.sin(r["x"] * freq + phase) * math.cos(r["y"] * freq * 1.3 + phase)
                for phase, freq in phases)
            for r in roads
        ]
    )
    weights = sim["weights"]
    latent = []
    for position, road in enumerate(roads):
        radial = math.exp(
            -math.hypot(road["x"] - cx, road["y"] - cy) / float(flow_cfg["radial_scale_m"])
        )
        capacity = ROAD_CLASS_SCORE[road["road_type"]] / max(ROAD_CLASS_SCORE.values())
        if road["lanes"] != "":
            capacity = min(capacity + 0.03 * (int(road["lanes"]) - 2), 1.0)
        latent.append(
            weights["radial"] * radial + weights["capacity"] * max(capacity, 0.0)
            + weights["infrastructure"] * road["infra"] + weights["smooth_noise"] * noise[position]
        )
    latent = minmax(latent)
    low, high = float(flow_cfg["min_vph"]), float(flow_cfg["max_vph"])
    for position, road in enumerate(roads):
        jitter = math.exp(rng.gauss(0.0, float(sim["lognormal_sigma"])))
        flow = low + (high - low) * (latent[position] ** float(sim["exponent"])) * jitter
        road["flow_vph"] = int(round(min(max(flow, low), high), -1))
        road["flow_status"] = sim["status"]
    roads.sort(key=lambda r: (r["road_name"], r["coordinates"][0]))
    for number, road in enumerate(roads, start=1):
        road["road_id"] = f"W{number:05d}"
        road["coordinates"] = json.dumps(road["coordinates"], separators=(",", ":"))
    return roads


def build_route_blocks(
    config: dict, wards: list[dict], projection: Projection, rng: random.Random
) -> list[dict]:
    """Street blocks: the land left between the real roads, one polygon per block and ward."""
    shp = load_shapely()
    roads = load_osm_roads(config, projection, shp)
    blocks = build_blocks(config, wards, projection, shp, roads)
    describe_boundary_roads(blocks, roads, config["route_division"], shp)
    assign_points_to_blocks(config, blocks, projection, shp)
    simulate_block_flow_and_rent(config, blocks, projection, rng)
    return blocks


def polygon_rings(polygon, projection: Projection, tolerance_m: float) -> list[list[list[float]]]:
    """[lat, lon] rings (outer first), lightly simplified, for the map."""
    simple = polygon.simplify(tolerance_m, preserve_topology=True)
    rings = [simple.exterior, *simple.interiors]
    return [
        [[round(v, 6) for v in projection.to_latlon(x, y)] for x, y in ring.coords]
        for ring in rings
    ]


def format_route_blocks(
    blocks: list[dict], projection: Projection, tolerance_m: float
) -> list[dict]:
    rows = []
    for block in blocks:
        min_x, min_y, max_x, max_y = block["polygon"].bounds
        lat_min, lon_min = projection.to_latlon(min_x, min_y)
        lat_max, lon_max = projection.to_latlon(max_x, max_y)
        lat, lon = projection.to_latlon(block["point"].x, block["point"].y)
        rows.append(
            {
                **block,
                "center_lat": round(lat, 7), "center_lon": round(lon, 7),
                "lat_min": round(lat_min, 7), "lat_max": round(lat_max, 7),
                "lon_min": round(lon_min, 7), "lon_max": round(lon_max, 7),
                "area_m2": round(block["polygon"].area, 1),
                "road_names": " | ".join(block["road_names"]),
                "road_length_m": round(block["road_length_m"], 1),
                "poi_count": round(block["poi_count"], 2),
                "poi_weighted": round(block["poi_weighted"], 2),
                "poi_status": "observed_collected_official_source",
                "subdivided": "true" if block["subdivided"] else "false",
                "polygon": json.dumps(
                    polygon_rings(block["polygon"], projection, tolerance_m), separators=(",", ":")
                ),
            }
        )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def format_cells(cells: list[dict], poi: dict, cell_size: int) -> list[dict]:
    rows = []
    for cell in cells:
        entry = poi["totals"].get(cell["cell_id"], {"count": 0.0, "weighted": 0.0})
        rows.append(
            {
                **cell,
                "cell_size_m": cell_size,
                "poi_count": round(entry["count"], 2),
                "poi_weighted": round(entry["weighted"], 2),
                "poi_status": "observed_collected_official_source",
                **{key: round(cell[key], 7) for key in (
                    "center_lat", "center_lon", "lat_min", "lat_max", "lon_min", "lon_max")},
            }
        )
    return rows


def build(config_path: Path, output_override: Path | None) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = output_override or ROOT / config["output_directory"]
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(config["seed"]))
    projection = Projection(
        float(config["grid"]["reference_latitude"]), float(config["grid"]["reference_longitude"])
    )
    wards = load_wards(ROOT / config["sources"]["pilot_units"])
    cells = build_grid(config, wards, projection)
    size = int(config["grid"]["cell_size_m"])
    index = CellIndex(cells, float(size), projection)
    poi = aggregate_poi(config, ROOT, index)
    infra_totals = infrastructure_counts(config, ROOT, index)
    poi_weighted = [poi["totals"].get(cell["cell_id"], {"weighted": 0.0})["weighted"]
                    for cell in cells]
    infra = [infra_totals.get(cell["cell_id"], 0.0) for cell in cells]
    simulate_flow_and_rent(config, cells, poi_weighted, infra, projection, rng)

    flow_norm = minmax([float(cell["flow_vph"]) for cell in cells])
    poi_norm = minmax(poi_weighted)
    for position, cell in enumerate(cells):
        cell["demand_hint"] = 0.5 * flow_norm[position] + 0.5 * poi_norm[position]
    stations, ports = simulate_stations(config, cells, poi["points"], index, projection, rng)

    cell_rows = format_cells(cells, poi, size)
    # A separate random stream keeps the grid and station files identical to earlier snapshots.
    route_rng = random.Random(int(config["seed"]) + 1)
    route_cells = build_route_blocks(config, wards, projection, route_rng)
    write_csv(
        output / "route_blocks.csv", ROUTE_FIELDS,
        format_route_blocks(route_cells, projection, float(config["route_division"]["simplify_m"])),
    )
    # Own random stream again, so adding the road layer leaves every other file unchanged.
    road_rows = simulate_road_flows(
        config, projection, index,
        dict(zip((cell["cell_id"] for cell in cells), percentile_rank(infra), strict=True)),
        random.Random(int(config["seed"]) + 2),
    )
    write_csv(output / "route_roads.csv", ROAD_FIELDS, road_rows)
    write_csv(output / "grid_cells.csv", CELL_FIELDS, cell_rows)
    write_csv(output / "gap_stations.csv", STATION_FIELDS, stations)
    write_csv(output / "gap_station_ports.csv", PORT_FIELDS, ports)

    summary = summarize_stations(stations, ports)
    (output / "station_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "analysis_defaults.json").write_text(
        json.dumps(config["analysis_defaults"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(config, config_path, output, cells, stations, ports, len(route_cells))
    return output


def summarize_stations(stations: list[dict], ports: list[dict]) -> dict:
    by_operator: dict[str, dict] = {}
    for station in stations:
        entry = by_operator.setdefault(
            station["operator_id"],
            {
                "operator_name": station["operator_name"],
                "relationship": station["relationship"],
                "stations": 0, "ports": 0, "dc_ports": 0, "ac_ports": 0, "total_power_kw": 0.0,
            },
        )
        entry["stations"] += 1
        entry["ports"] += station["port_count"]
        entry["dc_ports"] += station["dc_port_count"]
        entry["ac_ports"] += station["ac_port_count"]
        entry["total_power_kw"] = round(entry["total_power_kw"] + station["total_power_kw"], 1)
    by_power: Counter = Counter()
    for group in ports:
        label = f"{group['charger_type']} {group['power_kw_per_port']:g} kW"
        by_power[label] += group["port_count"]
    return {
        "stations": len(stations),
        "ports": sum(row["port_count"] for row in stations),
        "total_power_kw": round(sum(row["total_power_kw"] for row in stations), 1),
        "by_operator": by_operator,
        "ports_by_power_class": dict(sorted(by_power.items())),
        "stations_by_ward": dict(Counter(row["unit_name"] for row in stations)),
    }


def write_manifest(
    config: dict, config_path: Path, output: Path, cells: list[dict], stations: list[dict],
    ports: list[dict], segment_count: int,
) -> None:
    root_relative = {name: path for name, path in config["sources"].items()}
    manifest = {
        "snapshot_id": config["snapshot_id"],
        "generator_version": config["generator_version"],
        "prepared_on": config["prepared_on"],
        "seed": config["seed"],
        "counts": {
            "wards": len({cell["unit_id"] for cell in cells}),
            "cells": len(cells),
            "route_blocks": segment_count,
            "stations": len(stations),
            "port_groups": len(ports),
        },
        "data_labels": {
            "poi": "observed_collected_official_source (hcm_poi_official + transport layers)",
            "flow": "synthetic: simulated from distance to centre, traffic-infrastructure density"
                    " and smooth noise; not measured vehicle counts",
            "road_flow": "synthetic: simulated per road from distance to centre, road class,"
                         " traffic-infrastructure density and noise; not measured vehicle counts",
            "rent": "synthetic: simulated from distance to centre and POI density;"
                    " not real listings",
            "stations": "synthetic: simulated own network and competitors; not real inventory",
            "roads": "observed: street network from OpenStreetMap (c) OpenStreetMap contributors,"
                     " ODbL; blocks are the land left between the roads",
            "legal": "unknown for every cell: no legal evidence is collected or simulated",
        },
        "sources": {
            name: {"path": path, "sha256": sha256(ROOT / path)}
            for name, path in root_relative.items()
        },
        "config": {"path": config_path.relative_to(ROOT).as_posix(), "sha256": sha256(config_path)},
        "files": {
            name: sha256(output / name)
            for name in (
                "grid_cells.csv", "route_blocks.csv", "route_roads.csv", "gap_stations.csv",
                "gap_station_ports.csv", "station_summary.json", "analysis_defaults.json",
            )
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dependency-dir", type=Path, help="folder that contains shapely")
    arguments = parser.parse_args(argv)
    if arguments.dependency_dir:
        sys.path.insert(0, str(arguments.dependency_dir.resolve()))
    output = build(arguments.config, arguments.output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
