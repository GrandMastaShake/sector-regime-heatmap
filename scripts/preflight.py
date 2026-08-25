"""Repo preflight: fail loudly on config drift before any run or commit.

Run this locally and in CI. It is cheap and it catches the class of bug that
otherwise ships silently: three copies of the same weights that disagree.
"""
from __future__ import annotations

import csv
import datetime
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = (
    "regime_fit",
    "breadth",
    "relative_momentum",
    "volume_confirmation",
    "macro_catalyst",
)
HORIZONS = ("day", "week", "month")

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def check_weights_sum(weights_doc: dict) -> None:
    for h in HORIZONS:
        w = weights_doc["horizons"][h]
        total = sum(w[c] for c in COMPONENTS)
        if abs(total - 1.0) > 1e-6:
            fail(
                "config/score_weights.yaml: " + h + " component weights sum to "
                + format(total, ".4f") + ", not 1.0"
            )


def check_bands(weights_doc: dict) -> None:
    bands = weights_doc["bands"]
    floors = sorted(bands.values())
    if len(set(floors)) != len(floors):
        fail("config/score_weights.yaml: duplicate band floors")
    if min(floors) != 0:
        fail("config/score_weights.yaml: needs a band floor at 0 to cover all scores")


def load_watchlist() -> list[dict]:
    rows = list(csv.DictReader((ROOT / "config/watchlist_110.csv").open(encoding="utf-8")))
    for r in rows:
        r["mc"] = float(r["MarketCap_USD_Billions"])
    return rows


def check_baskets(baskets: dict, rows: list[dict]) -> None:
    sectors = [k for k in baskets if k not in ("version", "note")]
    if len(sectors) != 11:
        fail("config/sector_baskets.yaml: expected 11 GICS sectors, found " + str(len(sectors)))
    seen: dict[str, str] = {}
    for sector in sectors:
        names = baskets[sector]
        if len(names) != len(set(names)):
            fail("config/sector_baskets.yaml: duplicate ticker within " + sector)
        for t in names:
            if t in seen:
                fail(
                    "config/sector_baskets.yaml: ticker " + t + " appears in both "
                    + seen[t] + " and " + sector
                )
            seen[t] = sector

    watchlist = yaml.safe_load((ROOT / "config/watchlist.yaml").read_text(encoding="utf-8"))
    if len(seen) != watchlist["universe_size"]:
        fail(
            "sector_baskets holds " + str(len(seen)) + " unique tickers but watchlist.yaml "
            "declares universe_size " + str(watchlist["universe_size"])
        )

    # --- Baskets must match the approved watchlist exactly, not just in count.
    approved: dict[str, str] = {}
    for r in rows:
        if r["Ticker"] in approved:
            fail("config/watchlist_110.csv: duplicate ticker " + r["Ticker"])
        approved[r["Ticker"]] = r["Sector"]
    if len(approved) != watchlist["universe_size"]:
        fail(
            "watchlist_110.csv has " + str(len(approved)) + " tickers but watchlist.yaml "
            "declares universe_size " + str(watchlist["universe_size"])
        )
    for t, sector in sorted(seen.items()):
        if t not in approved:
            fail("basket ticker " + t + " (" + sector + ") is not on the approved watchlist")
        elif approved[t] != sector:
            fail(
                "sector mismatch for " + t + ": baskets say " + sector
                + ", watchlist says " + approved[t]
            )
    for t, sector in sorted(approved.items()):
        if t not in seen:
            fail("approved watchlist ticker " + t + " (" + sector + ") is in no basket")

    # --- Order carries meaning: top_two_contribution reads index 0 and 1.
    for sector in sectors:
        caps = [next(r["mc"] for r in rows if r["Ticker"] == t)
                for t in baskets[sector] if t in approved]
        if caps != sorted(caps, reverse=True):
            fail(
                sector + " basket is not ordered by descending market cap; "
                "run scripts/sync_baskets.py"
            )


def check_cap_tiers(rows: list[dict], overrides: dict) -> None:
    """Validate the derived boundaries, and report the source column's inversions."""
    b = overrides["cap_tier_boundaries_usd_billions"]
    canonical = ["Mega", "Large", "Mid", "Micro"]
    if sorted(b) != sorted(canonical):
        fail("watchlist_overrides.yaml: cap tiers must be exactly " + ", ".join(canonical))
        return
    floors = [b[label] for label in canonical]
    if floors != sorted(set(floors), reverse=True):
        fail(
            "watchlist_overrides.yaml: boundaries must decrease Mega > Large > Mid > Micro, got "
            + ", ".join(label + "=" + str(b[label]) for label in canonical)
        )
    ordered = [(label, b[label]) for label in canonical]
    if min(floors) != 0:
        fail("watchlist_overrides.yaml: cap tier boundaries need a floor at 0")

    def tier(mc: float) -> str:
        for label, floor in ordered:
            if mc >= floor:
                return label
        return ordered[-1][0]

    # The CapTier column transcribed from the spreadsheet is advisory. Count how
    # far it diverges from the derived tier so the drift stays visible.
    diverged = [r for r in rows if r["CapTier"] != tier(r["mc"])]
    if diverged:
        print(
            "  NOTE " + str(len(diverged)) + " of " + str(len(rows))
            + " CapTier labels in watchlist_110.csv disagree with the derived tier"
            + " (column is advisory; see config/watchlist_overrides.yaml)"
        )

    # The source column must at minimum not be self-contradictory in a way that
    # would break any future concentration logic reading it directly.
    rank = {label: i for i, (label, _) in enumerate(ordered)}
    inversions = 0
    for a in rows:
        for c in rows:
            if rank.get(a["CapTier"], 99) > rank.get(c["CapTier"], 99) and a["mc"] > c["mc"]:
                inversions += 1
                break
    if inversions:
        print(
            "  NOTE " + str(inversions) + " names carry a smaller CapTier label than a"
            " name with a lower market cap; do not read CapTier as an ordering"
        )


