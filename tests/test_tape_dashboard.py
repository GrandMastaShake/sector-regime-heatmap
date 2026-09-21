"""The README daily-tape block.

Same two rules as the forecast dashboard: the fenced chart must stay
single-width or its columns shear, and the block must never invent a number.
One rule of its own: the tape block and the forecast block sit on the same
page, so the tape must say what it is on its face.
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import render_tape as rt  # noqa: E402

README = ROOT / "README.md"


def test_readme_has_tape_markers():
    text = README.read_text(encoding="utf-8")
    assert rt.START in text
    assert rt.END in text


def test_readme_tape_is_current():
    text = README.read_text(encoding="utf-8")
    head = text[: text.index(rt.START)]
    tail = text[text.index(rt.END) + len(rt.END):]
    assert head + rt.build() + tail == text, (
        "README daily tape is stale. Run: python scripts/render_tape.py")


def test_tape_block_is_valid_utf8():
    raw = README.read_bytes()
    raw.decode("utf-8")


def test_chart_stays_single_width_so_columns_align():
    """Emoji are double-width and shear a padding-aligned chart. They belong
    in the prose and tables, where nothing has to line up."""
    block = rt.build()
    inside = False
    for line in block.splitlines():
        if line.strip() == "```":
            inside = not inside
            continue
        if not inside:
            continue
        for ch in line:
            assert unicodedata.east_asian_width(ch) not in ("W", "F"), (
                "double-width " + repr(ch) + " inside the aligned chart: " + line)


def test_chart_columns_are_all_the_same_width():
    block = rt.build()
    inside, widths = False, []
    for line in block.splitlines():
        if line.strip() == "```":
            inside = not inside
            continue
        if inside and line.strip():
            widths.append(len(line))
    assert widths, "no chart rendered"
    assert len(set(widths)) == 1, "chart rows have ragged widths: " + str(set(widths))


def test_block_says_it_is_not_a_forecast():
    """The page carries a forecast block too. These must not be confusable."""
    block = rt.build()
    assert "observation, not a forecast" in block
    assert "scores nothing" in block


def test_empty_state_publishes_no_numbers(monkeypatch):
    monkeypatch.setattr(rt, "latest_tape", lambda: None)
    block = rt.build()
    assert "No daily tape published" in block
    assert "%" not in block


def test_no_declared_regime_renders_arithmetic_only(monkeypatch, tmp_path):
    tape = json.loads((ROOT / "data/tape").glob("*.json").__next__()
                      .read_text(encoding="utf-8"))
    tape["_path"] = "data/tape/x.json"
    monkeypatch.setattr(rt, "latest_tape", lambda: tape)
    monkeypatch.setattr(rt.rp, "active_regime",
                        lambda *a, **k: {"archetype": None, "label": None,
                                         "declared_as_of": None,
                                         "age_days": None,
                                         "reason": "no forecast artifact published;"})
    block = rt.build()
    assert "No declared regime" in block
    assert "PRIOR" not in block


def test_diverging_bar_is_centred_and_fixed_width():
    for value in (-5.0, -0.1, 0.0, 0.1, 5.0, None):
        bar = rt.diverging_bar(value, 5.0)
        assert len(bar) == 2 * rt.HALF + 1
        assert bar[rt.HALF] == rt.AXIS


def test_diverging_bar_puts_negatives_left_and_positives_right():
    neg = rt.diverging_bar(-5.0, 5.0)
    pos = rt.diverging_bar(5.0, 5.0)
    assert neg.startswith(rt.FULL) and neg.endswith(rt.EMPTY)
    assert pos.startswith(rt.EMPTY) and pos.endswith(rt.FULL)


def test_contradictions_report_both_ranks_and_the_gap():
    tape = json.loads((ROOT / "data/tape").glob("*.json").__next__()
                      .read_text(encoding="utf-8"))
    cmp_block = rt.rp.compare(tape, 1)
    if not cmp_block["contradictions"]:
        pytest.skip("no contradiction in the published tape")
    lines = "\n".join(rt.render_contradictions(cmp_block))
    for sector in cmp_block["contradictions"]:
        assert sector in lines
    assert "positions apart" in lines
    assert "regime_fit" in lines


# -- the comparison rows: their own table, never the chart ---------------------

def _tape_with_rows(tmp_path, gld=True):
    """A real tape computed by src/daily_tape.py from a small synthetic panel."""
    from test_macro_comparisons import BASKETS, full_sessions, write_panel
    docs = full_sessions() if gld else full_sessions(gld=True)
    tape = rt.dt.compute_tape(write_panel(tmp_path, docs), BASKETS)
    tape["_path"] = "data/tape/" + tape["as_of"] + ".json"
    return tape


def _no_regime(monkeypatch):
    monkeypatch.setattr(rt.rp, "active_regime",
                        lambda *a, **k: {"archetype": None, "label": None,
                                         "declared_as_of": None, "age_days": None,
                                         "reason": "none declared;"})


def _row(lines, label):
    return next(line for line in lines if line.startswith("| " + label + " |"))


def test_comparison_rows_render_as_their_own_table(tmp_path):
    lines = rt.render_comparisons(_tape_with_rows(tmp_path))
    text = "\n".join(lines)
    assert "not sectors" in text
    assert "| Comparison | Reads | 1d | 1d vs SPY | 5d | 5d vs SPY |" in lines
    # GLD 200 -> 210 is +5.00%; SPY 100 -> 102 is +2.00%; so +3.00 against it.
    gold = _row(lines, "Gold")
    assert "`series.GLD`" in gold
    assert "+5.00%" in gold and "+3.00" in gold
    assert "`fx.DXY`" in _row(lines, "US dollar")
    assert "`series.BTC`" in _row(lines, "Bitcoin")
    assert "missing" not in gold


def test_comparison_rows_never_enter_the_chart(monkeypatch, tmp_path):
    """Sharing the chart would share its bar scale and its BRDTH/UPVOL
    columns, neither of which a comparison row has."""
    monkeypatch.setattr(rt, "latest_tape", lambda: _tape_with_rows(tmp_path))
    _no_regime(monkeypatch)
    block = rt.build()
    inside, chart = False, []
    for line in block.splitlines():
        if line.strip() == "```":
            inside = not inside
            continue
        if inside:
            chart.append(line)
    assert chart, "no chart rendered"
    for word in ("Gold", "dollar", "Bitcoin", "GLD", "DXY", "BTC"):
        assert not any(word in line for line in chart), word
    assert "| Gold |" in block


def test_a_missing_comparison_value_renders_as_missing(tmp_path):
    lines = rt.render_comparisons(_tape_with_rows(tmp_path, gld=False))
    gold = _row(lines, "Gold")
    assert gold.count("missing") == 4
    assert not any(ch.isdigit() for ch in gold.split("|", 3)[3])
    assert any(line.startswith("- **Gold**: absent from series at") for line in lines)


def test_a_tape_that_predates_the_rows_renders_every_row_missing():
    """The committed tapes up to 2026-09-18 predate the rows. They are
    immutable, so nothing is backfilled -- every row says missing."""
    first = sorted((ROOT / "data/tape").glob("*.json"))[0]
    tape = json.loads(first.read_text(encoding="utf-8"))
    assert "macro_comparisons" not in tape
    tape["_path"] = "data/tape/" + first.name
    lines = rt.render_comparisons(tape)
    for label in ("Gold", "US dollar", "Bitcoin"):
        row = _row(lines, label)
        assert row.count("missing") == 4
        assert not any(ch.isdigit() for ch in row.split("|", 3)[3])
    assert any("predates the comparison rows" in line for line in lines)
