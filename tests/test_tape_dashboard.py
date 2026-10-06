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


# -- more weekdays than sessions: both counts, neither cause -------------------
#
# The dates are September and early October 2026. Monday 2026-09-07 is Labor
# Day. Every date a session is put on here is a weekday.

NOTE = "More weekdays than sessions"


def _tape_over(tmp_path, days):
    """A real tape from src/daily_tape.py whose panel holds exactly `days`."""
    from test_macro_comparisons import BASKETS, session, write_panel
    docs = [session(d, spy=100.0 + i) for i, d in enumerate(days)]
    tape = rt.dt.compute_tape(write_panel(tmp_path, docs), BASKETS)
    tape["_path"] = "data/tape/" + tape["as_of"] + ".json"
    return tape


@pytest.mark.parametrize("start, end, weekdays", [
    ("2026-09-22", "2026-09-23", 1),     # Tuesday to Wednesday
    ("2026-09-11", "2026-09-14", 1),     # Friday to Monday: a weekend
    ("2026-09-11", "2026-09-18", 5),     # a plain week
    ("2026-09-18", "2026-09-22", 2),     # across Monday the 21st
    ("2026-09-15", "2026-09-23", 6),
    ("2026-09-02", "2026-09-10", 6),     # across Labor Day
    ("2026-09-04", "2026-09-14", 6),     # Labor Day and two weekends
    ("2026-09-23", "2026-10-05", 8),
    ("2026-09-16", "2026-10-05", 13),
])
def test_weekdays_are_counted_after_the_first_close(start, end, weekdays):
    """A window reads from one close to another, so its first date is not one
    of its sessions and its last date is."""
    assert rt.weekdays_in(start, end) == weekdays


def test_a_window_with_as_many_weekdays_as_sessions_renders_no_note(
        monkeypatch, tmp_path):
    """Friday to Friday: one session over one weekday, five over five. Every
    weekday in each window is a session on file, so there is nothing to say."""
    tape = _tape_over(tmp_path, ["2026-09-11", "2026-09-14", "2026-09-15",
                                 "2026-09-16", "2026-09-17", "2026-09-18"])
    assert rt.tape_windows(tape) == [(1, "2026-09-17", "2026-09-18"),
                                     (5, "2026-09-11", "2026-09-18")]
    assert rt.render_window_note(tape) == []
    monkeypatch.setattr(rt, "latest_tape", lambda: tape)
    _no_regime(monkeypatch)
    block = rt.build()
    assert NOTE not in block and "weekday" not in block


def test_a_weekend_alone_does_not_trigger_the_note(tmp_path):
    """Friday's close to Monday's is three calendar days and one weekday. A
    session cannot fall on a weekend, so nothing in it is unaccounted for."""
    tape = _tape_over(tmp_path, ["2026-09-11", "2026-09-14", "2026-09-15",
                                 "2026-09-16", "2026-09-17", "2026-09-18",
                                 "2026-09-21"])
    day, week = rt.tape_windows(tape)
    assert day == (1, "2026-09-18", "2026-09-21")
    assert week == (5, "2026-09-14", "2026-09-21")
    assert rt.weekdays_in(*day[1:]) == 1
    assert rt.weekdays_in(*week[1:]) == 5
    assert rt.render_window_note(tape) == []


def test_a_one_session_window_across_an_unfiled_weekday_renders_the_note(
        tmp_path):
    """Friday's close to Tuesday's with no file for the Monday: two weekdays,
    one session. Two sessions make a day window and no week window, so this
    is the day window on its own."""
    note = rt.render_window_note(_tape_over(tmp_path, ["2026-09-18",
                                                       "2026-09-22"]))
    assert len(note) == 1
    assert ("The 1d window runs from the 2026-09-18 close to the 2026-09-22 "
            "close: 2 weekdays, 1 session, so at least 1 weekday in it has no "
            "session in the panel.") in note[0]
    assert "5d window" not in note[0]


def test_a_five_session_window_across_an_unfiled_weekday_renders_the_note(
        tmp_path):
    """The shape of the published 2026-09-23 tape: the day window is whole and
    the week window holds a Monday the panel has no file for."""
    note = rt.render_window_note(_tape_over(
        tmp_path, ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
                   "2026-09-22", "2026-09-23"]))
    assert len(note) == 1
    assert ("The 5d window runs from the 2026-09-15 close to the 2026-09-23 "
            "close: 6 weekdays, 5 sessions, so at least 1 weekday in it has "
            "no session in the panel.") in note[0]
    assert "1d window" not in note[0]


def test_both_windows_are_named_in_one_note(tmp_path):
    """The shape of the published 2026-10-05 tape: seven weekdays without a
    file inside the day window, and an eighth further back in the week's."""
    note = rt.render_window_note(_tape_over(
        tmp_path, ["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-22",
                   "2026-09-23", "2026-10-05"]))
    assert len(note) == 1
    assert ("The 1d window runs from the 2026-09-23 close to the 2026-10-05 "
            "close: 8 weekdays, 1 session, so at least 7 weekdays in it have "
            "no session in the panel.") in note[0]
    assert ("The 5d window runs from the 2026-09-16 close to the 2026-10-05 "
            "close: 13 weekdays, 5 sessions, so at least 8 weekdays in it "
            "have no session in the panel.") in note[0]
    assert note[0].index("1d window") < note[0].index("5d window")


