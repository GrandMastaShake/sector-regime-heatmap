# 2026-09-11 - A daily tape, and the archetype prior beside it

## What was built

Three things, in two repos.

Upstream, `weekly-council-scan/scripts/daily_observe.py` writes
`data/daily/<session>.json` (DATA_FEED.md sec.4) for every completed US
session, on a weekday schedule. Same shape as the weekly feed plus a required
`cadence` discriminator and a `yahoo-daily` source label.

Here, `src/daily_tape.py` reads that panel and computes the three arithmetic
components per basket over 1 and 5 sessions, writing `data/tape/<as_of>.json`.
`src/regime_prior.py` puts the declared archetype's historical sector priors
beside the live arithmetic and names the places they disagree.
`scripts/render_tape.py` renders both into a README block with its own markers
and its own `--check`, wired into `preflight.py` like the other two generated
surfaces.

## Why a daily cadence was possible at all

`compute_metrics.py` says the day horizon "needs daily bars, and the upstream
feed commits Friday closes only." That was true of the *committed feed*, not of
the data: `snapshot.fetch_weekly_bars` has always downloaded daily bars over a
ranged window and kept one. The other four sessions were being discarded at
write time. Nothing new is fetched and no new provider or credential is
involved -- the bars were already crossing the wire.

## Why it is an observation and not a daily forecast

The obvious reading of "run it daily" is a daily score. That is refused, for
three reasons that are all already written down:

- **Two of the five components are judgment.** `regime_fit` and
  `macro_catalyst` have no daily source. A daily run would have to default them
  or synthesize them, and `heatmap.py` refuses a null component precisely so
  that cannot happen quietly.
- **The runbook wants 10 manual cycles before any schedule.** This is 1 of 10.
  A daily scored run would either burn through that forward test in a fortnight
  of unreviewed runs or bypass it.
- **No look-ahead.** Backdating judgment into past sessions to manufacture a
  history would be scoring against a panel that already contains what happened
  next.

So the tape scores nothing. `is_forecast: false` is in the artifact itself, not
only in the docs, and a test asserts the sector blocks carry neither judgment
component nor any score, band or rating. `evaluate.py` must never grade a tape:
a tape is not a call, and grading one would be scoring the market against
itself.

What this does give daily is the half that *is* arithmetic, on the day it
happens rather than the following Friday.

## Why the daily panel is read alone

Daily and weekly files carry different adjustment anchors, and the gap is
measured, not theoretical. On 2026-08-28 the weekly file (anchor 2026-08-29)
and the daily file (anchor 2026-09-12) agree on SPY to the penny and disagree
by roughly 1% across 57 dividend payers -- and by 50% on APH, which split 2:1
on 2026-09-03.

That is the same hazard `SOURCE_BASIS` guards on a different axis: not
total-return against price-only, but one total-return basis against another
struck on a different date. The anchor-spread gate would not have caught it
either, because the two files are 7 days apart and the warn threshold is 35.
A corporate action needs no 35 days.

`check_cadence` therefore refuses a panel that is not uniformly daily, and it
checks the `cadence` key rather than inferring from the directory name, which
is why that key is required upstream.

## The archetype prior, and why it only ever sits beside the arithmetic

`config/regime_sector_matrix.yaml` holds the published 11x10 sector
excess-return matrix; `config/regime_archetypes.yaml` holds the taxonomy and
the 16 gap-free transitions. Neither feeds a score. `heatmap.py` takes five
components and this is none of them.

The prior's job is to make a disagreement visible. Cycle 1 carried exactly one
and flagged it by hand: Healthcare's archetype-1 prior is -14 points, a
laggard, while the arithmetic had it rank 1 of 11. That contradiction was
written into the sector's `why` and deliberately left standing. `regime_prior.
compare` now finds that shape automatically -- prior rank and tape rank at
least 6 positions apart, half the board -- instead of depending on someone
noticing.

It names disagreements. It does not resolve them. A 1-4 observation prior
against 13 sessions of arithmetic is not a fact about which side is wrong; it
is the question `regime_fit` exists to answer, and that component is judgment
on purpose.

On the first run it flagged four: Energy (prior 11th, tape 3rd), Utilities
(10th, 4th), Financials (2nd, 8th) and Consumer Discretionary (3rd, 9th).
Technology agreed at 1 and 1.

## What the prior refuses to do

- **Infer its own archetype.** It parses `archetype N` out of the most recent
  forecast's `regime.label`, which is where a human declared it. No label, no
  prior, and the block says which. Inferring the regime from price action would
  be a mechanism-identification model -- the research is explicit that
  identifying the mechanism in real time tops out near two-thirds accuracy --
  and it would quietly automate the one call this repo protects.
- **Hide its age.** The declaration's date and age in days render with it. The
  prior on the first tape was 20 days old.
- **Read a null as a zero.** XLRE listed October 2015 and XLC June 2018, so
  neither has a dot-com-era observation. Those cells are null, are not ranked,
  and are never flagged.

## Precision of the transcribed matrix

Whole points, as published. A few cells are cited to one decimal in prose
elsewhere (-34.0, +44.6, -19.9); those round to the values stored and the extra
digit is not carried, because n per cell is 1-4 and a tenth of a point implies
a precision the sample does not have. Five of the ten archetypes are n=1.

Two tests check the transcription rather than trusting it: the 16 transitions
sum correctly, and no contraction archetype hands off to another contraction
archetype -- the finding the taxonomy rests on.

## What this does not change

The weekly forecast pipeline is untouched. It is still 1 of 10 manual cycles,
still gated at 10 before any schedule, and `premarket.yml` / `after-close.yml`
remain disabled placeholders. Nothing here advances the forward test, and it
was not built to: a tape is not a cycle.
