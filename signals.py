from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import config
from state import SymbolState


@dataclass(frozen=True, slots=True)
class Factor:
    """Interpreted datapoint that supports or challenges an active signal."""

    label: str
    value: str
    threshold: str
    meaning: str
    severity: str
    age_ms: int | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable factor payload."""
        return {
            "label": self.label,
            "value": self.value,
            "threshold": self.threshold,
            "meaning": self.meaning,
            "severity": self.severity,
            "age_ms": self.age_ms,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Signal:
    """Current actionable setup derived from live market state."""

    symbol: str
    action: str
    title: str
    strength: str
    confirmations: list[Factor]
    risks: list[Factor]
    updated_at_ms: int
    expires_at_ms: int

    @property
    def signal_key(self) -> str:
        """Return a stable key for current-state de-duplication."""
        return f"{self.symbol}:{self.action}:{self.title}".lower()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable signal payload."""
        return {
            "signal_key": self.signal_key,
            "symbol": self.symbol,
            "action": self.action,
            "title": self.title,
            "strength": self.strength,
            "confirmations": [factor.to_dict() for factor in self.confirmations],
            "risks": [factor.to_dict() for factor in self.risks],
            "updated_at": _ts_utc(self.updated_at_ms),
            "updated_at_ms": self.updated_at_ms,
            "expires_at": _ts_utc(self.expires_at_ms),
            "expires_at_ms": self.expires_at_ms,
        }


def evaluate_signal_set(
    states: Mapping[str, SymbolState],
    now_ms: int | None = None,
) -> list[Signal]:
    """Build active structured signals for the configured watchlist."""
    now_ms = now_ms or int(time.time() * 1000)
    active: list[Signal] = []
    for symbol in config.WATCHLIST:
        state = states.get(symbol)
        if state is None or not state.last_event_ts:
            continue

        for signal in (
            _long_squeeze_signal(symbol, state, now_ms),
            _short_squeeze_signal(symbol, state, now_ms),
            _capitulation_signal(symbol, state, now_ms),
            _grinding_trap_signal(symbol, state, now_ms),
        ):
            if signal is not None:
                active.append(signal)

    return sorted(
        active,
        key=lambda item: (_strength_rank(item.strength), len(item.confirmations)),
        reverse=True,
    )


