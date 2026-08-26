"""Assembler gates: sector identity, staleness, and data quality."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import assemble_payload  # noqa: E402

SECTORS = sorted(
    k for k in yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    if k not in ("version", "note")
)


def sector_file(name: str, as_of: str = "2026-08-25") -> dict:
    block = {
        "components": {c: 50 for c in
                       ("regime_fit", "breadth", "relative_momentum",
                        "volume_confirmation", "macro_catalyst")},
        "risk_penalty": 0.0, "why": ["x", "y"], "risks": ["z"],
    }
    return {"sector": name, "as_of_date": as_of,
            "data_quality": {"status": "pass"},
            "day": copy.deepcopy(block), "week": copy.deepcopy(block),
            "month": copy.deepcopy(block)}


def build(tmp_path, mutate=None, as_of="2026-08-25"):
    sd = tmp_path / "sectors"
    sd.mkdir(exist_ok=True)
    for s in SECTORS:
        d = sector_file(s, as_of)
        json.dump(d, open(sd / (s.lower().replace(" ", "_") + ".json"), "w", encoding="utf-8"))
    if mutate:
        mutate(sd)
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"as_of_date": as_of, "run_type": "manual",
                                "regime": {"label": "transition", "confidence": "low",
                                           "evidence": [], "disconfirming_evidence": []}}),
                    encoding="utf-8")
    out = tmp_path / "input.json"
    assemble_payload.main([
        str(base), str(sd), str(out),
        "--weights", str(ROOT / "config/score_weights.yaml"),
        "--baskets", str(ROOT / "config/sector_baskets.yaml"),
    ])
    return json.loads(out.read_text(encoding="utf-8"))


def test_assembler_injects_weights_and_bands_from_config(tmp_path):
    payload = build(tmp_path)
    assert set(payload["weights"]) == {"day", "week", "month"}
    assert payload["bands"]["favorable"] == 70
    assert payload["weights_config_version"] == 2
    assert len(payload["sectors"]) == 11


# --- Bug: a sector file left over from last week assembled silently into
#     today's forecast, violating the no-look-ahead rule in the upstream
#     research contract.
def test_stale_sector_file_is_rejected(tmp_path):
    def mutate(sd):
        p = sd / "energy.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["as_of_date"] = "2026-08-18"
        p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="Stale sector inputs"):
        build(tmp_path, mutate)


# --- Bug: only the COUNT was checked, so a typo'd sector name passed.
def test_misspelled_sector_name_is_rejected(tmp_path):
    def mutate(sd):
        p = sd / "utilities.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["sector"] = "Utilties"
        p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="not a GICS sector"):
        build(tmp_path, mutate)


def test_duplicate_sector_across_two_files_is_rejected(tmp_path):
    def mutate(sd):
        d = json.loads((sd / "energy.json").read_text(encoding="utf-8"))
        (sd / "energy_copy.json").write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="declared by two files"):
        build(tmp_path, mutate)


def test_failing_data_quality_blocks_assembly(tmp_path):
    def mutate(sd):
        p = sd / "materials.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["data_quality"]["status"] = "fail"
        p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="failing data"):
        build(tmp_path, mutate)


def test_placeholder_date_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="placeholder"):
        build(tmp_path, as_of="YYYY-MM-DD")


# --- Bug: stage_run.py writes _cross_sector_evidence.json into the same
#     directory as the sector files, and the assembler raised on it -- the two
#     halves of the shipped pipeline disagreed, so a staged run could not be
#     assembled without deleting a file the stager had just written.
def test_underscore_prefixed_staged_files_are_not_sectors(tmp_path):
    def mutate(sd):
        (sd / "_cross_sector_evidence.json").write_text(
            json.dumps({"available": True, "snapshot": "2026-08-24",
                        "extracts": []}), encoding="utf-8")

    payload = build(tmp_path, mutate)
    assert len(payload["sectors"]) == 11
    assert not any(k.startswith("_") for k in payload["sectors"])
