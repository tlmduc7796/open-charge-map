from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_gap_snapshot_lists_cells_and_simulated_stations_with_power_detail() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/planning/gap/snapshot", params={"division": "grid"})
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == "hcmc-nine-wards-gap-v1"
    assert body["division"] == "grid"
    assert all(cell["bounds"] and cell["road_name"] is None for cell in body["cells"])
    assert len(body["cells"]) > 100
    assert len({cell["unit_id"] for cell in body["cells"]}) == 9
    assert all(cell["rent_kvnd_m2_month"] is not None for cell in body["cells"])
    assert "synthetic" in body["data_labels"]["flow"]
    assert "synthetic" in body["data_labels"]["rent"]
    assert "synthetic" in body["data_labels"]["stations"]
    assert body["data_labels"]["poi"].startswith("observed")

    stations = body["stations"]
    operators = {station["operator_id"] for station in stations}
    assert operators == {"OWN", "CMP-A", "CMP-B", "CMP-C"}
    assert {s["relationship"] for s in stations if s["operator_id"] == "OWN"} == {"OWNED"}
    assert {s["relationship"] for s in stations if s["operator_id"] != "OWN"} == {"OTHER_NETWORK"}
    for station in stations:
        assert station["data_status"] == "synthetic"
        assert station["port_count"] == sum(g["port_count"] for g in station["port_groups"])
        assert station["total_power_kw"] == round(
            sum(g["port_count"] * g["power_kw_per_port"] for g in station["port_groups"]), 1
        )
        assert station["max_port_power_kw"] == max(
            g["power_kw_per_port"] for g in station["port_groups"]
        )
    summary = body["station_summary"]
    assert summary["stations"] == len(stations)
    assert summary["ports"] == sum(s["port_count"] for s in stations)
    assert sum(o["stations"] for o in summary["by_operator"].values()) == len(stations)


def test_gap_snapshot_carries_simulated_flow_for_every_road() -> None:
    with TestClient(app) as client:
        body = client.get("/api/v1/planning/gap/snapshot").json()
    roads = body["roads"]
    assert len(roads) > 1000
    assert all(250 <= road["flow_vph"] <= 4250 for road in roads)
    assert all(len(road["coordinates"]) >= 2 for road in roads)
    assert "synthetic" in body["data_labels"]["road_flow"]


def test_gap_run_defaults_return_ranked_candidates_with_unknown_legal_status() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/planning/gap/run", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["params"]["w_flow"] == 0.5
    assert body["params"]["lambda_m"] == 1000
    candidates = body["candidates"]
    assert body["params"]["top_n"] == 5
    assert len(candidates) == 5
    scores = [candidate["score"] for candidate in candidates]
    assert scores == sorted(scores, reverse=True)
    for candidate in candidates:
        assert candidate["legal_status"] == "unknown"
        assert candidate["pending_legal_checks"]
        nearby = candidate["nearby"]
        assert nearby["cell_count"] >= 1
        assert 0 <= nearby["flow_percentile"] <= 100
        assert nearby["flow_max_vph"] >= nearby["flow_mean_vph"] > 0
        assert nearby["rent_min_kvnd"] <= nearby["rent_mean_kvnd"] <= nearby["rent_max_kvnd"]
        expected_gap = candidate["demand"] / (1 + candidate["supply"])
        assert abs(candidate["gap"] - expected_gap) < 1e-9
    assert len(body["cells"]) == body["summary"]["cell_count"]
    assert any("mô phỏng" in warning for warning in body["warnings"])


def test_gap_run_responds_to_parameters_and_rejects_invalid_ones() -> None:
    with TestClient(app) as client:
        base = client.post("/api/v1/planning/gap/run", json={"with_sensitivity": False}).json()
        no_rent = client.post(
            "/api/v1/planning/gap/run", json={"rent_mode": "none", "with_sensitivity": False}
        ).json()
        filtered = client.post(
            "/api/v1/planning/gap/run",
            json={"rent_mode": "filter", "rent_max_kvnd": 250, "with_sensitivity": False},
        ).json()
        invalid = client.post("/api/v1/planning/gap/run", json={"w_flow": 1.5})
        unknown_snapshot = client.post("/api/v1/planning/gap/run", json={"snapshot_id": "other"})
    base_ids = [c["cell_id"] for c in base["candidates"]]
    assert base_ids != [c["cell_id"] for c in no_rent["candidates"]]
    assert filtered["summary"]["excluded_by_reason"]["rent_above_limit"] > 0
    assert all(c["rent_kvnd_m2_month"] <= 250 for c in filtered["candidates"])
    assert invalid.status_code == 422
    assert unknown_snapshot.status_code == 503


def test_gap_snapshot_defaults_to_street_blocks_bounded_by_roads() -> None:
    with TestClient(app) as client:
        body = client.get("/api/v1/planning/gap/snapshot").json()
        grid = client.get("/api/v1/planning/gap/snapshot", params={"division": "grid"}).json()
        invalid = client.get("/api/v1/planning/gap/snapshot", params={"division": "hex"})
    assert body["division"] == "route"
    assert len(body["cells"]) > 300
    assert len({cell["unit_id"] for cell in body["cells"]}) == 9
    assert all(cell["cell_id"].startswith("B") for cell in body["cells"])
    assert all(cell["polygon"] is None for cell in grid["cells"])
    shapes = set()
    for cell in body["cells"]:
        ring = cell["polygon"][0]
        assert len(ring) >= 4 and ring[0] == ring[-1]  # a closed outline, not a box
        lat_min, lon_min, lat_max, lon_max = cell["bounds"]
        slack = 1e-5  # outlines are simplified and rounded after the box is taken
        assert all(
            lat_min - slack <= lat <= lat_max + slack and lon_min - slack <= lon <= lon_max + slack
            for lat, lon in ring
        )
        shapes.add(len(ring))
        assert cell["area_m2"] >= 1500
        assert isinstance(cell["subdivided"], bool)
        assert cell["rent_kvnd_m2_month"] is not None
    assert len(shapes) > 3  # blocks have different shapes
    named = [cell for cell in body["cells"] if cell["road_names"]]
    assert len(named) > 0.9 * len(body["cells"])
    assert all(1 <= len(cell["road_names"]) <= 3 for cell in named)
    assert any(cell["subdivided"] for cell in body["cells"])
    assert body["stations"] == grid["stations"]
    assert invalid.status_code == 422


def test_gap_run_on_street_blocks_names_the_bounding_roads_and_differs_from_the_grid() -> None:
    with TestClient(app) as client:
        route = client.post("/api/v1/planning/gap/run", json={"with_sensitivity": False}).json()
        grid = client.post(
            "/api/v1/planning/gap/run", json={"division": "grid", "with_sensitivity": False}
        ).json()
        snapshot = client.get("/api/v1/planning/gap/snapshot").json()
    segments = {c["cell_id"] for c in snapshot["cells"]}
    assert route["params"]["division"] == "route"
    assert route["summary"]["cell_count"] != grid["summary"]["cell_count"]
    assert route["candidates"]
    for candidate in route["candidates"]:
        assert candidate["cell_id"] in segments
        assert candidate["road_name"]
        assert candidate["legal_status"] == "unknown"
    assert all(candidate["road_name"] is None for candidate in grid["candidates"])
    assert {cell["cell_id"] for cell in route["cells"]} == segments
