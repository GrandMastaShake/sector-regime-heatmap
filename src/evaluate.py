"""Grade a published forecast against what actually happened.

The arithmetic half of a score is disciplined by construction -- breadth,
relative momentum and volume confirmation are computed from the panel and
cannot be argued with. The judgment half, `regime_fit` and `macro_catalyst`,
is disciplined by nothing at all until the call is graded at close. This is
that grading.

    python src/evaluate.py data/forecasts/2026-08-21_manual.json \\
        --panel ../weekly-council-scan/data/weekly

Writes data/evaluations/<as_of>_close.json against
config/evaluation.schema.json.

What this refuses to do matters more than what it computes:

  * It will not grade a horizon whose window has not closed. Grading the week
    horizon before the next Friday close exists in the panel would be scoring
    a forecast against itself.
  * It will not grade a horizon the forecast declared ungradeable. Cycle 1 was
    written five days after the close it reads, and says so; a number produced
    by grading it would look like evidence and be nothing of the kind.
  * It will not assign error labels. Why a call missed is judgment, the same
    kind `regime_fit` is, and it is emitted empty for a human to fill.

An evaluation artifact is immutable once written, like the forecast it grades.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402

HORIZONS = ("week", "month")

# A rating is a directional claim. Grading asks whether the sector did what the
# rating said it would, relative to SPY -- not whether it went up.
EXPECTED = {
    "favorable": "outperform",
    "constructive": "outperform",
    "neutral": "track",
    "unfavorable": "underperform",
    "defensive": "underperform",
}

# Inside this band a sector is treated as having tracked the benchmark rather
# than beaten or missed it. Without it every rating is graded on noise.
TRACK_BAND_PCT = 1.0


class EvaluationError(RuntimeError):
    pass


def ranks(values: list[float]) -> list[float]:
    """Average ranks, so ties do not manufacture ordering."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation. None when it cannot be computed rather than 0.0."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy) ** 0.5, 4)


def ungradeable_horizons(forecast: dict) -> dict:
    """Horizons the forecast itself says must not be graded.

    Preferred form is an explicit `grading` block. Cycle 1 predates it and
    carries the statement in prose, so a deliberately conservative scan of the
    regime's disconfirming evidence is the bridge: it can only ever REFUSE a
    horizon, never permit one, so a false positive costs a grade and a false
    negative is impossible.
    """
    out = {}
    grading = forecast.get("grading") or {}
    for horizon in HORIZONS:
        block = grading.get(horizon) or {}
        if block.get("gradeable") is False:
            out[horizon] = block.get("reason") or "declared ungradeable"
    for line in (forecast.get("regime", {}).get("disconfirming_evidence") or []):
        # Sentence scope, not line scope. Cycle 1's disclosure forbids the week
        # horizon and in a LATER sentence says the month horizon is materially
        # less affected -- matching on the whole line refuses both, which is a
        # false refusal that silently costs a real grade.
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            low = sentence.lower()
            if "must not be graded" not in low:
                continue
            for horizon in HORIZONS:
                if horizon + " horizon" in low and horizon not in out:
                    out[horizon] = sentence.strip()
    return out


def realized(panel_dir: Path, baskets: dict, as_of: str, back: int) -> dict:
    """Basket returns over the window that STARTS at as_of and runs `back` weeks."""
    weeks = cm.load_panel(panel_dir)
    cm.check_basis(weeks)
    dates = [w["as_of"] for w in weeks]
    if as_of not in dates:
        raise EvaluationError(
            "The panel has no weekly file for the forecast date " + as_of
            + ", so the window cannot be anchored."
        )
    start = dates.index(as_of)
    end = start + back
    if end >= len(dates):
        raise EvaluationError(
            "WINDOW NOT CLOSED: grading this horizon needs the weekly file "
            + str(back) + " week(s) after " + as_of + ". The panel ends at "
            + dates[-1] + ". Grading now would score the forecast against "
            "itself."
        )
    window = weeks[: end + 1]
    sectors = {k: v for k, v in baskets.items() if k not in ("version", "note")}

    bench = cm.horizon_returns(window, [cm.BENCHMARK], back)
    bench_return = bench["returns"].get(cm.BENCHMARK, {}).get("return_pct")
    if bench_return is None:
        raise EvaluationError(
            cm.BENCHMARK + " has no return over " + as_of + ".." + dates[end]
            + "; relative performance is undefined without it."
        )

    out = {}
    for sector, tickers in sectors.items():
        block = cm.horizon_returns(window, tickers, back)
        m = cm.basket_metrics(block, bench_return, len(tickers))
        out[sector] = {
            "basket_return_pct": m["equal_weight_return_pct"],
            "return_vs_spy_pct": m["sector_return_vs_spy_pct"],
            "positive_return_breadth_pct": m["positive_return_breadth_pct"],
            "up_volume_share_pct": m["up_volume_share_pct"],
            "constituents_used": m["constituents_used"],
            "constituents_expected": m["constituents_expected"],
        }
    return {"window_from": as_of, "window_to": dates[end],
            "benchmark_return_pct": bench_return, "sectors": out}


def outcome_of(rating: str, excess: float | None) -> str:
    """hit / miss / partial for one directional claim."""
    if excess is None:
        return "no_data"
    expected = EXPECTED.get(rating)
    if expected is None:
        return "no_data"
    if abs(excess) <= TRACK_BAND_PCT:
        actual = "track"
    elif excess > 0:
        actual = "outperform"
    else:
        actual = "underperform"
    if actual == expected:
        return "hit"
    if "track" in (actual, expected):
        return "partial"
    return "miss"


