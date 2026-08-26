"""The README dashboard must reflect real artifacts and never invent numbers."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import render_dashboard as rd  # noqa: E402

SECTORS = sorted(
    k for k in yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    if k not in ("version", "note")
)


def test_readme_has_dashboard_markers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert rd.START in text
    assert rd.END in text
    assert text.index(rd.START) < text.index(rd.END)


def test_readme_dashboard_is_current():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/render_dashboard.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_dashboard_block_is_ascii():
    rd.build().encode("ascii")


# --- The whole point: no forecast means no numbers, not placeholder numbers.
def test_empty_state_publishes_no_scores(monkeypatch):
    monkeypatch.setattr(rd, "latest_forecast", lambda: None)
    block = rd.build()
    assert "none published" in block
    assert "| Sector | Day | Week | Month" not in block


# The empty state ended with cycle 1 (as_of 2026-08-21), the first published
# forecast. The tripwire above did its job -- it fired the moment a forecast
# was committed -- and is replaced by its inverse: the README must now SHOW
# that forecast rather than claim none exists. The behavioural gate above
# (no forecast means no numbers, not placeholder numbers) is unchanged.
def test_published_state_is_the_current_state():
    latest = rd.latest_forecast()
    assert latest is not None, "cycle 1 was published; a forecast must exist"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "none published" not in readme
    assert "| Sector | Day | Week | Month" in readme
    assert latest["as_of_date"] in readme


def make_forecast(tmp_path: Path, as_of: str) -> Path:
    tpl = json.loads((ROOT / "examples/sectors/sector_template.json").read_text(encoding="utf-8"))
    sd = tmp_path / ("sec_" + as_of)
    sd.mkdir()
    for s in SECTORS:
        x = copy.deepcopy(tpl)
        x["sector"] = s
        x["as_of_date"] = as_of
        for h in ("day", "week", "month"):
            x[h]["why"] = ["breadth 70pct positive", "basket +1.2pct vs SPY"]
            x[h]["risks"] = ["top-two contribution 41pct"]
        (sd / (s.lower().replace(" ", "_") + ".json")).write_text(
            json.dumps(x), encoding="utf-8")
    base = json.loads((ROOT / "examples/base_payload.json").read_text(encoding="utf-8"))
    base["as_of_date"] = as_of
    bp = tmp_path / ("base_" + as_of + ".json")
    bp.write_text(json.dumps(base), encoding="utf-8")
    inp = tmp_path / ("in_" + as_of + ".json")
    subprocess.run(
        [sys.executable, str(ROOT / "src/assemble_payload.py"), str(bp), str(sd), str(inp),
         "--weights", str(ROOT / "config/score_weights.yaml"),
         "--baskets", str(ROOT / "config/sector_baskets.yaml")],
        check=True, capture_output=True, cwd=ROOT,
    )
    out = tmp_path / "forecasts"
    subprocess.run(
        [sys.executable, str(ROOT / "src/heatmap.py"), str(inp),
         "--output-dir", str(out), "--dashboard-dir", str(tmp_path / "dash")],
        check=True, capture_output=True, cwd=ROOT,
    )
    return out / (as_of + "_manual.json")


def test_populated_state_renders_all_eleven_sectors(tmp_path, monkeypatch):
    path = make_forecast(tmp_path, "2026-08-25")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["_path"] = "data/forecasts/" + path.name
    monkeypatch.setattr(rd, "latest_forecast", lambda: doc)
    monkeypatch.setattr(rd, "forecast_count", lambda: 1)
    block = rd.build()
    for s in SECTORS:
        assert "| " + s + " |" in block
    assert "2026-08-25" in block
    assert "none published" not in block
    block.encode("ascii")


# --- Multiple artifacts: the dashboard must show the newest, not the first.
def test_latest_forecast_picks_the_newest_date(tmp_path, monkeypatch):
    dest = tmp_path / "data/forecasts"
    dest.mkdir(parents=True)
    for as_of in ("2026-08-25", "2026-09-02", "2026-08-31"):
        src = make_forecast(tmp_path, as_of)
        (dest / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        src.unlink()
    monkeypatch.setattr(rd, "ROOT", tmp_path)
    assert rd.latest_forecast()["as_of_date"] == "2026-09-02"
    assert rd.forecast_count() == 3


def test_standing_constraints_name_spcx():
    text = "\n".join(rd.render_constraints())
    assert "SPCX" in text
    assert "Industrials" in text
    assert "2026-09-11" in text


def test_missing_markers_is_an_error(tmp_path, monkeypatch):
    bad = tmp_path / "README.md"
    bad.write_text("# no markers here\n", encoding="utf-8")
    monkeypatch.setattr(rd, "README", bad)
    monkeypatch.setattr(sys, "argv", ["render_dashboard.py"])
    assert rd.main() == 1
