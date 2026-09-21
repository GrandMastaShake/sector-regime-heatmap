"""Staging refuses rather than producing a partial artifact that looks usable."""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402
import make_sector_inputs as msi  # noqa: E402
import stage_run  # noqa: E402
from test_compute_metrics import ALL, SECTORS, flat, panel, week  # noqa: E402


def snap(tmp_path: Path, as_of: str, verified: bool = True) -> Path:
    root = tmp_path / "repo"
    cfg = root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "sector_baskets.yaml").write_text(
        (ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    d = root / "data/weekly_research" / as_of
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({
        "as_of_date": as_of, "provenance_verified": verified,
        "source_commit_sha": "b" * 40, "files": [],
    }), encoding="utf-8")
    return root


def full_panel(tmp_path: Path, as_of: str = "2026-08-21") -> Path:
    weeks = []
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07", "2026-08-14", as_of]
    for i, d in enumerate(days):
        weeks.append(week(d, flat(ALL, 100.0 + i)))
    return panel(tmp_path, weeks, pad=False)


def run(monkeypatch, tmp_path, repo_root, panel_dir, extra=None):
    monkeypatch.setattr(stage_run, "ROOT", repo_root)
    argv = ["--panel", str(panel_dir), "--out-dir", str(tmp_path / "out")]
    return stage_run.main(argv + (extra or []))


def test_full_coverage_stages_successfully(monkeypatch, tmp_path, capsys):
    root = snap(tmp_path, "2026-08-24")
    rc = run(monkeypatch, tmp_path, root, full_panel(tmp_path))
    assert rc == 0
    out = tmp_path / "out"
    assert len(list(out.glob("*.json"))) == 12  # 11 sectors + cross-sector evidence
    doc = json.loads((out / "technology.json").read_text(encoding="utf-8"))
    assert doc["week"]["components"]["breadth"] is not None
    assert doc["week"]["components"]["regime_fit"] is None
    assert doc["week"]["components"]["macro_catalyst"] is None


def test_thin_coverage_is_refused(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-24")
    weeks, days = [], ["2026-07-17", "2026-07-24", "2026-07-31",
                       "2026-08-07", "2026-08-14", "2026-08-21"]
    import yaml
    baskets = yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    drop = baskets["Technology"][:7]
    for i, d in enumerate(days):
        closes = flat(ALL, 100.0 + i)
        if d == "2026-08-21":
            for t in drop:
                del closes[t]
        weeks.append(week(d, closes))
    assert run(monkeypatch, tmp_path, root, panel(tmp_path, weeks, pad=False)) == 2


def test_unverified_provenance_is_refused(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-24", verified=False)
    with pytest.raises(SystemExit, match="not provenance-verified"):
        run(monkeypatch, tmp_path, root, full_panel(tmp_path))


def test_research_predating_the_close_is_refused(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-14")
    with pytest.raises(SystemExit, match="predates the price close"):
        run(monkeypatch, tmp_path, root, full_panel(tmp_path))


def test_stale_research_is_refused(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-09-30")
    with pytest.raises(SystemExit, match="beyond the 7-day limit"):
        run(monkeypatch, tmp_path, root, full_panel(tmp_path))


def test_undeclared_price_source_is_refused(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-24")
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07",
            "2026-08-14", "2026-08-21"]
    weeks = [week(d, flat(ALL, 100.0 + i), source="mystery-csv")
             for i, d in enumerate(days)]
    assert run(monkeypatch, tmp_path, root, panel(tmp_path, weeks, pad=False)) == 2


def test_evidence_carries_provenance(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-24")
    d = root / "data/weekly_research/2026-08-24"
    (d / "technology.json").write_text(json.dumps({
        "sector": "Technology", "as_of_date": "2026-08-24",
        "extracts": [{"source_path": "wiki/tech.md", "source_file_sha": "a" * 40,
                      "content": '# Tech\n\n> *"Bonds ran the week."*\n\n## MACRO OVERLAY\n'}],
    }), encoding="utf-8")
    run(monkeypatch, tmp_path, root, full_panel(tmp_path))
    doc = json.loads((tmp_path / "out/technology.json").read_text(encoding="utf-8"))
    e = doc["evidence"]["extracts"][0]
    assert e["source_file_sha"] == "a" * 40
    assert "Bonds ran the week" in e["lead_summary"]
    assert "MACRO OVERLAY" in e["sections"]


# --- Denominators come from each basket; the floor of 8 does not move.
#     Real Estate holds nine names since 2026-09-21 (AVB left the list).

def _panel_missing(tmp_path, sector: str, drop: int) -> Path:
    """A full panel whose last week lacks the first `drop` names of `sector`."""
    days = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07",
            "2026-08-14", "2026-08-21"]
    weeks = []
    for i, d in enumerate(days):
        closes = flat(ALL, 100.0 + i)
        if d == days[-1]:
            for t in SECTORS[sector][:drop]:
                del closes[t]
        weeks.append(week(d, closes))
    return panel(tmp_path, weeks, pad=False)


def test_the_data_quality_floor_is_eight_everywhere():
    """Three places enforce the same floor. None of them moved when Real
    Estate went to nine names: loosening it is a decision, not a side effect."""
    assert cm.MIN_CONSTITUENTS == 8
    assert stage_run.MIN_COVERAGE == 8

    def block(used, expected):
        return {"week": {"constituents_used": used, "constituents_expected": expected,
                         "missing": [], "anomalies": []}}

    assert msi.data_quality(block(9, 9))["status"] == "pass"
    assert msi.data_quality(block(8, 9))["status"] == "warn"
    assert msi.data_quality(block(7, 9))["status"] == "fail"
    assert msi.data_quality(block(8, 10))["status"] == "warn"
    assert msi.data_quality(block(7, 10))["status"] == "fail"


def test_coverage_notes_name_the_baskets_own_size():
    note = msi.data_quality({"week": {"constituents_used": 8, "constituents_expected": 9,
                                      "missing": [], "anomalies": []}})
    assert note["coverage_notes"] == ["week: 8 of 9"]


def test_refusal_reports_each_basket_against_its_own_size(monkeypatch, tmp_path, capsys):
    root = snap(tmp_path, "2026-08-24")
    n = len(SECTORS["Real Estate"])
    drop = n - stage_run.MIN_COVERAGE + 1          # one name under the floor
    rc = run(monkeypatch, tmp_path, root, _panel_missing(tmp_path, "Real Estate", drop))
    assert rc == 2
    out = capsys.readouterr().out
    # The old message read "7/10" whatever the basket held.
    assert "Real Estate: " + str(n - drop) + "/" + str(n) in out


def test_a_basket_at_the_floor_stages_with_a_warn(monkeypatch, tmp_path):
    root = snap(tmp_path, "2026-08-24")
    n = len(SECTORS["Real Estate"])
    drop = n - stage_run.MIN_COVERAGE              # exactly at the floor
    rc = run(monkeypatch, tmp_path, root, _panel_missing(tmp_path, "Real Estate", drop))
    assert rc == 0
    doc = json.loads((tmp_path / "out/real_estate.json").read_text(encoding="utf-8"))
    expected_status = "warn" if drop else "pass"
    assert doc["data_quality"]["status"] == expected_status
    assert doc["week"]["metrics"]["constituents_expected"] == n


def test_a_full_nine_name_basket_is_a_pass_not_a_warn(monkeypatch, tmp_path):
    """Under the old list Real Estate carried a permanent warn at 9 of 10,
    because AVB had no bar. Its own nine, all present, is a pass."""
    root = snap(tmp_path, "2026-08-24")
    assert run(monkeypatch, tmp_path, root, full_panel(tmp_path)) == 0
    doc = json.loads((tmp_path / "out/real_estate.json").read_text(encoding="utf-8"))
    n = len(SECTORS["Real Estate"])
    assert doc["data_quality"]["status"] == "pass"
    assert doc["week"]["metrics"]["constituents_used"] == n
    assert doc["week"]["metrics"]["constituents_expected"] == n
