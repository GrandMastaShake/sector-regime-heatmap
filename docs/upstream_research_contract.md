# Weekly Council Scan Contract

## Purpose

`GrandMastaShake/weekly-council-scan` supplies a versioned weekly research prior to this repository. It does not directly determine daily sector ratings.

## Import rule

Each import must capture source repository, branch, source path, source commit SHA, source file SHA, and import timestamp. The original wiki content remains authoritative in the upstream repository; this project stores only dated structured extracts and provenance.

## Scoring rule

Weekly research may inform `regime_fit` and `macro_catalyst`. Live internal breadth, equal-weight relative momentum, volume participation, and risk controls can contradict it. When they do, the dashboard must retain the contradiction as disconfirming evidence and lower confidence rather than silently overriding either source.

## Technology mapping

Technology receives two upstream inputs: `wiki/tech.md` and `wiki/semiconductors.md`. Semiconductor evidence is preserved as a named sub-driver, not merged invisibly into general technology commentary.

## Import artifact

A dated import manifest belongs under `data/weekly_research/YYYY-MM-DD/manifest.json`. Every sector extract must cite its exact source path and Git SHAs.

## No look-ahead rule

A daily forecast may only use the most recent upstream weekly commit available before its forecast timestamp. Later weekly edits, corrections, or post-close reports may not be backfilled into prior forecast artifacts.
