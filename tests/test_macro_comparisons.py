"""Gold, the US dollar and bitcoin: comparison rows beside the daily tape.

Decided with the owner on 2026-09-21. Each row is one instrument's return over
the tape's own windows and that return minus SPY's, and nothing else. These
tests hold the lines that matter:

  * the rows are not sectors -- no score, band, breadth or volume component,
    and nothing on the forecast path can read them;
  * each value comes from its one declared source -- GLD and BTC from
    `series`, the dollar index from `fx` -- never from a proxy;
  * a value that does not exist renders as missing, with the reason.

That the eleven sector baskets do not move because the rows exist is held in
tests/test_daily_tape.py, beside the other sector-block tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402
import daily_tape as dt  # noqa: E402
import macro_comparisons as mc  # noqa: E402
import regime_prior as rp  # noqa: E402

BASKETS = {
    "Technology": ["AAA", "BBB", "CCC", "DDD", "EEE",
                   "FFF", "GGG", "HHH", "III", "JJJ"],
    "Energy": ["KKK", "LLL", "MMM", "NNN", "OOO",
               "PPP", "QQQ", "RRR", "SSS", "TTT"],
}
STOCKS = [t for ts in BASKETS.values() for t in ts]

# Six sessions: enough for the day window (1) and the week window (5).
DAYS = ["2026-09-11", "2026-09-14", "2026-09-15",
        "2026-09-16", "2026-09-17", "2026-09-18"]
SPY = [100.0, 100.5, 101.0, 101.5, 101.0, 102.0]
GLD = [200.0, 201.0, 202.0, 204.0, 205.0, 210.0]
DXY = [100.0, 99.5, 99.0, 98.5, 99.0, 98.0]
BTC = [50.0, 51.0, 52.0, 53.0, 54.0, 55.0]


def session(as_of, spy=100.0, gld=None, btc=None, dxy=None, gold_future=None):
    doc = {
        "as_of": as_of, "cadence": "daily", "source": "yahoo-daily",
        "fetched_at": as_of + "T21:00:00Z", "session": "close",
        "series": {t: {"close": 100.0, "volume": 1_000_000} for t in STOCKS},
        "rates": {}, "vol": {}, "commodities": {}, "fx": {}, "missing": [],
    }
    if spy is not None:
        doc["series"]["SPY"] = {"close": spy, "volume": 50_000_000}
    if gld is not None:
        doc["series"]["GLD"] = {"close": gld, "volume": 8_000_000}
    if btc is not None:
        doc["series"]["BTC"] = {"close": btc, "volume": 3_000_000}
    if dxy is not None:
        doc["fx"]["DXY"] = {"close": dxy, "volume": None}
    if gold_future is not None:
        doc["commodities"]["GOLD"] = {"close": gold_future, "volume": 100_000}
    return doc


def full_sessions(**drop):
    """All four instruments on all six sessions, minus anything in `drop`."""
    docs = []
    for i, d in enumerate(DAYS):
        docs.append(session(
            d, spy=SPY[i],
            gld=None if "gld" in drop else GLD[i],
            btc=None if "btc" in drop else BTC[i],
            dxy=None if "dxy" in drop else DXY[i]))
    return docs


def write_panel(tmp_path, docs):
    d = tmp_path / "daily"
    d.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (d / (doc["as_of"] + ".json")).write_text(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8", newline="\n")
    return d


def tape(tmp_path, docs):
    return dt.compute_tape(write_panel(tmp_path, docs), BASKETS)


def pct(new, old):
    return (new / old - 1.0) * 100.0


# -- the arithmetic ------------------------------------------------------------

def test_each_row_is_its_own_return_and_that_minus_spy(tmp_path):
    rows = tape(tmp_path, full_sessions())[mc.BLOCK_KEY]["rows"]
    for ticker, closes in (("GLD", GLD), ("DXY", DXY), ("BTC", BTC)):
        week, day = rows[ticker]["week"], rows[ticker]["day"]
        assert week["return_pct"] == pytest.approx(pct(closes[-1], closes[0]), abs=1e-3)
        assert week["return_vs_spy_pct"] == pytest.approx(
            pct(closes[-1], closes[0]) - pct(SPY[-1], SPY[0]), abs=1e-3)
        assert day["return_pct"] == pytest.approx(pct(closes[-1], closes[-2]), abs=1e-3)
        assert day["return_vs_spy_pct"] == pytest.approx(
            pct(closes[-1], closes[-2]) - pct(SPY[-1], SPY[-2]), abs=1e-3)
        assert (week["close_from"], week["close_to"]) == (closes[0], closes[-1])
        assert week["missing"] == [] and day["missing"] == []


def test_windows_are_the_tapes_own(tmp_path):
    """Same sessions as the sectors, horizon by horizon -- a comparison over a
    different window would not be a comparison."""
    res = tape(tmp_path, full_sessions())
    assert set(dt.HORIZON_SESSIONS) == {"day", "week"}
    for horizon, back in dt.HORIZON_SESSIONS.items():
        sector = res["sectors"]["Technology"][horizon]
        for row in res[mc.BLOCK_KEY]["rows"].values():
            assert row[horizon]["sessions"] == back
            assert row[horizon]["window_from"] == sector["window_from"]
            assert row[horizon]["window_to"] == sector["window_to"]


# -- one declared source per row, never a proxy --------------------------------

def test_the_sources_are_pinned():
    assert [(i["ticker"], i["block"]) for i in mc.INSTRUMENTS] == [
        ("GLD", "series"), ("DXY", "fx"), ("BTC", "series")]


def test_the_dollar_is_read_from_the_fx_block(tmp_path):
    docs = full_sessions()
    for doc in docs:                      # a decoy of the same name elsewhere
        doc["series"]["DXY"] = {"close": 1.0, "volume": 1}
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["DXY"]
    assert row["source"] == "fx.DXY"
    assert row["week"]["return_pct"] == pytest.approx(pct(DXY[-1], DXY[0]), abs=1e-3)


def test_gold_is_never_filled_from_the_gold_commodity(tmp_path):
    """The GOLD futures close in `commodities` is a different instrument.
    With GLD absent, the gold row is missing -- not a proxy."""
    docs = full_sessions(gld=True)
    for i, doc in enumerate(docs):
        doc["commodities"]["GOLD"] = {"close": 4400.0 + i * 10, "volume": 100_000}
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["GLD"]
    for horizon in dt.HORIZON_SESSIONS:
        w = row[horizon]
        assert w["return_pct"] is None
        assert w["return_vs_spy_pct"] is None
        assert w["close_from"] is None and w["close_to"] is None
        assert "absent from series" in w["missing"][0]["reason"]


# -- missing is missing ---------------------------------------------------------

def test_a_row_stays_missing_until_both_ends_of_a_window_exist(tmp_path):
    """How GLD and BTC arrive: the feed carries them from one session on. The
    first session has no day return; the day window fills a session later and
    the week window five sessions later. Nothing is extrapolated backwards."""
    docs = full_sessions(gld=True)
    docs[-1]["series"]["GLD"] = {"close": 210.0, "volume": 8_000_000}
    row = tape(tmp_path / "one", docs)[mc.BLOCK_KEY]["rows"]["GLD"]
    assert row["day"]["return_pct"] is None
    assert "absent from series at " + DAYS[-2] in row["day"]["missing"][0]["reason"]
    assert row["week"]["return_pct"] is None

    docs[-2]["series"]["GLD"] = {"close": 205.0, "volume": 8_000_000}
    row = tape(tmp_path / "two", docs)[mc.BLOCK_KEY]["rows"]["GLD"]
    assert row["day"]["return_pct"] == pytest.approx(pct(210.0, 205.0), abs=1e-3)
    assert row["week"]["return_pct"] is None


def test_the_feeds_own_reason_is_carried(tmp_path):
    docs = full_sessions(btc=True)
    docs[-1]["missing"].append({"ticker": "BTC",
                                "reason": "no bar dated 2026-09-18 in window"})
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["BTC"]
    reason = row["day"]["missing"][0]["reason"]
    assert "absent from series at 2026-09-18" in reason
    assert "the feed says: no bar dated 2026-09-18 in window" in reason


def test_a_zero_volume_bar_is_not_a_trade_here_either(tmp_path):
    docs = full_sessions()
    docs[-1]["series"]["GLD"] = {"close": 70.0, "volume": 0}
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["GLD"]
    assert row["day"]["return_pct"] is None
    assert "zero-volume" in row["day"]["missing"][0]["reason"]


def test_an_empty_fx_block_leaves_the_dollar_missing(tmp_path):
    """The daily files before 2026-09-11 carry `fx: {}`. A window that starts
    on one of them has no dollar return."""
    docs = full_sessions()
    docs[0]["fx"] = {}
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["DXY"]
    assert row["week"]["return_pct"] is None
    assert "absent from fx at " + DAYS[0] in row["week"]["missing"][0]["reason"]
    assert row["day"]["return_pct"] is not None


def test_a_null_dollar_close_is_missing_not_zero(tmp_path):
    docs = full_sessions()
    docs[-1]["fx"]["DXY"] = {"close": None, "volume": None}
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["DXY"]
    assert row["day"]["return_pct"] is None
    assert "null or zero close in fx" in row["day"]["missing"][0]["reason"]


def test_missing_spy_leaves_only_the_relative_return_missing(tmp_path):
    docs = full_sessions()
    docs[-1]["series"].pop("SPY")
    row = tape(tmp_path, docs)[mc.BLOCK_KEY]["rows"]["GLD"]
    assert row["day"]["return_pct"] == pytest.approx(pct(GLD[-1], GLD[-2]), abs=1e-3)
    assert row["day"]["return_vs_spy_pct"] is None
    assert row["day"]["missing"][0]["ticker"] == "SPY"


def test_a_short_panel_leaves_the_week_window_missing(tmp_path):
    rows = tape(tmp_path, full_sessions()[-2:])[mc.BLOCK_KEY]["rows"]
    for row in rows.values():
        assert row["day"]["return_pct"] is not None
        assert row["week"]["return_pct"] is None
        assert row["week"]["window_from"] is None
        assert "needs 6" in row["week"]["missing"][0]["reason"]


def test_an_extreme_move_is_flagged_and_retained(tmp_path):
    docs = full_sessions()
    docs[-1]["series"]["BTC"] = {"close": 75.0, "volume": 3_000_000}
    block = tape(tmp_path, docs)[mc.BLOCK_KEY]
    assert block["rows"]["BTC"]["week"]["return_pct"] == pytest.approx(50.0, abs=1e-3)
    assert any(w.startswith("comparison/BTC/week") for w in block["warnings"])


# -- not a sector, not a score, not an input -----------------------------------

FORBIDDEN_KEY_PARTS = ("score", "band", "rating", "breadth", "volume",
                       "component", "rank", "constituent", "regime_fit",
                       "macro_catalyst", "confidence")


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def test_the_block_carries_no_score_band_breadth_or_volume_component(tmp_path):
    block = tape(tmp_path, full_sessions())[mc.BLOCK_KEY]
    assert block["is_sector"] is False
    for key in _keys(block):
        for part in FORBIDDEN_KEY_PARTS:
            assert part not in key.lower(), key


def test_the_block_sits_outside_the_sectors(tmp_path):
    res = tape(tmp_path, full_sessions())
    assert set(res["sectors"]) == set(BASKETS)
    assert mc.BLOCK_KEY in res and mc.BLOCK_KEY not in res["sectors"]
    assert res["is_forecast"] is False


def test_the_prior_never_ranks_a_comparison_row(tmp_path):
    res = tape(tmp_path, full_sessions())
    cmp_block = rp.compare(res, 1)
    assert set(cmp_block["sectors"]) == set(BASKETS)
    assert cmp_block["sectors"]["Technology"]["tape_rank_of"] == len(BASKETS)


FORECAST_PATH = ("src/compute_metrics.py", "src/make_sector_inputs.py",
                 "src/assemble_payload.py", "src/heatmap.py",
                 "src/evaluate.py", "scripts/stage_run.py")


@pytest.mark.parametrize("rel", FORECAST_PATH)
def test_the_forecast_path_never_reads_the_rows(rel):
    """Never in a forecast, an input payload or an evaluation. The simplest
    guarantee is that nothing on that path can reach the module."""
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "macro_comparisons" not in src
    assert mc.BLOCK_KEY not in src


def test_weekly_metrics_carry_no_comparison_rows(tmp_path):
    """The weekly panel carries GLD, BTC and DXY too. The metrics that feed a
    forecast read the baskets and SPY, and nothing else."""
    d = tmp_path / "weekly"
    d.mkdir()
    days = ["2026-08-21", "2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18"]
    for i, day in enumerate(days):
        doc = session(day, spy=100.0 + i, gld=200.0 + i, btc=50.0 + i, dxy=99.0 + i)
        doc.pop("cadence")
        doc["source"] = "yahoo"
        (d / (day + ".json")).write_text(json.dumps(doc), encoding="utf-8",
                                         newline="\n")
    res = cm.compute(d, BASKETS, None)
    assert mc.BLOCK_KEY not in res
    assert set(res["sectors"]) == set(BASKETS)
    blob = json.dumps(res)
    for inst in mc.INSTRUMENTS:
        assert inst["ticker"] not in blob


def test_a_comparison_row_cannot_be_assembled_as_a_sector(tmp_path):
    from test_assemble import build

    def mutate(sd):
        doc = json.loads((sd / "energy.json").read_text(encoding="utf-8"))
        doc["sector"] = "Gold"
        (sd / "gold.json").write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError, match="not a GICS sector"):
        build(tmp_path, mutate)