def grade_horizon(forecast: dict, panel_dir: Path, baskets: dict,
                  horizon: str, back: int) -> dict:
    scores = forecast["scores"]
    result = realized(panel_dir, baskets, forecast["as_of_date"], back)

    rows, fc_scores, actual = {}, [], []
    for sector, row in sorted(scores.items()):
        block = row.get(horizon) or {}
        score = block.get("score")
        real = result["sectors"].get(sector)
        if score is None or real is None:
            rows[sector] = {"graded": False,
                            "reason": "no score" if score is None else "no panel data"}
            continue
        excess = real["return_vs_spy_pct"]
        rows[sector] = {
            "graded": True,
            "forecast_score": score,
            "forecast_rating": block.get("rating"),
            "forecast_confidence": block.get("confidence"),
            "basket_return_pct": real["basket_return_pct"],
            "return_vs_spy_pct": excess,
            "outcome": outcome_of(block.get("rating"), excess),
            "constituents_used": real["constituents_used"],
            "constituents_expected": real["constituents_expected"],
        }
        if excess is not None:
            fc_scores.append(score)
            actual.append(excess)

    graded = [r for r in rows.values() if r.get("graded")]
    hits = sum(1 for r in graded if r["outcome"] == "hit")
    misses = sum(1 for r in graded if r["outcome"] == "miss")
    partials = sum(1 for r in graded if r["outcome"] == "partial")

    by_conf: dict[str, dict] = {}
    for r in graded:
        b = by_conf.setdefault(r["forecast_confidence"] or "unknown",
                               {"n": 0, "hits": 0, "misses": 0})
        b["n"] += 1
        b["hits"] += r["outcome"] == "hit"
        b["misses"] += r["outcome"] == "miss"

    return {
        "graded": True,
        "window_from": result["window_from"],
        "window_to": result["window_to"],
        "benchmark_return_pct": result["benchmark_return_pct"],
        "rank_correlation": spearman(fc_scores, actual),
        "hits": hits, "misses": misses, "partial": partials,
        "sectors_graded": len(graded),
        "calibration_by_confidence": by_conf,
        "sectors": rows,
    }


def evaluate(forecast_path: Path, panel_dir: Path, baskets: dict) -> dict:
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    refused = ungradeable_horizons(forecast)
    horizons: dict[str, dict] = {}

    for horizon in HORIZONS:
        if horizon in refused:
            horizons[horizon] = {
                "graded": False,
                "refused": "declared ungradeable by the forecast",
                "detail": refused[horizon],
            }
            continue
        try:
            horizons[horizon] = grade_horizon(
                forecast, panel_dir, baskets, horizon, cm.HORIZON_WEEKS[horizon])
        except EvaluationError as e:
            horizons[horizon] = {"graded": False, "refused": str(e)}

    graded_any = [h for h in horizons.values() if h.get("graded")]
    needs_labels = sorted({
        sector
        for h in graded_any
        for sector, r in h["sectors"].items()
        if r.get("outcome") == "miss"
    })

    bench = next((h["benchmark_return_pct"] for h in graded_any), None)
    return {
        "as_of_date": forecast["as_of_date"],
        "forecast_artifact": str(forecast_path).replace("\\", "/"),
        "evaluated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "benchmark_return": bench if bench is not None else 0.0,
        "sector_outcomes": {h: horizons[h].get("sectors", {}) for h in HORIZONS},
        "horizons": horizons,
        # Why a call missed is judgment, the same kind regime_fit is. It is
        # emitted empty on purpose; a label picked by this script would be a
        # guess wearing a schema.
        "error_labels": [],
        "labels_required_for": needs_labels,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("forecast", type=Path)
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--baskets", type=Path,
                    default=ROOT / "config/sector_baskets.yaml")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data/evaluations")
    args = ap.parse_args(argv)

    baskets = yaml.safe_load(args.baskets.read_text(encoding="utf-8"))
    doc = evaluate(args.forecast, args.panel, baskets)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / (doc["as_of_date"] + "_close.json")
    if out.exists():
        raise SystemExit(
            str(out) + " already exists. Evaluation artifacts are immutable, "
            "like the forecasts they grade; write a dated correction instead.")

    graded = {h: b for h, b in doc["horizons"].items() if b.get("graded")}
    if not graded:
        for horizon, block in doc["horizons"].items():
            print("REFUSED " + horizon + ": " + block.get("refused", "unknown"))
            if block.get("detail"):
                print("  " + block["detail"][:300])
        print("")
        print("Nothing was gradeable, so no artifact was written. That is the "
              "correct outcome when the windows have not closed.")
        return 2

    out.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
                   encoding="utf-8", newline="\n")
    print("Wrote " + str(out))
    for horizon, block in doc["horizons"].items():
        if not block.get("graded"):
            print("  " + horizon + ": REFUSED -- " + block.get("refused", "")[:120])
            continue
        print("  " + horizon + " " + block["window_from"] + ".."
              + block["window_to"] + ": " + str(block["hits"]) + " hit / "
              + str(block["partial"]) + " partial / " + str(block["misses"])
              + " miss, rank correlation "
              + ("n/a" if block["rank_correlation"] is None
                 else str(block["rank_correlation"])))
    if doc["labels_required_for"]:
        print("")
        print("OUTSTANDING -- error_labels is empty and these sectors missed:")
        for s in doc["labels_required_for"]:
            print("  " + s)
        print("Pick from config/evaluation.schema.json; a label is judgment, "
              "not something this script should guess.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
