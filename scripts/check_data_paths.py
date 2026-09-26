#!/usr/bin/env python3
"""Check that all Phase 0–1 inputs required by the application are present."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import load_settings


def main() -> int:
    settings = load_settings()
    missing = [path for path in settings.required_data_paths() if not path.is_file()]
    if missing:
        print("Missing required data paths:")
        for path in missing:
            print(f"- {path}")
        return 1
    print(f"Data paths: PASS ({len(settings.required_data_paths())} required files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
