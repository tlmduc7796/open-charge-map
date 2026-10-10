from __future__ import annotations

import pytest
from data_platform.connection import release_database_url
from sqlalchemy.engine import make_url


def test_release_database_url_uses_configured_compose_host_port(tmp_path) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text(
        "POSTGRES_PASSWORD=secret with spaces\nPOSTGRES_HOST_PORT=5543\n",
        encoding="utf-8",
    )

    url = make_url(release_database_url(env_file))

    assert url.host == "127.0.0.1"
    assert url.port == 5543
    assert url.password == "secret with spaces"
    assert url.database == "smart_ev_data"


def test_release_database_url_uses_default_compose_host_port(tmp_path) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=release-secret\n", encoding="utf-8")

    assert make_url(release_database_url(env_file)).port == 5433


def test_release_database_url_requires_explicit_release_environment(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="release environment file"):
        release_database_url(tmp_path / "missing.env")

    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_HOST_PORT=5543\n", encoding="utf-8")
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        release_database_url(env_file)


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_release_database_url_rejects_invalid_host_port(tmp_path, port: str) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text(
        f"POSTGRES_PASSWORD=release-secret\nPOSTGRES_HOST_PORT={port}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="POSTGRES_HOST_PORT"):
        release_database_url(env_file)


def test_explicit_database_url_overrides_release_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "missing.env"
    configured = "postgresql+psycopg://operator:secret@db.internal:6432/release"
    monkeypatch.setenv("DATA_PLATFORM_DATABASE_URL", configured)

    assert release_database_url(env_file) == configured
