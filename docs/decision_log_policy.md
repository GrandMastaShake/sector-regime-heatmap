# Decision Log Policy

## Purpose

The repository is an audit trail for humans and AI agents. It should answer: what did we believe, why did we believe it, what happened, and what did we learn?

## Required daily artifacts

### Pre-market forecast

Path: `data/forecasts/YYYY-MM-DD_premarket.json`

Must include timestamp, Git commit SHA, data timestamp, regime call, confidence, all sector component scores, final ratings for day/week/month, evidence notes, key risks, and disconfirming evidence.

### After-close evaluation

Path: `data/evaluations/YYYY-MM-DD_close.json`

Must include actual sector-basket returns, return versus SPY, breadth and volume outcome, forecast grade, calibration observation, and one or more error labels if the call failed.

## Error labels

- `regime_miss`
- `event_shock`
- `breadth_failure`
- `concentration_failure`
- `macro_override`
- `data_quality`
- `unknown`

## Change discipline

Any change to regime definitions, sector membership, weights, thresholds, or scoring formulas requires a commit and a dated note explaining the rationale. Do not alter historical forecast artifacts.
