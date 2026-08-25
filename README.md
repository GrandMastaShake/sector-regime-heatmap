# Sector Regime Heatmap

An auditable daily research system that scores the expected relative opportunity of the 11 GICS sectors across day, week, and month horizons.

## Design principles

- The system is a decision-support and research tool, not a trading system or a guarantee of returns.
- Regime fit is a structural prior; watchlist breadth, relative momentum, volume, and macro data update that prior.
- Every pre-market call is saved before the open. Every after-close result is scored against that call.
- No model or threshold changes occur silently: configuration and methodology changes require a Git commit and an entry in the decision log.
- A sector can be neutral or uncertain. The system must not force a bullish or bearish call.

## Score

`score = sum(component * weight) - risk_penalty`, clamped to 0-100.

Weights differ by horizon and live in one place only: `config/score_weights.yaml`.
`src/assemble_payload.py` stamps them into each dated input so every forecast
artifact records the exact weights and bands it was scored against and stays
replayable after the config changes. Component weights must sum to 1.00 per
horizon; `scripts/preflight.py` fails the build if they do not.

| Component | Day | Week | Month |
|---|---:|---:|---:|
| regime_fit | 0.20 | 0.35 | 0.45 |
| breadth | 0.25 | 0.20 | 0.15 |
| relative_momentum | 0.25 | 0.20 | 0.15 |
| volume_confirmation | 0.20 | 0.15 | 0.10 |
| macro_catalyst | 0.10 | 0.10 | 0.15 |
| risk_penalty_max | 0.05 | 0.05 | 0.05 |

`risk_penalty` is a fraction in [0, risk_penalty_max], subtracted after the
weighted sum. It is never part of the 1.00 budget and can never be negative.
The weights are research defaults, not optimized parameters.

## Repository map

- `config/`: versioned watchlist, sector baskets, thresholds, and score weights
- `docs/`: methodology, data contracts, operational rules, and decision-log policy
- `data/forecasts/`: immutable pre-market forecast artifacts
- `data/evaluations/`: after-close forecast evaluations
- `src/`: data ingestion, regime classification, scoring, reporting, and evaluation code
- `scripts/preflight.py`: config-drift gate, run before every run and in CI
- `tests/`: regression tests, one per defect found in audit
- `dashboards/`: generated Markdown heatmaps (committed alongside forecasts)
- `.github/workflows/`: CI plus the manual weekly research import

## Status

Manual-only. No scheduled workflow and no automated market-data collection.
The weekly research import runs on `workflow_dispatch` with an explicit as-of
date and pinned upstream commit; it verifies every source file's Git blob SHA
before writing a snapshot and aborts on any mismatch.

Per `docs/manual_runbook.md`, complete at least 10 manual daily runs before
enabling any schedule.

## Quick start

```
pip install -r requirements.txt
python scripts/preflight.py
python -m pytest -q
python src/assemble_payload.py examples/base_payload.json inputs/2026-08-25 data/inputs/2026-08-25_manual.json
python src/heatmap.py data/inputs/2026-08-25_manual.json
```
