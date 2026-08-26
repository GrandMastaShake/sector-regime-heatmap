# 2026-08-25 - Repo hardening and weight normalization

Required by `docs/decision_log_policy.md`: any change to weights, thresholds,
or scoring formulas needs a commit and a dated rationale.

## Scoring change

`config/score_weights.yaml` v1 -> v2.

In v1 the five component weights summed to 0.95 on every horizon, because
`risk_penalty_max: 0.05` was counted inside the 1.00 budget. `risk_penalty` is
subtracted after the weighted sum, so it never belonged there. The effect was
that a sector scoring 100 on all five components topped out at 95, and the
rating bands (favorable at 70) were calibrated against a compressed scale.

The missing 0.05 is restored to `regime_fit` on each horizon. Evidence that
this is the original intent: the formula published in README.md
(`0.35*regime_fit + ...`) sums to exactly 1.00 and matches the week row once
the 0.05 is added back. Day goes 0.15 -> 0.20 and month 0.40 -> 0.45 by the
same reasoning.

Scores are not comparable across v1 and v2. No v1 forecast artifacts exist, so
nothing is being restated.

## Behavioural changes

- A negative `risk_penalty` is rejected. In v1 it raised the score: -0.50
  turned a 47.5 neutral into a 97.5 favorable at high confidence.
- A missing component is rejected. In v1 it was silently dropped from the
  weighted sum, lowering the score and reporting it at high confidence - data
  loss presented as a confident bearish call.
- A component outside 0-100 is rejected rather than clamped.
- Confidence is evidence-gated. A sector with no logged `why` entries can no
  longer be high confidence, per `docs/metric_definitions.md`.
- Forecast artifacts refuse to overwrite. Corrections must be new dated files.
- Weights and bands are stamped into each dated input by the assembler, so a
  historical artifact stays replayable after config changes.

## Provenance change

`src/import_weekly_research.py` now recomputes each source file's Git blob
SHA-1 from the bytes on disk and compares it to the pinned manifest. v1
recorded the claimed SHAs without ever verifying them. The import also checks
the upstream repository name and commit SHA, snapshots the previously ignored
`cross_sector_sources`, and emits a manifest that satisfies
`config/weekly_research_manifest.schema.json`.

All file I/O is explicit UTF-8 with `newline=''` and all JSON output is
`ensure_ascii=True`, so a Windows run and an ubuntu-latest run produce
byte-identical artifacts and identical content hashes.
