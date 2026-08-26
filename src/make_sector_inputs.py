"""Emit partial sector input files from a computed metrics artifact.

What this writes is deliberately incomplete. The three arithmetic components
are filled from the price panel; `regime_fit` and `macro_catalyst` are left
null for a human or an agent to supply with sourced reasoning, as are `why`
and `risks`.

src/heatmap.py will refuse to score a file in this state. That refusal is the
handoff working, not a failure: the numbers a machine can derive are derived,
and the judgment is visibly outstanding rather than quietly defaulted to 50.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMPUTED = ("breadth", "relative_momentum", "volume_confirmation")
JUDGMENT = ("regime_fit", "macro_catalyst")

METRIC_KEYS = (
    "positive_return_breadth_pct", "median_return_pct", "equal_weight_return_pct",
    "sector_return_vs_spy_pct", "sector_rank_among_eleven", "up_volume_share_pct",
    "top_two_contribution_pct", "constituents_used", "constituents_expected",
    "coverage_pct", "window_from", "window_to",
)


def data_quality(blocks: dict) -> dict:
    missing, anomalies, thin = [], [], []
    for horizon, m in blocks.items():
        for x in m["missing"]:
            missing.append({"horizon": horizon, **x})
        for a in m["anomalies"]:
            anomalies.append({"horizon": horizon, **a})
        if m["constituents_used"] < m["constituents_expected"]:
            thin.append(horizon + ": " + str(m["constituents_used"]) + " of "
                        + str(m["constituents_expected"]))
    status = "pass"
    if thin:
        status = "warn"
    if any(m["constituents_used"] < 8 for m in blocks.values()):
        status = "fail"
    return {
        "status": status,
        "missing_tickers": sorted({x["ticker"] for x in missing}),
        "stale_tickers": [],
        "anomalies": anomalies,
        "coverage_notes": thin,
    }


def build_sector(name: str, blocks: dict, as_of: str, basis: str, panel_weeks: int) -> dict:
    out = {
        "sector": name,
        "as_of_date": as_of,
        "data_quality": data_quality(blocks),
        "provenance": {
            "price_panel_weeks": panel_weeks,
            "adjustment_basis": basis,
            "computed_components": list(COMPUTED),
            "judgment_components": list(JUDGMENT),
            "note": ("Arithmetic components are derived from the price panel. "
                     "Judgment components are null and must be supplied with "
                     "sourced reasoning before this file can be scored."),
        },
    }
    for horizon in ("day", "week", "month"):
        m = blocks.get(horizon)
        if m is None:
            out[horizon] = {
                "components": {c: None for c in COMPUTED + JUDGMENT},
                "risk_penalty": 0.0,
                "metrics": {},
                "unavailable": ("The day horizon needs daily bars; the upstream feed "
                                "commits Friday closes only."),
                "why": [], "risks": [],
            }
            continue
        comp = dict(m["_components"])
        out[horizon] = {
            "components": {**{c: comp.get(c) for c in COMPUTED},
                           **{c: None for c in JUDGMENT}},
            "risk_penalty": 0.0,
            "metrics": {k: m.get(k) for k in METRIC_KEYS},
            "why": [], "risks": [],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("metrics", type=Path)
    p.add_argument("out_dir", type=Path)
    a = p.parse_args(argv)

    res = json.loads(a.metrics.read_text(encoding="utf-8"))
    a.out_dir.mkdir(parents=True, exist_ok=True)

    incomplete = 0
    for name, blocks in res["sectors"].items():
        doc = build_sector(name, blocks, res["as_of"], res["adjustment_basis"],
                           res["panel_weeks"])
        fn = name.lower().replace(" ", "_") + ".json"
        (a.out_dir / fn).write_text(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8", newline="\n")
        incomplete += 1

    print("Wrote " + str(incomplete) + " partial sector files to " + str(a.out_dir))
    print("Each needs " + " and ".join(JUDGMENT) + " supplied before scoring.")
    if res["warnings"]:
        print(str(len(res["warnings"])) + " data-quality warning(s) carried into "
              "the data_quality blocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
