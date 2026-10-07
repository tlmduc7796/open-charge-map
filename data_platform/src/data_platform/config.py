from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent


def _resolve_from_package(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PACKAGE_ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    database_url: str
    test_database_url: str | None
    legacy_data_dir: Path
    artifact_dir: Path


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATA_PLATFORM_DATABASE_URL",
            "postgresql+psycopg://smart_ev:smart_ev@127.0.0.1:5433/smart_ev_data",
        ),
        test_database_url=os.getenv("DATA_PLATFORM_TEST_DATABASE_URL") or None,
        legacy_data_dir=_resolve_from_package(
            os.getenv("DATA_PLATFORM_LEGACY_DATA_DIR", "data")
        ),
        artifact_dir=_resolve_from_package(
            os.getenv("DATA_PLATFORM_ARTIFACT_DIR", "artifacts")
        ),
    )
