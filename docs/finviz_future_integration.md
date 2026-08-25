# FinViz Future Integration

FinViz is intentionally optional in version 1.

## Candidate enrichments

- Relative-volume and unusual-volume signals
- Screener snapshots and industry ranking
- Insider and institutional context
- Valuation context and analyst changes

## Rule

The daily dashboard must publish without FinViz. A missing or failed FinViz provider produces an explicit `enrichment_unavailable` status; it must not fail the core job or silently substitute unknown data.
