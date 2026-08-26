"""Evaluation gates. The judgment half of a score is disciplined only here.

Every test records a way a grade could be produced that looks like evidence
and is not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate as ev  # noqa: E402

BASKETS = yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
SECTORS = {k: v for k, v in BASKETS.items() if k not in ("version", "note")}
ALL = sorted({t for ts in SECTORS.values() for t in ts} | {"SPY"})

WEEKS = ["2026-07-24", "2026-07-31", "2026-08-07", "2026-08-14", "2026-08-21",
         "2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18"]


def week(as_of: str, closes: dict) -> dict:
    return {
        "as_of": as_of, "source": "yahoo", "fetched_at": as_of + "T21:00:00Z",
        "session": "close",
        "series": {t: {"close": c, "volume": 1_000_000} for t, c in closes.items()},
        "missing": [],
    }


def panel(tmp_path: Path, through: str, closes_by_date=None) -> Path:
    """A panel ending at `through`, flat at 100 unless told otherwise."""
    d = tmp_path / "weekly"
    d.mkdir(exist_ok=True)
    for day in WEEKS:
        if day > through:
            break
        closes = (closes_by_date or {}).get(day) or {t: 100.0 for t in ALL}
        (d / (day + ".json")).write_text(json.dumps(week(day, closes)),
                                         encoding="utf-8")
    return d


def forecast(scores: dict, as_of: str = "2026-08-21", **over) -> dict:
    doc = {
        "as_of_date": as_of, "run_type": "manual",
        "regime": {"label": "test", "confidence": "medium",
                   "evidence": [], "disconfirming_evidence": []},
        "scores": scores,
    }
    doc.update(over)
    return doc


def scored(rating_by_sector: dict, score: float = 60.0) -> dict:
    out = {}
    for sector in SECTORS:
        rating = rating_by_sector.get(sector, "neutral")
        block = {"score": score, "rating": rating, "confidence": "medium",
                 "why": ["a", "b"], "risks": ["r"]}
        out[sector] = {"day": {"score": None, "rating": "unavailable"},
                       "week": dict(block), "month": dict(block)}
    return out


def write_forecast(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "forecast.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# --- Grading a window that has not closed is scoring a forecast against
#     itself. The panel ending at the forecast date is the common case: the
#     evaluation runs before the next Friday exists.
def test_open_window_is_refused(tmp_path):
    doc = ev.evaluate(write_forecast(tmp_path, forecast(scored({}))),
                      panel(tmp_path, "2026-08-21"), BASKETS)
    for horizon in ("week", "month"):
        assert doc["horizons"][horizon]["graded"] is False
        assert "WINDOW NOT CLOSED" in doc["horizons"][horizon]["refused"]


def test_week_grades_once_its_friday_exists_but_month_still_waits(tmp_path):
    doc = ev.evaluate(write_forecast(tmp_path, forecast(scored({}))),
                      panel(tmp_path, "2026-08-28"), BASKETS)
    assert doc["horizons"]["week"]["graded"] is True
    assert doc["horizons"]["week"]["window_to"] == "2026-08-28"
    assert doc["horizons"]["month"]["graded"] is False


# --- Cycle 1 was written five days after the close it reads and says so. A
#     grade computed from it would look like evidence and be nothing of the
#     kind.
def test_horizon_the_forecast_declared_ungradeable_is_refused(tmp_path):
    f = forecast(scored({}))
    f["regime"]["disconfirming_evidence"] = [
        "MID-CYCLE MANUAL RUN: two of five sessions had already traded. "
        "The week horizon is nonetheless NOT a clean ex-ante forecast and "
        "must not be graded as one."
    ]
    doc = ev.evaluate(write_forecast(tmp_path, f), panel(tmp_path, "2026-09-18"),
                      BASKETS)
    assert doc["horizons"]["week"]["graded"] is False
    assert "ungradeable" in doc["horizons"]["week"]["refused"]


# --- Regression: the first version matched on the whole evidence line, and
#     cycle 1's disclosure forbids the week horizon in one sentence and calls
#     the month "materially less affected" in the NEXT one. Line-scope
#     matching refused both -- a false refusal that silently costs a real
#     grade. Scope is per sentence.
def test_a_later_sentence_about_another_horizon_does_not_refuse_it(tmp_path):
    f = forecast(scored({}))
    f["regime"]["disconfirming_evidence"] = [
        "The week horizon is NOT a clean ex-ante forecast and must not be "
        "graded as one. The month horizon is materially less affected."
    ]
    doc = ev.evaluate(write_forecast(tmp_path, f), panel(tmp_path, "2026-09-18"),
                      BASKETS)
    assert doc["horizons"]["week"]["graded"] is False
    assert doc["horizons"]["month"]["graded"] is True, (
        "the month was refused by a sentence that permits it")


def test_explicit_grading_block_is_honoured(tmp_path):
    f = forecast(scored({}))
    f["grading"] = {"week": {"gradeable": False, "reason": "scored late"}}
    doc = ev.evaluate(write_forecast(tmp_path, f), panel(tmp_path, "2026-09-18"),
                      BASKETS)
    assert doc["horizons"]["week"]["graded"] is False
    assert doc["horizons"]["week"]["detail"] == "scored late"


# --- The grade itself.
def _moving_panel(tmp_path):
    """SPY flat; Technology up 10 percent; Utilities down 10 percent."""
    tech = set(SECTORS["Technology"])
    utes = set(SECTORS["Utilities"])
    later = {}
    for t in ALL:
        later[t] = 110.0 if t in tech else 90.0 if t in utes else 100.0
    later["SPY"] = 100.0
    return panel(tmp_path, "2026-08-28", {"2026-08-28": later})


def test_a_correct_call_is_a_hit_and_a_backwards_one_is_a_miss(tmp_path):
    f = forecast(scored({"Technology": "favorable", "Utilities": "favorable"}))
    doc = ev.evaluate(write_forecast(tmp_path, f), _moving_panel(tmp_path), BASKETS)
    wk = doc["horizons"]["week"]["sectors"]
    assert wk["Technology"]["outcome"] == "hit"
    assert wk["Utilities"]["outcome"] == "miss"
    assert wk["Technology"]["return_vs_spy_pct"] > 0
    assert wk["Utilities"]["return_vs_spy_pct"] < 0


def test_a_sector_that_tracked_the_benchmark_is_partial_not_a_miss(tmp_path):
    f = forecast(scored({"Healthcare": "favorable"}))
    doc = ev.evaluate(write_forecast(tmp_path, f), _moving_panel(tmp_path), BASKETS)
    # Healthcare is flat and SPY is flat, so it tracked.
    assert doc["horizons"]["week"]["sectors"]["Healthcare"]["outcome"] == "partial"


def test_rank_correlation_is_none_rather_than_zero_when_undefined(tmp_path):
    # Every sector carries the same score, so the forecast has no ordering.
    doc = ev.evaluate(write_forecast(tmp_path, forecast(scored({}))),
                      _moving_panel(tmp_path), BASKETS)
    assert doc["horizons"]["week"]["rank_correlation"] is None


def test_spearman_ranks_ties_without_inventing_order():
    assert ev.ranks([5, 5, 9]) == [1.5, 1.5, 3.0]
    assert ev.spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert ev.spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert ev.spearman([1, 2], [1, 2]) is None       # too few
    assert ev.spearman([1, 1, 1], [1, 2, 3]) is None  # no variance


# --- Why a call missed is judgment, the same kind regime_fit is. A label
#     chosen by the script would be a guess wearing a schema.
def test_error_labels_are_never_auto_assigned(tmp_path):
    f = forecast(scored({"Utilities": "favorable"}))
    doc = ev.evaluate(write_forecast(tmp_path, f), _moving_panel(tmp_path), BASKETS)
    assert doc["error_labels"] == []
    assert "Utilities" in doc["labels_required_for"]


def test_artifact_satisfies_the_schema(tmp_path):
    import jsonschema
    schema = json.loads((ROOT / "config/evaluation.schema.json").read_text(encoding="utf-8"))
    f = forecast(scored({"Technology": "favorable"}))
    doc = ev.evaluate(write_forecast(tmp_path, f), _moving_panel(tmp_path), BASKETS)
    jsonschema.validate(doc, schema)


def test_evaluation_artifact_is_immutable(tmp_path):
    f = write_forecast(tmp_path, forecast(scored({"Technology": "favorable"})))
    out = tmp_path / "evals"
    argv = [str(f), "--panel", str(_moving_panel(tmp_path)),
            "--output-dir", str(out)]
    assert ev.main(argv) == 0
    with pytest.raises(SystemExit, match="immutable"):
        ev.main(argv)


def test_nothing_gradeable_writes_no_artifact(tmp_path):
    f = write_forecast(tmp_path, forecast(scored({})))
    out = tmp_path / "evals"
    assert ev.main([str(f), "--panel", str(panel(tmp_path, "2026-08-21")),
                    "--output-dir", str(out)]) == 2
    assert not out.exists() or not list(out.glob("*.json"))
