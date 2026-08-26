# 2026-08-26 - The adjustment anchor is resolved per series, not per file

## What changed

`anchor_of()` takes an optional ticker. When the week carries a
`provenance.series` entry for that ticker, its `fetched_at` is the anchor;
otherwise the file-level `fetched_at` still is. `window_anchor()` takes the
tickers the horizon actually reads and spans every anchor they carry.
`check_basis()` validates per-series `source` values against `SOURCE_BASIS`
alongside the file-level one.

Nothing changes for a file without `provenance`: same anchor, same spread, same
thresholds. `WARN_WINDOW_ANCHOR_DAYS` (35) and `MAX_WINDOW_ANCHOR_DAYS` (180)
are untouched.

## Why

On 2026-08-26 a targeted backfill in `weekly-council-scan` replaced every
weekly file with just its 44 `--only` tickers -- 287 series became 44 across
107 files -- and the workflow reported success. The panel was restored, and the
fix upstream was to add merge semantics: `--merge` adds the named tickers to an
existing week and leaves everything else alone.

That creates a file this repo could not read honestly. Adjusted closes are
back-adjusted to the fetch date. Names merged in today are anchored to today;
the 287 already there are anchored to their original scan. The upstream file
records the difference in `provenance.series` precisely because writing two
adjustment bases under one timestamp would be a confident wrong number.

Reading only the file-level `fetched_at` would have reported one anchor for
two, and the spread that the 180-day refusal is calculated from would have been
understated by however long the gap between the original scan and the backfill
turned out to be. The gate would have looked green while the panel was mixed.

## The case this now catches

Two anchors inside a *single* week is a mixed basis within one cross-section,
not just across time. Breadth compares constituents of one basket against each
other in the same week; if some of those names were merged in later, their
dividend-payer history disagrees with the rest of the basket. That is exactly
the ~2.7 points of phantom dispersion documented in
`2026-08-25-price-panel-and-metrics.md`, arriving through a different door.

## Scope

`adjustment_anchor` in the artifact gains two fields, `distinct_anchors` and
`series_by_anchor`, so a merged window is visible in the record rather than
implied. A merged name that sits in no basket does not widen the spread --
the anchor question is asked of the series actually scored, which is every
basket constituent plus the benchmark.

Five tests cover it: per-series resolution, unchanged behaviour without
provenance, a merged name widening the spread, a two-year splice refused, and
an undeclared per-series source refused. Suite is 99.
