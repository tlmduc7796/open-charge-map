import json
import shutil
from pathlib import Path

from script.__main__ import SNAPSHOT_NAME, main

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_snapshot.json"


def prepare(tmp_path: Path, user_config: dict | None = None) -> list[str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copyfile(FIXTURE, data_dir / SNAPSHOT_NAME)
    config_path = tmp_path / "simulator.config.json"
    config_path.write_text(
        json.dumps(user_config or {"end_date": "2026-08-07"}), encoding="utf-8"
    )
    return ["--config", str(config_path), "--data-dir", str(data_dir)]


def test_run_writes_outputs_and_passes_validation(tmp_path: Path) -> None:
    assert main([*prepare(tmp_path), "run"]) == 0
    data_dir = tmp_path / "data"
    for name in ("sessions.csv", "ports.csv", "validation_report.md", "run_manifest.json",
                 "debug/arrivals.csv", "debug/queue_log.csv"):
        assert (data_dir / name).is_file(), name
    manifest = json.loads((data_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation"] == "PASS" and manifest["is_synthetic"] is True
    assert manifest["counts"]["sessions"] > 0 and manifest["counts"]["ports"] == 9
    assert "**PASS**" in (data_dir / "validation_report.md").read_text(encoding="utf-8")


def test_same_inputs_give_identical_outputs(tmp_path: Path) -> None:
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        root.mkdir()
        assert main([*prepare(root), "run"]) == 0
    manifests = [
        json.loads((root / "data" / "run_manifest.json").read_text(encoding="utf-8"))
        for root in roots
    ]
    assert manifests[0] == manifests[1]  # includes sha256 of sessions.csv, snapshot and config


def test_bad_config_exits_with_an_error_not_a_traceback(tmp_path: Path, capsys) -> None:
    args = prepare(tmp_path, {"sed": 1})
    assert main([*args, "run"]) == 2
    assert "sed" in capsys.readouterr().err


def test_run_without_snapshot_tells_the_user_to_pull(tmp_path: Path, capsys) -> None:
    args = ["--config", str(tmp_path / "c.json"), "--data-dir", str(tmp_path / "empty")]
    assert main([*args, "run"]) == 2
    assert "pull" in capsys.readouterr().err


def test_pull_creates_a_config_listing_every_station_and_keeps_an_existing_one(
    tmp_path: Path, monkeypatch
) -> None:
    from script import db

    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(db, "pull_snapshot", lambda url: snapshot)
    config_path = tmp_path / "simulator.config.json"
    args = ["--config", str(config_path), "--data-dir", str(tmp_path / "data"), "pull"]

    assert main(args) == 0
    created = json.loads(config_path.read_text(encoding="utf-8"))
    assert created["station_factor"] == {s["station_id"]: 1.0 for s in snapshot["stations"]}

    config_path.write_text(json.dumps({"seed": 5}), encoding="utf-8")
    assert main(args) == 0
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"seed": 5}
