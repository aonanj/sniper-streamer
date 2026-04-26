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
USDC spot book. If there is no spot market, or if spot basis diverges from
Hyperliquid's premium by more than
`BASIS_SPOT_PREMIUM_MAX_DIVERGENCE_PCT`, it falls back to `oraclePx`.

## Layout

The terminal has three panels:

- Main screener table - one row per watchlist symbol
- Alerts - recent threshold/composite alerts
- Flow Clusters (1h) - volume-by-price buckets from aggressive taker flow

If you later wire in a separate liquidation source and set
`LIQUIDATION_FEED_ENABLED = True`, the bottom-right panel can still show
liquidation clusters. With the default Hyperliquid-only setup, dormant
liquidation columns are not shown in the main table.

## Alerts

Simple alerts:

- `FUNDING` - absolute funding exceeds `ALERT_FUNDING_PCT`
- `OI_1H` - 1-hour OI change exceeds `ALERT_OI_DELTA_1H_PCT`
- `THIN_BOOK` - impact excess exceeds `ALERT_IMPACT_EXCESS_BPS` (or the
  per-symbol override in `ALERT_IMPACT_EXCESS_BPS_OVERRIDES`)
- `FLOW_CLUSTER` - aggressive taker-flow cluster exceeds a stricter
  alert-only volume-scaled threshold and is at least 70% one-sided

Composite alerts:

- `LONG_SQUEEZE` - positive funding at or above `ALERT_FUNDING_SQUEEZE_PCT`,
  OI rising, crowded buying tape, and a thin or ask-heavy book
- `SHORT_SQUEEZE` - negative funding at or below `-ALERT_FUNDING_SQUEEZE_PCT`,
  OI rising, sell-dominated tape, and the perp trading below spot; fires when
  shorts are crowded and the setup is fragile for a violent short-covering rally
- `CAPITULATION` - sell CVD, low taker%, negative basis, and thin impact book
- `GRINDING_TRAP` - price is rising in realized-vol units while CVD is flat or
  negative and OI/funding are building

Display-level dollar thresholds scale against `dayNtlVlm`, with a floor from
`ALERT_MIN_NOTIONAL_USD`, so BTC/ETH-scale settings do not make DOGE/ICP
effectively silent. Flow-cluster alerts use a separate, stricter alert floor,
daily-volume fraction, trade count, dominance check, and 30-minute side-level
dedupe so the Alerts panel does not repeat every visible cluster.

`THIN_BOOK` uses a per-symbol threshold when an entry exists in
`ALERT_IMPACT_EXCESS_BPS_OVERRIDES`; this keeps structurally high-impact
markets like ICP from firing constantly while allowing tighter markets like BTC
to alert on genuinely unusual thinness.

## Tuning

Important knobs in `config.py`:

```python

WATCHLIST = ["btc-usdc", "eth-usdc", "icp-usdc", "sol-usdc", "doge-usdc", "bnb-usdc"]

# ── Simple threshold alerts ──────────────────────────────────────────────────
ALERT_FUNDING_PCT     = 0.005       # |funding| > this (%) fires an alert; session range 0.001–0.007%/hr
ALERT_LIQ_VOL_5M_USD  = 2_000_000  # 5-minute liq notional > this ($)
ALERT_OI_DELTA_1H_PCT = 0.75       # 1h OI % change > this fires an alert; latest run p95 was ~0.4–0.7%
ALERT_MIN_NOTIONAL_USD = 10_000     # floor for volume-scaled dollar thresholds

# ── Composite setup alerts ───────────────────────────────────────────────────
# Loaded long squeeze: funding hot, OI rising, buyers crowding, longs stacked below
ALERT_TAKER_HIGH_PCT        = 60.0     # taker% above this = crowded buying tape
ALERT_TAKER_LOW_PCT         = 30.0     # taker% below this = crowded selling / capitulation
ALERT_FUNDING_SQUEEZE_PCT   = 0.001    # funding (%) threshold for squeeze composites; BNB/DOGE cap at 0.00125%
# Capitulation reversal: forced selling hammering the perp book
ALERT_CVD_SHARP_NEG_USD     = -500_000 # CVD must be below this ($) for capitulation
ALERT_CVD_SHARP_NEG_DAY_FRACTION = 0.0005  # CVD threshold scales to 24h volume
ALERT_BASIS_CAPITULATION    = -0.20    # basis (%) must be below this; session min was SOL -0.289%, ETH -0.239%
ALERT_LIQ_CAPITULATION_USD  = 500_000  # minimum 5m liq vol for capitulation context ($)
ALERT_LIQ_VOL_5M_DAY_FRACTION = 0.001  # liquidation/proxy threshold scales to 24h volume
# Grinding trap: price rising on positioning, not real demand
ALERT_PRICE_GRIND_PCT       = 0.3      # price must rise this much in 15m (%)
ALERT_PRICE_GRIND_SIGMA     = 1.5      # portable price-move threshold; 1.0 caused BNB/ICP noise
ALERT_FUNDING_DELTA_1H_PCT  = 0.001    # 1h funding change, in percentage points; latest p95 was <=0.0027pp
ALERT_IMPACT_EXCESS_BPS     = 4.0      # impact width minus natural spread (global default)
ALERT_IMPACT_EXCESS_BPS_OVERRIDES = {  # per-symbol overrides from the 2026-04-25 retained run
    "bnb-usdc": 3.0,
    "btc-usdc": 2.0,
    "doge-usdc": 8.0,
    "icp-usdc": 13.0,
}
ALERT_BOOK_IMBALANCE_PCT    = 50.0     # top-10 book side imbalance threshold; 25% was common noise

# REST polling cadence (seconds). Hyperliquid info requests are public snapshots.
OI_POLL_INTERVAL = 60

# OI history ring buffer depth (samples). At 60s per sample: 720 = 12 hours.
OI_HISTORY_MAXLEN = 720

# Rolling market histories. allMids is frequent, so samples are throttled.
PRICE_HISTORY_MAXLEN = 7200
PRICE_HISTORY_MIN_INTERVAL_MS = 5_000
FUNDING_HISTORY_MAXLEN = 720
FUNDING_HISTORY_MIN_INTERVAL_MS = 60_000

# Liquidation cluster detection
LIQ_CLUSTER_BUCKET_PCT = 0.1  # price bucket width as % of mark
LIQ_CLUSTER_MIN_COUNT  = 3    # minimum events in a bucket to flag as cluster
LIQUIDATION_FEED_ENABLED = False  # Hyperliquid has no official public all-market liq stream
BASIS_SPOT_PREMIUM_MAX_DIVERGENCE_PCT = 0.5  # fallback to oracle if spot basis disagrees with HL premium

# Taker-flow cluster proxy used while public liquidation data is unavailable.
TAKER_CLUSTER_MIN_USD = 500_000
TAKER_CLUSTER_MIN_DAY_FRACTION = 0.0015  # raised from 0.001; SOL floor lifts from $184k→$276k
TAKER_CLUSTER_MIN_COUNT = 3
TAKER_CLUSTER_ALERT_FLOOR_USD = 25_000
TAKER_CLUSTER_ALERT_MIN_USD = 5_000_000
TAKER_CLUSTER_ALERT_MIN_DAY_FRACTION = 0.01
TAKER_CLUSTER_ALERT_MIN_COUNT = 10
TAKER_CLUSTER_ALERT_DOMINANCE_PCT = 70.0
TAKER_CLUSTER_ALERT_DEDUP_WINDOW_SEC = 1_800.0
TAKER_CLUSTER_BUCKET_MIN_PCT = 0.1
TAKER_CLUSTER_BUCKET_MAX_PCT = 0.6
TAKER_CLUSTER_BUCKET_VOL_MULTIPLIER = 0.25

# WebSocket endpoints
WS_URL   = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_DEX = ""  # empty string = default perp dex

# Dashboard
DASHBOARD_REFRESH_HZ = 2

# SQLite persistence. The writer runs as its own coroutine and keeps WAL enabled
# so notebooks and other readers can query while the app appends.
SQLITE_PATH = "data/sniper_streamer.sqlite3"
PERSIST_RETENTION_DAYS = 14
PERSIST_BATCH_SIZE = 500
PERSIST_FLUSH_INTERVAL_SEC = 0.5
PERSIST_PURGE_INTERVAL_SEC = 3_600
PERSIST_SNAPSHOT_SCAN_INTERVAL_SEC = 1.0
PERSIST_SNAPSHOT_MIN_INTERVAL_MS = 5_000
PERSIST_SNAPSHOT_FUNDING_DELTA_PCT = 0.0001
```

Start by watching the dashboard for a session before tightening thresholds.
Mid-cap names often need lower absolute notional thresholds, but the
day-volume fractions should keep the first pass usable across the watchlist.

The funding-related thresholds (`ALERT_FUNDING_PCT`, `ALERT_FUNDING_SQUEEZE_PCT`)
are compared to `st.funding * 100` in the alert engine, where `st.funding` is the
raw per-hour rate fraction from the Hyperliquid API (e.g. `0.0000125` → `0.00125%/hr`).
Keep this in mind when adjusting: `0.005` means "fire when funding exceeds
0.005%/hr, or about 0.12%/day equivalent", not 0.5% per period.

## Limitations

- Public Hyperliquid data still does not reveal full liquidation geography.
- Spot basis only exists for watchlist assets with a Hyperliquid USDC spot book.
- `impactPxs` is standardized by Hyperliquid; it is a thinness proxy, not your
  exact execution model.
- BTC beta/correlation needs enough `allMids` history before it is meaningful.
- Flow clusters are not stop clusters. They show where aggressive trading
  actually happened, which can still act as a retest magnet or support/resistance
  proxy.
