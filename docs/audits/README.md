# Daily audits

One report per run of the scheduled audit, `YYYY-MM-DD.md`, written by the
routine through the GitHub contents API after it has finished reading. The
audit is read-only everywhere else: it never touches `data/`, `config/`,
`src/` or `scripts/` in either repo, and a refused gate is reported, not
fixed.

The repo is public. A report carries derived numbers only: no raw watchlist
rows, no local paths, no transcript or stack-trace excerpts.

One row per day below, appended by the same run, so "what changed since
yesterday" can be read off the table. Columns: newest weekly file; series
count min/max; anchor spread in days over the two newest weeks (warn above
35, refuse above 180); SPY drawdown from the forward-test peak (alert at
-5%, trigger at -10%); forecasts on disk / evaluations on disk; checks
failed.

| Date | Newest week | Series min/max | Anchor spread (d) | SPY drawdown | Forecasts/evals | Fails |
|---|---|---|---|---|---|---|
| 2026-10-27 | 2026-10-23 | 334/338 | 0 | -2.39% | 6/0 | 1 (evaluation coverage) |
| 2026-10-28 | 2026-10-23 | 334/338 | 7 (across both weeks) | -2.39% | 6/0 | 1 (evaluation coverage) |
| 2026-10-29 | 2026-10-23 | 334/338 | 7.6 (across both weeks) | -2.39% | 7/0 | 1 (evaluation coverage) |
| 2026-10-30 | 2026-10-23 | 334/338 | 7.6 (across both weeks) | -2.39% | 7/0 | 1 (evaluation coverage) |
