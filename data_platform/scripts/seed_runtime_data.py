from __future__ import annotations

from data_platform.config import PACKAGE_ROOT, load_settings
from data_platform.runtime_seed import seed_runtime_data
from sqlalchemy import create_engine


def main() -> None:
    settings = load_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        counts = seed_runtime_data(
            engine,
            PACKAGE_ROOT / "data" / "runtime" / "planned_arrivals.json",
            PACKAGE_ROOT / "data" / "demo" / "queue_assumptions.json",
        )
    finally:
        engine.dispose()
    print(
        "Runtime seed synchronized: "
        f"{counts['planned_arrivals']} planned arrivals, "
        f"{counts['station_arrival_rates']} station arrival rates, "
        f"{counts['app_config']} app config"
    )


if __name__ == "__main__":
    main()
