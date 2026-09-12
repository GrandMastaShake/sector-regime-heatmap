"""The daily tape: cadence isolation, arithmetic only, no forecast.

The cadence gate is the load-bearing test here. data/daily and data/weekly
carry different adjustment anchors, and differencing across them reports
dividend and split drift as sector dispersion -- the same failure the
SOURCE_BASIS gate exists to prevent, on a different axis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import daily_tape as dt  # noqa: E402
from compute_metrics import PanelError  # noqa: E402

BASKETS = {
    "Technology": ["AAA", "BBB", "CCC", "DDD", "EEE",
                   "FFF", "GGG", "HHH", "III", "JJJ"],
    "Energy": ["KKK", "LLL", "MMM", "NNN", "OOO",
               "PPP", "QQQ", "RRR", "SSS", "TTT"],
}
ALL = [t for ts in BASKETS.values() for t in ts]


def session(as_of, closes, volume=1_000_000, cadence="daily",
            source="yahoo-daily"):
    doc = {
        "as_of": as_of, "cadence": cadence, "source": source,
        "fetched_at": as_of + "T21:00:00Z", "session": "close",
        "series": {t: {"close": c, "volume": volume} for t, c in closes.items()},
        "rates": {}, "vol": {}, "commodities": {}, "fx": {}, "missing": [],
    }
    return doc


def write_panel(tmp_path, docs):
    d = tmp_path / "daily"
    d.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (d / (doc["as_of"] + ".json")).write_text(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8", newline="\n")
    return d


def flat(value=100.0):
    closes = {t: value for t in ALL}
    closes["SPY"] = value
    return closes


# -- the cadence gate --------------------------------------------------------

def test_refuses_a_weekly_file_in_the_daily_panel(tmp_path):
    """The failure this prevents: differencing across two anchors."""
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0))
    b.pop("cadence")                      # a weekly file has no cadence key
    b["source"] = "yahoo"
    panel = write_panel(tmp_path, [a, b])
    with pytest.raises(PanelError) as exc:
        dt.compute_tape(panel, BASKETS)
    assert "cadence" in str(exc.value)
    assert "adjustment anchor" in str(exc.value)


def test_refuses_an_undeclared_source(tmp_path):
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0), source="some-new-provider")
    panel = write_panel(tmp_path, [a, b])
    with pytest.raises(PanelError) as exc:
        dt.compute_tape(panel, BASKETS)
    assert "adjustment basis is undeclared" in str(exc.value)


def test_accepts_a_uniformly_daily_panel(tmp_path):
    panel = write_panel(tmp_path, [session("2026-09-09", flat()),
                                   session("2026-09-10", flat(101.0))])
    res = dt.compute_tape(panel, BASKETS)
    assert res["as_of"] == "2026-09-10"
    assert res["adjustment_basis"] == "total_return"


# -- it is not a forecast ----------------------------------------------------

def test_tape_declares_itself_not_a_forecast(tmp_path):
    panel = write_panel(tmp_path, [session("2026-09-09", flat()),
                                   session("2026-09-10", flat(101.0))])
    res = dt.compute_tape(panel, BASKETS)
    assert res["artifact_type"] == "daily_tape"
    assert res["is_forecast"] is False


def test_tape_emits_no_judgment_components(tmp_path):
    """regime_fit and macro_catalyst have no daily source. A tape that
    carried them would be inventing them."""
    panel = write_panel(tmp_path, [session("2026-09-09", flat()),
                                   session("2026-09-10", flat(101.0))])
    res = dt.compute_tape(panel, BASKETS)
    # Scoped to the sector blocks: the top-level `note` names both components
    # in order to say it does not emit them, and that sentence is the point.
    blob = json.dumps(res["sectors"])
    assert "regime_fit" not in blob
    assert "macro_catalyst" not in blob
    for horizons in res["sectors"].values():
        for block in horizons.values():
            assert set(block["_components"]) == {
                "breadth", "relative_momentum", "volume_confirmation"}


def test_tape_emits_no_score(tmp_path):
    panel = write_panel(tmp_path, [session("2026-09-09", flat()),
                                   session("2026-09-10", flat(101.0))])
    res = dt.compute_tape(panel, BASKETS)
    for horizons in res["sectors"].values():
        for block in horizons.values():
            assert "score" not in block
            assert "band" not in block
            assert "rating" not in block


# -- inherited gates ---------------------------------------------------------

def test_zero_volume_bar_is_rejected(tmp_path):
    """The AVB case: a close printed behind no trades is not a trade."""
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0))
    b["series"]["AAA"] = {"close": 65.9, "volume": 0}
    panel = write_panel(tmp_path, [a, b])
    res = dt.compute_tape(panel, BASKETS)
    tech = res["sectors"]["Technology"]["day"]
    assert tech["constituents_used"] == 9
    assert tech["constituents_expected"] == 10
    assert any("zero-volume" in m["reason"] for m in tech["missing"])


def test_extreme_move_is_flagged_and_retained(tmp_path):
    """Dropping real crashes is worse than reporting them."""
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0))
    b["series"]["AAA"] = {"close": 200.0, "volume": 1_000_000}
    panel = write_panel(tmp_path, [a, b])
    res = dt.compute_tape(panel, BASKETS)
    tech = res["sectors"]["Technology"]["day"]
    assert tech["constituents_used"] == 10, "the name must be retained"
    assert any(x["ticker"] == "AAA" for x in tech["anomalies"])
    assert any("AAA" in w for w in res["warnings"])


def test_thin_basket_warns_with_a_true_denominator(tmp_path):
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0))
    for t in ["AAA", "BBB", "CCC"]:
        b["series"].pop(t)
    panel = write_panel(tmp_path, [a, b])
    res = dt.compute_tape(panel, BASKETS)
    tech = res["sectors"]["Technology"]["day"]
    assert tech["constituents_used"] == 7
    assert tech["constituents_expected"] == 10
    assert any("only 7 of 10" in w for w in res["warnings"])


def test_correction_supersedes_its_original(tmp_path):
    a = session("2026-09-09", flat())
    b = session("2026-09-10", flat(101.0))
    panel = write_panel(tmp_path, [a, b])
    corrected = session("2026-09-10", flat(150.0))
    corrected["corrects"] = "2026-09-10.json"
    corrected["reason"] = "provider restated"
    (panel / "2026-09-10.corrected.json").write_text(
        json.dumps(corrected, indent=2) + "\n", encoding="utf-8", newline="\n")
    res = dt.compute_tape(panel, BASKETS)
    assert res["sectors"]["Technology"]["day"]["equal_weight_return_pct"] == 50.0


# -- horizons ----------------------------------------------------------------

def test_week_horizon_is_omitted_when_the_panel_is_too_short(tmp_path):
    panel = write_panel(tmp_path, [session("2026-09-09", flat()),
                                   session("2026-09-10", flat(101.0))])
    res = dt.compute_tape(panel, BASKETS)
    assert "day" in res["sectors"]["Technology"]
    assert "week" not in res["sectors"]["Technology"]
    assert any("week" in w and "omitted" in w for w in res["warnings"])


def test_empty_panel_is_an_error(tmp_path):
    d = tmp_path / "daily"
    d.mkdir(parents=True)
    with pytest.raises(PanelError):
        dt.compute_tape(d, BASKETS)
