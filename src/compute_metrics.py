"""Compute the deterministic sector components from a weekly price panel.

Three of the five scoring components are arithmetic, not judgment:

    breadth               percent of the equal-weight basket with positive return
    relative_momentum     basket return minus SPY, ranked across the 11 sectors
    volume_confirmation   advancing share of basket volume

This module computes those and nothing else. `regime_fit` and `macro_catalyst`
are left null for a human or an agent to fill with sourced reasoning. A partial
sector file cannot be scored: src/heatmap.py rejects missing components, which
is the intended handoff, not a bug.

Two gates exist because violating either produces confident wrong numbers
rather than obvious broken ones:

1. Adjustment basis. Total-return and price-only closes cannot be mixed in one
   basket. Dividend payers diverge from non-payers in proportion to accumulated
   yield -- roughly 2.7 points over a year on this watchlist -- which reads as
   sector dispersion and is indistinguishable from signal.

2. Denominator honesty. A basket where constituents are missing is reported
   with its true denominator, never silently computed over the survivors.
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

BENCHMARK = "SPY"

# Weekly bars per horizon. The day horizon is absent on purpose: it needs daily
# bars, and the upstream feed commits Friday closes only.
HORIZON_WEEKS = {"week": 1, "month": 4}

# Which price sources produce which adjustment basis. An unlisted source is
# refused rather than assumed.
SOURCE_BASIS = {
    "yahoo": "total_return",
    "yahoo-backfill": "total_return",
}

MIN_CONSTITUENTS = 8

# Adjusted closes are back-adjusted to the date they were fetched. data/weekly
# is an observation log -- each Friday scan records the closes the council saw
# that week -- so an ongoing panel legitimately spans months of fetch dates and
# that is not an error.
#
# What matters is the two weeks a horizon actually reads. If those were fetched
# far apart, a dividend paid in between is baked into one end and not the other.
# Over a 4-week window that is roughly one quarter's yield on the affected
# names: worth surfacing, not worth refusing.
WARN_WINDOW_ANCHOR_DAYS = 35

# Beyond this the divergence compounds across every payer and the panel is not
# one panel. This is the stale-splice case, not normal operation.
MAX_WINDOW_ANCHOR_DAYS = 180

MIN_CONSTITUENTS = 8

# Adjusted closes are back-adjusted to the date they were fetched. data/weekly
# is an observation log -- each Friday scan records the closes the council saw
# that week -- so an ongoing panel legitimately spans months of fetch dates and
# that is not an error.
#
# What matters is the two weeks a horizon actually reads. If those were fetched
# far apart, a dividend paid in between is baked into one end and not the other.
# Over a 4-week window that is roughly one quarter's yield on the affected
# names: worth surfacing, not worth refusing.
WARN_WINDOW_ANCHOR_DAYS = 35

# Beyond this the divergence compounds across every payer and the panel is not
# one panel. This is the stale-splice case, not normal operation.
MAX_WINDOW_ANCHOR_DAYS = 180

# Adjusted closes are back-adjusted relative to the fetch date, so two fetches
# taken far apart disagree on the pre-ex history of any name that paid a
# dividend in between. `fetched_at` is that anchor.
#
# A normal backfill spans a few days and a targeted --only run adds a few more;
# the current panel sits at 10 days and the bias over such a window is one
# quarter's yield on the affected names, which is tolerable. This bound exists
# to catch the case that is not tolerable: splicing in files fetched months or
# years apart, where the divergence compounds across every payer.

# A bar with no volume is not a trade. metric_definitions.md requires flagging
# zero-volume records; a printed close behind zero volume is a provider
# artifact and must never reach a return calculation.
REJECT_ZERO_VOLUME = True

# A weekly move beyond this is reported as an anomaly. It is NOT excluded --
# real crashes happen and dropping them would be worse than flagging them.
EXTREME_WEEKLY_MOVE_PCT = 40.0


class PanelError(RuntimeError):
    pass


def load_panel(panel_dir: Path) -> list[dict]:
    files = sorted(panel_dir.glob("*.json"))
    if not files:
        raise PanelError("No weekly files found in " + str(panel_dir))
    weeks = []
    for f in files:
        if f.name.endswith(".corrected.json"):
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        corrected = f.with_name(f.stem + ".corrected.json")
        if corrected.is_file():
            doc = json.loads(corrected.read_text(encoding="utf-8"))
        weeks.append(doc)
    weeks.sort(key=lambda d: d["as_of"])
    return weeks


def anchor_of(week: dict, ticker: str | None = None) -> str:
    """The adjustment anchor for one series, or for the file as a whole.

    A week merged by weekly-council-scan's `backfill_weekly.py --merge`
    carries series fetched at two different times: the names added later
    are listed in `provenance.series` with their own `fetched_at`, and the
    file-level stamp still describes everything else. Resolving the anchor
    per file in that case reports one anchor for two, which is the error
    the block exists to prevent (DATA_FEED.md sec.1).
    """
    if ticker is not None:
        prov = week.get("provenance")
        if isinstance(prov, dict):
            entry = (prov.get("series") or {}).get(ticker)
            if isinstance(entry, dict) and entry.get("fetched_at"):
                return str(entry["fetched_at"])[:10]
    got = week.get("fetched_at")
    if not got:
        raise PanelError(
            "Week " + week["as_of"] + " has no fetched_at. That timestamp is the "
            "adjustment anchor; without it a stale splice cannot be detected."
        )
    return got[:10]


def anchors_in_window(weeks: list[dict], tickers) -> dict[str, set]:
    """Map anchor date -> the tickers reading that anchor across the weeks."""
    found: dict[str, set] = {}
    for w in weeks:
        series = w.get("series") or {}
        for t in tickers:
            if t in series:
                found.setdefault(anchor_of(w, t), set()).add(t)
    if not found:
        for w in weeks:
            found.setdefault(anchor_of(w), set())
    return found


def window_anchor(start_week: dict, end_week: dict, horizon: str,
                  tickers=None) -> dict:
    """Anchor spread across the two weeks a horizon actually reads.

    With `tickers`, the spread covers every anchor those series actually
    carry -- including two anchors inside a single merged week, which is a
    real mixed basis in one cross-section, not just across time.
    """
    if tickers:
        found = anchors_in_window([start_week, end_week], tickers)
    else:
        found = {anchor_of(start_week): set(), anchor_of(end_week): set()}
    dates = sorted(found)
    a, b = dates[0], dates[-1]
    spread = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
    if spread > MAX_WINDOW_ANCHOR_DAYS:
        raise PanelError(
            "The " + horizon + " window reads weeks fetched " + str(spread)
            + " days apart (" + a + " to " + b + "). Adjusted closes are "
            "back-adjusted to the fetch date, so across that gap every dividend "
            "payer's history disagrees with itself. Re-run the backfill so the "
            "window shares one anchor."
        )
    return {"earliest": a, "latest": b, "spread_days": spread,
            "warn": spread > WARN_WINDOW_ANCHOR_DAYS,
            "distinct_anchors": len(dates),
            "series_by_anchor": {d: len(found[d]) for d in dates
                                 if found[d]} or None}


def check_basis(weeks: list[dict]) -> str:
    """Every week in the panel must share one declared adjustment basis."""
    seen: dict[str, set[str]] = {}
    for w in weeks:
        # A merged week declares the source of each added series separately;
        # those closes are on that source's basis, not the file's.
        prov = w.get("provenance")
        prov_series = (prov or {}).get("series") or {}
        for ticker, entry in sorted(prov_series.items()):
            psrc = (entry or {}).get("source")
            if psrc not in SOURCE_BASIS:
                raise PanelError(
                    "Week " + w["as_of"] + " declares source " + repr(psrc)
                    + " for " + ticker + ", whose adjustment basis is "
                    "undeclared. Add it to SOURCE_BASIS only after confirming "
                    "whether its closes are total-return or price-only."
                )
            seen.setdefault(SOURCE_BASIS[psrc], set()).add(w["as_of"])
        src = w.get("source")
        if src not in SOURCE_BASIS:
            raise PanelError(
                "Week " + w["as_of"] + " has source " + repr(src)
                + ", whose adjustment basis is undeclared. Add it to SOURCE_BASIS "
                "only after confirming whether its closes are total-return or "
                "price-only. Mixing bases silently biases breadth against "
                "dividend payers."
            )
        seen.setdefault(SOURCE_BASIS[src], set()).add(w["as_of"])
    if len(seen) > 1:
        detail = "; ".join(
            b + ": " + str(len(d)) + " weeks (" + min(d) + ".." + max(d) + ")"
            for b, d in sorted(seen.items())
        )
        raise PanelError("Panel mixes adjustment bases -- " + detail)
    return next(iter(seen))


def series_at(week: dict, ticker: str) -> dict | None:
    bar = week["series"].get(ticker)
    if bar is None:
        return None
    if bar.get("close") in (None, 0):
        return None
    if REJECT_ZERO_VOLUME and bar.get("volume") == 0:
        return None
    return bar


def reject_reason(week: dict, ticker: str) -> str:
    bar = week["series"].get(ticker)
    if bar is None:
        return "absent from series at " + week["as_of"]
    if bar.get("close") in (None, 0):
        return "null or zero close at " + week["as_of"]
    if bar.get("volume") == 0:
        return ("zero-volume bar at " + week["as_of"] + " (close "
                + str(bar.get("close")) + " printed behind no trades)")
    return "unusable bar at " + week["as_of"]


def pct_change(new: float, old: float) -> float | None:
    if old in (None, 0) or new is None:
        return None
    return (new / old - 1.0) * 100.0


def horizon_returns(weeks: list[dict], tickers: list[str], back: int) -> dict:
    """Return per-ticker percent change over `back` weekly bars, plus coverage."""
    if len(weeks) < back + 1:
        raise PanelError(
            "Panel has " + str(len(weeks)) + " weeks; need " + str(back + 1)
            + " for that horizon"
        )
    end, start = weeks[-1], weeks[-1 - back]
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
         "reason": "weekly move beyond " + str(EXTREME_WEEKLY_MOVE_PCT)
                   + " pct; check for an unhandled corporate action"}
        for t, v in out.items() if abs(v["return_pct"]) > EXTREME_WEEKLY_MOVE_PCT
    ]
    return {"returns": out, "missing": missing, "anomalies": anomalies,
            "as_of": end["as_of"], "from": start["as_of"]}


def basket_metrics(block: dict, bench_return: float | None, universe: int) -> dict:
    r = block["returns"]
    n = len(r)
    rets = [v["return_pct"] for v in r.values()]
    positive = sum(1 for x in rets if x > 0)

    vols = {t: v["volume"] for t, v in r.items() if v["volume"]}
    adv = sum(v for t, v in vols.items() if r[t]["return_pct"] > 0)
    total = sum(vols.values())

    contrib = sorted((abs(x) for x in rets), reverse=True)
    denom = sum(contrib)

    equal_weight = statistics.fmean(rets) if rets else None
    return {
        "constituents_used": n,
        "constituents_expected": universe,
        "coverage_pct": round(n / universe * 100, 1) if universe else None,
        "missing": block["missing"],
        "anomalies": block["anomalies"],
        "positive_return_breadth_pct": round(positive / n * 100, 1) if n else None,
        "median_return_pct": round(statistics.median(rets), 3) if rets else None,
        "equal_weight_return_pct": round(equal_weight, 3) if equal_weight is not None else None,
        "sector_return_vs_spy_pct": (round(equal_weight - bench_return, 3)
                                     if equal_weight is not None and bench_return is not None
                                     else None),
        "up_volume_share_pct": round(adv / total * 100, 1) if total else None,
        "volume_names_used": len(vols),
        "top_two_contribution_pct": (round(sum(contrib[:2]) / denom * 100, 1)
                                     if denom else None),
        "window_from": block["from"],
        "window_to": block["as_of"],
    }


def rank_to_score(value: float | None, ordered: list[float]) -> float | None:
    """Cross-sectional rank of one sector among the eleven, scaled 0-100."""
    if value is None or not ordered:
        return None
    below = sum(1 for x in ordered if x < value)
    ties = sum(1 for x in ordered if x == value)
    return round((below + (ties - 1) / 2) / (len(ordered) - 1) * 100, 1) if len(ordered) > 1 else 50.0


def compute(panel_dir: Path, baskets: dict, as_of: str | None) -> dict:
    weeks = load_panel(panel_dir)
    basis = check_basis(weeks)
    if as_of:
        weeks = [w for w in weeks if w["as_of"] <= as_of]
        if not weeks or weeks[-1]["as_of"] != as_of:
            raise PanelError("No weekly file for as_of " + as_of)

    sectors = {k: v for k, v in baskets.items() if k not in ("version", "note")}
    result: dict = {
        "as_of": weeks[-1]["as_of"],
        "panel_weeks": len(weeks),
        "adjustment_basis": basis,
        "adjustment_anchor": {},
        "benchmark": BENCHMARK,
        "sectors": {},
        "warnings": [],
    }

    # The anchor question is about the series actually scored, so ask it of
    # exactly those: every basket constituent plus the benchmark. A merged
    # name outside every basket must not widen a spread nobody reads.
    scored_tickers = {BENCHMARK}
    for _tickers in sectors.values():
        scored_tickers.update(_tickers)

    per_horizon: dict[str, dict[str, dict]] = {}
    for horizon, back in HORIZON_WEEKS.items():
        if len(weeks) > back:
            anc = window_anchor(weeks[-1 - back], weeks[-1], horizon,
                                scored_tickers)
            result["adjustment_anchor"][horizon] = anc
            if anc["warn"]:
                detail = ""
                if anc.get("distinct_anchors", 1) > 2:
                    detail = (" across " + str(anc["distinct_anchors"])
                              + " distinct anchors -- some series in these "
                              "weeks were merged in later")
                result["warnings"].append(
                    "The " + horizon + " window reads weeks fetched "
                    + str(anc["spread_days"]) + " days apart (" + anc["earliest"]
                    + " to " + anc["latest"] + ")" + detail + "; dividend "
                    "payers' history is adjusted to different anchors across "
                    "that gap"
                )
        bench = horizon_returns(weeks, [BENCHMARK], back)
        bench_return = bench["returns"].get(BENCHMARK, {}).get("return_pct")
        if bench_return is None:
            result["warnings"].append(
                BENCHMARK + " missing for the " + horizon
                + " window; relative momentum cannot be computed"
            )
        per_horizon[horizon] = {}
        for sector, tickers in sectors.items():
            block = horizon_returns(weeks, tickers, back)
            m = basket_metrics(block, bench_return, len(tickers))
            per_horizon[horizon][sector] = m
            for a in m["anomalies"]:
                result["warnings"].append(
                    sector + "/" + horizon + ": " + a["ticker"] + " moved "
                    + str(a["return_pct"]) + " pct -- " + a["reason"]
                )
            for mis in m["missing"]:
                if "zero-volume" in mis["reason"] or "null or zero close" in mis["reason"]:
                    result["warnings"].append(
                        sector + "/" + horizon + ": " + mis["ticker"] + " excluded -- "
                        + mis["reason"]
                    )
            if m["constituents_used"] < MIN_CONSTITUENTS:
                result["warnings"].append(
                    sector + "/" + horizon + " has only "
                    + str(m["constituents_used"]) + " of " + str(len(tickers))
                    + " constituents; too thin to characterise the sector"
                )

    for horizon in HORIZON_WEEKS:
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
                "relative_momentum": rank_to_score(m["sector_return_vs_spy_pct"], rel_sorted),
                "volume_confirmation": m["up_volume_share_pct"],
            }

    for sector in sectors:
        result["sectors"][sector] = {
            h: per_horizon[h][sector] for h in HORIZON_WEEKS
        }
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True,
                   help="directory of weekly-council-scan format YYYY-MM-DD.json files")
    p.add_argument("--baskets", type=Path, default=ROOT / "config/sector_baskets.yaml")
    p.add_argument("--as-of", default=None)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)

    baskets = yaml.safe_load(a.baskets.read_text(encoding="utf-8"))
    res = compute(a.panel, baskets, a.as_of)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=2, ensure_ascii=True) + "\n",
                     encoding="utf-8", newline="\n")
    print("Wrote " + str(a.out) + " (" + res["as_of"] + ", basis "
          + res["adjustment_basis"] + ")")
    for w in res["warnings"]:
        print("  WARNING " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
