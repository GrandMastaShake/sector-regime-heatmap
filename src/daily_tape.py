"""Daily sector tape: the three arithmetic components, computed per session.

What this is
------------
An OBSERVATION of the eleven baskets over daily bars. It computes exactly the
three components that are arithmetic:

    breadth               percent of the equal-weight basket with positive return
    relative_momentum     basket return minus SPY, ranked across the eleven
    volume_confirmation   advancing share of basket volume

and it stops there. It does not score. `regime_fit` and `macro_catalyst` are
judgment and have no daily source; a daily artifact carrying them would be
inventing them, which is the one rule this repo does not bend. Nothing here
writes to data/forecasts/, and src/evaluate.py must never grade a tape file --
a tape is not a forecast and grading one would be scoring the market against
itself.

Why it is a separate panel
--------------------------
data/daily and data/weekly carry different adjustment anchors. The weekly
files were fetched the morning after each Friday; the daily files were
bootstrapped in one ranged download. On 2026-08-28 the two agree on SPY to the
penny and disagree by ~1% across 57 dividend payers, and by 50% on APH, which
split 2:1 on 2026-09-03. Splicing them would inject exactly the phantom
dispersion the SOURCE_BASIS gate exists to prevent -- same hazard, different
axis. So this module reads data/daily and only data/daily, and refuses a panel
that mixes cadences.

Everything else is inherited from src/compute_metrics.py unchanged: zero-volume
bars are rejected, extreme moves are flagged and retained, and a basket under
MIN_CONSTITUENTS is reported failed rather than computed over survivors. Each
basket is measured against its own size -- Real Estate holds nine names since
2026-09-21, the others ten -- never against an assumed ten.

Comparison rows
---------------
Beside the sectors, never among them: gold (GLD), the US dollar index (DXY,
the panel's fx block) and bitcoin (BTC), each as its own return over the same
windows and that return minus SPY's. src/macro_comparisons.py computes them
into a separate top-level block. They carry no breadth, no volume
confirmation, no rank and no score, and a missing value stays missing.

A tape is a dated artifact
--------------------------
`main` never rewrites one. Recomputing a date whose tape already exists is a
no-op when the result is identical -- the scheduled job relies on that when
upstream has no new session -- and a refusal when it is not. Different bytes
for a published date mean the code or the panel changed underneath it, and
quietly replacing the record is exactly what the immutability rule forbids.
"""
from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compute_metrics import (  # noqa: E402
    BENCHMARK,
    MIN_CONSTITUENTS,
    PanelError,
    basket_metrics,
    pct_change,
    rank_to_score,
    reject_reason,
    series_at,
)
import macro_comparisons as mc  # noqa: E402

# Sessions per horizon. "day" is one session; "week" is five, which is a
# trading week rather than a calendar one. The weekly pipeline's week/month
# horizons are deliberately NOT reproduced here -- four weekly bars and twenty
# daily bars answer different questions, and publishing both under the same
# name would invite reading one as a check on the other.
HORIZON_SESSIONS = {"day": 1, "week": 5}

# The daily feed's own source label. Same provider and same basis as the
# weekly feed; the distinct label is what keeps a mixed panel detectable.
DAILY_SOURCE_BASIS = {"yahoo-daily": "total_return"}

# A single session beyond this is an anomaly worth surfacing. Lower than the
# weekly gate at 40 because one session moving 25% is a different event from a
# week doing it. Flagged and RETAINED, never dropped -- real crashes happen.
EXTREME_DAILY_MOVE_PCT = 25.0


def load_daily_panel(daily_dir: Path) -> list[dict]:
    """Load data/daily, oldest first, corrections preferred over originals."""
    files = sorted(daily_dir.glob("*.json"))
    if not files:
        raise PanelError("No daily files found in " + str(daily_dir))
    sessions = []
    for f in files:
        if f.name.endswith(".corrected.json"):
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        corrected = f.with_name(f.stem + ".corrected.json")
        if corrected.is_file():
            doc = json.loads(corrected.read_text(encoding="utf-8"))
        sessions.append(doc)
    sessions.sort(key=lambda d: d["as_of"])
    return sessions


