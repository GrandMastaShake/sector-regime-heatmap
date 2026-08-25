# Noise-Resistant Sector Metrics

## Design rule
A sector rating requires broad, independent confirmation. A single large constituent cannot establish sector strength.

## Core metrics
- Breadth: percentage of the basket with positive return.
- Median return: resistant to individual outliers.
- Relative return: equal-weight sector basket minus SPY over the same horizon.
- Sector rank: relative-return rank among 11 sectors.
- Trend participation: percentage above a logged trend threshold.
- Up-volume share: advancing volume divided by total advancing and declining volume.
- Relative-volume ratio: current volume divided by a consistent rolling baseline.
- Top-two contribution: contribution of the two largest effects; high concentration lowers confidence.

## Noise controls
- Equal-weight the 10-name sector baskets for internal breadth and return measures.
- Keep cap-weighted results separate if later added.
- Flag anomalies, zero-volume records, stale quotes, missing tickers, and incomplete history.
- Apply a risk penalty for concentration, signal disagreement, or contradictory macro evidence.
- Keep confidence separate from rating.

## Evidence requirement
Every non-neutral rating needs at least two independent confirmations from regime fit, breadth, relative momentum, volume, or macro/catalyst. A single confirmation produces neutral or low-confidence status.