def check_listing_history(rows: list[dict], overrides: dict) -> None:
    """A constituent without enough history cannot silently supply a metric."""
    tickers = {r["Ticker"] for r in rows}
    sessions = overrides["minimum_sessions"]
    for ticker, meta in (overrides.get("listings") or {}).items():
        if ticker not in tickers:
            fail("watchlist_overrides.yaml lists " + ticker + ", which is not on the watchlist")
            continue
        first = meta["first_trade_date"]
        if isinstance(first, str):
            first = datetime.date.fromisoformat(first)
        blocked = meta.get("insufficient_history_for") or []
        if not blocked:
            continue
        # Roughly 21 trading sessions per calendar month.
        need_days = int(sessions["month"] / 21 * 30.4)
        clear_on = first + datetime.timedelta(days=need_days)
        for d in sorted((ROOT / "data/weekly_research").iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            try:
                as_of = datetime.date.fromisoformat(d.name)
            except ValueError:
                continue
            if as_of < clear_on:
                print(
                    "  NOTE " + ticker + " listed " + first.isoformat()
                    + "; month-horizon metrics " + ", ".join(blocked)
                    + " are not computable for the " + d.name
                    + " snapshot (clears " + clear_on.isoformat() + ")"
                )


def check_council_config(cfg: dict, baskets: dict) -> None:
    gics = {k for k in baskets if k not in ("version", "note")}
    mapped = set(cfg["sector_sources"])
    if mapped != gics:
        for s in sorted(mapped - gics):
            fail("weekly_council_scan.yaml maps unknown sector: " + s)
        for s in sorted(gics - mapped):
            fail("weekly_council_scan.yaml has no upstream source for sector: " + s)


def check_ascii(paths: list[Path]) -> None:
    for p in paths:
        raw = p.read_bytes()
        bad = [i for i, b in enumerate(raw) if b > 127]
        if bad:
            fail(
                str(p.relative_to(ROOT)).replace("\\", "/")
                + " contains non-ASCII bytes at offset " + str(bad[0])
                + " (repo is ASCII-only for Windows/CI parity)"
            )


def check_snapshot_dirs() -> None:
    root = ROOT / "data/weekly_research"
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        shas = d / "source_file_shas.json"
        manifest = d / "manifest.json"
        if shas.is_file() and not manifest.is_file():
            fail(
                "data/weekly_research/" + d.name + " pins source SHAs but has no "
                "manifest.json - the import has never been run for this date"
            )
        if manifest.is_file():
            m = json.loads(manifest.read_text(encoding="utf-8"))
            for key in ("as_of_date", "imported_at_utc", "source", "source_commit_sha", "files"):
                if key not in m:
                    fail("manifest " + d.name + " violates its own schema: missing " + key)
            if m.get("as_of_date") != d.name:
                fail("manifest " + d.name + " as_of_date is " + str(m.get("as_of_date")))


def main() -> int:
    weights_doc = yaml.safe_load((ROOT / "config/score_weights.yaml").read_text(encoding="utf-8"))
    baskets = yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((ROOT / "config/weekly_council_scan.yaml").read_text(encoding="utf-8"))

    overrides = yaml.safe_load(
        (ROOT / "config/watchlist_overrides.yaml").read_text(encoding="utf-8"))
    rows = load_watchlist()

    check_weights_sum(weights_doc)
    check_bands(weights_doc)
    check_baskets(baskets, rows)
    check_cap_tiers(rows, overrides)
    check_listing_history(rows, overrides)
    check_council_config(cfg, baskets)
    check_snapshot_dirs()

    tracked = sorted(
        list((ROOT / "src").glob("*.py"))
        + list((ROOT / "scripts").glob("*.py"))
        + [p for p in (ROOT / "config").glob("*") if p.suffix != ".csv"]
        + [ROOT / "README.md"]
    )
    check_ascii([p for p in tracked if p.is_file()])

    if errors:
        print("PREFLIGHT FAILED (" + str(len(errors)) + " issue(s)):")
        for e in errors:
            print("  - " + e)
        return 1
    print("PREFLIGHT OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
