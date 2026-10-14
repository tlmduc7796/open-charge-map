from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import geo_features as gf


def test_build_station_geo_table_covers_all_37_real_stations():
    table = gf.build_station_geo_table()
    sites = gf.load_station_sites()

    assert len(table) == 37
    assert set(table.index) == set(sites["station_id"])
    assert list(table.columns) == list(gf.GEO_COLUMNS) + [gf.NEAREST_STATION_ID_COLUMN]
    assert not table[list(gf.GEO_COLUMNS)].isna().any().any()
    # 37 trạm thật -> luôn có một trạm khác, không tự tham chiếu chính nó.
    assert (table[gf.NEAREST_STATION_ID_COLUMN] != table.index).all()
    assert table[gf.NEAREST_STATION_ID_COLUMN].isin(table.index).all()


def test_poi_and_neighbor_columns_are_non_negative():
    table = gf.build_station_geo_table()
    for column in gf.POI_COLUMNS + gf.NEIGHBOR_COLUMNS:
        assert (table[column] >= 0).all(), column
    assert (table["ward_population"] > 0).all()


def test_poi_category_shares_sum_to_at_most_the_total():
    table = gf.build_station_geo_table()
    category_sum = sum(table[f"poi_weighted_{group}_r300"] for group in gf.CATEGORY_GROUPS)
    total = table["poi_weighted_count_r300"]
    np.testing.assert_allclose(category_sum.to_numpy(), total.to_numpy())


def test_nearest_station_is_mutual_and_zero_distance_to_self():
    sites = gf.load_station_sites()
    sites = sites.iloc[:2].reset_index(drop=True)  # cặp 2 trạm thật gần nhau nhất trong danh sách
    out = gf._neighbor_features(sites)
    assert out[gf.NEAREST_STATION_ID_COLUMN].iloc[0] == sites["station_id"].iloc[1]
    assert out[gf.NEAREST_STATION_ID_COLUMN].iloc[1] == sites["station_id"].iloc[0]
    assert (out["nearest_other_station_m"] > 0).all()


def test_single_station_self_references_as_nearest():
    sites = gf.load_station_sites().iloc[:1].reset_index(drop=True)
    out = gf._neighbor_features(sites)
    assert out[gf.NEAREST_STATION_ID_COLUMN].iloc[0] == sites["station_id"].iloc[0]
    assert out["nearest_other_station_m"].iloc[0] == 0.0
    assert out["n_stations_within_300m"].iloc[0] == 0.0


def test_haversine_matches_known_distance():
    # Hà Nội -> TP.HCM theo đường chim bay, dùng để chéo-kiểm công thức haversine (~1140-1165km).
    distance_m = gf._haversine_m(
        np.array([21.0285]), np.array([105.8542]), np.array([10.7769]), np.array([106.7009])
    )
    assert 1_140_000 < distance_m[0] < 1_165_000


def test_load_poi_rejects_unknown_category_group(tmp_path):
    geojson_path = tmp_path / "poi.geojson"
    weights_path = tmp_path / "weights.csv"
    geojson_path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"feature_id":"x1","category_group":"not_a_real_group"},'
        '"geometry":{"type":"Point","coordinates":[106.7,10.78]}}]}',
        encoding="utf-8",
    )
    pd.DataFrame({"feature_id": ["x1"], "modeling_weight": [1.0]}).to_csv(
        weights_path, index=False
    )
    with pytest.raises(ValueError, match="unknown POI category_group"):
        gf.load_poi(geojson_path, weights_path)
