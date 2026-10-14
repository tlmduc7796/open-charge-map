"""Bảng đặc trưng địa lý tĩnh theo trạm (37 trạm `EVC-*`), dùng cho mô hình occupancy.

Nguồn dữ liệu: `data_platform/station_planning/demo_hcmc_v3/` (existing_sites.csv,
population.csv, context_poi.geojson, poi_model_weights.csv) — hiện chỉ phục vụ quy hoạch vị
trí trạm mới (`data_plan.py`), chưa nối vào pipeline occupancy. Không dùng road/giao thông
(không có dữ liệu trong repo) và không dùng demand_nodes/demand_cells (dữ liệu nhu cầu ở đó
là synthetic, không thực tế).

    python -m ml.geo_features            # in bảng ra stdout, chạy từ gốc repo
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANNING_DIR = REPO_ROOT / "data_platform" / "station_planning" / "demo_hcmc_v3"
EXISTING_SITES_CSV = PLANNING_DIR / "existing_sites.csv"
POPULATION_CSV = PLANNING_DIR / "population.csv"
POI_GEOJSON = PLANNING_DIR / "context_poi.geojson"
POI_WEIGHTS_CSV = PLANNING_DIR / "poi_model_weights.csv"
# existing_sites.csv.site_id (vd. "EVC-145") == stations.code trong DB, nhưng
# station_occupancy_5m (và mọi bảng runtime khác) dùng stations.id (UUID) làm station_id —
# cần map code -> id để bảng geo join đúng với pipeline occupancy.
STATIONS_SQL = REPO_ROOT / "database" / "data" / "catalog" / "stations.sql"
_STATION_ROW_RE = re.compile(
    r"\(\s*'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'\s*,\s*'([^']+)'"
)

RADIUS_M = 300.0
EARTH_RADIUS_M = 6_371_000.0

# 7 category_group có trong context_poi.geojson (demo_hcmc_v3); cố định để cột đầu ra ổn định
# không phụ thuộc dữ liệu POI hiện có trong file.
CATEGORY_GROUPS = (
    "healthcare",
    "education",
    "retail_financial",
    "culture_leisure_hospitality",
    "public_buildings",
    "business",
    "utility",
)

POI_COLUMNS = ("poi_weighted_count_r300",) + tuple(
    f"poi_weighted_{group}_r300" for group in CATEGORY_GROUPS
)
NEIGHBOR_COLUMNS = (
    "n_stations_within_300m",
    "competing_ports_within_300m",
    "nearest_other_station_m",
    "nearest_station_total_ports",
)
# Đặc trưng của model: POI theo trọng số + dân số phường + tác động trạm lân cận (tĩnh).
GEO_COLUMNS = POI_COLUMNS + ("ward_population",) + NEIGHBOR_COLUMNS

# Không phải đặc trưng của model: build_dataset.py dùng để join occupancy của trạm gần nhất
# tại cùng t_last (đặc trưng spatial-lag theo thời gian, xem ml/features.py::SPATIAL_LAG_COLUMNS).
NEAREST_STATION_ID_COLUMN = "nearest_station_id"


def _haversine_m(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    lat1, lon1, lat2, lon2 = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def load_station_sites(path: Path = EXISTING_SITES_CSV) -> pd.DataFrame:
    """`station_id, lat, lon, total_ports, unit_id` — một dòng mỗi trạm hiện có."""
    raw = pd.read_csv(path, encoding="utf-8-sig")
    required = {"site_id", "lat", "lon", "port_count", "unit_id"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"existing_sites.csv misses columns: {sorted(missing)}")
    sites = raw.loc[:, ["site_id", "lat", "lon", "port_count", "unit_id"]].rename(
        columns={"site_id": "station_id", "port_count": "total_ports"}
    )
    if sites["station_id"].duplicated().any():
        raise ValueError("duplicate site_id in existing_sites.csv")
    if sites[["lat", "lon"]].isna().any().any():
        raise ValueError("existing_sites.csv has missing lat/lon")
    return sites.reset_index(drop=True)


def load_population(path: Path = POPULATION_CSV) -> pd.Series:
    """`unit_id -> population` (dân số phường)."""
    raw = pd.read_csv(path, encoding="utf-8-sig")
    missing = {"unit_id", "population"} - set(raw.columns)
    if missing:
        raise ValueError(f"population.csv misses columns: {sorted(missing)}")
    if raw["unit_id"].duplicated().any():
        raise ValueError("duplicate unit_id in population.csv")
    return raw.set_index("unit_id")["population"].astype(float)


def load_station_code_to_id(path: Path = STATIONS_SQL) -> dict[str, str]:
    """`stations.code` ("EVC-145") -> `stations.id` (UUID), đọc từ seed SQL tĩnh.

    Không chạy SQL/kết nối DB: `id` rồi `code` là hai cột `'...'` đầu tiên của mỗi dòng
    `INSERT INTO public.stations (id, code, ...) VALUES (...)` — regex chỉ cần khớp phần đầu
    dòng, nên các cột sau (địa chỉ có thể chứa dấu phẩy) không ảnh hưởng.
    """
    text = path.read_text(encoding="utf-8")
    pairs = _STATION_ROW_RE.findall(text)
    if not pairs:
        raise ValueError(f"no station rows found in {path}")
    mapping = {code: station_id for station_id, code in pairs}
    if len(mapping) != len(pairs):
        raise ValueError("duplicate station code in stations.sql")
    return mapping


def load_poi(
    geojson_path: Path = POI_GEOJSON, weights_path: Path = POI_WEIGHTS_CSV
) -> pd.DataFrame:
    """`feature_id, category_group, lat, lon, modeling_weight` — một dòng mỗi POI."""
    with geojson_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    rows = [
        {
            "feature_id": feature["properties"]["feature_id"],
            "category_group": feature["properties"]["category_group"],
            "lon": feature["geometry"]["coordinates"][0],
            "lat": feature["geometry"]["coordinates"][1],
        }
        for feature in data["features"]
    ]
    poi = pd.DataFrame(rows)
    unknown = set(poi["category_group"]) - set(CATEGORY_GROUPS)
    if unknown:
        raise ValueError(f"unknown POI category_group(s): {sorted(unknown)}")

    weights = pd.read_csv(weights_path, encoding="utf-8-sig")
    missing = {"feature_id", "modeling_weight"} - set(weights.columns)
    if missing:
        raise ValueError(f"poi_model_weights.csv misses columns: {sorted(missing)}")
    weight_by_feature = weights.set_index("feature_id")["modeling_weight"].astype(float)

    poi = poi.join(weight_by_feature.rename("modeling_weight"), on="feature_id")
    if poi["modeling_weight"].isna().any():
        raise ValueError("POI feature(s) missing a modeling_weight")
    return poi


def _poi_features(sites: pd.DataFrame, poi: pd.DataFrame) -> pd.DataFrame:
    """Tổng trọng số POI (chung và theo từng category_group) trong bán kính `RADIUS_M`."""
    distance_m = _haversine_m(
        sites["lat"].to_numpy()[:, None],
        sites["lon"].to_numpy()[:, None],
        poi["lat"].to_numpy()[None, :],
        poi["lon"].to_numpy()[None, :],
    )
    within = distance_m <= RADIUS_M
    weight = poi["modeling_weight"].to_numpy()[None, :]
    weighted_within = np.where(within, weight, 0.0)

    out = pd.DataFrame(index=pd.Index(sites["station_id"].to_numpy(), name="station_id"))
    out["poi_weighted_count_r300"] = weighted_within.sum(axis=1)
    category = poi["category_group"].to_numpy()[None, :]
    for group in CATEGORY_GROUPS:
        out[f"poi_weighted_{group}_r300"] = np.where(category == group, weighted_within, 0.0).sum(
            axis=1
        )
    return out


def _neighbor_features(sites: pd.DataFrame) -> pd.DataFrame:
    """Số trạm + tổng cổng trong `RADIUS_M`, và quy mô/khoảng cách tới trạm gần nhất.

    Chỉ một trạm (không có trạm khác) thì tự tham chiếu chính nó (khoảng cách 0) — không xảy
    ra với 37 trạm thật, nhưng là quy ước hợp lý cho trường hợp thoái hoá này.
    """
    lat, lon = sites["lat"].to_numpy(), sites["lon"].to_numpy()
    n = len(sites)
    distance_m = _haversine_m(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    np.fill_diagonal(distance_m, np.inf)  # chính trạm đó không tính là "trạm khác"
    total_ports = sites["total_ports"].to_numpy(dtype=float)
    station_ids = sites["station_id"].to_numpy()

    within = distance_m <= RADIUS_M
    out = pd.DataFrame(index=pd.Index(station_ids, name="station_id"))
    out["n_stations_within_300m"] = within.sum(axis=1).astype(float)
    out["competing_ports_within_300m"] = np.where(within, total_ports[None, :], 0.0).sum(axis=1)

    if n > 1:
        nearest_index = distance_m.argmin(axis=1)
        out["nearest_other_station_m"] = distance_m[np.arange(n), nearest_index]
    else:
        nearest_index = np.arange(n)
        out["nearest_other_station_m"] = np.zeros(n)
    out["nearest_station_total_ports"] = total_ports[nearest_index]
    out[NEAREST_STATION_ID_COLUMN] = station_ids[nearest_index]
    return out


def build_station_geo_table(
    sites_path: Path = EXISTING_SITES_CSV,
    population_path: Path = POPULATION_CSV,
    poi_geojson_path: Path = POI_GEOJSON,
    poi_weights_path: Path = POI_WEIGHTS_CSV,
) -> pd.DataFrame:
    """Một dòng mỗi trạm: `GEO_COLUMNS` + `NEAREST_STATION_ID_COLUMN`.

    Chỉ mục là `site_id`/`stations.code` ("EVC-145") — giống `station_id` dùng xuyên suốt tầng
    domain của backend (`backend/app/catalog_repository.py` luôn trả `station_id=row["code"]`).
    `stations.id` (UUID) chỉ là khoá nội bộ của DB, không lộ ra tầng domain/API — xem
    `load_station_code_to_id` nếu cần quy đổi (vd. khi khớp với `station_occupancy_5m` thô,
    bảng này dùng UUID của DB làm `station_id`).
    """
    sites = load_station_sites(sites_path)
    population = load_population(population_path)
    poi = load_poi(poi_geojson_path, poi_weights_path)

    ward_population = sites.set_index("station_id")["unit_id"].map(population)
    if ward_population.isna().any():
        missing = ward_population[ward_population.isna()].index.tolist()
        raise ValueError(f"no population found for ward of station(s): {missing}")
    ward_population.name = "ward_population"

    table = _poi_features(sites, poi).join(ward_population).join(_neighbor_features(sites))
    return table.loc[:, list(GEO_COLUMNS) + [NEAREST_STATION_ID_COLUMN]]


def main() -> int:
    table = build_station_geo_table()
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(table)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
