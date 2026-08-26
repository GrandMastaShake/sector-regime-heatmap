"""Regenerate config/sector_baskets.yaml from the watchlist CSV.

The CSV is the source of truth. The YAML is a derived convenience file ordered
by descending market cap. Run this after any watchlist change, then commit both.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "config/watchlist_110.csv"
OUT = ROOT / "config/sector_baskets.yaml"

HEADER = [
    "version: 2",
    "# GENERATED from config/watchlist_110.csv by scripts/sync_baskets.py. Do not hand-edit.",
    "# Order is descending market cap as of the watchlist snapshot, so index 0-1 are",
    "# the two largest names and top_two_contribution has a defined referent.",
    "# scripts/preflight.py fails if this file and the CSV disagree.",
]


def build() -> str:
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    by: dict[str, list] = {}
    for r in rows:
        r["mc"] = float(r["MarketCap_USD_Billions"])
        by.setdefault(r["Sector"], []).append(r)
    lines = list(HEADER)
    for s in sorted(by):
        tickers = [r["Ticker"] for r in sorted(by[s], key=lambda r: -r["mc"])]
        lines.append(s + ": [" + ", ".join(tickers) + "]")
    return "\n".join(lines) + "\n"


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8")
        if current != text:
            print("sector_baskets.yaml is stale. Run: python scripts/sync_baskets.py")
            return 1
        print("sector_baskets.yaml is in sync with the watchlist CSV.")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print("Wrote " + str(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
