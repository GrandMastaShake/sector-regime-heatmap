# Methodology

## Objective

Generate an explainable sector heatmap for the 11-sector, 110-stock internal watchlist. The output describes relative opportunity and uncertainty for daily, weekly, and monthly horizons.

## Regime-first framework

The regime label is an input prior, not a daily prediction engine. Initial labels include: broad expansion, policy relief, rate-driven stress, credit contagion, exogenous shock, stagflation shock, valuation risk, and transition.

The system must preserve an `unknown` or `transition` state when evidence is mixed. It must not convert uncertainty into a forced directional recommendation.

## Sector components

1. Regime fit: sector sensitivity relative to the active regime.
2. Breadth: percent positive, median constituent return, trend participation, and leadership concentration within the sector basket.
3. Relative momentum: sector basket return versus SPY and versus peer sectors.
4. Volume confirmation: up-volume/down-volume balance and abnormal participation.
5. Macro/catalyst: relevant rates, dollar, commodities, credit, policy, earnings, or scheduled events.
6. Risk penalty: disagreement, one-name concentration, volatility shock, contradictory signals, or data quality flags.

## Rating bands

- 70-100: favorable
- 55-69: constructive but mixed
- 45-54: neutral
- 30-44: unfavorable
- 0-29: defensive

Confidence is separate from score. A high score with weak breadth or conflicting regime evidence must show lower confidence.

## Non-negotiable guardrails

- Do not infer sector strength from a single constituent.
- Display the evidence trail for each sector.
- Keep inputs and outputs immutable by date.
- Grade the forecast at close and at the stated week/month horizons.
- Treat FinViz as optional future enrichment, never as a required source.
