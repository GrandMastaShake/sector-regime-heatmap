# 2026-10-05 - A window is weeks on the calendar, not files in the panel

## What changed

`src/compute_metrics.py` gains `horizon_window(weeks, back, horizon=None)`. It
takes a window's two ends by position, as before, and then holds them to the
calendar: the start must be dated exactly `7 * back` days before the end. If it
is not, it raises `PanelError` and names the week the panel owes.

`horizon_returns` reads its two weeks through it, so every return computed in
this repo over weekly files passes the check -- the scoring path
(`compute`) and the grading path (`src/evaluate.py`, which calls
`horizon_returns` directly). `compute` asks it before the anchor gate, because
the anchor spread is a property of the pair of weeks and of the wrong pair it
is the wrong question.

No weight, band, threshold or formula changed, and no output field was added
or renamed. On a panel that holds one file per week the function returns the
same two files position always picked.

## The defect, measured

`horizon_returns` picked `weeks[-1]` and `weeks[-1 - back]` and nothing checked
how far apart they were. Position counts files. With a week absent, the file
in that position is seven days further off for every week missing.

Run at `a8363de` on a copy of the council's committed panel, cut at 2026-07-31,
with `2026-07-03.json` removed:

| as_of | horizon | window read | Communication Services vs SPY | the real figure |
|---|---|---|---:|---:|
| 2026-07-10 | week | 2026-06-26..2026-07-10 (two weeks) | +0.733 | -1.276 |
| 2026-07-10 | month | 2026-06-05..2026-07-10 (five weeks) | +2.458 | +2.623 |
| 2026-07-31 | month | 2026-06-26..2026-07-31 (five weeks) | -1.890 | -3.298 |

Ten of ten constituents each time, no `PanelError`, no warning. Only
`window_from` in the output shows it. With the file present but `series: {}`
the same runs give 0 of 10 and twelve warnings, which is loud and fine: the
dangerous case is the file that is not there.

It never shipped. The committed panel is 113 Fridays, 2024-08-09 to
2026-10-02, every one seven days after the last.

## Why now

weekly-council-scan PR #136 (merged 2026-10-05) changes the council's weekly
writer to refuse a week whose Friday has no SPY bar until a later session
proves the Friday was a holiday. The week is then written about a week late,
from the week's last session, with a top-level `session_note`. The next two are
2026-12-25 and 2027-01-01, Fridays running.

The council's own gate now fails when a Friday between two weekly files has no
file, so a hole should never be committed. This repo should not depend on
that. Its one rule is never invent a number, and a two-week return reported as
a week is one.

## Refuse the run, not the horizon

The choice was between `PanelError`, which refuses the whole run, and a
per-horizon refusal carried in the output. It is `PanelError`.

- **It is what the module already does with the same failure.** A panel too
  short for the month horizon refuses the whole run although the week horizon
  is computable (`test_short_panel_is_refused_for_the_month_horizon`). That is
  a window whose start does not exist; a hole is the same thing in the middle
  of the panel instead of at its head. The anchor gate is also a property of
  one horizon's pair of weeks, and it too raises.
- **The module's line is structural against per-series.** A missing or
  zero-volume bar is reported in the output with its denominator. Which weeks
  the panel holds, on what basis and what anchor, is refused. A missing week
  is the second kind.
- **A per-horizon refusal would need a shape nothing downstream has.**
  `stage_run.py` reads `b["week"]` unconditionally, `make_sector_inputs`
  describes any absent horizon with the day horizon's "needs daily bars"
  text, and `heatmap.py` would record the horizon as unavailable in a forecast
  artifact that can never be rewritten. A refused run costs the days it takes
  upstream to write the week. A half forecast is permanent.
- **The remedy is upstream and specific**, and the message says so.
  `stage_run.py` already catches `PanelError`, prints `REFUSING to stage` and
  exits 2. Nothing downstream changed.

