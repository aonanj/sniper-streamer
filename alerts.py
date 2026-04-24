"""
Threshold-based alert engine — simple signals and composite setup alerts.

All alerts are de-duplicated within a 5-minute window per (symbol, kind) pair
so a sustained condition fires once rather than on every dashboard refresh.

Composite setups
────────────────
LONG_SQUEEZE   funding hot + OI rising + crowded buying + thin/downstream book
CAPITULATION   sharp CVD sell + crowded selling + perp-spot discount + thin book
GRINDING_TRAP  price rising in sigma terms + CVD flat/neg + funding/OI building
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import config
from state import SymbolState


@dataclass
class Alert:
    ts: float
    sym: str
    kind: str
    message: str


_log: deque[Alert] = deque(maxlen=50)
_DEDUP_WINDOW = 300.0  # seconds


# ------------------------------------------------------------------ #
# Public API

def check(sym: str, st: SymbolState) -> None:
    _check_simple(sym, st)
    if config.LIQUIDATION_FEED_ENABLED:
        _check_long_squeeze(sym, st)
        _check_capitulation(sym, st)
    else:
        _check_structural_long_squeeze(sym, st)
        _check_flow_capitulation(sym, st)
    _check_grinding_trap(sym, st)


def recent(n: int = 8) -> list[Alert]:
    return list(_log)[:n]


# ------------------------------------------------------------------ #
# Simple threshold alerts

def _check_simple(sym: str, st: SymbolState) -> None:
    now = time.time()
    funding_pct = st.funding * 100

    if abs(funding_pct) >= config.ALERT_FUNDING_PCT:
        _fire(now, sym, "FUNDING",
              f"rate {funding_pct:+.4f}% (±{config.ALERT_FUNDING_PCT}% threshold)")

    if config.LIQUIDATION_FEED_ENABLED:
        recent_liqs = st.recent_liqs(300_000)
        liq_vol = sum(q * p for _, _, q, p in recent_liqs)
        liq_threshold = st.volume_scaled_threshold(
            config.ALERT_LIQ_VOL_5M_USD,
            config.ALERT_LIQ_VOL_5M_DAY_FRACTION,
        )
        if liq_vol >= liq_threshold:
            _fire(now, sym, "LIQ_VOL",
                  f"5m vol ${liq_vol:,.0f} (threshold ${liq_threshold:,.0f})")

    oi_d1h = st.oi_history.delta_pct(3_600_000)
    if oi_d1h is not None and abs(oi_d1h) >= config.ALERT_OI_DELTA_1H_PCT:
        _fire(now, sym, "OI_1H",
              f"1h OI Δ {oi_d1h:+.2f}% (±{config.ALERT_OI_DELTA_1H_PCT}% threshold)")

    if config.LIQUIDATION_FEED_ENABLED:
        clusters = st.liq_clusters()
        if clusters:
            top = clusters[0]
            _fire(now, sym, "CLUSTER",
                  f"stop cluster @ {top['price']:,.4f}  "
                  f"x{top['count']} events  ${top['notional']:,.0f}")

    impact = st.impact_excess_bps
    if impact is not None and impact >= config.ALERT_IMPACT_EXCESS_BPS:
        _fire(now, sym, "THIN_BOOK",
              f"impact excess {impact:.1f}bp over spread")

    clusters = st.taker_flow_clusters(window_ms=3_600_000)
    if clusters:
        top = clusters[0]
        threshold = st.volume_scaled_threshold(
            config.TAKER_CLUSTER_MIN_USD,
            config.TAKER_CLUSTER_MIN_DAY_FRACTION,
        )
        if top["notional"] >= threshold:
            side = "BUY" if top["buy"] >= top["sell"] else "SELL"
            _fire(now, sym, "FLOW_CLUSTER",
                  f"{side} flow cluster @ {top['price']:,.4f}  "
                  f"x{top['count']}  ${top['notional']:,.0f}")


# ------------------------------------------------------------------ #
# Composite setup alerts

def _check_long_squeeze(sym: str, st: SymbolState) -> None:
    """Loaded long-squeeze setup.

    Fires when: funding hot, OI building, buying tape crowded, AND there is a
    cluster of long liquidations sitting below the current mark — meaning longs
    are already stacked in a zone that price could flush through.
    """
    if not st.mark:
        return
    funding_pct = st.funding * 100
    oi_d1h      = st.oi_history.delta_pct(3_600_000)
    tp5         = st.trades_5m.taker_pct()

    if not (
        funding_pct >= config.ALERT_FUNDING_SQUEEZE_PCT
        and oi_d1h is not None and oi_d1h >= config.ALERT_OI_DELTA_1H_PCT
        and tp5 is not None and tp5 >= config.ALERT_TAKER_HIGH_PCT
    ):
        return

    clusters_1h = st.liq_clusters(window_ms=3_600_000, min_count=2)
    long_below  = [
        c for c in clusters_1h
        if c["price"] < st.mark and c["longs"] > c["shorts"]
    ]
    if not long_below:
        return

    nearest  = min(long_below, key=lambda c: st.mark - c["price"])
    dist_pct = (st.mark - nearest["price"]) / st.mark * 100
    _fire(
        time.time(), sym, "LONG_SQUEEZE",
        f"fund {funding_pct:+.4f}%  OI +{oi_d1h:.1f}%  "
        f"tkr {tp5:.0f}%  ↓L cluster -{dist_pct:.2f}% away",
    )


def _check_capitulation(sym: str, st: SymbolState) -> None:
    """Capitulation reversal setup.

    Fires when forced sellers are hammering the perp book: large liq volume,
    sharply negative CVD, crowded selling tape, and the perp is trading below
    spot (negative basis). This combination often marks a short-term bottom.
    """
    liq_vol = sum(q * p for _, _, q, p in st.recent_liqs(300_000))
    cvd5 = st.trades_5m.cvd()
    tp5 = st.trades_5m.taker_pct()
    liq_threshold = st.volume_scaled_threshold(
        config.ALERT_LIQ_CAPITULATION_USD,
        config.ALERT_LIQ_VOL_5M_DAY_FRACTION,
    )
    cvd_threshold = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )

    if not (
        liq_vol >= liq_threshold
        and cvd5 <= cvd_threshold
        and tp5 is not None and tp5 <= config.ALERT_TAKER_LOW_PCT
        and st.basis_pct <= config.ALERT_BASIS_CAPITULATION
    ):
        return

    _fire(
        time.time(), sym, "CAPITULATION",
        f"liq ${liq_vol:,.0f}  CVD {cvd5/1_000_000:.2f}M  "
        f"tkr {tp5:.0f}%  basis {st.basis_pct:+.3f}%",
    )


def _check_structural_long_squeeze(sym: str, st: SymbolState) -> None:
    """Loaded-long structure without relying on a public liquidation stream."""
    if not st.mark:
        return

    funding_pct = st.funding * 100
    funding_delta = st.funding_delta_pct()
    oi_d1h = st.oi_history.delta_pct(3_600_000)
    tp5 = st.trades_5m.taker_pct()
    impact = st.impact_excess_bps
    ask_heavy = (
        st.book_imbalance_pct is not None
        and st.book_imbalance_pct <= -config.ALERT_BOOK_IMBALANCE_PCT
    )

    if not (
        funding_pct >= config.ALERT_FUNDING_SQUEEZE_PCT
        and (funding_delta is None or funding_delta >= config.ALERT_FUNDING_DELTA_1H_PCT)
        and oi_d1h is not None and oi_d1h >= config.ALERT_OI_DELTA_1H_PCT
        and tp5 is not None and tp5 >= config.ALERT_TAKER_HIGH_PCT
        and impact is not None and impact >= config.ALERT_IMPACT_EXCESS_BPS
    ):
        return

    book_note = "ask-heavy book" if ask_heavy else "thin impact book"
    _fire(
        time.time(), sym, "LONG_SQUEEZE",
        f"fund {funding_pct:+.4f}%  FΔ {funding_delta or 0:+.4f}%  "
        f"OI +{oi_d1h:.1f}%  tkr {tp5:.0f}%  {book_note} {impact:.1f}bp",
    )


def _check_flow_capitulation(sym: str, st: SymbolState) -> None:
    """Sell-pressure exhaustion proxy when liquidations are not public."""
    cvd5 = st.trades_5m.cvd()
    tp5 = st.trades_5m.taker_pct()
    impact = st.impact_excess_bps
    cvd_threshold = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )

    if not (
        cvd5 <= cvd_threshold
        and tp5 is not None and tp5 <= config.ALERT_TAKER_LOW_PCT
        and st.basis_pct <= config.ALERT_BASIS_CAPITULATION
        and impact is not None and impact >= config.ALERT_IMPACT_EXCESS_BPS
    ):
        return

    _fire(
        time.time(), sym, "CAPITULATION",
        f"CVD {cvd5/1_000_000:.2f}M <= {cvd_threshold/1_000_000:.2f}M  "
        f"tkr {tp5:.0f}%  basis {st.basis_pct:+.3f}%  impact {impact:.1f}bp",
    )


def _check_grinding_trap(sym: str, st: SymbolState) -> None:
    """Grinding trap setup.

    Price is rising, but the move is entirely positioning-driven rather than
    real demand: CVD is flat or negative (no aggressive buying), funding is
    creeping up (longs building), and OI is expanding. Fragile structure.
    """
    px_d15 = st.mark_delta_pct(900_000)   # 15m price change
    px_sigma = st.mark_move_sigma(900_000)
    cvd5 = st.trades_5m.cvd()
    oi_d15 = st.oi_history.delta_pct(900_000)
    funding_delta = st.funding_delta_pct()
    price_condition = (
        px_sigma is not None and px_sigma >= config.ALERT_PRICE_GRIND_SIGMA
    ) or (
        px_sigma is None and px_d15 is not None and px_d15 >= config.ALERT_PRICE_GRIND_PCT
    )
    funding_condition = (
        st.funding > 0
        and (funding_delta is None or funding_delta >= 0)
    )

    if not (
        px_d15 is not None and price_condition
        and cvd5 <= 0
        and funding_condition
        and oi_d15 is not None and oi_d15 > 0
    ):
        return

    _fire(
        time.time(), sym, "GRINDING_TRAP",
        f"px +{px_d15:.2f}% 15m ({px_sigma or 0:.1f}σ)  "
        f"CVD {cvd5/1_000_000:.2f}M  fund {st.funding*100:+.4f}%  "
        f"FΔ {funding_delta or 0:+.4f}%  OI +{oi_d15:.2f}% 15m",
    )


# ------------------------------------------------------------------ #
# Internals

def _fire(ts: float, sym: str, kind: str, message: str) -> None:
    cutoff = ts - _DEDUP_WINDOW
    for a in _log:
        if a.sym == sym and a.kind == kind and a.ts >= cutoff:
            return
    _log.appendleft(Alert(ts=ts, sym=sym, kind=kind, message=message))
