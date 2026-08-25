"""Regression tests. Each test name records a bug that shipped in v1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import heatmap  # noqa: E402

COMPONENTS = heatmap.COMPONENTS
BANDS = {"favorable": 70, "constructive": 55, "neutral": 45, "unfavorable": 30, "defensive": 0}


def weights(horizon: str = "week") -> dict:
    doc = yaml.safe_load((ROOT / "config/score_weights.yaml").read_text(encoding="utf-8"))
    return dict(doc["horizons"][horizon])


def sector(value: float = 50, **over) -> dict:
    d = {"components": {c: value for c in COMPONENTS}, "risk_penalty": 0.0,
         "why": ["a", "b"], "risks": ["r"]}
    d.update(over)
    return d


# --- Bug: every horizon's weights summed to 0.95, so 100/100 topped out at 95.
@pytest.mark.parametrize("horizon", ["day", "week", "month"])
def test_weights_sum_to_one(horizon):
    w = weights(horizon)
    assert abs(sum(w[c] for c in COMPONENTS) - 1.0) < 1e-9


@pytest.mark.parametrize("horizon", ["day", "week", "month"])
def test_perfect_sector_scores_100(horizon):
    r = heatmap.score_sector(sector(100), weights(horizon), BANDS)
    assert r["score"] == 100.0
    assert r["rating"] == "favorable"


def test_unnormalized_weights_are_rejected():
    w = weights()
    w["regime_fit"] = w["regime_fit"] - 0.05
    with pytest.raises(ValueError, match="sum to"):
        heatmap.validate_weights(w, "week")


# --- Bug: a negative risk_penalty RAISED the score (-0.5 gave 97.5/favorable).
def test_negative_risk_penalty_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        heatmap.score_sector(sector(risk_penalty=-0.5), weights(), BANDS)


def test_risk_penalty_is_capped_not_unbounded():
    r = heatmap.score_sector(sector(risk_penalty=0.99), weights(), BANDS)
    assert r["risk_penalty"] == weights()["risk_penalty_max"]
    assert r["risk_penalty_capped"] is True
    assert r["score"] == 45.0


# --- Bug: a missing component was silently dropped, producing a lower score
#     reported at HIGH confidence. Data loss must never look like a bearish call.
def test_missing_component_raises_instead_of_silently_lowering_score():
    s = sector()
    del s["components"]["breadth"]
    with pytest.raises(ValueError, match="missing component"):
        heatmap.score_sector(s, weights(), BANDS)


def test_unknown_component_is_rejected():
    s = sector()
    s["components"]["vibes"] = 90
    with pytest.raises(ValueError, match="unknown component"):
        heatmap.score_sector(s, weights(), BANDS)


# --- Bug: an out-of-range component clamped to 100 with no complaint.
@pytest.mark.parametrize("bad", [900, -10, 100.5])
def test_out_of_range_component_is_rejected(bad):
    s = sector()
    s["components"]["breadth"] = bad
    with pytest.raises(ValueError, match="outside 0-100"):
        heatmap.score_sector(s, weights(), BANDS)


def test_non_numeric_component_is_rejected():
    s = sector()
    s["components"]["breadth"] = "high"
    with pytest.raises(ValueError, match="not numeric"):
        heatmap.score_sector(s, weights(), BANDS)


# --- Bug: the all-50 placeholder template scored "neutral" at HIGH confidence
#     with zero evidence logged. docs/metric_definitions.md forbids this.
def test_unsourced_sector_cannot_be_high_confidence():
    r = heatmap.score_sector(sector(why=[], risks=[]), weights(), BANDS)
    assert r["confidence"] == "low"


def test_single_confirmation_is_at_most_medium():
    r = heatmap.score_sector(sector(why=["one thing"]), weights(), BANDS)
    assert r["confidence"] == "medium"


def test_wide_component_spread_lowers_confidence():
    s = sector()
    s["components"]["breadth"] = 10
    s["components"]["regime_fit"] = 90
    r = heatmap.score_sector(s, weights(), BANDS)
    assert r["confidence"] == "low"


# --- Rating bands must be continuous and cover the whole 0-100 range.
@pytest.mark.parametrize(
    "score,expected",
    [(100, "favorable"), (70, "favorable"), (69.9, "constructive"), (55, "constructive"),
     (54.9, "neutral"), (45, "neutral"), (44.9, "unfavorable"), (30, "unfavorable"),
     (29.9, "defensive"), (0, "defensive")],
)
def test_band_boundaries(score, expected):
    assert heatmap.rating(score, BANDS) == expected


# --- Bug: dashboard header used a non-ASCII em dash.
def test_rendered_dashboard_is_ascii():
    payload = {
        "as_of_date": "2026-08-25", "run_type": "manual",
        "regime": {"label": "transition", "confidence": "low"},
    }
    scored = {"Technology": {h: heatmap.score_sector(sector(), weights(h), BANDS)
                             for h in ("day", "week", "month")}}
    heatmap.render(payload, scored).encode("ascii")


# --- Forecast artifacts are immutable (docs/manual_runbook.md).
def test_existing_forecast_is_not_overwritten(tmp_path):
    payload = {
        "as_of_date": "2026-08-25", "run_type": "manual",
        "regime": {"label": "transition", "confidence": "low", "evidence": [],
                   "disconfirming_evidence": []},
        "weights": {h: weights(h) for h in ("day", "week", "month")},
        "bands": BANDS,
        "sectors": {"Technology": {h: sector() for h in ("day", "week", "month")}},
    }
    src = tmp_path / "input.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    out, dash = tmp_path / "f", tmp_path / "d"
    heatmap.main([str(src), "--output-dir", str(out), "--dashboard-dir", str(dash)])
    with pytest.raises(FileExistsError):
        heatmap.main([str(src), "--output-dir", str(out), "--dashboard-dir", str(dash)])


def test_payload_without_bands_is_rejected(tmp_path):
    payload = {
        "as_of_date": "2026-08-25", "run_type": "manual",
        "regime": {"label": "transition", "confidence": "low"},
        "weights": {h: weights(h) for h in ("day", "week", "month")},
        "sectors": {"Technology": {h: sector() for h in ("day", "week", "month")}},
    }
    src = tmp_path / "input.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="no 'bands' block"):
        heatmap.main([str(src), "--output-dir", str(tmp_path / "f")])