The cost is real and accepted: a hole at week W refuses every run from W+7 to
W+28, including three whose week horizon is whole. That is the trade the
short-panel refusal already makes.

What staging prints, for the measured case:

    REFUSING to stage -- the price panel is not usable:
      The week window ending 2026-07-10 must start 7 days earlier, at 2026-07-03.
      The panel has no weekly file for 2026-07-03, so the file 1 place before the end is 2026-06-26, 14 days earlier.
      A return over 14 days is not a week return and is refused rather than reported as one.
      Upstream (weekly-council-scan) has to write that week before this window can be read.

Every Friday absent between the two files is named, so the three-week gap
over Christmas and New Year reads `2026-12-25, 2027-01-01`. When the window is
too short instead -- a duplicated or off-cycle file -- the message lists the
files it found.

## Scope: the two ends, and only the weeks a horizon reads

The check is on the two ends because those are what a return reads. That is
the scope the anchor gate takes, for the same reason: `data/weekly` is an
observation log, and a week missing months back moves no number in this run. A
test pins it.

A week that is present is an ordinary week, whatever session it holds. The
five holiday weeks already in the panel (2025-04-18, 2025-07-04, 2026-04-03,
2026-06-19, 2026-07-03) are filed under their Friday with
`"session_note": "Friday holiday; bars from <the Thursday>"`. The date is what
is checked and the note is not read: the same week filed under its Thursday
would leave the Friday without a file, and is refused. A test pins that too.

## The grading side had the same defect

`src/evaluate.py` anchors its window at the forecast date and counts `back`
files forward, then hands the slice to `horizon_returns`. Not changed here, and
it did not need to be: it inherits the gate.

Measured in memory, nothing written, on a copy of the committed panel with
`2026-09-18.json` removed, grading the 2026-09-11 forecast's week horizon:

| | window graded | SPY | hit / partial / miss | rank correlation |
|---|---|---:|---|---:|
| panel whole | 2026-09-11..2026-09-18 | -0.340 | 5 / 3 / 3 | -0.0182 |
| `a8363de`, week absent | 2026-09-11..2026-09-25 | +0.924 | 5 / 2 / 4 | +0.1818 |
| this change, week absent | refused, naming 2026-09-18 | | | |

It surfaces as an uncaught `PanelError`, the way the basis gate already does
on that path, and no artifact is written. Two things are left as they are and
are worth knowing. The message calls the window `1-week` or `4-week`, because
`horizon_returns` knows how far back it reads and not what the horizon is
called. And `WINDOW NOT CLOSED` is still decided by counting files, so with a
week absent inside a month window that has in fact closed it reports "not
closed" for one more week and then refuses on the gap. Both are refusals; a
wrong grade is not reachable.

## The daily tape: checked, and deliberately not changed

`src/daily_tape.py` and `src/macro_comparisons.py` also take their two ends by
position. The same check does not apply, and nothing was changed beyond a
docstring that says so.

**What their windows are.** `HORIZON_SESSIONS = {"day": 1, "week": 5}`: one
session and five sessions, read as `sessions[-1]` and `sessions[-1 - back]`.
`macro_comparisons` has no window of its own. It is handed the tape's session
list and the tape's horizons, and a test holds its `window_from` /
`window_to` equal to the sectors'.

**Why there is nothing to hold them to.** Sessions are not on a grid. Every
published tape, against the calendar and the daily panel:

| tape | horizon | window | calendar days | weekdays | weekdays with no file |
|---|---|---|---:|---:|---|
| 2026-09-10 | week | 2026-09-02..2026-09-10 | 8 | 6 | 2026-09-07 (Labor Day) |
| 2026-09-11 | week | 2026-09-03..2026-09-11 | 8 | 6 | 2026-09-07 (Labor Day) |
| 2026-09-14 | day | 2026-09-11..2026-09-14 | 3 | 1 | |
| 2026-09-14 | week | 2026-09-04..2026-09-14 | 10 | 6 | 2026-09-07 (Labor Day) |
| 2026-09-22 | day | 2026-09-18..2026-09-22 | 4 | 2 | 2026-09-21 |
| 2026-09-22 | week | 2026-09-14..2026-09-22 | 8 | 6 | 2026-09-21 |
| 2026-09-23 | week | 2026-09-15..2026-09-23 | 8 | 6 | 2026-09-21 |

