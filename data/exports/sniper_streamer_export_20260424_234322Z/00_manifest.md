# sniper-streamer Persisted Data Export

This export is arranged for LLM review of the current Hyperliquid USDC perp screener setup. Start with the summaries before opening raw tables.

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


## Export Context

- Generated at UTC: `2026-04-24T23:43:22.830440+00:00`
- SQLite database: `/Users/alexo/Projects/sniper-streamer/data/sniper_streamer.sqlite3`
- Selected window: `all retained rows`
- Flow-cluster candidate bucket: `0.25%`
- Raw table CSVs included: `True`
- API payload JSON included: `False`

## File Order

- `00_manifest.md` - this guide
- `01_schema.sql` - persisted SQLite schema
- `02_config.json` - current watchlist, thresholds, and persistence knobs
- `03_table_counts.csv` - row counts and time ranges per table
- `04_snapshot_symbol_summary.csv` - per-symbol latest values and threshold hit counts
- `05_snapshot_metric_summary.csv` - per-symbol distributions for persisted snapshot metrics
- `06_latest_snapshots.csv` - latest normalized market snapshot per symbol
- `07_trade_flow_minutes.csv` - one-minute taker-flow buckets from persisted trades
- `08_flow_cluster_candidates.csv` - derived hourly taker-flow price buckets
- `09_alert_summary.csv` - alert counts by symbol and kind
- `10_alerts.csv` - alert event rows with normalized snapshot fields
- `raw_*.csv` - complete normalized table rows when raw export is enabled

> *Note: CSVs of raw market snapshots and raw trades are omitted from this export.*
> *If certain records or ranges of records from one or both of these CSVs, ask the user to provide those.* 

## Review Notes

- Hyperliquid public data has no Binance-style all-market forced-order stream, so liquidation rows may be empty unless a separate source has been wired in.
- `basis_source` is `spot` when Hyperliquid spot is available and `oracle` when the dashboard falls back to oracle basis.
- `impact_excess_bps`, `book_imbalance_pct`, taker-flow buckets, and volume-scaled thresholds are the main current tuning surfaces.
- `08_flow_cluster_candidates.csv` is derived from trades for offline review; it is not an exact replay of the live dashboard's volatility-scaled buckets.
