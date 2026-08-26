# CLAUDE.md - sector-regime-heatmap

Scores the expected relative opportunity of the 11 GICS sectors across day,
week and month horizons. Manual, auditable, deliberately slow.

## Environment

Windows. All file I/O is explicit `encoding="utf-8", newline="\n"`; all JSON is
`ensure_ascii=True`. A bare `read_text()` picks up cp1252 on Windows and
crashes on the arrow and check-mark glyphs in the upstream wiki, and it makes
content hashes differ between a local run and CI.

`scripts/preflight.py` requires `src/`, `scripts/`, `config/` and `README.md`
to be **valid UTF-8**. It required pure ASCII until 2026-08-26; the hazard it
was guarding is the implicit-encoding read above, which the explicit
`encoding="utf-8"` already fixes, so human-facing markdown may use symbols. A
stray cp1252 byte from an editor still fails the gate.

**Data artifacts are still strictly ASCII** and that has not moved: every JSON
writer passes `ensure_ascii=True` so a content hash is byte-identical on
Windows and in CI. `tests/test_import.py` pins it.

The README dashboard chart is aligned by padding, so everything inside its
fenced block must be single-width. Emoji are double-width and shear the bars;
they belong in the markdown table, where nothing lines up. A test enforces it.

## Before anything

    python scripts/preflight.py     # config-drift gate
    python -m pytest -q             # 94 tests

Three NOTE lines on preflight are informational, not failures: the CapTier
divergence count, the CapTier ordering warning, and the SPCX month-horizon
constraint.

## The one rule

**Never invent a number.** Every defect this repo has hit came from data that
was wrong but confident, not data that was obviously broken. The gates below
exist because each one shipped at least once. Do not loosen one to make a run
succeed -- a refused run is the system working.

## The five components

Three are arithmetic and are computed from the price panel. Two are judgment.

| Component | Source |
|---|---|
| `breadth` | percent of the equal-weight basket with positive return |
| `relative_momentum` | basket return minus SPY, ranked across the eleven |
| `volume_confirmation` | advancing share of basket volume |
| `regime_fit` | **judgment** -- emitted null |
| `macro_catalyst` | **judgment** -- emitted null |

`src/heatmap.py` refuses to score a file with a null component. That refusal is
the handoff, not a bug. Never fill a judgment component to make the pipeline
run; never default one to 50.

The day horizon is not offered. It needs daily bars and the upstream feed
commits Friday closes only.

## The gates, and what each one caught

- **Adjustment basis** (`SOURCE_BASIS`). Total-return and price-only closes
  cannot be mixed. A supplied spreadsheet agreed with the panel to 0.0000% on
  the latest week and diverged 1.56% median a year back -- non-payers matched
  exactly, dividend payers diverged by accumulated yield. Splicing injects ~2.7
  points of phantom dispersion, worst in Utilities, Real Estate, Staples and
  Energy, and it reads as signal.
- **Adjustment anchor**. Adjusted closes are back-adjusted to the *fetch* date.
  Scoped to the two weeks a horizon actually reads, not the whole panel --
  `data/weekly` is an observation log and legitimately spans months of fetch
  dates. Warns past 35 days, refuses past 180.
- **Zero-volume bars**. A close printed behind zero volume is not a trade. AVB
  shipped one: close 65.9005 on 2026-08-21 against a real 184.06. Left in it
  computes -64.2% and moved Real Estate from rank 6 to rank 11 of 11. The
  median was untouched at -0.05%, which is why `metric_definitions.md` prefers
  the median.
- **Extreme moves** are flagged and **retained**, never dropped. NEM ran +41.2%
  over four weeks on healthy volume. Dropping real crashes is worse than
  reporting them.
- **Denominator honesty**. Every basket reports `constituents_used` against
  `constituents_expected`. Under 8 of 10 sets `data_quality.status: fail` and
  `assemble_payload.py` refuses. Never compute over survivors while reporting
  as though it ran over ten.
- **Immutability**. Forecast artifacts refuse to overwrite. Corrections are new
  dated files.
- **No look-ahead**. Do not backdate forecasts. The panel contains what
  happened next; any judgment written today for a past date is contaminated,
  and ten backdated runs would trip the automation gate on false evidence.

## Single sources of truth

- `config/watchlist_110.csv` -- basket membership. Never hand-edit; it is a
  transcription of `Seven_Orbs_Watchlist_110.xlsx`.
- `config/sector_baskets.yaml` -- **generated** by `scripts/sync_baskets.py`,
  cap-descending so `top_two_contribution_pct` has a referent. Do not edit.
- `config/score_weights.yaml` -- the only copy of weights and bands.
  `assemble_payload.py` stamps them into each dated input so artifacts stay
  replayable. Component weights must sum to 1.00 per horizon.
- `config/watchlist_overrides.yaml` -- derived corrections. The spreadsheet's
  `CapTier` column is **not an ordering**: 26 of 110 names carry a smaller tier
  than a name with a lower market cap. `DivYield_%` is populated for 69 of 110
  and must not be used.

Any change to weights, thresholds or formulas needs a dated entry in
`docs/decisions/`. That is `docs/decision_log_policy.md`, not a preference.

## A cycle

    python scripts/stage_run.py --panel ../weekly-council-scan/data/weekly
    # fill regime_fit, macro_catalyst, why, risks from the attached evidence
    python src/assemble_payload.py examples/base_payload.json inputs/<date> data/inputs/<date>_manual.json
    python src/heatmap.py data/inputs/<date>_manual.json
    python scripts/render_dashboard.py

`stage_run.py` attaches per-sector evidence from the pinned research snapshot
with `source_path` and blob SHA, so a `why` entry can cite verified text. Two
entries minimum or confidence caps at low, by design.

`scripts/crosscheck_prices.py` compares the panel against the fundamentals
snapshot. Advisory, not a gate. This is how AVB surfaced. Run it when a new
snapshot lands.

## Outstanding

- **Backfill not run.** 9 of 11 sectors below 8 constituents; `stage_run.py`
  correctly refuses. Dispatch "Backfill weekly panel" in weekly-council-scan.
- **0 of 10 manual runs.** The runbook wants 10 before any schedule. They are a
  forward test; do not compress them.
- **No evaluation loop.** `config/evaluation.schema.json` is unused and
  `data/evaluations/` is empty. The arithmetic half is disciplined by
  construction; the judgment half is disciplined only by grading at close. This
  is the most valuable thing left to build.
- **The rank-based momentum mapping is untested** against outcomes. If cycle 1
  reads wrong, suspect that first.
- **Market caps in `watchlist_110.csv` are undated.** They drive ordering and
  tier derivation only, never scoring, but the ordering will go stale.
