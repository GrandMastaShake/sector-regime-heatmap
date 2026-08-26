"""Metrics engine gates. Each test records a way confident wrong numbers arise."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402

BASKETS = yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
SECTORS = {k: v for k, v in BASKETS.items() if k not in ("version", "note")}


def week(as_of: str, closes: dict, source: str = "yahoo", volumes: dict | None = None) -> dict:
    volumes = volumes or {}
    return {
        "as_of": as_of,
        "source": source,
        "fetched_at": as_of + "T21:00:00Z",
        "session": "close",
        "series": {t: {"close": c, "volume": volumes.get(t, 1_000_000)}
                   for t, c in closes.items()},
        "missing": [],
    }


# The month horizon reads 4 weekly bars back, so a usable panel needs 5 weeks.
# Fixtures supply the last two; PAD fills the earlier weeks flat so returns over
# the tested window are unaffected.
PAD_WEEKS = ("2026-07-24", "2026-07-31", "2026-08-07")


def panel(tmp_path: Path, weeks: list[dict], pad: bool = True) -> Path:
    d = tmp_path / "weekly"
    d.mkdir(exist_ok=True)
    if pad:
        base = weeks[0]
        for day in PAD_WEEKS:
            filler = json.loads(json.dumps(base))
            filler["as_of"] = day
            filler["fetched_at"] = day + "T21:00:00Z"
            (d / (day + ".json")).write_text(json.dumps(filler), encoding="utf-8")
    for w in weeks:
        (d / (w["as_of"] + ".json")).write_text(json.dumps(w), encoding="utf-8")
    return d


def flat(tickers, value=100.0):
    return {t: value for t in tickers}


ALL = sorted({t for ts in SECTORS.values() for t in ts} | {"SPY"})


# --- Gate 1: adjustment basis. Mixing total-return and price-only closes
#     biases breadth against dividend payers by ~2.7 points over a year.
def test_undeclared_source_is_refused(tmp_path):
    p = panel(tmp_path, [week("2026-08-14", flat(ALL), source="somebody-elses-csv"),
                         week("2026-08-21", flat(ALL), source="somebody-elses-csv")])
    with pytest.raises(cm.PanelError, match="adjustment basis is undeclared"):
        cm.compute(p, BASKETS, None)


def test_mixed_adjustment_bases_are_refused(tmp_path, monkeypatch):
    monkeypatch.setitem(cm.SOURCE_BASIS, "spreadsheet", "price_only")
    p = panel(tmp_path, [week("2026-08-14", flat(ALL), source="spreadsheet"),
                         week("2026-08-21", flat(ALL), source="yahoo")])
    with pytest.raises(cm.PanelError, match="mixes adjustment bases"):
        cm.compute(p, BASKETS, None)


def test_single_basis_panel_is_accepted(tmp_path):
    p = panel(tmp_path, [week("2026-08-14", flat(ALL)), week("2026-08-21", flat(ALL))])
    assert cm.compute(p, BASKETS, None)["adjustment_basis"] == "total_return"


# --- Gate 2: a zero-volume bar is a provider artifact, not a trade.
#     AVB shipped one on 2026-08-21: close 65.9005 behind volume 0, a -64.2%
#     weekly "return" that moved Real Estate from rank 6 to rank 11 of 11.
def test_zero_volume_bar_is_excluded(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    cur["AVB"] = 35.0
    p = panel(tmp_path, [week("2026-08-14", prev),
                         week("2026-08-21", cur, volumes={"AVB": 0})])
    res = cm.compute(p, BASKETS, None)
    re_week = res["sectors"]["Real Estate"]["week"]
    assert "AVB" in [m["ticker"] for m in re_week["missing"]]
    assert re_week["constituents_used"] == 9
    assert re_week["constituents_expected"] == 10
    assert any("zero-volume" in w for w in res["warnings"])


def test_zero_volume_bar_does_not_reach_the_return(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    cur["AVB"] = 35.0
    clean = panel(tmp_path, [week("2026-08-14", prev),
                             week("2026-08-21", cur, volumes={"AVB": 0})])
    res = cm.compute(clean, BASKETS, None)["sectors"]["Real Estate"]["week"]
    # Every surviving name rose 1%, so the basket must read exactly 1%.
    assert res["equal_weight_return_pct"] == pytest.approx(1.0, abs=1e-6)
    assert res["positive_return_breadth_pct"] == 100.0


def test_null_or_zero_close_is_excluded(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    cur["AVB"] = 0
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    res = cm.compute(p, BASKETS, None)["sectors"]["Real Estate"]["week"]
    assert "AVB" in [m["ticker"] for m in res["missing"]]


# --- Gate 3: extreme moves are flagged but NOT dropped. Real crashes happen,
#     and silently excluding them would be worse than reporting them.
def test_extreme_move_is_warned_but_retained(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    cur["NEM"] = 145.0
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    res = cm.compute(p, BASKETS, None)
    mat = res["sectors"]["Materials"]["week"]
    assert mat["constituents_used"] == 10
    assert "NEM" in [a["ticker"] for a in mat["anomalies"]]
    assert any("NEM moved" in w for w in res["warnings"])


# --- Gate 4: denominator honesty. A thin basket says so.
def test_thin_basket_is_warned_with_true_denominator(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    for t in SECTORS["Technology"][:7]:
        del cur[t]
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    res = cm.compute(p, BASKETS, None)
    tech = res["sectors"]["Technology"]["week"]
    assert tech["constituents_used"] == 3
    assert tech["constituents_expected"] == 10
    assert tech["coverage_pct"] == 30.0
    assert any("only 3 of 10" in w for w in res["warnings"])


# --- Arithmetic correctness.
def test_breadth_and_median_are_exact(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 100.0)
    for i, t in enumerate(SECTORS["Energy"]):
        cur[t] = 100.0 + (i - 4.5)  # five down, five up, symmetric
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    e = cm.compute(p, BASKETS, None)["sectors"]["Energy"]["week"]
    assert e["positive_return_breadth_pct"] == 50.0
    assert e["median_return_pct"] == pytest.approx(0.0, abs=1e-9)


def test_relative_return_subtracts_the_benchmark(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 102.0)
    cur["SPY"] = 101.0
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    e = cm.compute(p, BASKETS, None)["sectors"]["Energy"]["week"]
    assert e["equal_weight_return_pct"] == pytest.approx(2.0, abs=1e-6)
    assert e["sector_return_vs_spy_pct"] == pytest.approx(1.0, abs=1e-6)


def test_up_volume_share_uses_advancing_volume(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 100.0)
    vols = {}
    for i, t in enumerate(SECTORS["Utilities"]):
        up = i < 3
        cur[t] = 101.0 if up else 99.0
        vols[t] = 300 if up else 100
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur, volumes=vols)])
    e = cm.compute(p, BASKETS, None)["sectors"]["Utilities"]["week"]
    # 3 advancers at 300 = 900; 7 decliners at 100 = 700; 900/1600 = 56.25
    assert e["up_volume_share_pct"] == pytest.approx(56.2, abs=0.1)


def test_missing_benchmark_warns_and_nulls_relative_momentum(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    del cur["SPY"]
    p = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    res = cm.compute(p, BASKETS, None)
    assert any("SPY missing" in w for w in res["warnings"])
    assert res["sectors"]["Energy"]["week"]["sector_return_vs_spy_pct"] is None


# --- The day horizon needs daily bars the upstream feed does not commit.
def test_day_horizon_is_not_offered():
    assert "day" not in cm.HORIZON_WEEKS
    assert set(cm.HORIZON_WEEKS) == {"week", "month"}


def test_short_panel_is_refused_for_the_month_horizon(tmp_path):
    p = panel(tmp_path, [week("2026-08-14", flat(ALL)), week("2026-08-21", flat(ALL))],
              pad=False)
    with pytest.raises(cm.PanelError, match="need 5"):
        cm.compute(p, BASKETS, None)


# --- Corrections supersede originals, per the upstream DATA_FEED contract.
def test_corrected_file_supersedes_the_original(tmp_path):
    prev, cur = flat(ALL, 100.0), flat(ALL, 101.0)
    cur["AVB"] = 35.0
    d = panel(tmp_path, [week("2026-08-14", prev), week("2026-08-21", cur)])
    fixed = week("2026-08-21", {k: v for k, v in cur.items() if k != "AVB"})
    fixed["corrects"] = "2026-08-21.json"
    fixed["missing"] = [{"ticker": "AVB", "reason": "zero-volume bar dropped"}]
    (d / "2026-08-21.corrected.json").write_text(json.dumps(fixed), encoding="utf-8")
    res = cm.compute(d, BASKETS, None)["sectors"]["Real Estate"]["week"]
    assert res["equal_weight_return_pct"] == pytest.approx(1.0, abs=1e-6)


# --- Adjustment anchor. Adjusted closes are back-adjusted to the fetch date,
#     so splicing files fetched far apart makes every payer's pre-ex history
#     disagree. A normal backfill spans days; this catches months.
def test_missing_fetched_at_is_refused(tmp_path):
    weeks = [week("2026-08-14", flat(ALL)), week("2026-08-21", flat(ALL))]
    for w in weeks:
        del w["fetched_at"]
    p = panel(tmp_path, weeks, pad=False)
    with pytest.raises(cm.PanelError, match="no fetched_at"):
        cm.compute(p, BASKETS, None)


def test_ongoing_weekly_panel_is_not_refused(tmp_path):
    """data/weekly is an observation log; fetch dates legitimately span months."""
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07",
            "2026-08-14", "2026-08-21"]
    weeks = [week(d, flat(ALL, 100.0 + i)) for i, d in enumerate(days)]
    for w in weeks:                       # each Friday scan stamps its own date
        w["fetched_at"] = w["as_of"] + "T21:00:00Z"
    res = cm.compute(panel(tmp_path, weeks, pad=False), BASKETS, None)
    assert res["adjustment_anchor"]["week"]["spread_days"] == 7
    assert res["adjustment_anchor"]["month"]["spread_days"] == 28


def test_wide_window_anchor_warns_without_refusing(tmp_path):
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07",
            "2026-08-14", "2026-08-21"]
    weeks = [week(d, flat(ALL, 100.0 + i)) for i, d in enumerate(days)]
    for w in weeks:
        w["fetched_at"] = w["as_of"] + "T21:00:00Z"
    # weeks[-5] is the start of the month window; stamp it well before the end
    weeks[-5]["fetched_at"] = "2026-06-01T21:00:00Z"
    res = cm.compute(panel(tmp_path, weeks, pad=False), BASKETS, None)
    assert res["adjustment_anchor"]["month"]["warn"] is True
    assert any("different anchors" in w for w in res["warnings"])


def test_stale_splice_is_refused(tmp_path):
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07",
            "2026-08-14", "2026-08-21"]
    weeks = [week(d, flat(ALL, 100.0 + i)) for i, d in enumerate(days)]
    for w in weeks:
        w["fetched_at"] = w["as_of"] + "T21:00:00Z"
    weeks[1]["fetched_at"] = "2024-01-05T21:00:00Z"
    with pytest.raises(cm.PanelError, match="days apart"):
        cm.compute(panel(tmp_path, weeks, pad=False), BASKETS, None)


def test_anchor_is_recorded_per_horizon(tmp_path):
    p = panel(tmp_path, [week("2026-08-14", flat(ALL)), week("2026-08-21", flat(ALL))])
    res = cm.compute(p, BASKETS, None)
    assert set(res["adjustment_anchor"]) == {"week", "month"}
    assert set(res["adjustment_anchor"]["week"]) == {
        "earliest", "latest", "spread_days", "warn"}
