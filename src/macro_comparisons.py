"""Comparison rows beside the daily tape: gold, the US dollar and bitcoin.

What these are
--------------
Three instruments the owner watches next to the sectors (decided 2026-09-21).
Each row is one instrument's own return over the daily tape's windows, and
that return minus SPY's over the same window. Nothing else.

What they are not
-----------------
Not sectors. There is no basket behind a row, so there is no breadth; there is
no volume confirmation (the dollar index has no volume at all); there is no
rank among the eleven and no score, band or rating. They are never an input to
a forecast, an input payload or an evaluation: nothing on the weekly forecast
path imports this module, and tests/test_macro_comparisons.py holds that line.
In the tape artifact they live in their own top-level block, never under
`sectors`, so nothing that iterates the sectors can pick one up.

Where each value comes from
---------------------------
    GLD   series["GLD"]   SPDR Gold Shares
    DXY   fx["DXY"]       US Dollar Index, the council panel's fx block
    BTC   series["BTC"]   Grayscale Bitcoin Mini Trust ETF

The sources are fixed on purpose. The panel's `commodities` block carries a
GOLD futures close; that is a different instrument, and putting it in the gold
row because GLD is not there yet would be inventing the row. A value that is
absent at either end of a window leaves that window missing, with the reason,
until the feed carries it.

Inherited gates, unchanged: a series bar with zero volume is not a trade and
is rejected exactly as it is for a basket constituent, and a move beyond the
tape's extreme-move threshold is flagged and retained, never dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compute_metrics import (  # noqa: E402
    BENCHMARK,
    pct_change,
    reject_reason,
    series_at,
)

# The key the tape artifact files these rows under.
BLOCK_KEY = "macro_comparisons"

# Row order is the order the owner named them. `block` is the panel block the
# value is read from and `ticker` its key there; neither is configurable at
# run time, because a configurable source is how a proxy gets substituted.
INSTRUMENTS = (
    {"ticker": "GLD", "block": "series", "label": "Gold",
     "name": "SPDR Gold Shares"},
    {"ticker": "DXY", "block": "fx", "label": "US dollar",
     "name": "US Dollar Index"},
    {"ticker": "BTC", "block": "series", "label": "Bitcoin",
     "name": "Grayscale Bitcoin Mini Trust ETF"},
)

NOTE = ("Comparison rows, not sectors. Each is one instrument's return over "
        "the tape's windows and that return minus SPY's. No breadth, no volume "
        "confirmation, no rank, no score. Never an input to a forecast, an "
        "input payload or an evaluation.")


def _feed_says(session: dict, ticker: str) -> str | None:
    """The upstream feed's own reason, when its `missing` list names the ticker."""
    for entry in session.get("missing") or []:
        if isinstance(entry, dict) and entry.get("ticker") == ticker:
            return entry.get("reason")
    return None


def close_in(session: dict, inst: dict) -> tuple[float | None, str | None]:
    """One instrument's usable close in one session, or the reason there is none."""
    ticker, block = inst["ticker"], inst["block"]
    if block == "series":
        bar = series_at(session, ticker)
        if bar is not None:
            return bar["close"], None
        reason = reject_reason(session, ticker)
    else:
        bar = (session.get(block) or {}).get(ticker)
        if bar is not None and bar.get("close") not in (None, 0):
            return bar["close"], None
        reason = (("absent from " if bar is None else "null or zero close in ")
                  + block + " at " + str(session.get("as_of")))
    feed = _feed_says(session, ticker)
    if feed:
        reason += " (the feed says: " + feed + ")"
    return None, reason


def window(sessions: list[dict], inst: dict, back: int,
           bench_return: float | None) -> tuple[dict, float | None]:
    """The instrument over the last `back` sessions -- the tape's own window.

    Returns the artifact block and the unrounded return, which the extreme-
    move check reads exactly as the basket check does.
    """
    out = {
        "sessions": back,
        "window_from": None,
        "window_to": None,
        "close_from": None,
        "close_to": None,
        "return_pct": None,
        "return_vs_spy_pct": None,
        "missing": [],
    }
    if len(sessions) <= back:
        out["missing"].append({
            "ticker": inst["ticker"],
            "reason": ("panel has " + str(len(sessions)) + " session(s); this "
                       "window needs " + str(back + 1))})
        return out, None
    end, start = sessions[-1], sessions[-1 - back]
    out["window_from"], out["window_to"] = start["as_of"], end["as_of"]
    close_to, why_to = close_in(end, inst)
    close_from, why_from = close_in(start, inst)
    if why_to or why_from:
        out["missing"].append({"ticker": inst["ticker"],
                               "reason": why_to or why_from})
        return out, None
    r = pct_change(close_to, close_from)
    out["close_from"], out["close_to"] = close_from, close_to
    out["return_pct"] = round(r, 3)
    if bench_return is None:
        out["missing"].append({
            "ticker": BENCHMARK,
            "reason": (BENCHMARK + " missing for this window; the return "
                       "relative to it cannot be computed")})
    else:
        out["return_vs_spy_pct"] = round(r - bench_return, 3)
    return out, r


def compute(sessions: list[dict], horizon_sessions: dict,
            bench_returns: dict, extreme_move_pct: float) -> dict:
    """The comparison block for one tape.

    `horizon_sessions` and `bench_returns` are the tape's own: the same
    windows the sectors are read over, and SPY's return over each (None where
    SPY is missing or the window is too long for the panel).
    """
    rows: dict[str, dict] = {}
    warnings: list[str] = []
    for inst in INSTRUMENTS:
        row = {
            "label": inst["label"],
            "name": inst["name"],
            "source": inst["block"] + "." + inst["ticker"],
        }
        for horizon, back in horizon_sessions.items():
            row[horizon], r = window(sessions, inst, back,
                                     bench_returns.get(horizon))
            if r is not None and abs(r) > extreme_move_pct:
                warnings.append(
                    "comparison/" + inst["ticker"] + "/" + horizon + ": moved "
                    + str(round(r, 2)) + " pct over " + str(back)
                    + " session(s); check for an unhandled corporate action")
        rows[inst["ticker"]] = row
    return {
        "is_sector": False,
        "note": NOTE,
        "benchmark": BENCHMARK,
        "rows": rows,
        "warnings": warnings,
    }
