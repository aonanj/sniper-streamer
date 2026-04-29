from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

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

    def _reference_value(self, lookback_ms: int) -> tuple[float, float] | None:
        """Return current and lookback OI values, or None if history is insufficient.

        Walks newest->oldest to find the most recent sample at or before the
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
        if past_oi is None:
            return None
        return current, past_oi

    def delta_pct(self, lookback_ms: int) -> float | None:
        """Return OI % change over the given lookback window."""
        values = self._reference_value(lookback_ms)
        if values is None:
            return None
        current, past_oi = values
        if past_oi == 0.0:
            return None
        return (current - past_oi) / past_oi * 100

    def delta_abs(self, lookback_ms: int) -> float | None:
        """Return absolute OI-unit change over the given lookback window."""
        values = self._reference_value(lookback_ms)
        if values is None:
            return None
        current, past_oi = values
        return current - past_oi


@dataclass
class NumericHistory:
    """Timestamped numeric samples for funding, prices, and return stats."""

    maxlen: int
    _samples: deque = field(init=False)

    def __post_init__(self) -> None:
        self._samples = deque(maxlen=self.maxlen)

    def record(
        self, ts_ms: int, value: float, min_interval_ms: int | None = None
    ) -> None:
        if not math.isfinite(value):
            return
        if self._samples and min_interval_ms is not None:
            latest_ts = self._samples[-1][0]
            if ts_ms - latest_ts < min_interval_ms:
                self._samples[-1] = (latest_ts, value)
                return
        self._samples.append((ts_ms, value))

    def latest_ts(self) -> int | None:
        if not self._samples:
            return None
        return self._samples[-1][0]

    def _reference_value(self, lookback_ms: int) -> tuple[float, float] | None:
        if len(self._samples) < 2:
            return None
        current_ts, current = self._samples[-1]
        cutoff = current_ts - lookback_ms
        past_value = None
        for ts, value in reversed(self._samples):
            if ts <= cutoff:
                if cutoff - ts > lookback_ms:
                    return None
                past_value = value
                break
        if past_value is None:
            return None
        return current, past_value

    def delta_pct(self, lookback_ms: int) -> float | None:
        values = self._reference_value(lookback_ms)
        if values is None:
            return None
        current, past = values
        if not past:
            return None
        return (current - past) / past * 100

    def delta_abs(self, lookback_ms: int) -> float | None:
        values = self._reference_value(lookback_ms)
        if values is None:
            return None
        current, past = values
        return current - past

    def window_samples(self, window_ms: int) -> list[tuple[int, float]]:
        cutoff = int(time.time() * 1000) - window_ms
        return [(ts, value) for ts, value in self._samples if ts >= cutoff]

    def realized_vol_pct(self, window_ms: int) -> float | None:
        """Realized volatility over the window, expressed as a percent move."""
        samples = [(ts, value) for ts, value in self.window_samples(window_ms) if value > 0]
        if len(samples) < 3:
            return None
        log_returns = []
        prev = samples[0][1]
        for _, value in samples[1:]:
            if prev > 0 and value > 0:
                log_returns.append(math.log(value / prev))
            prev = value
        if len(log_returns) < 2:
            return None
        return math.sqrt(sum(r * r for r in log_returns)) * 100

    def bucketed_returns(
        self, window_ms: int, interval_ms: int = 60_000
    ) -> dict[int, float]:
        samples = [(ts, value) for ts, value in self.window_samples(window_ms) if value > 0]
        if len(samples) < 3:
            return {}

        last_by_bucket: dict[int, float] = {}
        for ts, value in samples:
            last_by_bucket[ts // interval_ms] = value

        returns: dict[int, float] = {}
        prev_value = None
        for bucket in sorted(last_by_bucket):
            value = last_by_bucket[bucket]
            if prev_value:
                returns[bucket] = (value - prev_value) / prev_value
            prev_value = value
        return returns


@dataclass
class TradeWindow:
    """Rolling window that tracks taker buy and sell notional separately.

    Tuple layout: (ts_ms, buy_notional, sell_notional, price, qty)
    """

    window_ms: int | None
    max_trades: int = 120_000
    _trades: deque = field(init=False)

    def __post_init__(self) -> None:
        self._trades = deque(maxlen=self.max_trades)

    def add(self, ts_ms: int, is_buyer_maker: bool, qty: float, price: float) -> None:
        notional = qty * price
        if notional <= 0 or price <= 0:
            return
        if is_buyer_maker:
            self._trades.append((ts_ms, 0.0, notional, price, qty))
        else:
            self._trades.append((ts_ms, notional, 0.0, price, qty))

    def _recent(self) -> Iterable[tuple[int, float, float, float, float]]:
        if self.window_ms is None:
            return iter(self._trades)
        cutoff = int(time.time() * 1000) - self.window_ms
        return (trade for trade in self._trades if trade[0] >= cutoff)

    def _window_totals(self) -> tuple[float, float]:
        buy = sell = 0.0
        for _, b, s, _, _ in self._recent():
            buy += b
            sell += s
        return buy, sell

    def cvd(self) -> float:
        """Signed taker notional: positive = net buy pressure, negative = net sell."""
        buy, sell = self._window_totals()
        return buy - sell

    def taker_pct(self) -> float | None:
        """Fraction of taker volume that was aggressive buying (0-100)."""
        buy, sell = self._window_totals()
        total = buy + sell
        return (buy / total * 100) if total > 0 else None

    def total_notional(self) -> float:
        buy, sell = self._window_totals()
        return buy + sell

    def vwap(self) -> float | None:
        qty_total = weighted_price = 0.0
        for _, _, _, price, qty in self._recent():
            if price <= 0 or qty <= 0:
                continue
            qty_total += qty
            weighted_price += price * qty
        return weighted_price / qty_total if qty_total > 0 else None

    def average_trade_notional(self) -> float | None:
        trades = list(self._recent())
        if not trades:
            return None
        return sum(b + s for _, b, s, _, _ in trades) / len(trades)

    def clusters(
        self,
        reference_price: float,
        bucket_pct: float,
        reference_source: str = "vwap",
        min_notional: float = 0.0,
        min_count: int = 2,
    ) -> list[dict]:
        """Aggregate aggressive taker flow into price buckets."""
        if not reference_price or bucket_pct <= 0:
            return []

        bucket_size = reference_price * bucket_pct / 100
        if bucket_size <= 0:
            return []

        buckets: dict[int, dict] = {}
        for _, buy, sell, price, _ in self._recent():
            key = round((price - reference_price) / bucket_size)
            if key not in buckets:
                buckets[key] = {
                    "price": round(reference_price + key * bucket_size, 6),
                    "ref_price": round(reference_price, 6),
                    "ref_source": reference_source,
                    "count": 0,
                    "buy": 0.0,
                    "sell": 0.0,
                    "notional": 0.0,
                }
            b = buckets[key]
            b["count"] += 1
            b["buy"] += buy
            b["sell"] += sell
            b["notional"] += buy + sell

        clusters = [
            bucket
            for bucket in buckets.values()
            if bucket["count"] >= min_count and bucket["notional"] >= min_notional
        ]
        return sorted(clusters, key=lambda x: x["notional"], reverse=True)


@dataclass
class SymbolState:
    # Market prices and funding
    mark: float = 0.0
    mid: float = 0.0
    funding: float = 0.0       # fraction (e.g. 0.001 = 0.1%); next-period rate
    next_funding_ts: int = 0

    # Reference prices. Basis prefers Hyperliquid spot when available and falls
    # back to the oracle otherwise.
    oracle: float = 0.0
    hl_spot: float = 0.0
    spot_symbol: str = ""

    # Extra fields already present in metaAndAssetCtxs
    day_ntl_vlm: float = 0.0
    premium: float = 0.0
    prev_day_px: float = 0.0
    impact_bid_px: float = 0.0
    impact_ask_px: float = 0.0

    # Open interest
    oi: float = 0.0
    oi_history: OIHistory = field(default_factory=OIHistory)

    # Book state from l2Book
    best_bid: float = 0.0
    best_ask: float = 0.0
    bid_depth10: float = 0.0
    ask_depth10: float = 0.0
    book_imbalance_pct: float | None = None
    wall_side: str = ""
    wall_px: float = 0.0
    wall_notional: float = 0.0
    wall_ratio: float = 0.0
    wall_dist_bps: float = 0.0

    # Liquidation events: (ts_ms, side, qty, avg_fill_price)
    liqs: deque = field(default_factory=lambda: deque(maxlen=500))

    # Taker trade windows - buy/sell notional tracked per horizon
    trades_15s: TradeWindow = field(default_factory=lambda: TradeWindow(15_000))
    trades_30s: TradeWindow = field(default_factory=lambda: TradeWindow(30_000))
    trades_1m: TradeWindow = field(default_factory=lambda: TradeWindow(60_000))
    trades_5m: TradeWindow = field(default_factory=lambda: TradeWindow(300_000))
    trades_15m: TradeWindow = field(default_factory=lambda: TradeWindow(900_000))
    trades_1h: TradeWindow = field(default_factory=lambda: TradeWindow(3_600_000))
    trades_session: TradeWindow = field(
        default_factory=lambda: TradeWindow(
            None,
            config.TAKER_CLUSTER_SESSION_MAX_TRADES,
        )
    )

    # First usable live price seen after process start; used as a stable fallback
    # if a VWAP reference cannot be computed yet.
    session_open_price: float = 0.0
    session_open_ts: int = 0

    # Rolling histories for portable thresholds and cross-asset stats
    price_history: NumericHistory = field(
        default_factory=lambda: NumericHistory(config.PRICE_HISTORY_MAXLEN)
    )
    funding_history: NumericHistory = field(
        default_factory=lambda: NumericHistory(config.FUNDING_HISTORY_MAXLEN)
    )

    # Per-subscription drift timestamps
    last_context_ts: int = 0
    last_trade_ts: int = 0
    last_book_ts: int = 0
    last_all_mids_ts: int = 0
    last_event_ts: int = 0

    # ------------------------------------------------------------------ #
    # Mutators

    def add_trade(
        self, ts_ms: int, is_buyer_maker: bool, qty: float, price: float
    ) -> None:
        self._record_session_open(ts_ms, price)
        self.trades_15s.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_30s.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_1m.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_5m.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_15m.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_1h.add(ts_ms, is_buyer_maker, qty, price)
        self.trades_session.add(ts_ms, is_buyer_maker, qty, price)
        self._touch_trade(ts_ms)

    def add_liq(self, ts_ms: int, side: str, qty: float, price: float) -> None:
        self.liqs.append((ts_ms, side, qty, price))
        self._touch_trade(ts_ms)

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

    def record_funding(self, ts_ms: int, funding: float) -> None:
        self.funding = funding
        self.funding_history.record(
            ts_ms, funding, config.FUNDING_HISTORY_MIN_INTERVAL_MS
        )

    def record_mark(self, ts_ms: int) -> None:
        if self.mark:
            self._record_session_open(ts_ms, self.mark)
            self.price_history.record(
                ts_ms, self.mark, config.PRICE_HISTORY_MIN_INTERVAL_MS
            )
        self._touch_context(ts_ms)

    def record_mid(self, ts_ms: int, mid: float) -> None:
        if mid <= 0:
            return
        self._record_session_open(ts_ms, mid)
        self.mid = mid
        self.price_history.record(
            ts_ms, mid, config.PRICE_HISTORY_MIN_INTERVAL_MS
        )
        self._touch_all_mids(ts_ms)

    def record_hl_spot(self, spot_symbol: str, price: float) -> None:
        if price <= 0:
            return
        self.spot_symbol = spot_symbol
        self.hl_spot = price

    def record_book(
        self, ts_ms: int, bids: list[dict], asks: list[dict]
    ) -> None:
        bid_levels = _level_stats(bids[:10])
        ask_levels = _level_stats(asks[:10])
        if not bid_levels or not ask_levels:
            return

        self.best_bid = bid_levels[0]["px"]
        self.best_ask = ask_levels[0]["px"]
        self.bid_depth10 = sum(level["notional"] for level in bid_levels)
        self.ask_depth10 = sum(level["notional"] for level in ask_levels)

        total_depth = self.bid_depth10 + self.ask_depth10
        self.book_imbalance_pct = (
            (self.bid_depth10 - self.ask_depth10) / total_depth * 100
            if total_depth > 0 else None
        )

        all_levels = [
            ("B", level) for level in bid_levels
        ] + [
            ("A", level) for level in ask_levels
        ]
        avg_depth = total_depth / len(all_levels) if all_levels else 0.0
        wall_side, wall = max(all_levels, key=lambda item: item[1]["notional"])
        self.wall_side = wall_side
        self.wall_px = wall["px"]
        self.wall_notional = wall["notional"]
        self.wall_ratio = wall["notional"] / avg_depth if avg_depth else 0.0

        mid = self.book_mid or self.mid or self.mark
        self.wall_dist_bps = (
            (wall["px"] - mid) / mid * 10_000 if mid else 0.0
        )
        self._touch_book(ts_ms)

    def _touch_context(self, ts_ms: int) -> None:
        self.last_context_ts = max(self.last_context_ts, ts_ms)
        self.last_event_ts = max(self.last_event_ts, ts_ms)

    def _touch_trade(self, ts_ms: int) -> None:
        self.last_trade_ts = max(self.last_trade_ts, ts_ms)
        self.last_event_ts = max(self.last_event_ts, ts_ms)

    def _touch_book(self, ts_ms: int) -> None:
        self.last_book_ts = max(self.last_book_ts, ts_ms)
        self.last_event_ts = max(self.last_event_ts, ts_ms)

    def _touch_all_mids(self, ts_ms: int) -> None:
        self.last_all_mids_ts = max(self.last_all_mids_ts, ts_ms)
        self.last_event_ts = max(self.last_event_ts, ts_ms)

    def _record_session_open(self, ts_ms: int, price: float) -> None:
        if self.session_open_price or price <= 0 or not math.isfinite(price):
            return
        self.session_open_price = price
        self.session_open_ts = ts_ms

    # ------------------------------------------------------------------ #
    # Derived properties

    @property
    def basis_reference(self) -> float:
        return self.hl_spot if self._spot_basis_is_reliable() else self.oracle

    @property
    def basis_source(self) -> str:
        return "spot" if self._spot_basis_is_reliable() else "oracle"

    @property
    def basis_pct(self) -> float:
        ref = self.basis_reference
        if not ref:
            return 0.0
        return (self.mark - ref) / ref * 100

    @property
    def spot_basis_pct(self) -> float | None:
        if not self.hl_spot:
            return None
        return (self.mark - self.hl_spot) / self.hl_spot * 100

    def _spot_basis_is_reliable(self) -> bool:
        spot_basis = self.spot_basis_pct
        if spot_basis is None:
            return False
        return (
            abs(spot_basis - self.premium_pct)
            <= config.BASIS_SPOT_PREMIUM_MAX_DIVERGENCE_PCT
        )

    @property
    def oracle_basis_pct(self) -> float:
        if not self.oracle:
            return 0.0
        return (self.mark - self.oracle) / self.oracle * 100

    @property
    def premium_pct(self) -> float:
        return self.premium * 100

    @property
    def prev_day_change_pct(self) -> float | None:
        if not self.prev_day_px:
            return None
        price = self.mark or self.mid
        if not price:
            return None
        return (price - self.prev_day_px) / self.prev_day_px * 100

    @property
    def book_mid(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0.0

    @property
    def book_spread_bps(self) -> float | None:
        mid = self.book_mid
        if not mid:
            return None
        return (self.best_ask - self.best_bid) / mid * 10_000

    @property
    def impact_width_bps(self) -> float | None:
        if not self.impact_bid_px or not self.impact_ask_px:
            return None
        ref = self.mid or self.mark or self.book_mid
        if not ref:
            return None
        return (self.impact_ask_px - self.impact_bid_px) / ref * 10_000

    @property
    def impact_excess_bps(self) -> float | None:
        width = self.impact_width_bps
        if width is None:
            return None
        spread = self.book_spread_bps
        if spread is None:
            return None
        return max(0.0, width - spread)

    @property
    def oi_notional(self) -> float:
        return self.oi * (self.mark or self.mid)

    @property
    def oi_volume_ratio(self) -> float | None:
        if not self.day_ntl_vlm:
            return None
        return self.oi_notional / self.day_ntl_vlm

    def mark_delta_pct(self, lookback_ms: int) -> float | None:
        return self.price_history.delta_pct(lookback_ms)

    def funding_delta_pct(self, lookback_ms: int = 3_600_000) -> float | None:
        delta = self.funding_history.delta_abs(lookback_ms)
        return delta * 100 if delta is not None else None

    def realized_vol_pct(self, window_ms: int) -> float | None:
        return self.price_history.realized_vol_pct(window_ms)

    def mark_move_sigma(self, lookback_ms: int) -> float | None:
        move = self.mark_delta_pct(lookback_ms)
        vol = self.realized_vol_pct(lookback_ms)
        if move is None or not vol:
            return None
        return move / vol

    def beta_correlation(
        self,
        other: "SymbolState",
        window_ms: int = 3_600_000,
        interval_ms: int = 60_000,
    ) -> tuple[float, float] | None:
        own = self.price_history.bucketed_returns(window_ms, interval_ms)
        ref = other.price_history.bucketed_returns(window_ms, interval_ms)
        keys = sorted(set(own) & set(ref))
        if len(keys) < 4:
            return None

        own_vals = [own[k] for k in keys]
        ref_vals = [ref[k] for k in keys]
        own_mean = sum(own_vals) / len(own_vals)
        ref_mean = sum(ref_vals) / len(ref_vals)
        own_dev = [x - own_mean for x in own_vals]
        ref_dev = [x - ref_mean for x in ref_vals]
        cov = sum(a * b for a, b in zip(own_dev, ref_dev, strict=False))
        ref_var = sum(x * x for x in ref_dev)
        own_var = sum(x * x for x in own_dev)
        if not ref_var or not own_var:
            return None
        beta = cov / ref_var
        corr = cov / math.sqrt(own_var * ref_var)
        return beta, corr

    def volume_scaled_threshold(self, default_usd: float, day_fraction: float) -> float:
        if self.day_ntl_vlm <= 0 or day_fraction <= 0:
            return default_usd
        scaled = self.day_ntl_vlm * day_fraction
        return max(config.ALERT_MIN_NOTIONAL_USD, min(default_usd, scaled))

    def flow_cluster_bucket_pct(self) -> float:
        vol15 = self.realized_vol_pct(900_000)
        if vol15 is None:
            return config.TAKER_CLUSTER_BUCKET_MIN_PCT
        return min(
            config.TAKER_CLUSTER_BUCKET_MAX_PCT,
            max(
                config.TAKER_CLUSTER_BUCKET_MIN_PCT,
                vol15 * config.TAKER_CLUSTER_BUCKET_VOL_MULTIPLIER,
            ),
        )

    def taker_flow_clusters(
        self,
        window_ms: int | None = None,
        min_notional: float | None = None,
        min_count: int | None = None,
    ) -> list[dict]:
        bucket_pct = self.flow_cluster_bucket_pct()
        if window_ms is None:
            window_ms = config.TAKER_CLUSTER_WINDOW_MS
        if min_notional is None:
            min_notional = self.volume_scaled_threshold(
                config.TAKER_CLUSTER_MIN_USD,
                config.TAKER_CLUSTER_MIN_DAY_FRACTION,
            )
        if min_count is None:
            min_count = config.TAKER_CLUSTER_MIN_COUNT
        if window_ms <= 0:
            trade_window = self.trades_session
        elif window_ms <= 15_000:
            trade_window = self.trades_15s
        elif window_ms <= 30_000:
            trade_window = self.trades_30s
        elif window_ms <= 60_000:
            trade_window = self.trades_1m
        elif window_ms <= 300_000:
            trade_window = self.trades_5m
        elif window_ms <= 900_000:
            trade_window = self.trades_15m
        else:
            trade_window = self.trades_1h
        ref_price, ref_source = self.flow_cluster_reference(trade_window)
        return trade_window.clusters(
            reference_price=ref_price,
            reference_source=ref_source,
            bucket_pct=bucket_pct,
            min_notional=min_notional,
            min_count=min_count,
        )

    def flow_cluster_reference(self, trade_window: TradeWindow) -> tuple[float, str]:
        vwap = trade_window.vwap()
        if vwap:
            return vwap, "vwap"
        if self.session_open_price:
            return self.session_open_price, "session_open"
        ref = self.mid or self.mark or self.book_mid
        return (ref, "current") if ref else (0.0, "none")

    def recent_liqs(self, window_ms: int = 300_000) -> list[tuple]:
        cutoff = int(time.time() * 1000) - window_ms
        return [(ts, s, q, p) for ts, s, q, p in self.liqs if ts >= cutoff]

    def liq_clusters(
        self,
        window_ms: int = 300_000,
        bucket_pct: float | None = None,
        min_count: int | None = None,
    ) -> list[dict]:
        """Identify price levels where liquidations cluster - the stop-cluster signal."""
        bucket_pct = bucket_pct or config.LIQ_CLUSTER_BUCKET_PCT
        min_count = min_count or config.LIQ_CLUSTER_MIN_COUNT

        recent = self.recent_liqs(window_ms)
        if not recent or not self.mark:
            return []

        bucket_size = self.mark * bucket_pct / 100
        buckets: dict[int, dict] = {}
        for _, side, qty, price in recent:
            key = round(price / bucket_size)
            if key not in buckets:
                buckets[key] = {
                    "price": round(key * bucket_size, 4),
                    "count": 0,
                    "notional": 0.0,
                    "longs": 0,    # side == "SELL" -> long liquidation
                    "shorts": 0,   # side == "BUY"  -> short liquidation
                }
            b = buckets[key]
            b["count"] += 1
            b["notional"] += qty * price
            if side == "SELL":
                b["longs"] += 1
            else:
                b["shorts"] += 1

        return sorted(
            [v for v in buckets.values() if v["count"] >= min_count],
            key=lambda x: x["notional"],
            reverse=True,
        )


def _level_stats(levels: list[dict]) -> list[dict[str, float]]:
    parsed = []
    for level in levels:
        try:
            price = float(level.get("px", 0))
            size = float(level.get("sz", 0))
        except (TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        parsed.append({"px": price, "sz": size, "notional": price * size})
    return parsed
