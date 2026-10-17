from __future__ import annotations

import math

import pytest

from backend.app.planning.gap_analysis import (
    GapCell,
    GapParams,
    GapStation,
    compute_cells,
    distance_matrix,
    haversine_m,
    normalize,
    run_gap_analysis,
    select_candidates,
)

LAT0, LON0 = 10.78, 106.69
M_PER_DEG_LAT = 111_195.0  # matches haversine with the earth radius used by the engine


def cell(
    cell_id: str, north_m: float, *, flow: float = 100.0, poi: float = 10.0,
    rent: float | None = 200.0,
) -> GapCell:
    return GapCell(
        cell_id=cell_id, unit_id="u", unit_name="Phường U", lat=LAT0 + north_m / M_PER_DEG_LAT,
        lon=LON0, poi_count=poi, poi_weighted=poi, flow_vph=flow, rent_kvnd_m2_month=rent,
    )


def station(
    station_id: str, north_m: float, *, ports: int = 4, own: bool = False, power: float = 60.0
) -> GapStation:
    return GapStation(
        station_id=station_id, operator_id="OWN" if own else "CMP",
        operator_name="Mạng của mình" if own else "Đối thủ",
        relationship="OWNED" if own else "OTHER_NETWORK", unit_id="u", unit_name="Phường U",
        lat=LAT0 + north_m / M_PER_DEG_LAT, lon=LON0, site_type="parking", opening_hours="24/7",
        port_count=ports, dc_port_count=ports, ac_port_count=0, total_power_kw=ports * power,
        max_port_power_kw=power,
    )


def params(**overrides) -> GapParams:
    base = {"rent_mode": "none", "min_demand": 0.0}
    return GapParams(**{**base, **overrides})


def rows_by_id(cells, stations, p):
    rows = compute_cells(cells, stations, distance_matrix(cells, stations), p)
    return {row["cell_id"]: row for row in rows}


def test_normalize_minmax_percentile_and_constant_series() -> None:
    assert normalize([10, 20, 30], "minmax") == [0.0, 0.5, 1.0]
    assert normalize([5, 5, 5], "minmax") == [0.0, 0.0, 0.0]
    assert normalize([1, 2, 2, 9], "percentile") == [0.0, 0.5, 0.5, 1.0]
    assert normalize([], "minmax") == []


def test_gap_matches_the_plan_formula() -> None:
    cells = [cell("A", 0, flow=100, poi=0), cell("B", 2000, flow=300, poi=40),
             cell("C", 4000, flow=500, poi=20)]
    stations = [station("S1", 0, ports=6, own=True), station("S2", 4000, ports=2)]
    p = params(w_flow=0.4, lambda_m=1000.0)
    rows = rows_by_id(cells, stations, p)

    # B: flow_norm 0.5, poi_norm 1.0
    d_b = 0.4 * 0.5 + 0.6 * 1.0
    d1 = haversine_m(cells[1].lat, cells[1].lon, stations[0].lat, stations[0].lon)
    d2 = haversine_m(cells[1].lat, cells[1].lon, stations[1].lat, stations[1].lon)
    cung_b = 6 * math.exp(-d1 / 1000) + 2 * math.exp(-d2 / 1000)
    assert rows["B"]["demand"] == pytest.approx(d_b)
    assert rows["B"]["supply"] == pytest.approx(cung_b)
    assert rows["B"]["supply_own"] == pytest.approx(6 * math.exp(-d1 / 1000))
    assert rows["B"]["supply_competitor"] == pytest.approx(2 * math.exp(-d2 / 1000))
    assert rows["B"]["gap"] == pytest.approx(d_b / (1 + cung_b))
    assert rows["B"]["score"] == pytest.approx(rows["B"]["gap"])


def test_competitors_and_own_stations_both_count_as_supply() -> None:
    cells = [cell("A", 0), cell("B", 5000)]
    own_only = rows_by_id(cells, [station("S", 0, own=True)], params())["A"]["supply"]
    competitor_only = rows_by_id(cells, [station("S", 0, own=False)], params())["A"]["supply"]
    assert own_only == pytest.approx(competitor_only)
    assert own_only > 0


def test_supply_basis_power_uses_reference_kw() -> None:
    cells = [cell("A", 0)]
    s = [station("S", 0, ports=2, power=120.0)]
    by_ports = rows_by_id(cells, s, params(supply_basis="ports"))["A"]["supply"]
    by_power = rows_by_id(cells, s, params(supply_basis="power", reference_power_kw=60.0))["A"][
        "supply"
    ]
    assert by_ports == pytest.approx(2.0, rel=0.01)
    assert by_power == pytest.approx(4.0, rel=0.01)


