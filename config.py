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
