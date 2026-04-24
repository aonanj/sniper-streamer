# sniper-streamer - Usage Tutorial

`sniper-streamer` is a read-only Hyperliquid context dashboard for watching
margin-snipe conditions across a small perp watchlist. It does not place
orders or generate instructions to trade. It helps you see where leverage,
flow, book thinness, basis, and funding stress are lining up.

Hyperliquid does not expose an official public all-market liquidation stream
like Binance `!forceOrder@arr`. This dashboard therefore treats liquidation
data as optional and, by default, uses data that Hyperliquid actually exposes:
asset contexts, trades, `l2Book`, `allMids`, and spot market contexts where
available.

## Running It

From the repo root:

```bash
./.venv/bin/python main.py
```

The shell wrapper is equivalent when it is executable:

```bash
./sniper-streamer.sh
```

Press `Ctrl+C` to quit. OI deltas, funding velocity, realized vol, and beta
columns need a little runtime history before they fill in.

The watchlist lives in `config.py`:

```python
WATCHLIST = ["btc-usdc", "eth-usdc", "icp-usdc", "sol-usdc", "doge-usdc", "bnb-usdc"]
```

## Data Persistence

The app writes a local SQLite database at `data/sniper_streamer.sqlite3`.
SQLite runs in WAL mode, so notebooks and ad hoc readers can query the file
while the streamer is appending.

Persistence runs as a fourth coroutine beside the websocket feed, REST poller,
and renderer. Feed handlers only enqueue events; a dedicated writer owns disk
I/O, schema setup, batching, and retention.

Persisted tables:

- `trades` - every valid watched taker trade, used for later CVD/backtesting
- `liquidations` - every liquidation observed in the trade payload
- `market_snapshots` - downsampled state snapshots, at most once every 5s per
  symbol unless funding changes by at least `0.0001` percentage points
- `alerts` - deduped alerts plus a `snapshot_json` column containing the state
  values at fire time

Rows older than `PERSIST_RETENTION_DAYS` are purged automatically. The default
retention is 14 days.

To export the retained SQLite data for LLM review and threshold tuning:

```bash
./.venv/bin/python scripts/export_persisted_data.py
```

The export lands under `data/exports/` and includes a manifest, current config,
per-symbol summaries, metric distributions, alert summaries, minute trade-flow
buckets, derived flow-cluster candidates, and normalized raw CSVs. To keep only
the most recent run window:

```bash
./.venv/bin/python scripts/export_persisted_data.py --since-hours 4
```

## Data Sources

WebSocket subscriptions:

- `activeAssetCtx` - mark, oracle, funding, OI context
- `trades` - aggressive taker flow for CVD, taker%, average trade size, clusters
- `l2Book` - spread, top-10 depth imbalance, large resting orders
- `allMids` - watchlist mids for realized vol, BTC beta/correlation, spot refresh

Info endpoint polling:

- `metaAndAssetCtxs` - `impactPxs`, `dayNtlVlm`, `premium`, `prevDayPx`, OI
- `spotMetaAndAssetCtxs` - Hyperliquid spot markets for true perp-vs-spot basis

For basis, the dashboard prefers Hyperliquid spot when the watched asset has a
USDC spot book. If there is no spot market, it falls back to `oraclePx`.

## Layout

The terminal has three panels:

- Main screener table - one row per watchlist symbol
- Alerts - recent threshold/composite alerts
- Flow Clusters (1h) - volume-by-price buckets from aggressive taker flow

If you later wire in a separate liquidation source and set
`LIQUIDATION_FEED_ENABLED = True`, the bottom-right panel can still show
liquidation clusters. With the default Hyperliquid-only setup, dormant
liquidation columns are not shown in the main table.

## Main Columns

### Symbol

The configured watchlist symbol.

### Mark $

The current perp mark price.

### 24h%

The mark price change versus `prevDayPx` from Hyperliquid's asset context.

### Fund/Fd1h

Current funding rate, then the 1-hour funding-rate change in percentage
points. Funding level tells you the current crowding state; funding velocity
tells you whether stress is still building.

### Basis% s/o

Perp mark versus the best available reference:

- `s` means true Hyperliquid spot basis
- `o` means oracle fallback basis

This matters because the oracle is smoothed. Spot basis is the better
dislocation measure when Hyperliquid has a spot market for the asset.

### Prem%

Hyperliquid's own `premium` field, shown beside basis because it can diverge
from the dashboard's direct mark-reference calculation.

### OI D15m%

15-minute open-interest change. Rising OI into one-sided taker flow is the
basic leverage-build signature.

