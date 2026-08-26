# 2026-08-26 - Grading the judgment half

## What was built

`src/evaluate.py` grades a published forecast against the panel and writes
`data/evaluations/<as_of>_close.json` against the schema that had sat unused
since the repo was created.

Per horizon it computes the realized equal-weight basket return, the excess
over SPY, a hit/partial/miss for each sector's directional claim, the rank
correlation between forecast score and realized excess across the eleven, and
a hit rate broken out by the confidence the call carried.

## Why it is the piece that was missing

Three of the five components are arithmetic and cannot be argued with. The
other two, `regime_fit` and `macro_catalyst`, are judgment, and until a call is
graded at close nothing disciplines them at all. Ten forward cycles produce ten
unfalsified opinions unless something scores them.

The calibration-by-confidence breakout is the point. A run is allowed to be
wrong; what it is not allowed to be is wrong *and* confident, repeatedly,
without that showing up somewhere.

## What it refuses to do

- **An open window.** Grading the week horizon before the next Friday exists in
  the panel is scoring a forecast against itself. Refused with the date it
  needs.
- **A horizon the forecast declared ungradeable.** Cycle 1 was written five
  days after the close it reads and says so; grading it would produce a number
  that looks like evidence and is not. Going forward this is an explicit
  `grading` block on the input payload, carried into the artifact by
  `heatmap.py`. Cycle 1 predates it, so a deliberately conservative scan of the
  regime's disconfirming evidence bridges the gap -- it can only ever refuse a
  horizon, never permit one.
- **Assigning an error label.** Why a call missed is judgment of exactly the
  kind `regime_fit` is. `error_labels` is emitted empty with
  `labels_required_for` naming the sectors that missed, the same handoff shape
  `stage_run.py` uses.

An evaluation artifact is immutable once written, like the forecast it grades.

## One bug worth recording

The first version matched the ungradeable declaration against the whole
evidence line. Cycle 1's disclosure forbids the *week* horizon in one sentence
and calls the *month* horizon "materially less affected" in the next, so
line-scope matching refused both -- a false refusal that would have silently
cost a real grade four weeks from now. Matching is per sentence, and
`test_a_later_sentence_about_another_horizon_does_not_refuse_it` pins it.

The failure direction was the safe one by construction: the inference can only
refuse, so the bug cost a grade rather than manufacturing one.

## Status

Running it against cycle 1 today refuses both horizons and writes nothing --
week by declaration, month because the window closes 2026-09-18. That is the
correct output, and it is what the loop will keep saying until there is
something honest to grade.

13 tests. Suite is 119.
