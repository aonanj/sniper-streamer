from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import config


@dataclass
class OIHistory:
    """Ring buffer of (ts_ms, oi) samples used to compute rolling OI deltas."""

    _samples: deque = field(
        default_factory=lambda: deque(maxlen=config.OI_HISTORY_MAXLEN)
    )

    def record(self, ts_ms: int, oi: float) -> None:
        self._samples.append((ts_ms, oi))

    def latest_ts(self) -> int | None:
        if not self._samples:
            return None
        return self._samples[-1][0]

    def delta_pct(self, lookback_ms: int) -> float | None:
        """Return OI % change over the given lookback window, or None if insufficient data.

        Walks newest→oldest to find the most recent sample at or before the
        cutoff. Rejects the reference if it is more than one window-length
        stale (prevents a 12h-old sample masquerading as a "15m ago" value).
        """
        if len(self._samples) < 2:
            return None
        _, current = self._samples[-1]
        cutoff = self._samples[-1][0] - lookback_ms
        past_oi = None
        for ts, oi in reversed(self._samples):
            if ts <= cutoff:
                if cutoff - ts > lookback_ms:
                    return None
                past_oi = oi
                break
        if past_oi is None or past_oi == 0.0:
            return None
        return (current - past_oi) / past_oi * 100


@dataclass
class TradeWindow:
    """Rolling window that tracks taker buy and sell notional separately.

    Storing both sides lets us compute CVD *and* taker% from a single deque,
    avoiding double bookkeeping.

    Tuple layout: (ts_ms, buy_notional, sell_notional)
    """

    window_ms: int
    _trades: deque = field(default_factory=lambda: deque(maxlen=100_000))

    def add(self, ts_ms: int, is_buyer_maker: bool, qty: float, price: float) -> None:
        notional = qty * price
        if is_buyer_maker:
            self._trades.append((ts_ms, 0.0, notional))
        else:
            self._trades.append((ts_ms, notional, 0.0))

    def _window_totals(self) -> tuple[float, float]:
        cutoff = int(time.time() * 1000) - self.window_ms
        buy = sell = 0.0
        for ts, b, s in self._trades:
            if ts >= cutoff:
                buy  += b
                sell += s
        return buy, sell

    def cvd(self) -> float:
        """Signed taker notional: positive = net buy pressure, negative = net sell."""
        buy, sell = self._window_totals()
        return buy - sell

    def taker_pct(self) -> float | None:
        """Fraction of taker volume that was aggressive buying (0–100).

        Returns None when there is no volume in the window yet.
        """
        buy, sell = self._window_totals()
        total = buy + sell
        return (buy / total * 100) if total > 0 else None


@dataclass
class SymbolState:
    # Mark price + predicted funding rate
    mark: float = 0.0
    funding: float = 0.0       # fraction (e.g. 0.001 = 0.1%); next-period rate
    next_funding_ts: int = 0

    # Reference price used for perp-reference basis. Hyperliquid supplies oraclePx
    # in asset contexts.
    spot: float = 0.0

    # Open interest
    oi: float = 0.0
    oi_history: OIHistory = field(default_factory=OIHistory)

    # Liquidation events: (ts_ms, side, qty, avg_fill_price)
    liqs: deque = field(default_factory=lambda: deque(maxlen=500))

    # Taker trade windows — buy/sell notional tracked per horizon
    trades_1m:  TradeWindow = field(default_factory=lambda: TradeWindow(60_000))
    trades_5m:  TradeWindow = field(default_factory=lambda: TradeWindow(300_000))
    trades_15m: TradeWindow = field(default_factory=lambda: TradeWindow(900_000))

    # Mark price snapshots for trend detection: (ts_ms, price)
    # maxlen=1800 covers roughly 30 minutes at a 1-second mark cadence
    mark_history: deque = field(default_factory=lambda: deque(maxlen=1800))

    # Last event timestamp for WS drift detection
    last_event_ts: int = 0

    # ------------------------------------------------------------------ #
    # Mutators

    def add_trade(
        self, ts_ms: int, is_buyer_maker: bool, qty: float, price: float
    ) -> None:
        self.trades_1m.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_5m.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_15m.add(ts_ms, is_buyer_maker, qty, price)
        if ts_ms > self.last_event_ts:
            self.last_event_ts = ts_ms

    def add_liq(self, ts_ms: int, side: str, qty: float, price: float) -> None:
        self.liqs.append((ts_ms, side, qty, price))
        if ts_ms > self.last_event_ts:
            self.last_event_ts = ts_ms

    def record_oi(
        self, ts_ms: int, oi: float, min_interval_ms: int | None = None
    ) -> None:
        self.oi = oi
        latest_ts = self.oi_history.latest_ts()
        if (
            latest_ts is None
            or min_interval_ms is None
            or ts_ms - latest_ts >= min_interval_ms
        ):
            self.oi_history.record(ts_ms, oi)

    def record_mark(self, ts_ms: int) -> None:
        if self.mark:
            self.mark_history.append((ts_ms, self.mark))
        if ts_ms > self.last_event_ts:
            self.last_event_ts = ts_ms

    # ------------------------------------------------------------------ #
    # Derived properties

    @property
    def basis_pct(self) -> float:
        if not self.spot:
            return 0.0
        return (self.mark - self.spot) / self.spot * 100

    def mark_delta_pct(self, lookback_ms: int) -> float | None:
        """Price % change over the given lookback window."""
        if len(self.mark_history) < 2:
            return None
        _, current = self.mark_history[-1]
        cutoff = self.mark_history[-1][0] - lookback_ms
        past_price = None
        for ts, p in reversed(self.mark_history):
            if ts <= cutoff:
                if cutoff - ts > lookback_ms:
                    return None
                past_price = p
                break
        if not past_price:
            return None
        return (current - past_price) / past_price * 100

    def recent_liqs(self, window_ms: int = 300_000) -> list[tuple]:
        cutoff = int(time.time() * 1000) - window_ms
        return [(ts, s, q, p) for ts, s, q, p in self.liqs if ts >= cutoff]

    def liq_clusters(
        self,
        window_ms: int = 300_000,
        bucket_pct: float | None = None,
        min_count: int | None = None,
    ) -> list[dict]:
        """Identify price levels where liquidations cluster — the stop-cluster signal.

        Returns up to 5 buckets sorted by notional, descending.
        """
        bucket_pct = bucket_pct or config.LIQ_CLUSTER_BUCKET_PCT
        min_count  = min_count  or config.LIQ_CLUSTER_MIN_COUNT

        recent = self.recent_liqs(window_ms)
        if not recent or not self.mark:
            return []

        bucket_size = self.mark * bucket_pct / 100
        buckets: dict[int, dict] = {}
        for _, side, qty, price in recent:
            key = round(price / bucket_size)
            if key not in buckets:
                buckets[key] = {
                    "price":    round(key * bucket_size, 4),
                    "count":    0,
                    "notional": 0.0,
                    "longs":    0,   # side == "SELL" → long liquidation
                    "shorts":   0,   # side == "BUY"  → short liquidation
                }
            b = buckets[key]
            b["count"]    += 1
            b["notional"] += qty * price
            if side == "SELL":
                b["longs"]  += 1
            else:
                b["shorts"] += 1

        return sorted(
            [v for v in buckets.values() if v["count"] >= min_count],
            key=lambda x: x["notional"],
            reverse=True,
        )[:5]