### OI/Vol

Open-interest notional divided by 24-hour dollar volume. High OI on low churn
means stale leverage is sitting in a market that may not absorb much forced
flow.

### sigma15m

Short-term realized volatility over 15 minutes. Price-grind alerts use this
so a 0.3% move on BTC is not treated the same as a 0.3% move on a higher-vol
alt.

### CVD 1/5/15

Aggressive buy notional minus aggressive sell notional over 1m, 5m, and 15m.
The stack is useful because exhaustion often appears as the short horizon
rolling over while the longer horizon is still positive.

Color convention is intentionally sniping-oriented:

- Red positive CVD - aggressive buyers are crowded
- Green negative CVD - aggressive sellers may be exhausting

### Taker5

The percentage of 5-minute taker notional that was aggressive buying.

### AvgTrd

Average 5-minute trade notional. Rising average trade size suggests the flow
mix is shifting toward larger participants.

### Book

`spread / top-10 imbalance`, with optional wall marker:

- Spread is in basis points from `l2Book`
- Positive imbalance means top-10 bid depth is heavier
- Negative imbalance means top-10 ask depth is heavier
- `B2.8x` or `A2.8x` marks a large resting bid/ask level relative to average
  top-of-book depth

### Impact

Hyperliquid `impactPxs` width minus the natural top-of-book spread. This is a
free book-thinness proxy: high values mean a standardized meaningful order
would slip more than the visible spread implies.

### Flow Clus

The largest 1-hour aggressive taker-flow price bucket. The bucket width scales
with 15-minute realized volatility instead of staying fixed at 0.1% for every
asset.

Example:

```text
0.42% ↑B $1.20M
```

This means the strongest recent taker-flow cluster is 0.42% above mark,
dominated by aggressive buys, with about $1.2M notional in the bucket.

### beta/rho BTC

BTC beta and 1-minute return correlation over the recent history window. A
SOL squeeze while BTC is quiet is different from a SOL move that is just beta.

### Drift C/T/B

Per-subscription age for context, trades, and book data. A quiet trade tape
can show old trade drift without meaning the market-core feed is broken; stale
context or book drift is more actionable.

## Alerts

Simple alerts:

- `FUNDING` - absolute funding exceeds `ALERT_FUNDING_PCT`
- `OI_1H` - 1-hour OI change exceeds `ALERT_OI_DELTA_1H_PCT`
- `THIN_BOOK` - impact excess exceeds `ALERT_IMPACT_EXCESS_BPS`
- `FLOW_CLUSTER` - aggressive taker-flow cluster exceeds a volume-scaled threshold

Composite alerts:

- `LONG_SQUEEZE` - funding/OI/taker flow are crowded long and the book is thin
- `CAPITULATION` - sell CVD, low taker%, negative basis, and thin impact book
- `GRINDING_TRAP` - price is rising in realized-vol units while CVD is flat or
  negative and OI/funding are building

Dollar thresholds scale against `dayNtlVlm`, with a floor from
`ALERT_MIN_NOTIONAL_USD`, so BTC/ETH-scale settings do not make DOGE/ICP
effectively silent.

## Tuning

Important knobs in `config.py`:

```python
ALERT_CVD_SHARP_NEG_DAY_FRACTION = 0.0005
ALERT_LIQ_VOL_5M_DAY_FRACTION = 0.001
ALERT_PRICE_GRIND_SIGMA = 1.0
ALERT_FUNDING_DELTA_1H_PCT = 0.02
ALERT_IMPACT_EXCESS_BPS = 8.0
ALERT_BOOK_IMBALANCE_PCT = 25.0

TAKER_CLUSTER_MIN_DAY_FRACTION = 0.001
TAKER_CLUSTER_BUCKET_MIN_PCT = 0.1
TAKER_CLUSTER_BUCKET_MAX_PCT = 0.6
TAKER_CLUSTER_BUCKET_VOL_MULTIPLIER = 0.25
```

Start by watching the dashboard for a session before tightening thresholds.
Mid-cap names often need lower absolute notional thresholds, but the
day-volume fractions should keep the first pass usable across the watchlist.

## Limitations

- Public Hyperliquid data still does not reveal full liquidation geography.
- Spot basis only exists for watchlist assets with a Hyperliquid USDC spot book.
- `impactPxs` is standardized by Hyperliquid; it is a thinness proxy, not your
  exact execution model.
- BTC beta/correlation needs enough `allMids` history before it is meaningful.
- Flow clusters are not stop clusters. They show where aggressive trading
  actually happened, which can still act as a retest magnet or support/resistance
  proxy.
