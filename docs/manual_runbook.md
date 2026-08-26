# Manual Runbook

## Purpose

Run the first heat-map iterations manually before enabling scheduled jobs.

## Steps

1. Create a dated input file from a modular base payload plus the relevant sector input files.
2. Replace all example values with dated, source-backed evidence.
3. Include all 11 sectors and all three horizons.
4. Record regime evidence and disconfirming evidence.
5. Run `python src/heatmap.py path/to/input.json`.
6. Review the generated JSON forecast artifact and Markdown dashboard.
7. Run `python scripts/render_dashboard.py` to refresh the README dashboard block.
8. After close, write a matching evaluation artifact using `config/evaluation.schema.json`.
9. Commit inputs, outputs, and methodology changes together.

## Before automation

Complete at least 10 manual daily runs. Validate sector membership, data-quality behavior, forecast grading, and confidence calibration before enabling a schedule.

## Audit rule

Do not overwrite a dated forecast artifact. Corrections create a new, dated correction artifact with a note explaining what changed.
## README dashboard

The block between the `DASHBOARD` markers in `README.md` is generated from
`data/forecasts/`, `data/weekly_research/`, and
`config/watchlist_overrides.yaml`. Never edit it by hand.

It renders the most recent forecast artifact. If none exists it says so rather
than showing placeholder scores; a grid of 50s on the front page looks
authoritative to anyone who lands on the repo. `scripts/preflight.py` fails if
the block has drifted from the artifacts it claims to describe.
