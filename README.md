# Sector Regime Heatmap

An auditable daily research system that scores the expected relative opportunity of the 11 GICS sectors across day, week, and month horizons.

## Design principles

- The system is a decision-support and research tool, not a trading system or a guarantee of returns.
- Regime fit is a structural prior; watchlist breadth, relative momentum, volume, and macro data update that prior.
- Every pre-market call is saved before the open. Every after-close result is scored against that call.
- No model or threshold changes occur silently: configuration and methodology changes require a Git commit and an entry in the decision log.
- A sector can be neutral or uncertain. The system must not force a bullish or bearish call.

## Initial score

`score = 0.35*regime_fit + 0.20*breadth + 0.20*relative_momentum + 0.15*volume_confirmation + 0.10*macro_catalyst - risk_penalty`

Scores are maintained independently for day, week, and month horizons. The weights are research defaults, not optimized parameters.

## Repository map

- `config/`: versioned watchlist, sector baskets, thresholds, and score weights
- `docs/`: methodology, data contracts, operational rules, and decision-log policy
- `data/forecasts/`: immutable pre-market forecast artifacts
- `data/evaluations/`: after-close forecast evaluations
- `src/`: data ingestion, regime classification, scoring, reporting, and evaluation code
- `.github/workflows/`: scheduled job definitions; disabled until data access is configured

## Status

Foundation only. No scheduled workflow or automated data collection is enabled yet.
