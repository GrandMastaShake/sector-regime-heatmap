# 2026-08-26 - An unavailable horizon is recorded, not scored

## What changed

`src/heatmap.py` honours an explicit `unavailable` marker on a horizon block:
it records `score: null`, `rating: "unavailable"` and the stated reason instead
of scoring it. If a block carries `unavailable` **and** a non-null component,
the run refuses -- `unavailable` is not a way to skip a gate.

`src/assemble_payload.py` skips files in the staged directory whose names begin
with an underscore. `scripts/render_dashboard.py` renders `n/a` for a null
score.

No weights, bands, thresholds or formulas changed. A horizon that is offered is
scored exactly as before, including the null-component refusal.

## Why

Cycle 1 was the first end-to-end run of the shipped pipeline, and it did not
run end to end. Three seams between `stage_run.py` and the scorer:

1. `stage_run.py` writes `_cross_sector_evidence.json` into the staged sector
   directory. `assemble_payload.py` globbed `*.json` and raised
   `has no 'sector' field` on it. The stager produced a file the assembler
   refused.
2. `stage_run.py` marks the day block `unavailable` -- the upstream feed
   commits Friday closes only, so there are no daily bars, and `CLAUDE.md`
   states the day horizon is not offered. `heatmap.py` scored all three
   horizons unconditionally and died on `day/regime_fit is not numeric: None`.
3. `render_dashboard.py` string-concatenated `score` and `rating`, which a null
   score would have rendered as `None unavailable`.

Each failure was a disagreement about what an unscored horizon looks like, not
a disagreement about arithmetic.

## The shape of the fix

The refusal that mattered stayed. `heatmap.py` still refuses a null component
in a horizon that claims to be scored -- that gate exists because a dropped
component once read as a confident bearish call. What changed is that a horizon
which openly declares it has no data is now describable in the artifact rather
than being a crash.

The added guard is the important half: a block claiming both `unavailable` and
a supplied component is refused outright, so the marker cannot become the
escape hatch from the null gate. Two tests cover exactly that pair -- the
recorded case and the refused case.

Suite is 102.