def test_rent_divide_uses_normalised_rent_plus_epsilon() -> None:
    cells = [cell("A", 0, rent=100), cell("B", 3000, rent=300), cell("C", 6000, rent=500)]
    stations = [station("S", 20000)]
    rows = rows_by_id(cells, stations, params(rent_mode="divide", epsilon=0.1))
    assert rows["B"]["rent_norm"] == pytest.approx(0.5)
    assert rows["B"]["score"] == pytest.approx(rows["B"]["gap"] / 0.6)
    assert rows["A"]["score"] == pytest.approx(rows["A"]["gap"] / 0.1)


def test_rent_filter_excludes_cells_above_the_limit_and_ranks_the_rest() -> None:
    cells = [cell("A", 0, flow=500, poi=50, rent=900), cell("B", 3000, flow=100, poi=10, rent=200)]
    rows = rows_by_id(cells, [station("S", 20000)], params(rent_mode="filter", rent_max_kvnd=600))
    assert rows["A"]["excluded_reason"] == "rent_above_limit"
    assert rows["A"]["rank"] is None
    assert rows["B"]["rank"] == 1


def test_missing_rent_is_not_treated_as_zero() -> None:
    cells = [cell("A", 0, rent=None), cell("B", 3000, rent=300), cell("C", 6000, rent=100)]
    rows = rows_by_id(cells, [station("S", 20000)], params(rent_mode="divide"))
    assert rows["A"]["rent_missing"] is True
    assert rows["A"]["rent_norm"] is None
    assert rows["A"]["score"] == pytest.approx(rows["A"]["gap"])
    filtered = rows_by_id(cells, [station("S", 20000)], params(rent_mode="filter"))
    assert filtered["A"]["excluded_reason"] is None


def test_own_station_nearby_flags_or_excludes_but_competitors_do_not() -> None:
    cells = [cell("A", 0), cell("B", 3000)]
    near_own = [station("S", 300, own=True)]
    flagged = rows_by_id(cells, near_own, params(own_min_distance_m=500, own_mode="flag"))
    assert flagged["A"]["own_overlap"] is True and flagged["A"]["rank"] is not None
    assert flagged["B"]["own_overlap"] is False
    excluded = rows_by_id(cells, near_own, params(own_min_distance_m=500, own_mode="exclude"))
    assert excluded["A"]["excluded_reason"] == "own_station_nearby"
    rival = rows_by_id(cells, [station("R", 300, own=False)], params(own_min_distance_m=500))
    assert rival["A"]["own_overlap"] is False
    assert rival["A"]["d_own_m"] is None


def test_demand_floor_drops_cells_with_almost_no_demand() -> None:
    cells = [cell("A", 0, flow=100, poi=0), cell("B", 3000, flow=500, poi=50)]
    rows = rows_by_id(cells, [station("S", 20000)], params(min_demand=0.2))
    assert rows["A"]["excluded_reason"] == "demand_below_floor"
    assert rows["B"]["rank"] == 1


def test_candidates_keep_minimum_separation_and_cluster_neighbours() -> None:
    # A and B are 300 m apart and both strong; C is far away and weaker.
    cells = [cell("A", 0, flow=500, poi=50), cell("B", 300, flow=490, poi=49),
             cell("C", 5000, flow=300, poi=30), cell("D", 9000, flow=100, poi=5)]
    p = params(top_n=3, min_separation_m=1000)
    far = [station("S", 30000)]
    rows = compute_cells(cells, far, distance_matrix(cells, far), p)
    picked = select_candidates(cells, rows, p)
    assert [c["cell_id"] for c in picked] == ["A", "C", "D"]
    assert picked[0]["cluster_cell_ids"] == ["B"]


def test_weight_changes_which_signal_drives_the_ranking() -> None:
    cells = [cell("flowy", 0, flow=900, poi=0), cell("poiy", 5000, flow=100, poi=90)]
    stations = [station("S", 50000)]
    assert rows_by_id(cells, stations, params(w_flow=1.0))["flowy"]["rank"] == 1
    assert rows_by_id(cells, stations, params(w_flow=0.0))["poiy"]["rank"] == 1


def test_run_returns_unknown_legal_status_and_stability() -> None:
    cells = [cell(f"C{i}", i * 1500, flow=100 + i * 40, poi=10 + i * 3) for i in range(8)]
    stations = [station("S", 0, own=True), station("R", 9000)]
    result = run_gap_analysis(cells, stations, params(top_n=3, min_separation_m=1000))
    assert 1 <= len(result["candidates"]) <= 3
    assert result["summary"]["sensitivity_variant_count"] == 9
    for candidate in result["candidates"]:
        assert candidate["legal_status"] == "unknown"
        assert candidate["pending_legal_checks"]
        assert 0.0 <= candidate["stability"] <= 1.0
        assert candidate["nearest_own"]["station_id"] == "S"
        assert candidate["nearest_competitor"]["station_id"] == "R"
        assert len(candidate["top_supply_stations"]) == 2
    skipped = run_gap_analysis(cells, stations, params(), with_sensitivity=False)
    assert skipped["summary"]["sensitivity_variant_count"] == 0
    assert skipped["candidates"][0]["stability"] is None
