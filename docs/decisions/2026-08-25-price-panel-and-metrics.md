# 2026-08-25 - Deterministic components from the price panel

## What is computed and what is not

Three of the five scoring components are arithmetic and are now derived from
the weekly price panel, never assessed:

    breadth              percent of the equal-weight basket with positive return
    relative_momentum    basket return minus SPY, ranked across the eleven
    volume_confirmation  advancing share of basket volume

`regime_fit` and `macro_catalyst` stay judgment and are emitted null.
`src/heatmap.py` refuses to score a file with a null component, so a partial
sector file cannot become a forecast by accident. That refusal is the handoff.

The day horizon is not offered. It needs daily bars; the upstream feed commits
Friday closes only. `HORIZON_WEEKS` holds week and month, and the day block in
every generated sector file carries an explicit `unavailable` note rather than
a fabricated score.

## Gate: adjustment basis

The supplied `Watchlist_110_Weekly_History_1Year.xlsx` covers all 110 names for
52 weeks and agrees with `weekly-council-scan/data/weekly/` to 0.0000 percent
on the most recent week. It still cannot be used.

Across all 52 weeks the two diverge monotonically going backwards: 0 percent
recently, 1.56 percent median a year ago. The split is exact. NVDA, AMZN, TSLA,
ISRG, VRTX and AMD agree to within 0.13 percent; XOM is 2.24 percent apart, PEP
3.96, PSA 4.15, D 4.42, SPG 4.76, O 5.48, PGR 6.50. Non-payers match and
dividend payers diverge in proportion to accumulated yield.

`backfill_weekly.py` upstream uses `yfinance auto_adjust=True`, so the panel is
total-return adjusted and the spreadsheet is price-only. Splicing them puts one
basket on two bases and injects roughly 2.7 points of phantom dispersion
against dividend payers over a year -- systematic, worst in Utilities, Real
Estate, Staples and Energy, and indistinguishable from signal.

`SOURCE_BASIS` maps each price source to its basis. An unlisted source is
refused rather than assumed, and a panel carrying two bases is refused outright.

## Gate: zero-volume bars

Found while validating, not by looking for it. `data/weekly/2026-08-21.json`
carried `AVB: {close: 65.9005, volume: 0}`. AVB closed 184.06 the prior week
with a 52-week range of 160.10 to 198.63, so the print is not a market move,
and the supplied spreadsheet omits AVB for that week entirely -- two
independent sources agreeing the bar is bad.

Left in, it computes a -64.2 percent weekly return and moved Real Estate from
rank 6 to rank 11 of 11, and from +1.07 to -6.03 percent versus SPY. Median
return was unaffected at -0.05, which is exactly why
`docs/metric_definitions.md` prefers the median.

A bar with no volume is not a trade. It is excluded and recorded in `missing`
with its reason. A correction file has been filed upstream per the DATA_FEED
contract; no price was invented, AVB simply moves to `missing`.

## Gate: extreme moves are flagged, not dropped

NEM ran +41.2 percent over four weeks with healthy volume on both ends, which
is a real gold move. Moves beyond 40 percent are recorded as anomalies and
warned; they are never excluded, because silently dropping real crashes would
be worse than reporting them.

## Gate: denominator honesty

Every basket reports `constituents_used` against `constituents_expected` and a
coverage percentage. Fewer than eight of ten raises a warning and sets
`data_quality.status` to `fail`; any shortfall sets `warn`. Nothing is ever
computed over survivors while reporting as though it ran over ten.

Until the 44-name backfill lands upstream, coverage is thin for most sectors --
Communication Services has two of ten. The engine says so on every run rather
than producing numbers that look complete.