def check_cadence(sessions: list[dict]) -> str:
    """Refuse a panel that is not uniformly daily.

    The failure this prevents is a weekly file landing in data/daily -- or the
    reverse -- and being differenced against a daily one across two adjustment
    anchors. `cadence` is required by DATA_FEED.md sec.4 precisely so this is
    checkable rather than inferred from a filename.
    """
    for s in sessions:
        cadence = s.get("cadence")
        if cadence != "daily":
            raise PanelError(
                "Session " + str(s.get("as_of")) + " declares cadence "
                + repr(cadence) + ", not 'daily'. A daily tape must read one "
                "cadence: daily and weekly files carry different adjustment "
                "anchors and differencing across them reports dividend and "
                "split drift as sector dispersion."
            )
        src = s.get("source")
        if src not in DAILY_SOURCE_BASIS:
            raise PanelError(
                "Session " + str(s.get("as_of")) + " has source " + repr(src)
                + ", whose adjustment basis is undeclared for the daily feed. "
                "Add it to DAILY_SOURCE_BASIS only after confirming whether "
                "its closes are total-return or price-only."
            )
    return "total_return"


def session_returns(sessions: list[dict], tickers: list[str], back: int) -> dict:
    """Per-ticker percent change over `back` sessions, plus coverage."""
    if len(sessions) < back + 1:
        raise PanelError(
            "Panel has " + str(len(sessions)) + " sessions; need "
            + str(back + 1) + " for that horizon"
        )
    end, start = sessions[-1], sessions[-1 - back]
    out, missing = {}, []
    for t in tickers:
        a, b = series_at(end, t), series_at(start, t)
        if a is None or b is None:
            bad = end if a is None else start
            missing.append({"ticker": t, "reason": reject_reason(bad, t)})
            continue
        r = pct_change(a["close"], b["close"])
        if r is None:
            missing.append({"ticker": t, "reason": "zero or null close"})
            continue
        out[t] = {"return_pct": r, "volume": a.get("volume")}
    anomalies = [
        {"ticker": t, "return_pct": round(v["return_pct"], 2),
         "reason": "move beyond " + str(EXTREME_DAILY_MOVE_PCT)
                   + " pct over " + str(back) + " session(s); check for an "
                   "unhandled corporate action"}
        for t, v in out.items() if abs(v["return_pct"]) > EXTREME_DAILY_MOVE_PCT
    ]
    return {"returns": out, "missing": missing, "anomalies": anomalies,
            "as_of": end["as_of"], "from": start["as_of"]}