def _long_squeeze_signal(
    symbol: str,
    state: SymbolState,
    now_ms: int,
) -> Signal | None:
    funding_pct = state.funding * 100
    oi_delta = state.oi_history.delta_pct(3_600_000)
    taker_pct = state.trades_5m.taker_pct()
    impact = state.impact_excess_bps
    impact_threshold = _impact_threshold(symbol)
    confirmations: list[Factor] = []
    risks: list[Factor] = []

    if funding_pct >= config.ALERT_FUNDING_SQUEEZE_PCT:
        confirmations.append(
            _funding_factor(funding_pct, now_ms, state.last_context_ts)
        )
    if _oi_rising(state, oi_delta):
        confirmations.append(_oi_factor(state, oi_delta, now_ms))
    if taker_pct is not None and taker_pct >= config.ALERT_TAKER_HIGH_PCT:
        confirmations.append(
            _factor(
                "Taker flow",
                f"{taker_pct:.1f}% aggressive buy",
                f">= {config.ALERT_TAKER_HIGH_PCT:.1f}%",
                "Buying is crowded enough to make long leverage fragile.",
                "strong",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )

    if config.LIQUIDATION_FEED_ENABLED and state.mark:
        long_below = [
            cluster
            for cluster in state.liq_clusters(window_ms=3_600_000, min_count=2)
            if cluster["price"] < state.mark and cluster["longs"] > cluster["shorts"]
        ]
        if long_below:
            nearest = min(long_below, key=lambda cluster: state.mark - cluster["price"])
            distance_pct = (state.mark - nearest["price"]) / state.mark * 100
            confirmations.append(
                _factor(
                    "Long liquidation level",
                    f"{distance_pct:.2f}% below mark, {_money(nearest['notional'])}",
                    "cluster below current mark",
                    "Nearby long-liquidation pressure can accelerate a flush.",
                    "strong",
                    _age(now_ms, _latest_liq_ts(state)),
                    "Bybit allLiquidation",
                )
            )

    ask_heavy = (
        state.book_imbalance_pct is not None
        and state.book_imbalance_pct <= -config.ALERT_BOOK_IMBALANCE_PCT
    )
    thin_book = impact is not None and impact >= impact_threshold
    if ask_heavy:
        confirmations.append(
            _factor(
                "Book imbalance",
                f"{state.book_imbalance_pct:.0f}% ask-heavy",
                f"<= -{config.ALERT_BOOK_IMBALANCE_PCT:.0f}%",
                "Ask-side depth can cap crowded longs on a retest.",
                "context",
                _age(now_ms, state.last_book_ts),
                "Hyperliquid l2Book",
            )
        )
    elif thin_book:
        confirmations.append(
            _impact_factor(symbol, impact, impact_threshold, now_ms, state.last_book_ts)
        )

    if state.basis_pct <= config.ALERT_BASIS_CAPITULATION:
        risks.append(
            _factor(
                "Basis discount",
                f"{state.basis_pct:+.3f}%",
                f"> {config.ALERT_BASIS_CAPITULATION:+.3f}%",
                "Perp already trades cheap to reference, reducing short-entry quality.",
                "risk",
                _age(now_ms, state.last_context_ts),
                _basis_source(state),
            )
        )

    if not (
        funding_pct >= config.ALERT_FUNDING_SQUEEZE_PCT
        and _oi_rising(state, oi_delta)
        and len(confirmations) >= 3
    ):
        return None

    return _signal(
        symbol,
        "OPEN SHORT / CLOSE LONG",
        "Crowded Long Squeeze",
        confirmations,
        risks,
        now_ms,
    )


def _short_squeeze_signal(
    symbol: str,
    state: SymbolState,
    now_ms: int,
) -> Signal | None:
    funding_pct = state.funding * 100
    oi_delta = state.oi_history.delta_pct(3_600_000)
    taker_pct = state.trades_5m.taker_pct()
    confirmations: list[Factor] = []
    risks: list[Factor] = []

    if funding_pct <= -config.ALERT_FUNDING_SQUEEZE_PCT:
        confirmations.append(
            _funding_factor(funding_pct, now_ms, state.last_context_ts)
        )
    if _oi_rising(state, oi_delta):
        confirmations.append(_oi_factor(state, oi_delta, now_ms))
    if taker_pct is not None and taker_pct <= config.ALERT_TAKER_LOW_PCT:
        confirmations.append(
            _factor(
                "Taker flow",
                f"{taker_pct:.1f}% aggressive buy",
                f"<= {config.ALERT_TAKER_LOW_PCT:.1f}%",
                "Selling is crowded enough to create short-covering risk.",
                "strong",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )
    if state.basis_pct < 0:
        confirmations.append(
            _factor(
                "Basis discount",
                f"{state.basis_pct:+.3f}%",
                "< 0.000%",
                "Perp trades below reference while shorts are crowded.",
                "context",
                _age(now_ms, state.last_context_ts),
                _basis_source(state),
            )
        )

    bid_heavy = (
        state.book_imbalance_pct is not None
        and state.book_imbalance_pct >= config.ALERT_BOOK_IMBALANCE_PCT
    )
    if bid_heavy:
        confirmations.append(
            _factor(
                "Book imbalance",
                f"{state.book_imbalance_pct:.0f}% bid-heavy",
                f">= {config.ALERT_BOOK_IMBALANCE_PCT:.0f}%",
                "Bid-side depth can support a short-covering bounce.",
                "context",
                _age(now_ms, state.last_book_ts),
                "Hyperliquid l2Book",
            )
        )

    if state.basis_pct > 0:
        risks.append(
            _factor(
                "Basis premium",
                f"{state.basis_pct:+.3f}%",
                "< 0.000%",
                "Perp is not discounted, weakening the short-squeeze setup.",
                "risk",
                _age(now_ms, state.last_context_ts),
                _basis_source(state),
            )
        )

    if not (
        funding_pct <= -config.ALERT_FUNDING_SQUEEZE_PCT
        and _oi_rising(state, oi_delta)
        and taker_pct is not None
        and taker_pct <= config.ALERT_TAKER_LOW_PCT
        and state.basis_pct < 0
    ):
        return None

    return _signal(
        symbol,
        "OPEN LONG / CLOSE SHORT",
        "Crowded Short Squeeze",
        confirmations,
        risks,
        now_ms,
    )


def _capitulation_signal(
    symbol: str,
    state: SymbolState,
    now_ms: int,
) -> Signal | None:
    cvd_15s = state.trades_15s.cvd()
    cvd_5m = state.trades_5m.cvd()
    taker_pct = state.trades_5m.taker_pct()
    liq_vol = sum(qty * price for _, _, qty, price in state.recent_liqs(300_000))
    liq_threshold = state.volume_scaled_threshold(
        config.ALERT_LIQ_CAPITULATION_USD,
        config.ALERT_LIQ_VOL_5M_DAY_FRACTION,
    )
    cvd_threshold_5m = -state.volume_scaled_threshold(
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )
    cvd_threshold_15s = -state.volume_scaled_threshold(
        abs(config.ALERT_CVD_15S_SHARP_NEG_USD),
        config.ALERT_CVD_15S_SHARP_NEG_DAY_FRACTION,
    )
    confirmations: list[Factor] = []
    risks: list[Factor] = []

    if config.LIQUIDATION_FEED_ENABLED and liq_vol >= liq_threshold:
        confirmations.append(
            _factor(
                "Liquidation pressure",
                _money(liq_vol),
                f">= {_money(liq_threshold)}",
                "Forced exits are large enough to matter for reversal timing.",
                "strong",
                _age(now_ms, _latest_liq_ts(state)),
                "Bybit allLiquidation",
            )
        )

    if cvd_15s <= cvd_threshold_15s and cvd_5m > cvd_threshold_5m:
        confirmations.append(
            _factor(
                "Cascade onset",
                f"15s {_money(cvd_15s)} CVD, 5m {_money(cvd_5m)} CVD",
                f"15s <= {_money(cvd_threshold_15s)}",
                "Ultra-short sell pressure is breaking before 5m flow catches up.",
                "strong",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )
    elif cvd_5m <= cvd_threshold_5m:
        confirmations.append(
            _factor(
                "Sell CVD",
                _money(cvd_5m),
                f"<= {_money(cvd_threshold_5m)}",
                "Aggressive selling is extreme enough for exhaustion watch.",
                "strong",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )

    if taker_pct is not None and taker_pct <= config.ALERT_TAKER_LOW_PCT:
        confirmations.append(
            _factor(
                "Taker exhaustion",
                f"{taker_pct:.1f}% aggressive buy",
                f"<= {config.ALERT_TAKER_LOW_PCT:.1f}%",
                "Selling dominates the 5m tape.",
                "context",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )
    if state.basis_pct <= config.ALERT_BASIS_CAPITULATION:
        confirmations.append(
            _factor(
                "Basis discount",
                f"{state.basis_pct:+.3f}%",
                f"<= {config.ALERT_BASIS_CAPITULATION:+.3f}%",
                "Perp trades materially cheap to reference during forced selling.",
                "context",
                _age(now_ms, state.last_context_ts),
                _basis_source(state),
            )
        )

    if state.basis_pct > config.ALERT_BASIS_CAPITULATION:
        risks.append(
            _factor(
                "Basis not washed out",
                f"{state.basis_pct:+.3f}%",
                f"<= {config.ALERT_BASIS_CAPITULATION:+.3f}%",
                "Discount is not deep enough for a clean capitulation read.",
                "risk",
                _age(now_ms, state.last_context_ts),
                _basis_source(state),
            )
        )

    if len(confirmations) < 3:
        return None
    if not any(
        factor.label in {"Cascade onset", "Sell CVD"} for factor in confirmations
    ):
        return None

    return _signal(
        symbol,
        "CLOSE SHORT / OPEN LONG",
        "Sell Capitulation",
        confirmations,
        risks,
        now_ms,
    )


def _grinding_trap_signal(
    symbol: str,
    state: SymbolState,
    now_ms: int,
) -> Signal | None:
    price_delta = state.mark_delta_pct(900_000)
    price_sigma = state.mark_move_sigma(900_000)
    cvd_5m = state.trades_5m.cvd()
    oi_delta = state.oi_history.delta_pct(900_000)
    funding_delta = state.funding_delta_pct()
    confirmations: list[Factor] = []
    risks: list[Factor] = []

    price_condition = (
        price_sigma is not None and price_sigma >= config.ALERT_PRICE_GRIND_SIGMA
    ) or (
        price_sigma is None
        and price_delta is not None
        and price_delta >= config.ALERT_PRICE_GRIND_PCT
    )
    funding_condition = state.funding > 0 and (
        funding_delta is None or funding_delta >= 0
    )

    if price_delta is not None and price_condition:
        confirmations.append(
            _factor(
                "Price grind",
                f"{price_delta:+.2f}% / {price_sigma or 0:.1f} sigma",
                f">= {config.ALERT_PRICE_GRIND_PCT:.2f}% or {config.ALERT_PRICE_GRIND_SIGMA:.1f} sigma",
                "Price is rising faster than recent realized volatility supports.",
                "strong",
                _age(now_ms, state.price_history.latest_ts()),
                "Hyperliquid allMids",
            )
        )
    if cvd_5m <= 0:
        confirmations.append(
            _factor(
                "Buyer support",
                f"{_money(cvd_5m)} 5m CVD",
                "<= $0",
                "Move lacks aggressive buyer confirmation.",
                "strong",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )
    if funding_condition:
        confirmations.append(
            _factor(
                "Funding build",
                f"{state.funding * 100:+.4f}%",
                "> 0.0000%",
                "Longs are paying while price rises without CVD support.",
                "context",
                _age(now_ms, state.last_context_ts),
                "Hyperliquid activeAssetCtx",
            )
        )
    if oi_delta is not None and oi_delta > 0:
        confirmations.append(
            _factor(
                "OI build",
                f"{oi_delta:+.2f}% over 15m",
                "> 0.00%",
                "Positioning is expanding into the grind.",
                "context",
                _age(now_ms, state.oi_history.latest_ts()),
                "Hyperliquid metaAndAssetCtxs",
            )
        )

    if cvd_5m > 0:
        risks.append(
            _factor(
                "CVD confirms move",
                _money(cvd_5m),
                "<= $0",
                "Aggressive buyers are present, reducing trap quality.",
                "risk",
                _age(now_ms, state.last_trade_ts),
                "Hyperliquid trades",
            )
        )

    if not (
        price_delta is not None
        and price_condition
        and cvd_5m <= 0
        and funding_condition
        and oi_delta is not None
        and oi_delta > 0
    ):
        return None

    return _signal(
        symbol,
        "CLOSE LONG / OPEN SHORT",
        "Grinding Long Trap",
        confirmations,
        risks,
        now_ms,
    )


def _signal(
    symbol: str,
    action: str,
    title: str,
    confirmations: list[Factor],
    risks: list[Factor],
    now_ms: int,
) -> Signal:
    return Signal(
        symbol=symbol,
        action=action,
        title=title,
        strength=_strength(confirmations, risks),
        confirmations=confirmations,
        risks=risks,
        updated_at_ms=now_ms,
        expires_at_ms=now_ms + config.SIGNAL_TTL_MS,
    )


def _factor(
    label: str,
    value: str,
    threshold: str,
    meaning: str,
    severity: str,
    age_ms: int | None,
    source: str,
) -> Factor:
    return Factor(
        label=label,
        value=value,
        threshold=threshold,
        meaning=meaning,
        severity=severity,
        age_ms=age_ms,
        source=source,
    )


def _funding_factor(funding_pct: float, now_ms: int, ts_ms: int) -> Factor:
    side = "longs paying" if funding_pct > 0 else "shorts paying"
    return _factor(
        "Funding crowding",
        f"{funding_pct:+.4f}%",
        f"+/-{config.ALERT_FUNDING_SQUEEZE_PCT:.4f}%",
        f"{side}; leverage is directionally crowded.",
        "strong",
        _age(now_ms, ts_ms),
        "Hyperliquid activeAssetCtx",
    )


def _oi_factor(state: SymbolState, oi_delta: float | None, now_ms: int) -> Factor:
    return _factor(
        "Open interest",
        f"{oi_delta:+.2f}% over 1h, {_fmt_oi_day_fraction(state)} of 24h volume",
        (
            f">= {config.ALERT_OI_DELTA_1H_PCT:.2f}% or "
            f"{config.ALERT_OI_DELTA_1H_DAY_FRACTION * 100:.2f}% volume"
        ),
        "New leverage is entering the setup.",
        "strong",
        _age(now_ms, state.oi_history.latest_ts()),
        "Hyperliquid metaAndAssetCtxs",
    )


def _impact_factor(
    symbol: str,
    impact: float,
    threshold: float,
    now_ms: int,
    ts_ms: int,
) -> Factor:
    return _factor(
        "Impact thinness",
        f"{impact:.1f}bp excess impact",
        f">= {threshold:.1f}bp",
        f"{symbol.upper()} book can amplify forced flow.",
        "context",
        _age(now_ms, ts_ms),
        "Hyperliquid metaAndAssetCtxs + l2Book",
    )


def _oi_rising(state: SymbolState, oi_delta: float | None) -> bool:
    oi_day_fraction = _oi_delta_day_fraction(state, 3_600_000)
    return (
        oi_delta is not None
        and oi_delta > 0
        and (
            oi_delta >= config.ALERT_OI_DELTA_1H_PCT
            or (
                oi_day_fraction is not None
                and oi_day_fraction >= config.ALERT_OI_DELTA_1H_DAY_FRACTION
            )
        )
    )


def _oi_delta_day_fraction(
    state: SymbolState,
    lookback_ms: int,
) -> float | None:
    delta_oi = state.oi_history.delta_abs(lookback_ms)
    ref_price = state.mark or state.mid
    if delta_oi is None or not ref_price or state.day_ntl_vlm <= 0:
        return None
    return delta_oi * ref_price / state.day_ntl_vlm


def _fmt_oi_day_fraction(state: SymbolState) -> str:
    value = _oi_delta_day_fraction(state, 3_600_000)
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def _impact_threshold(symbol: str) -> float:
    return config.ALERT_IMPACT_EXCESS_BPS_OVERRIDES.get(
        symbol,
        config.ALERT_IMPACT_EXCESS_BPS,
    )


def _basis_source(state: SymbolState) -> str:
    if state.basis_source == "spot":
        return "Hyperliquid spot basis"
    return "Hyperliquid oracle basis fallback"


def _latest_liq_ts(state: SymbolState) -> int | None:
    if not state.liqs:
        return None
    return max(ts for ts, _, _, _ in state.liqs)


def _age(now_ms: int, ts_ms: int | None) -> int | None:
    if not ts_ms:
        return None
    return max(0, now_ms - ts_ms)


def _strength(confirmations: list[Factor], risks: list[Factor]) -> str:
    strong_count = sum(1 for factor in confirmations if factor.severity == "strong")
    if strong_count >= 3 and not risks:
        return "strong"
    if strong_count >= 2:
        return "moderate"
    return "context"


def _strength_rank(strength: str) -> int:
    return {"strong": 3, "moderate": 2, "context": 1}.get(strength, 0)


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}${amount / 1_000:.1f}k"
    return f"{sign}${amount:.0f}"


def _ts_utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