def test_a_holiday_and_a_lost_session_render_the_same_note(tmp_path):
    """Labor Day, when the market was closed, and 2026-09-21, a session the
    feed never wrote, leave the same thing in a panel: a weekday with no file.
    The note cannot tell them apart and must not pretend to. It names both
    readings and asserts neither."""
    holiday = rt.render_window_note(_tape_over(
        tmp_path / "holiday", ["2026-09-01", "2026-09-02", "2026-09-03",
                               "2026-09-04", "2026-09-08", "2026-09-09"]))
    lost = rt.render_window_note(_tape_over(
        tmp_path / "lost", ["2026-09-15", "2026-09-16", "2026-09-17",
                            "2026-09-18", "2026-09-22", "2026-09-23"]))
    assert len(holiday) == 1 and len(lost) == 1
    for old, new in (("2026-09-01", "FROM"), ("2026-09-09", "TO")):
        holiday[0] = holiday[0].replace(old, new)
    for old, new in (("2026-09-15", "FROM"), ("2026-09-23", "TO")):
        lost[0] = lost[0].replace(old, new)
    assert "FROM close to the TO close" in lost[0]
    assert holiday == lost
    assert "a market holiday or a session the feed never wrote" in lost[0]
    assert "the panel cannot tell which" in lost[0]


@pytest.mark.parametrize("days, noted", [
    (["2026-09-18"], False),                    # no window at all
    (["2026-09-17", "2026-09-18"], False),      # a whole day window
    (["2026-09-18", "2026-09-22"], True),       # a day window across a Monday
])
def test_a_tape_without_the_week_horizon_does_not_crash(
        monkeypatch, tmp_path, days, noted):
    """Under six sessions the tape has no week horizon, and under two it has
    no day horizon either. The block still renders, and the note speaks only
    for a window the tape read."""
    tape = _tape_over(tmp_path, days)
    assert all("week" not in horizons for horizons in tape["sectors"].values())
    assert len(rt.tape_windows(tape)) == len(days) - 1
    monkeypatch.setattr(rt, "latest_tape", lambda: tape)
    _no_regime(monkeypatch)
    block = rt.build()
    assert "observation, not a forecast" in block
    assert (NOTE in block) is noted
    assert "5d window" not in block


def test_the_note_sits_above_the_chart_and_never_inside_it(
        monkeypatch, tmp_path):
    """The chart is aligned by padding. The note is prose and carries an
    emoji, so it belongs with the other lines above the fence."""
    tape = _tape_over(tmp_path, ["2026-09-16", "2026-09-17", "2026-09-18",
                                 "2026-09-22", "2026-09-23", "2026-10-05"])
    monkeypatch.setattr(rt, "latest_tape", lambda: tape)
    _no_regime(monkeypatch)
    lines = rt.build().splitlines()
    at = [i for i, line in enumerate(lines) if NOTE in line]
    fence = [i for i, line in enumerate(lines) if line.strip() == "```"]
    assert len(at) == 1 and len(fence) == 2
    assert at[0] < fence[0]
    assert lines[at[0]].startswith("> ")
    for line in lines[fence[0] + 1:fence[1]]:
        assert "weekday" not in line
        for ch in line:
            assert unicodedata.east_asian_width(ch) not in ("W", "F"), line


# Every tape published before the note existed, and each of its windows that
# holds more weekdays than sessions: (sessions, from, to, weekdays). The three
# tapes to 2026-09-14 read across Labor Day, and their labels are right. The
# three from 2026-09-22 read across the eight sessions weekly-council-scan
# records as lost between 2026-09-21 and 2026-10-02, and their labels are
# not. Nothing in a tape separates the two, which is why one note serves both.
PUBLISHED = {
    "2026-09-10": [(5, "2026-09-02", "2026-09-10", 6)],
    "2026-09-11": [(5, "2026-09-03", "2026-09-11", 6)],
    "2026-09-14": [(5, "2026-09-04", "2026-09-14", 6)],
    "2026-09-15": [],
    "2026-09-16": [],
    "2026-09-17": [],
    "2026-09-18": [],
    "2026-09-22": [(1, "2026-09-18", "2026-09-22", 2),
                   (5, "2026-09-14", "2026-09-22", 6)],
    "2026-09-23": [(5, "2026-09-15", "2026-09-23", 6)],
    "2026-10-05": [(1, "2026-09-23", "2026-10-05", 8),
                   (5, "2026-09-16", "2026-10-05", 13)],
}


@pytest.mark.parametrize("as_of", sorted(PUBLISHED))
def test_the_published_tapes_note_exactly_the_windows_measured(as_of):
    """Read off the committed artifacts, which are never rewritten."""
    tape = json.loads((ROOT / "data/tape" / (as_of + ".json"))
                      .read_text(encoding="utf-8"))
    counted = [(s, a, b, rt.weekdays_in(a, b))
               for s, a, b in rt.tape_windows(tape)]
    over = [w for w in counted if w[3] > w[0]]
    assert over == PUBLISHED[as_of]
    note = rt.render_window_note(tape)
    assert len(note) == (1 if over else 0)
    for sessions, start, end, weekdays in over:
        assert ("The " + str(sessions) + "d window runs from the " + start
                + " close to the " + end + " close: " + str(weekdays)
                + " weekdays, ") in note[0]
    # The comparison rows are read over these same windows, so the note
    # speaks for the table under the chart as well as for the chart.
    rows = (tape.get(rt.mc.BLOCK_KEY) or {}).get("rows") or {}
    for row in rows.values():
        for horizon in rt.dt.HORIZON_SESSIONS:
            w = row[horizon]
            assert ((w["sessions"], w["window_from"], w["window_to"])
                    in rt.tape_windows(tape))
