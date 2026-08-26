"""Cross-check the price panel against an independent fundamentals snapshot.

Two sources that disagree in a predictable way are a validator. This compares
the committed weekly panel against the dated fundamentals snapshot and reports
divergences above a threshold.

Ordinary drift is expected: the snapshot is a live screener pull taken on a
different session than the Friday close, so a couple of percent is normal.
What this catches is the other kind. On 2026-08-21 it flags AVB at 179 percent
-- the panel carried a zero-volume close of 65.9005 against a real price of
184.06 -- an order of magnitude clear of everything else.

Advisory by design. It reports and does not fail the build, because the
snapshot is price-only and the panel is total-return adjusted; on older dates
the two legitimately diverge by accumulated dividend yield.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Above this, report. Below it, ordinary session drift.
REPORT_PCT = 2.0

# Above this, treat as a probable bad bar rather than drift.
SUSPECT_PCT = 25.0


def load_panel_week(panel: Path, as_of: str) -> dict:
    corrected = panel / (as_of + ".corrected.json")
    path = corrected if corrected.is_file() else panel / (as_of + ".json")
    if not path.is_file():
        raise FileNotFoundError("No panel file for " + as_of)
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--as-of", required=True)
    a = p.parse_args(argv)

    week = load_panel_week(a.panel, a.as_of)
    series = week["series"]
    rows = list(csv.DictReader(a.snapshot.open(encoding="utf-8")))

    compared, diffs, suspects = 0, [], []
    for r in rows:
        t = r["Ticker"]
        bar = series.get(t)
        if not bar or not bar.get("close") or not r.get("Price"):
            continue
        try:
            snap = float(r["Price"])
        except ValueError:
            continue
        panel_close = bar["close"]
        pct = abs(snap - panel_close) / panel_close * 100
        compared += 1
        if pct >= SUSPECT_PCT:
            suspects.append((pct, t, snap, panel_close, bar.get("volume")))
        elif pct >= REPORT_PCT:
            diffs.append((pct, t, snap, panel_close))

    diffs.sort(reverse=True)
    suspects.sort(reverse=True)

    print("Cross-check " + a.as_of + ": " + str(compared) + " of "
          + str(len(rows)) + " names comparable")
    if compared:
        allp = [d[0] for d in diffs] or [0.0]
        print("  median reported divergence: " + format(statistics.median(allp), ".2f") + " pct")

    if suspects:
        print("  SUSPECT (>= " + str(SUSPECT_PCT) + " pct, likely a bad bar):")
        for pct, t, snap, close, vol in suspects:
            note = " [volume 0]" if vol == 0 else ""
            print("    " + t + ": snapshot " + str(snap) + " vs panel "
                  + str(close) + "  " + format(pct, ".1f") + " pct" + note)

    if diffs:
        print("  drift (" + str(REPORT_PCT) + " to " + str(SUSPECT_PCT) + " pct), "
              + str(len(diffs)) + " names, expected for a different session:")
        for pct, t, snap, close in diffs[:10]:
            print("    " + t + ": " + str(snap) + " vs " + str(close)
                  + "  " + format(pct, ".1f") + " pct")

    if not suspects and not diffs:
        print("  no divergence above " + str(REPORT_PCT) + " pct")

    return 0


if __name__ == "__main__":
    sys.exit(main())
