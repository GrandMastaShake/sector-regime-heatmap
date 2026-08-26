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


# The README was ASCII-only until 2026-08-26. It is now UTF-8, but the fenced
# chart still has to stay single-width or its columns shear -- see
# test_chart_stays_single_width_so_columns_align.
def test_dashboard_block_is_valid_utf8():
    rd.build().encode("utf-8").decode("utf-8")


# --- The whole point: no forecast means no numbers, not placeholder numbers.
def test_empty_state_publishes_no_scores(monkeypatch):
    monkeypatch.setattr(rd, "latest_forecast", lambda: None)
    block = rd.build()
    assert "none published" in block
    assert "| Sector | Week | Month | Trend | Confidence |" not in block


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
    assert "| Sector | Week | Month | Trend | Confidence |" in readme
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
        assert "**" + s + "**" in block
    assert "2026-08-25" in block
    assert "none published" not in block
    block.encode("utf-8")


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


# --- The Why column pasted two paragraphs of rationale into a table cell, which
#     made the table unscannable. The reasoning stays in the block, collapsed.
def test_rationale_is_collapsed_out_of_the_table(tmp_path, monkeypatch):
    doc = json.loads((ROOT / "data/forecasts/2026-08-21_manual.json").read_text(encoding="utf-8"))
    doc["_path"] = "data/forecasts/2026-08-21_manual.json"
    monkeypatch.setattr(rd, "latest_forecast", lambda: doc)
    block = rd.build()

    table_rows = [ln for ln in block.splitlines()
                  if ln.startswith("| ") and "favorable" in ln or "defensive" in ln]
    a_why = doc["scores"]["Utilities"]["week"]["why"][0]
    assert all(a_why not in row for row in table_rows), "rationale is back in the table"
    assert "<details>" in block and a_why in block


def test_strongest_week_sorts_first_and_unscored_sorts_last():
    doc = json.loads((ROOT / "data/forecasts/2026-08-21_manual.json").read_text(encoding="utf-8"))
    rows = sorted(doc["scores"].items(), key=rd.sort_key, reverse=True)
    scores = [r["week"]["score"] for _s, r in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0][0] == "Financials"


# --- The chart is aligned by padding sector names, so every glyph inside the
#     fenced block must occupy one column. Emoji are double-width and would
#     shear the bars out of line; they belong in the markdown table, where
#     nothing has to line up. This is the invariant that would break silently.
def test_chart_stays_single_width_so_columns_align(monkeypatch):
    doc = json.loads((ROOT / "data/forecasts/2026-08-21_manual.json").read_text(encoding="utf-8"))
    doc["_path"] = "x.json"
    monkeypatch.setattr(rd, "latest_forecast", lambda: doc)
    block = rd.build()

    fenced, inside = [], False
    for line in block.splitlines():
        if line.strip() == "```":
            inside = not inside
            continue
        if inside:
            fenced.append(line)
    assert fenced, "no fenced chart rendered"

    import unicodedata
    for line in fenced:
        for ch in line:
            assert unicodedata.east_asian_width(ch) not in ("W", "F"), (
                "double-width " + repr(ch) + " inside the aligned chart: " + line)

    # and the bars really do line up
    bar_lines = [ln for ln in fenced if rd.FULL in ln or rd.EMPTY in ln]
    assert len(bar_lines) == 11
    starts = {ln.find(rd.FULL) if rd.FULL in ln else ln.find(rd.EMPTY) for ln in bar_lines}
    assert len(starts) == 1, "week bars start at different columns: " + str(starts)


def test_bar_never_renders_a_missing_horizon_as_zero():
    assert rd.bar(None) == rd.MISSING * rd.BAR_CELLS   # not offered
    assert rd.bar(0) == rd.EMPTY * rd.BAR_CELLS        # scored, and it is zero
    assert rd.bar(None) != rd.bar(0)
