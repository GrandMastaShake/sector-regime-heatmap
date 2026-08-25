"""The approved watchlist is the source of truth for basket membership."""
from __future__ import annotations

import csv
import datetime
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


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


def test_watchlist_has_110_unique_tickers():
    r = rows()
    assert len(r) == 110
    assert len({x["Ticker"] for x in r}) == 110


def test_watchlist_matches_declared_universe_size():
    wl = yaml.safe_load((ROOT / "config/watchlist.yaml").read_text(encoding="utf-8"))
    assert len(rows()) == wl["universe_size"]


def test_every_sector_has_exactly_ten_names():
    counts: dict[str, int] = {}
    for r in rows():
        counts[r["Sector"]] = counts.get(r["Sector"], 0) + 1
    assert len(counts) == 11
    assert set(counts.values()) == {10}


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
