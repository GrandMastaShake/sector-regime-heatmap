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
