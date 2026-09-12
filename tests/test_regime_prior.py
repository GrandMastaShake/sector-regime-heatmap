"""The archetype prior, its refusals, and the contradiction detector.

The refusals matter more than the lookups. A prior that guesses its own
archetype would turn the one judgment call this repo protects into an
automated one, silently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import regime_prior as rp  # noqa: E402

SECTORS = ["Communication Services", "Consumer Discretionary",
           "Consumer Staples", "Energy", "Financials", "Healthcare",
           "Industrials", "Materials", "Real Estate", "Technology",
           "Utilities"]


def tape_with(excess: dict, sessions=13) -> dict:
    return {
        "as_of": "2026-09-10", "panel_sessions": sessions,
        "sectors": {s: {"week": {"sector_return_vs_spy_pct": excess.get(s)}}
                    for s in SECTORS},
    }


# -- config integrity --------------------------------------------------------

def test_matrix_covers_every_sector_in_the_baskets():
    baskets = yaml.safe_load(
        (ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    basket_sectors = {k for k in baskets if k not in ("version", "note")}
    matrix = rp.load_matrix()
    for archetype, entry in matrix.items():
        assert set(entry["sectors"]) == basket_sectors, (
            "archetype " + str(archetype) + " sector keys do not match "
            "config/sector_baskets.yaml")


def test_matrix_and_archetype_metadata_agree():
    matrix = rp.load_matrix()
    meta = rp.load_archetypes()["archetypes"]
    assert set(matrix) == set(meta)
    for k in matrix:
        assert matrix[k]["name"] == meta[k]["name"]
        assert matrix[k]["direction"] == meta[k]["direction"]


def test_pre_listing_sectors_are_null_not_zero():
    """XLRE listed 2015 and XLC 2018, so neither has a dot-com observation.
    A null must never be read as 'no excess return'."""
    matrix = rp.load_matrix()
    for archetype in (9, 10):
        assert matrix[archetype]["sectors"]["Real Estate"] is None
        assert matrix[archetype]["sectors"]["Communication Services"] is None


def test_transitions_never_run_contraction_to_contraction():
    """The finding the taxonomy rests on: 16 gap-free transitions, none from
    a contraction archetype into another contraction archetype."""
    doc = rp.load_archetypes()
    meta, trans = doc["archetypes"], doc["transitions"]
    offenders = []
    for src, dests in trans.items():
        if meta[src]["direction"] != "contraction":
            continue
        for dest in dests:
            if meta[dest]["direction"] == "contraction":
                offenders.append((src, dest))
    assert offenders == [], offenders


def test_transition_count_is_sixteen():
    trans = rp.load_archetypes()["transitions"]
    assert sum(sum(d.values()) for d in trans.values()) == 16


# -- parsing and refusal -----------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("AI-capex recovery -- archetype 1, steady mid-cycle expansion", 1),
    ("archetype 10, tech-bubble unwind", 10),
    ("ARCHETYPE 7", 7),
    ("Archetype  3 with extra space", 3),
])
def test_parses_a_declared_archetype(label, expected):
    assert rp.parse_archetype(label) == expected


@pytest.mark.parametrize("label", [
    None, "", "steady mid-cycle expansion", "regime 1", "archetypes",
])
def test_refuses_to_infer_an_undeclared_archetype(label):
    assert rp.parse_archetype(label) is None


def test_no_forecast_means_no_prior(tmp_path):
    reg = rp.active_regime(tmp_path, "2026-09-10")
    assert reg["archetype"] is None
    assert "no forecast artifact" in reg["reason"]


def test_unparseable_label_reports_why_rather_than_guessing(tmp_path):
    (tmp_path / "2026-08-21_manual.json").write_text(json.dumps({
        "as_of_date": "2026-08-21",
        "regime": {"label": "a regime with no archetype number"},
    }), encoding="utf-8", newline="\n")
    reg = rp.active_regime(tmp_path, "2026-09-10")
    assert reg["archetype"] is None
    assert "refusing to infer" in reg["reason"]


def test_reports_the_age_of_the_declaration(tmp_path):
    (tmp_path / "2026-08-21_manual.json").write_text(json.dumps({
        "as_of_date": "2026-08-21",
        "regime": {"label": "archetype 1, steady mid-cycle expansion",
                   "confidence": "medium"},
    }), encoding="utf-8", newline="\n")
    reg = rp.active_regime(tmp_path, "2026-09-10")
    assert reg["archetype"] == 1
    assert reg["age_days"] == 20
    assert reg["confidence"] == "medium"


def test_unknown_archetype_is_refused():
    with pytest.raises(rp.PriorError):
        rp.compare(tape_with({}), 99)


# -- contradiction detection -------------------------------------------------

def test_agreement_produces_no_contradiction():
    """Tape ordering identical to the prior ordering."""
    matrix = rp.load_matrix()
    priors = matrix[1]["sectors"]
    excess = {s: (v or 0) / 10.0 for s, v in priors.items()}
    out = rp.compare(tape_with(excess), 1)
    assert out["contradictions"] == []
    assert out["sectors"]["Technology"]["rank_divergence"] == 0


def test_reversed_tape_flags_the_extremes():
    matrix = rp.load_matrix()
    priors = matrix[1]["sectors"]
    excess = {s: -(v or 0) / 10.0 for s, v in priors.items()}
    out = rp.compare(tape_with(excess), 1)
    assert "Technology" in out["contradictions"]
    assert out["sectors"]["Technology"]["flag"] == "prior_leader_tape_laggard"
    assert out["sectors"]["Energy"]["flag"] == "prior_laggard_tape_leader"


def test_divergence_below_the_threshold_is_not_flagged():
    out = rp.compare(tape_with({s: 0.0 for s in SECTORS}), 1)
    for sector, row in out["sectors"].items():
        if row["rank_divergence"] is not None:
            assert (row["flag"] is None) == (
                row["rank_divergence"] < rp.DIVERGENCE_FLAG)


def test_comparison_carries_the_sample_size_with_it():
    out = rp.compare(tape_with({s: 0.0 for s in SECTORS}), 1)
    assert out["archetype_n"] == 4
    assert "4 episodes" in out["note"]
    assert "regime_fit" in out["note"]


def test_null_prior_sectors_are_not_ranked_or_flagged():
    """Archetype 9 has no Real Estate or Comm Services observation."""
    out = rp.compare(tape_with({s: 1.0 for s in SECTORS}), 9)
    for sector in ("Real Estate", "Communication Services"):
        row = out["sectors"][sector]
        assert row["prior_available"] is False
        assert row["prior_rank"] is None
        assert row["rank_divergence"] is None
        assert row["flag"] is None


def test_successors_are_reported_with_their_counts():
    succ = rp.likely_successors(1)
    assert {s["archetype"] for s in succ} == {4, 7}
    assert all(s["of"] == 2 for s in succ)


def test_successors_empty_for_an_archetype_with_no_recorded_handoff():
    doc = rp.load_archetypes()
    doc["transitions"] = {}
    assert rp.likely_successors(1, doc) == []