def compute_tape(daily_dir: Path, baskets: dict, as_of: str | None = None) -> dict:
    sessions = load_daily_panel(daily_dir)
    basis = check_cadence(sessions)
    if as_of:
        sessions = [s for s in sessions if s["as_of"] <= as_of]
        if not sessions or sessions[-1]["as_of"] != as_of:
            raise PanelError("No daily file for as_of " + str(as_of))

    sectors = {k: v for k, v in baskets.items() if k not in ("version", "note")}
    result: dict = {
        "as_of": sessions[-1]["as_of"],
        "artifact_type": "daily_tape",
        # Stated in the artifact, not just the docs: a consumer that finds
        # this file must not be able to mistake it for a forecast.
        "is_forecast": False,
        "note": ("Observation only. Three arithmetic components over daily "
                 "bars. No score, no regime_fit, no macro_catalyst -- those "
                 "are judgment and have no daily source."),
        "panel_sessions": len(sessions),
        "panel_from": sessions[0]["as_of"],
        "adjustment_basis": basis,
        "benchmark": BENCHMARK,
        "sectors": {},
        # Filled below. Its own key, so nothing that walks `sectors` -- the
        # ranking, the prior comparison, the chart -- can ever meet a row.
        mc.BLOCK_KEY: None,
        "warnings": [],
    }

    per_horizon: dict[str, dict[str, dict]] = {}
    bench_by_horizon: dict[str, float | None] = {}
    for horizon, back in HORIZON_SESSIONS.items():
        if len(sessions) <= back:
            result["warnings"].append(
                "Panel has " + str(len(sessions)) + " sessions; the " + horizon
                + " horizon needs " + str(back + 1) + " and is omitted"
            )
            continue
        bench = session_returns(sessions, [BENCHMARK], back)
        bench_return = bench["returns"].get(BENCHMARK, {}).get("return_pct")
        bench_by_horizon[horizon] = bench_return
        if bench_return is None:
            result["warnings"].append(
                BENCHMARK + " missing for the " + horizon
                + " window; relative momentum cannot be computed"
            )
        per_horizon[horizon] = {}
        for sector, tickers in sectors.items():
            block = session_returns(sessions, tickers, back)
            m = basket_metrics(block, bench_return, len(tickers))
            per_horizon[horizon][sector] = m
            for a in m["anomalies"]:
                result["warnings"].append(
                    sector + "/" + horizon + ": " + a["ticker"] + " moved "
                    + str(a["return_pct"]) + " pct -- " + a["reason"]
                )
            if m["constituents_used"] < MIN_CONSTITUENTS:
                result["warnings"].append(
                    sector + "/" + horizon + " has only "
                    + str(m["constituents_used"]) + " of " + str(len(tickers))
                    + " constituents; too thin to characterise the sector"
                )

    for horizon in per_horizon:
        rel = [m["sector_return_vs_spy_pct"] for m in per_horizon[horizon].values()
               if m["sector_return_vs_spy_pct"] is not None]
        rel_sorted = sorted(rel)
        for sector, m in per_horizon[horizon].items():
            m["sector_rank_among_eleven"] = (
                len(rel) - rel_sorted.index(m["sector_return_vs_spy_pct"])
                if m["sector_return_vs_spy_pct"] in rel_sorted else None
            )
            m["_components"] = {
                "breadth": m["positive_return_breadth_pct"],
                "relative_momentum": rank_to_score(
                    m["sector_return_vs_spy_pct"], rel_sorted),
                "volume_confirmation": m["up_volume_share_pct"],
            }

    for sector in sectors:
        result["sectors"][sector] = {
            h: per_horizon[h][sector] for h in per_horizon
        }

    # Same sessions, same windows, same SPY return as the sectors above.
    result[mc.BLOCK_KEY] = mc.compute(sessions, HORIZON_SESSIONS,
                                      bench_by_horizon, EXTREME_DAILY_MOVE_PCT)
    return result


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", type=Path, required=True,
                   help="directory of daily YYYY-MM-DD.json files (data/daily)")
    p.add_argument("--baskets", type=Path,
                   default=ROOT / "config/sector_baskets.yaml")
    p.add_argument("--as-of", default=None)
    p.add_argument("--out", type=Path, default=None,
                   help="write the tape artifact here (default data/tape/<as_of>.json)")
    a = p.parse_args(argv)

    baskets = yaml.safe_load(a.baskets.read_text(encoding="utf-8"))
    res = compute_tape(a.panel, baskets, a.as_of)

    out = a.out or (ROOT / "data" / "tape" / (res["as_of"] + ".json"))
    text = json.dumps(res, indent=2, ensure_ascii=True) + "\n"
    if out.is_file():
        # read_text translates newlines, so a Windows checkout's CRLF copy of
        # an identical tape still compares equal.
        if out.read_text(encoding="utf-8") == text:
            print("Unchanged: " + str(out) + " already holds this tape.")
            return 0
        print("REFUSED: " + str(out) + " already exists and this run computes "
              "something different for " + res["as_of"] + ".")
        print("  A tape is a dated artifact and is never rewritten. The code or "
              "the panel changed")
        print("  underneath it; the published record stays as it was. The next "
              "session gets a new tape.")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print("Wrote " + str(out) + " (" + res["as_of"] + ", "
          + str(res["panel_sessions"]) + " sessions from " + res["panel_from"] + ")")
    for w in res["warnings"]:
        print("  WARNING " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
