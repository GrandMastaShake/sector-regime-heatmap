"""The approved watchlist is the source of truth for basket membership.

Since 2026-09-21 the watchlist is the owner's own Finviz list, and no test here
assumes a basket size. Counts come from config/watchlist_110.csv itself -- the
filename is historical -- and the one declared number is universe_size in
config/watchlist.yaml, which exists so that a dropped row is caught rather than
silently regenerated into a smaller basket.
"""
from __future__ import annotations

import csv
import datetime
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402
import macro_comparisons as mc  # noqa: E402
import preflight  # noqa: E402


def rows():
    out = list(csv.DictReader((ROOT / "config/watchlist_110.csv").open(encoding="utf-8")))
    for r in out:
        r["mc"] = float(r["MarketCap_USD_Billions"])
    return out


def baskets():
    d = yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if k not in ("version", "note")}


def overrides():
    return yaml.safe_load((ROOT / "config/watchlist_overrides.yaml").read_text(encoding="utf-8"))


def test_watchlist_tickers_are_unique():
    r = rows()
    assert len({x["Ticker"] for x in r}) == len(r)


def test_watchlist_matches_declared_universe_size():
    wl = yaml.safe_load((ROOT / "config/watchlist.yaml").read_text(encoding="utf-8"))
    assert len(rows()) == wl["universe_size"]


def test_watchlist_covers_the_eleven_gics_sectors():
    assert len({r["Sector"] for r in rows()}) == 11


def test_basket_sizes_are_the_watchlist_counts():
    """Every basket is exactly as large as its sector's rows in the CSV --
    never an assumed ten."""
    counts = Counter(r["Sector"] for r in rows())
    assert {s: len(ts) for s, ts in baskets().items()} == dict(counts)


def test_every_basket_clears_the_data_quality_floor():
    """The floor does not move with the list. A basket that starts below
    MIN_CONSTITUENTS would be data_quality fail on every run."""
    for sector, tickers in baskets().items():
        assert len(tickers) >= cm.MIN_CONSTITUENTS, sector


# --- The owner's decisions of 2026-09-21.
def test_avb_left_the_watchlist():
    """AVB was never on the owner's list; it was added to give Real Estate a
    tenth name, and it stopped trading on 2026-08-18."""
    assert "AVB" not in {r["Ticker"] for r in rows()}
    assert all("AVB" not in ts for ts in baskets().values())


def test_comparison_instruments_are_not_sector_members():
    """BTC and GLD are on the owner's list but are comparison rows, like DXY.
    None of them may enter a basket."""
    listed = {r["Ticker"] for r in rows()}
    placed = {t for ts in baskets().values() for t in ts}
    for inst in mc.INSTRUMENTS:
        assert inst["ticker"] not in listed
        assert inst["ticker"] not in placed


# --- The two preflight gates that replaced "exactly ten per sector".
@pytest.fixture
def preflight_errors(monkeypatch):
    errs: list[str] = []
    monkeypatch.setattr(preflight, "errors", errs)
    return errs


def test_preflight_refuses_a_basket_under_the_floor(preflight_errors):
    floor = cm.MIN_CONSTITUENTS
    preflight.check_basket_floor(
        {"version": 2, "Real Estate": ["T" + str(i) for i in range(floor - 1)],
         "Energy": ["E" + str(i) for i in range(floor)]}, floor)
    assert len(preflight_errors) == 1
    assert "Real Estate" in preflight_errors[0]


def test_preflight_accepts_the_committed_baskets(preflight_errors):
    preflight.check_basket_floor(
        yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8")),
        cm.MIN_CONSTITUENTS)
    preflight.check_comparisons_are_not_sectors(
        yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8")),
        rows(), mc.INSTRUMENTS)
    assert preflight_errors == []


def test_preflight_refuses_a_comparison_instrument_in_a_basket(preflight_errors):
    b = {"version": 2, "Materials": ["LIN", "NEM", "GLD"]}
    preflight.check_comparisons_are_not_sectors(
        b, [{"Ticker": "BTC", "Sector": "Financials"}], mc.INSTRUMENTS)
    assert any("GLD" in e and "Materials" in e for e in preflight_errors)
    assert any("BTC" in e and "watchlist_110.csv" in e for e in preflight_errors)


def test_baskets_match_the_approved_watchlist_exactly():
    approved: dict[str, str] = {r["Ticker"]: r["Sector"] for r in rows()}
    flat = {t: s for s, ts in baskets().items() for t in ts}
    assert flat == approved


def test_baskets_are_ordered_by_descending_market_cap():
    mc = {r["Ticker"]: r["mc"] for r in rows()}
    for sector, tickers in baskets().items():
        caps = [mc[t] for t in tickers]
        assert caps == sorted(caps, reverse=True), sector


# --- Regenerating from the CSV must be idempotent, or the YAML can drift.
def test_sector_baskets_yaml_is_in_sync_with_the_csv():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sync_baskets.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# --- The spreadsheet CapTier column is not an ordering. Nothing may rely on it.
def test_source_cap_tier_column_is_known_to_be_non_monotonic():
    rank = {"Mega": 0, "Large": 1, "Mid": 2, "Micro": 3}
    r = rows()
    inverted = [a["Ticker"] for a in r
                if any(rank[a["CapTier"]] > rank[c["CapTier"]] and a["mc"] > c["mc"] for c in r)]
    # Documented in config/watchlist_overrides.yaml. If this ever hits zero the
    # source spreadsheet was fixed and the advisory note can be retired.
    assert len(inverted) == 26


def test_derived_cap_tiers_are_monotonic():
    b = overrides()["cap_tier_boundaries_usd_billions"]
    ordered = sorted(b.items(), key=lambda kv: kv[1], reverse=True)

    def tier(mc):
        for label, floor in ordered:
            if mc >= floor:
                return label
        return ordered[-1][0]

    ranges: dict[str, list[float]] = {}
    for r in rows():
        ranges.setdefault(tier(r["mc"]), []).append(r["mc"])
    labels = [label for label, _ in ordered if label in ranges]
    for hi, lo in zip(labels, labels[1:]):
        assert min(ranges[hi]) > max(ranges[lo])


# --- SPCX listed 2026-06-12 and cannot supply month-horizon trailing metrics
#     for the 2026-08-24 snapshot. It is the largest Industrials constituent.
def test_spcx_history_constraint_is_recorded():
    spcx = overrides()["listings"]["SPCX"]
    first = spcx["first_trade_date"]
    if isinstance(first, str):
        first = datetime.date.fromisoformat(first)
    assert first == datetime.date(2026, 6, 12)
    assert "three_month_relative_return_pct" in spcx["insufficient_history_for"]


def test_names_with_history_constraints_are_on_the_watchlist():
    tickers = {r["Ticker"] for r in rows()}
    for t in overrides().get("listings", {}):
        assert t in tickers


def test_spcx_is_the_largest_industrials_constituent():
    assert baskets()["Industrials"][0] == "SPCX"
