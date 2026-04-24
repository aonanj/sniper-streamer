# sniper-streamer Persisted Data Export

This export is arranged for LLM review of the current Hyperliquid USDC perp screener setup. Start with the summaries before opening raw tables.

## Export Context

- Generated at UTC: `2026-04-24T23:41:30.024088+00:00`
- SQLite database: `/Users/alexo/Projects/sniper-streamer/data/sniper_streamer.sqlite3`
- Selected window: `rows with ts_ms >= 1777059690025 (2026-04-24T19:41:30.025000+00:00)`
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
- `11_llm_review_prompt.md` - ready-to-use review prompt
- `raw_*.csv` - complete normalized table rows when raw export is enabled

## Review Notes

- Hyperliquid public data has no Binance-style all-market forced-order stream, so liquidation rows may be empty unless a separate source has been wired in.
- `basis_source` is `spot` when Hyperliquid spot is available and `oracle` when the dashboard falls back to oracle basis.
- `impact_excess_bps`, `book_imbalance_pct`, taker-flow buckets, and volume-scaled thresholds are the main current tuning surfaces.
- `08_flow_cluster_candidates.csv` is derived from trades for offline review; it is not an exact replay of the live dashboard's volatility-scaled buckets.
