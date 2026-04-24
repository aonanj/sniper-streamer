# Review Prompt

You are reviewing persisted data from a local Hyperliquid USDC perp screener.
Use the files in this export to recommend precise tuning changes to the current
setup.

Focus on:

1. Whether alert thresholds are too noisy or too quiet by symbol.
2. Whether volume-scaled thresholds need different fractions or floors.
3. Whether `ALERT_IMPACT_EXCESS_BPS` and `ALERT_BOOK_IMBALANCE_PCT` match the
   observed book conditions.
4. Whether taker-flow cluster settings need a different minimum notional,
   bucket width, or count.
5. Whether each watchlist symbol should share one global config or need
   symbol-specific overrides.
6. Any persisted metrics that are always missing, stale, or non-discriminating.

Start with:

- `02_config.json`
- `03_table_counts.csv`
- `04_snapshot_symbol_summary.csv`
- `05_snapshot_metric_summary.csv`
- `07_trade_flow_minutes.csv`
- `08_flow_cluster_candidates.csv`
- `09_alert_summary.csv`
- `10_alerts.csv`

Recommend concrete changes as config diffs or exact replacement values, and
explain which rows or distributions support each recommendation.
