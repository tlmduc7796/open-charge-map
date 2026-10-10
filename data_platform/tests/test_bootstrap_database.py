from __future__ import annotations

import runpy
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

from alembic.script import ScriptDirectory


def test_bootstrap_compose_commands_use_explicit_release_files(
    monkeypatch, tmp_path: Path
) -> None:
    module = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "bootstrap_database.py"),
        run_name="bootstrap_database_module",
    )
    run = Mock(return_value=CompletedProcess(args=[], returncode=0, stdout=""))
    monkeypatch.setattr(module["subprocess"], "run", run)
    env_file = tmp_path / ".env.release"
    compose_file = tmp_path / "compose.release.yaml"

    module["_docker"](
        "up",
        "-d",
        "postgres",
        env_file=env_file,
        compose_file=compose_file,
    )

    command = run.call_args.args[0]
    assert command[:6] == [
        "docker",
        "compose",
        "--env-file",
        str(env_file.resolve()),
        "-f",
        str(compose_file.resolve()),
    ]
    assert command[6:] == ["up", "-d", "postgres"]


def test_bootstrap_defaults_to_local_database_compose(monkeypatch) -> None:
    module = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "bootstrap_database.py"),
        run_name="bootstrap_database_module",
    )
    run = Mock(return_value=CompletedProcess(args=[], returncode=0, stdout=""))
    monkeypatch.setattr(module["subprocess"], "run", run)

    module["_docker"](
        "up",
        "-d",
        "postgres",
        env_file=None,
        compose_file=module["DEFAULT_COMPOSE_FILE"],
    )

    command = run.call_args.args[0]
    assert command[:4] == [
        "docker",
        "compose",
        "-f",
        str((Path(__file__).parents[1] / "compose.yaml").resolve()),
    ]
    assert command[4:] == ["up", "-d", "postgres"]


def test_bootstrap_migration_location_is_independent_of_current_directory(
    monkeypatch,
) -> None:
    module = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "bootstrap_database.py"),
        run_name="bootstrap_database_module",
    )
    upgrade = Mock()
    monkeypatch.setattr(module["command"], "upgrade", upgrade)

    module["_migrate"]("postgresql+psycopg://user:password@localhost/db")

    config = upgrade.call_args.args[0]
    script_directory = ScriptDirectory.from_config(config)
    assert Path(script_directory.dir) == Path(__file__).parents[1] / "migrations"
