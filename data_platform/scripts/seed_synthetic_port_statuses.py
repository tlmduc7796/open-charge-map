from __future__ import annotations

from data_platform.config import PACKAGE_ROOT, load_settings
from data_platform.synthetic_port_seed import seed_synthetic_port_statuses
from sqlalchemy import create_engine


def main() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    try:
        counts = seed_synthetic_port_statuses(
            engine, PACKAGE_ROOT / "data" / "runtime" / "station_status.json"
        )
    finally:
        engine.dispose()
    print(
        f"Synthetic runtime seed: {counts['stations']} stations, "
        f"{counts['port_status']} port statuses, "
        f"{counts['station_live_metrics']} station metrics"
    )


if __name__ == "__main__":
    main()