The other eleven windows are one session over one weekday, or five sessions
over five weekdays and 7 calendar days.

A rule of "five sessions is seven days" would have refused three correct
tapes. And no rule on the calendar separates the last three rows from the
first: Labor Day and 2026-09-21 both leave a 5-session window 8 days long with
six weekdays in it and one of them unfiled.

**What was found.** 2026-09-21 was not a holiday. weekly-council-scan's
CLAUDE.md records eight sessions lost between 2026-09-21 and 2026-10-02 with
every run green, and the daily panel has no file for that Monday. So three
published windows are one session longer than their label: the 2026-09-22 day
window is two sessions and its week window six, and the 2026-09-23 week window
is six. 2026-09-23 is the newest tape, so it is the one the README renders
under `5d`. This is the weekly defect's shape, and on the tape it has shipped.

**What the panel can and cannot say.** A window whose weekday count equals its
session count is provably whole: a session cannot fall on a weekend, so no
session is missing from it. Twelve of the eighteen published windows are that.
A window with more weekdays than sessions holds a weekday with no file, and
whether that is a holiday or a hole is not in the panel. It is the upstream
witness's knowledge (`daily_observe.py --audit`, which asks the provider which
sessions exist).

**Options, none taken here.**

1. Upstream writes the previous session into each daily file, from the same
   witness that gates the write. The tape then checks the chain exactly, and
   refuses a break. This is the fix that needs no calendar.
2. The tape says what it can prove: weekdays in the window beside sessions
   read, and a note when they differ. In the artifact that changes the bytes
   of every tape, and `daily_tape.py` refuses a recompute of a published date
   that differs, so the scheduled job would exit 2 on 2026-09-23 until
   upstream posts a new session. In `render_tape.py` it touches no artifact.
   Either way it fires on every holiday as well.
3. An exchange calendar in this repo. Upstream's writer waits for a later
   session as proof rather than consult one, its offline gate knows no
   holidays, and a list of holidays is not a list of sessions held.

Published tapes are not rewritten and nothing is backfilled, whichever is
chosen.

## Verification

On the council panel at upstream `e8b1605` (main, with PR #136 merged):

- `compute()` for every `as_of` in the panel, 113 of them, before and after
  the change: byte-identical JSON, 109 computed and the same 4 refused at the
  head of the panel for being too short.
- The five committed cycles (2026-08-21, 09-11, 09-18, 09-25, 10-02): every
  computed component in the staged inputs, the assembled input and the
  forecast reproduces. Against the basket file each cycle was staged with,
  all 396 compared values per cycle match. Against today's baskets the only
  differences are Real Estate's `constituents_expected` (10, now 9) and
  `coverage_pct` in the three cycles staged before AVB left on 2026-09-21,
  the same before and after this change.
- The measured case above now refuses, naming 2026-07-03, for both dates.

No forecast was re-scored and nothing under `data/` was written.

Fifteen tests, twenty cases with their parameters, cover it: the gate
returning the same two files position picks; a contiguous panel giving the
same windows and returns; the week before the end missing; each week of the
month window missing in turn; a present holiday week as the end, the start and
the inside of a window; the same week misfiled under its Thursday; both weeks
owed over Christmas and New Year named, and accepted once written; a hole
older than both windows; a duplicated file; an `as_of` that is not a date; the
label when no horizon is given; staging refusing and writing nothing; grading
refusing a hole in the week and the month window; and a hole before the
forecast date costing nothing. Run against `a8363de`, the seven cases that
assert unchanged behaviour pass and the thirteen that need the gate fail.
Suite is 266.
