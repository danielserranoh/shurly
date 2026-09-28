#!/usr/bin/env python3
"""
Phase 3.12 — write the countries and time zones the profile picker offers
(frontend/src/data/timezones.json), from the `tzdata` package the API validates with
(server/utils/timezones.py).

Run it after upgrading `tzdata`; tests/test_phase312_profile.py fails until you do.

Usage:
    uv run python scripts/generate_timezones.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "frontend" / "src" / "data" / "timezones.json"

sys.path.insert(0, str(ROOT))

from server.utils.timezones import picker_data  # noqa: E402


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(picker_data(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
