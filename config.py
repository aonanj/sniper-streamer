from __future__ import annotations

import os


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


WATCHLIST = ["btc-usdc", "eth-usdc", "xrp-usdc", "sol-usdc", "doge-usdc", "hype-usdc"]

# ── Simple threshold alerts ──────────────────────────────────────────────────
ALERT_FUNDING_PCT     = 0.003     # |funding| >= this (%) fires; baseline is 0.00125%
ALERT_FUNDING_DEDUP_WINDOW_SEC = 3_600.0  # funding moves slowly; avoid 5-minute repeats
ALERT_LIQ_VOL_5M_USD  = 2_000_000  # 5-minute liq notional > this ($)
ALERT_OI_DELTA_1H_PCT = 0.77       # 1h OI % change > this fires; BTC-scale percentage gate
ALERT_OI_DELTA_1H_DAY_FRACTION = 0.015  # also fire when 1h OI notional delta exceeds 1.5% of 24h volume
ALERT_MIN_NOTIONAL_USD = 10_000     # floor for volume-scaled dollar thresholds

# ── Composite setup alerts ───────────────────────────────────────────────────
# Loaded long squeeze: funding hot, OI rising, buyers crowding, longs stacked below
ALERT_TAKER_HIGH_PCT        = 60.0     # taker% above this = crowded buying tape
ALERT_TAKER_LOW_PCT         = 30.0     # taker% below this = crowded selling / capitulation
ALERT_FUNDING_SQUEEZE_PCT   = 0.005    # funding (%) threshold for squeeze composites
# Capitulation reversal: forced selling hammering the perp book
ALERT_CVD_SHARP_NEG_USD     = -500_000 # CVD must be below this ($) for capitulation
ALERT_CVD_SHARP_NEG_DAY_FRACTION = 0.0005  # CVD threshold scales to 24h volume
# Ultra-short CVD thresholds for cascade-onset detection (15s window).
# Scaled proportionally to 5m: 15s is 1/20th the window so threshold is 1/20th.
# Divergence between 15s deeply negative and 5m still green is the cascade entry signal.
ALERT_CVD_15S_SHARP_NEG_USD          = -25_000
ALERT_CVD_15S_SHARP_NEG_DAY_FRACTION = 0.000025
ALERT_BASIS_CAPITULATION    = -0.10    # basis (%) must be below this; latest run tail was BTC/ETH/SOL near -0.10%
ALERT_LIQ_CAPITULATION_USD  = 500_000  # minimum 5m liq vol for capitulation context ($)
ALERT_LIQ_VOL_5M_DAY_FRACTION = 0.001  # liquidation/proxy threshold scales to 24h volume
# Grinding trap: price rising on positioning, not real demand
ALERT_PRICE_GRIND_PCT       = 0.3      # price must rise this much in 15m (%)
ALERT_PRICE_GRIND_SIGMA     = 1.5      # portable price-move threshold; 1.0 was noisy in retained runs
ALERT_FUNDING_DELTA_1H_PCT  = 0.001    # 1h funding change, in percentage points; latest p95 was <=0.0027pp
ALERT_IMPACT_EXCESS_BPS     = 4.0      # impact width minus natural spread (global default)
ALERT_IMPACT_EXCESS_BPS_OVERRIDES = {  # per-symbol overrides from retained Hyperliquid exports
    "btc-usdc": 2.0,
    "doge-usdc": 2.5,
    "xrp-usdc": 2.0,
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
LIQUIDATION_FEED_ENABLED = True  # consume Bybit allLiquidation for unthrottled liq events
LIQUIDATION_FEED_SOURCE = "bybit_all_liquidation"
BASIS_SPOT_PREMIUM_MAX_DIVERGENCE_PCT = 0.5  # fallback to oracle if spot basis disagrees with HL premium

# Bybit's allLiquidation feed is per exchange symbol. The local watchlist stays
# Hyperliquid-oriented (e.g. "btc-usdc"), so these map watched coins to Bybit.
BYBIT_LIQUIDATION_WS_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_LIQUIDATION_QUOTE = "USDT"
BYBIT_LIQUIDATION_SYMBOL_OVERRIDES = {}
BYBIT_LIQUIDATION_PING_INTERVAL_SEC = 20.0

# Taker-flow cluster fallback used when the liquidation feed is disabled.
TAKER_CLUSTER_MIN_USD = 500_000
TAKER_CLUSTER_MIN_DAY_FRACTION = 0.0015  # visible flow clusters scale to 24h volume
TAKER_CLUSTER_MIN_COUNT = 3
TAKER_CLUSTER_ALERT_FLOOR_USD = 25_000
TAKER_CLUSTER_ALERT_MIN_USD = 5_000_000
TAKER_CLUSTER_ALERT_MIN_DAY_FRACTION = 0.01
TAKER_CLUSTER_ALERT_MIN_COUNT = 10
TAKER_CLUSTER_ALERT_DOMINANCE_PCT = 70.0
TAKER_CLUSTER_ALERT_DEDUP_WINDOW_SEC = 1_800.0
TAKER_CLUSTER_WINDOW_MS = 0  # 0 = whole in-memory session
TAKER_CLUSTER_SESSION_MAX_TRADES = 120_000
TAKER_CLUSTER_BUCKET_MIN_PCT = 0.1
TAKER_CLUSTER_BUCKET_MAX_PCT = 0.6
TAKER_CLUSTER_BUCKET_VOL_MULTIPLIER = 0.25

# WebSocket endpoints
WS_URL   = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_DEX = ""  # empty string = default perp dex

# Dashboard
DASHBOARD_REFRESH_HZ = 2

# API service. When API_TOKEN is empty, local development endpoints are open.
API_HOST = _env_str("API_HOST", "0.0.0.0")
API_PORT = _env_int("PORT", _env_int("API_PORT", 8000))
API_TOKEN = _env_str("API_TOKEN", "")
API_POLL_INTERVAL_SEC = _env_float("API_POLL_INTERVAL_SEC", 1.0)

# Runtime database. SQLite remains the default only when DATABASE_URL is absent.
DATABASE_URL = _env_str("DATABASE_URL", "")
DATABASE_BACKEND = _env_str(
    "SNIPER_DATABASE_BACKEND",
    "postgres" if DATABASE_URL else "sqlite",
).lower()

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

# Structured signal snapshots are current-state read models for the API.
SIGNAL_SCAN_INTERVAL_SEC = _env_float("SIGNAL_SCAN_INTERVAL_SEC", 1.0)
SIGNAL_MIN_INTERVAL_MS = _env_int("SIGNAL_MIN_INTERVAL_MS", 5_000)
SIGNAL_TTL_MS = _env_int("SIGNAL_TTL_MS", 15_000)
SIGNAL_RETENTION_DAYS = _env_int("SIGNAL_RETENTION_DAYS", 30)

# Production singleton worker guard and storage reporting.
POSTGRES_WORKER_LOCK_ID = _env_int("POSTGRES_WORKER_LOCK_ID", 741_447_301)
WORKER_LOCK_RETRY_SEC = _env_float("WORKER_LOCK_RETRY_SEC", 10.0)
STORAGE_REPORT_INTERVAL_SEC = _env_float("STORAGE_REPORT_INTERVAL_SEC", 86_400.0)
STORAGE_WARNING_BYTES = _env_int("STORAGE_WARNING_BYTES", 10 * 1024 * 1024 * 1024)
