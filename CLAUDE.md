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
    python -m pytest -q             # the whole suite, and it must be green

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

The day horizon is not offered *in the scored forecast*. It needs daily bars,
and for the forecast that is still the binding constraint -- but see the daily
tape below: the upstream feed now commits daily sessions too, and the three
arithmetic components are computed over them. The two judgment components are
what keep the day horizon out of a *score*, not the bars.

## The daily tape

    python src/daily_tape.py --panel ../weekly-council-scan/data/daily
    python scripts/render_tape.py

An observation, not a forecast. It computes the three arithmetic components
per basket over 1 and 5 sessions and writes `data/tape/<as_of>.json`. It
scores nothing: `is_forecast: false` is in the artifact, and a test asserts the
sector blocks carry no judgment component, score, band or rating.
`src/evaluate.py` must never grade a tape -- a tape is not a call.

This does NOT advance the 10-cycle count and was not built to. A tape is not a
cycle, and `premarket.yml` / `after-close.yml` stay disabled.

- **The daily panel is read alone.** `check_cadence` refuses a panel that is
  not uniformly `cadence: daily`. Daily and weekly files carry different
  adjustment anchors: on 2026-08-28 they agree on SPY to the penny and disagree
  ~1% across 57 dividend payers, and 50% on APH, which split 2:1 on
  2026-09-03. The anchor-spread gate would not have caught it -- those two
  files are 7 days apart and the warn threshold is 35. A corporate action needs
  no 35 days.
- **The archetype prior sits beside the arithmetic and never inside it.**
  `config/regime_sector_matrix.yaml` is the published 11x10 matrix;
  `src/regime_prior.py` ranks it against the tape and flags any sector 6 or
  more rank positions apart. It names disagreements and does not resolve them
  -- that is `regime_fit`, and it is judgment on purpose.
- **The prior never infers its own archetype.** It parses `archetype N` from
  the latest forecast's `regime.label`, where a human declared it. No parse, no
  prior, and the block says so. Its age renders with it.
- Null matrix cells (Real Estate and Communication Services before their ETFs
  listed) are not ranked and never flagged. A null is not a zero.

`docs/decisions/2026-09-11-daily-observation-tape.md` has the reasoning.

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

Then, once the window has closed -- a week later for the week horizon, four
for the month:

    python src/evaluate.py data/forecasts/<date>_manual.json \
        --panel ../weekly-council-scan/data/weekly

It refuses rather than guesses. It will not grade a window that has not closed
(that is scoring a forecast against itself), it will not grade a horizon the
forecast declared ungradeable, and it will not assign an `error_label` -- why a
call missed is judgment, the same kind `regime_fit` is, and it is emitted empty
for you to fill. Mark a horizon ungradeable with a `grading` block in the input
payload; cycle 1 predates that and says it in prose instead.

`stage_run.py` attaches per-sector evidence from the pinned research snapshot
with `source_path` and blob SHA, so a `why` entry can cite verified text. Two
entries minimum or confidence caps at low, by design.

`scripts/crosscheck_prices.py` compares the panel against the fundamentals
snapshot. Advisory, not a gate. This is how AVB surfaced. Run it when a new
snapshot lands.

## Outstanding

- **The 2026-08-28 and 2026-09-04 closes cannot be scored now, and should not
  be.** Their week-horizon windows have fully elapsed. Cycle 1 was written five
  days late and had to mark its week horizon ungradeable; these are eight and
  fifteen days late, so there is no partial version worth writing. They are
  lost as forward tests. Do not "catch up" the count with them -- ten backdated
  runs would trip the automation gate on false evidence, which is exactly what
  the no-look-ahead rule is protecting.
- **Cycle 2 is the next Friday close whose research has landed, scored before
  the following Monday opens.** `stage_run.py` requires a research snapshot
  dated 0-7 days AFTER the close it reads. Only one snapshot exists
  (2026-08-24), which predates every close in the panel, so every attempt
  refuses -- correctly. The upstream wikis through 2026-09-08 describe the week
  ending 09-04, not 09-11.

      python scripts/pin_research_snapshot.py --upstream ../weekly-council-scan           --commit <sha> --as-of-date <council session date>
      # then Actions -> "Weekly research import", or the local command it prints
      python scripts/stage_run.py --panel ../weekly-council-scan/data/weekly

  `pin_research_snapshot.py` exists because pinning used to mean transcribing
  sixteen blob SHAs by hand, which is why the repo has one snapshot against a
  plan for weekly ones. It reproduces the hand-built 2026-08-24 manifest
  exactly; a test checks that.
- **1 of 10 manual runs.** Cycle 1 (`2026-08-21`) is published. The runbook
  wants 10 before any schedule. They are a forward test; do not compress them.
  Cycle 2 should read the 2026-08-28 close, which is the first fully ex-ante
  run -- cycle 1 was scored five days late and its week horizon is marked
  ungradeable because of it.
- **Nothing graded yet.** `src/evaluate.py` exists and `data/evaluations/` is
  still empty because no window has closed: cycle 1's week horizon was declared
  ungradeable by the run itself, and its month horizon closes 2026-09-18.
- **The rank-based momentum mapping is untested** against outcomes. If cycle 1
  reads wrong, suspect that first.
- **Market caps in `watchlist_110.csv` are undated.** They drive ordering and
  tier derivation only, never scoring, but the ordering will go stale.
