"""
Threshold-based alert engine — simple signals and composite setup alerts.

Most alerts are de-duplicated within a 5-minute window per (symbol, kind) pair
so a sustained condition fires once rather than on every dashboard refresh.
Funding and flow-cluster alerts use longer dedupe windows.

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
import persistence
from state import SymbolState


@dataclass
class Alert:
    ts: float
    sym: str
    kind: str
    message: str


_log: deque[Alert] = deque(maxlen=50)
_DEDUP_WINDOW = 300.0  # seconds
_last_fired_by_key: dict[str, float] = {}


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
    _check_structural_short_squeeze(sym, st)
    _check_grinding_trap(sym, st)


def recent(n: int = 8) -> list[Alert]:
    return list(_log)[:n]


# ------------------------------------------------------------------ #
# Simple threshold alerts

def _check_simple(sym: str, st: SymbolState) -> None:
    now = time.time()
    funding_pct = st.funding * 100

    if abs(funding_pct) >= config.ALERT_FUNDING_PCT:
        _fire(now, sym, st, "FUNDING",
              _detail(
                  _funding_bias(funding_pct),
                  "weak",
                  _funding_why(funding_pct),
                  f"funding {funding_pct:+.4f}% vs +/-{config.ALERT_FUNDING_PCT:.4f}%",
              ),
              dedup_window=config.ALERT_FUNDING_DEDUP_WINDOW_SEC)

    if config.LIQUIDATION_FEED_ENABLED:
        recent_liqs = st.recent_liqs(300_000)
        liq_vol = sum(q * p for _, _, q, p in recent_liqs)
        liq_threshold = st.volume_scaled_threshold(
            config.ALERT_LIQ_VOL_5M_USD,
            config.ALERT_LIQ_VOL_5M_DAY_FRACTION,
        )
        if liq_vol >= liq_threshold:
            long_liq = sum(q * p for _, side, q, p in recent_liqs if side == "SELL")
            short_liq = liq_vol - long_liq
            if long_liq >= short_liq:
                move = "close SHORT / open LONG"
                why = "long liquidations into book"
                dominant = f"long liq {_money(long_liq)}"
            else:
                move = "close LONG / open SHORT"
                why = "short liquidations into book"
                dominant = f"short liq {_money(short_liq)}"
            _fire(now, sym, st, "LIQ_VOL",
                  _detail(
                      move,
                      "late reversal watch",
                      why,
                      f"5m liq {_money(liq_vol)} vs {_money(liq_threshold)} alert; {dominant}",
                  ))

    oi_d1h = st.oi_history.delta_pct(3_600_000)
    oi_day_fraction = _oi_delta_day_fraction(st, 3_600_000)
    if oi_d1h is not None and _oi_delta_alert_hit(oi_d1h, oi_day_fraction):
        if oi_d1h > 0:
            oi_move = "leverage opening"
            oi_strength = "context"
            oi_why = (
                "new margin event; read with funding/taker side"
                " long vs short crowding"
            )
        else:
            oi_move = "deleveraging / take-profit signal"
            oi_strength = "context"
            oi_why = "positions closing → less squeeze pressure"
        _fire(
            now, sym, st, "OI_1H",
            _detail(
                oi_move,
                oi_strength,
                oi_why,
                f"OI 1h {oi_d1h:+.2f}%; "
                f"notional {_fmt_fraction_pct(oi_day_fraction)} of 24h volume vs "
                f"+/-{config.ALERT_OI_DELTA_1H_PCT:.2f}% or "
                f"+/-{config.ALERT_OI_DELTA_1H_DAY_FRACTION * 100:.2f}% volume",
            ),
        )

    if config.LIQUIDATION_FEED_ENABLED:
        clusters = st.liq_clusters()
        if clusters:
            top = clusters[0]
            if top["longs"] >= top["shorts"]:
                cluster_move = "short cascade level / long-exit zone"
                cluster_why = "long liquidations clustered at one price bucket"
            else:
                cluster_move = "long squeeze level / short-exit zone"
                cluster_why = "short liquidations clustered at one price bucket"
            _fire(now, sym, st, "CLUSTER",
                  _detail(
                      cluster_move,
                      "context",
                      cluster_why,
                      f"price {top['price']:,.4f}; {top['count']} events; "
                      f"{_money(top['notional'])}",
                  ))

    impact = st.impact_excess_bps
    impact_threshold = _impact_threshold(sym)
    if impact is not None and impact >= impact_threshold:
        _fire(now, sym, st, "THIN_BOOK",
              _detail(
                  "cascade amplifier",
                  "weak",
                  "thin impact book can increase liquidation (long / short)",
                  f"impact excess: {impact:.1f}bp vs {impact_threshold:.1f}bp",
              ))

    flow_threshold = _volume_scaled_threshold(
        st,
        config.TAKER_CLUSTER_ALERT_MIN_USD,
        config.TAKER_CLUSTER_ALERT_MIN_DAY_FRACTION,
        config.TAKER_CLUSTER_ALERT_FLOOR_USD,
    )
    clusters = st.taker_flow_clusters(
        min_notional=flow_threshold,
        min_count=config.TAKER_CLUSTER_ALERT_MIN_COUNT,
    )
    if clusters:
        top = clusters[0]
        dominance = (
            max(top["buy"], top["sell"]) / top["notional"] * 100
            if top["notional"] else 0.0
        )
        if dominance >= config.TAKER_CLUSTER_ALERT_DOMINANCE_PCT:
            side = "BUY" if top["buy"] >= top["sell"] else "SELL"
            if side == "BUY":
                move = "long crowding zone"
                why = "aggressive buys concentrated; read with funding (positive) and OI (increasing)"
            else:
                move = "short crowding zone"
                why = "aggressive sells concentrated; read with funding (negative) and OI (increasing)"
            _fire(now, sym, st, "FLOW_CLUSTER",
                  _detail(
                      move,
                      "context",
                      why,
                      f"{side.lower()} cluster @ {top['price']:,.4f}; "
                      f"{top['count']} trades; {_money(top['notional'])}; "
                      f"{dominance:.0f}% one-sided; "
                      f"{top.get('ref_source', 'ref')} bucket ref",
                  ),
                  dedup_key=f"FLOW_CLUSTER:{sym}:{side}",
                  dedup_window=config.TAKER_CLUSTER_ALERT_DEDUP_WINDOW_SEC)


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
        and _oi_rising_alert_hit(st, oi_d1h)
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
        time.time(), sym, st, "LONG_SQUEEZE",
        _detail(
            "open SHORT / close LONG",
            "strong",
            "crowded longs near liquidation",
            f"funding {funding_pct:+.4f}%; OI 1h +{oi_d1h:.1f}%; "
            f"OI notional {_fmt_oi_day_fraction(st)} of 24h volume; "
            f"taker buy {tp5:.0f}%; long-liq cluster {dist_pct:.2f}% below",
        ),
    )


def _check_capitulation(sym: str, st: SymbolState) -> None:
    """Capitulation reversal setup.

    Two trigger paths:

    1. CASCADE ONSET (early): 15s CVD hammered while 5m CVD is still green.
       The divergence between ultra-short and medium-term flow is the precise
       moment a liquidation cascade begins — before the 5m window averages it out.

    2. CLASSIC (lagging): 5m CVD deeply negative, crowded selling, negative basis.
       Fires after the cascade is well underway, useful as confirmation.
    """
    liq_vol = sum(q * p for _, _, q, p in st.recent_liqs(300_000))
    cvd_15s = st.trades_15s.cvd()
    cvd_5m = st.trades_5m.cvd()
    tp5 = st.trades_5m.taker_pct()
    liq_threshold = st.volume_scaled_threshold(
        config.ALERT_LIQ_CAPITULATION_USD,
        config.ALERT_LIQ_VOL_5M_DAY_FRACTION,
    )
    cvd_threshold_5m = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )
    cvd_threshold_15s = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_15S_SHARP_NEG_USD),
        config.ALERT_CVD_15S_SHARP_NEG_DAY_FRACTION,
    )

    if liq_vol < liq_threshold or st.basis_pct > config.ALERT_BASIS_CAPITULATION:
        return

    if cvd_15s <= cvd_threshold_15s and cvd_5m > cvd_threshold_5m:
        _fire(
            time.time(), sym, st, "CAPITULATION",
            _detail(
                "close SHORT / consider LONG",
                "early — cascade onset",
                "15s CVD deep red while 5m still green: liquidation cascade just started",
                f"5m liq {_money(liq_vol)}; {_cvd_label(cvd_15s)} (15s); "
                f"{_cvd_label(cvd_5m)} (5m); basis {st.basis_pct:+.3f}%",
            ),
        )
    elif (
        cvd_5m <= cvd_threshold_5m
        and tp5 is not None and tp5 <= config.ALERT_TAKER_LOW_PCT
    ):
        _fire(
            time.time(), sym, st, "CAPITULATION",
            _detail(
                "close SHORT / consider LONG",
                "strong (lagging)",
                "forced selling into negative basis can mark exhaustion",
                f"5m liq {_money(liq_vol)}; {_cvd_label(cvd_5m)}; "
                f"taker buy {tp5:.0f}%; basis {st.basis_pct:+.3f}%",
            ),
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
    impact_threshold = _impact_threshold(sym)
    ask_heavy = (
        st.book_imbalance_pct is not None
        and st.book_imbalance_pct <= -config.ALERT_BOOK_IMBALANCE_PCT
    )
    thin_book = impact is not None and impact >= impact_threshold

    if not (
        funding_pct >= config.ALERT_FUNDING_SQUEEZE_PCT
        and (funding_delta is None or funding_delta >= config.ALERT_FUNDING_DELTA_1H_PCT)
        and _oi_rising_alert_hit(st, oi_d1h)
        and tp5 is not None and tp5 >= config.ALERT_TAKER_HIGH_PCT
        and (thin_book or ask_heavy)
    ):
        return

    if ask_heavy:
        book_note = f"book ask-heavy {st.book_imbalance_pct:.0f}%"
    else:
        book_note = f"impact thin {impact:.1f}bp"
    _fire(
        time.time(), sym, st, "LONG_SQUEEZE",
        _detail(
            "open SHORT / close LONG",
            "strong",
            "crowded longs accumulating in thin/ask-heavy book",
            f"funding {funding_pct:+.4f}%; funding 1h {_fmt_pp(funding_delta)}; "
            f"OI 1h +{oi_d1h:.1f}% ({_fmt_oi_day_fraction(st)} of 24h volume); "
            f"taker buy {tp5:.0f}%; {book_note}",
        ),
    )


def _check_structural_short_squeeze(sym: str, st: SymbolState) -> None:
    """Loaded-short structure: shorts crowded, leverage building, tape sell-dominated.

    Fires when negative funding (shorts paying longs), OI rising, sell-dominated
    taker flow, and the perp is already trading below spot — the combination that
    precedes violent short-covering rallies.
    """
    if not st.mark:
        return

    funding_pct = st.funding * 100
    oi_d1h = st.oi_history.delta_pct(3_600_000)
    tp5 = st.trades_5m.taker_pct()

    if not (
        funding_pct <= -config.ALERT_FUNDING_SQUEEZE_PCT
        and _oi_rising_alert_hit(st, oi_d1h)
        and tp5 is not None and tp5 <= config.ALERT_TAKER_LOW_PCT
        and st.basis_pct < 0
    ):
        return

    bid_heavy = (
        st.book_imbalance_pct is not None
        and st.book_imbalance_pct >= config.ALERT_BOOK_IMBALANCE_PCT
    )
    book_note = "bid-heavy book" if bid_heavy else f"basis {st.basis_pct:+.3f}%"
    _fire(
        time.time(), sym, st, "SHORT_SQUEEZE",
        _detail(
            "open LONG / close SHORT",
            "strong",
            "crowded shorts trending down to spot/bid support",
            f"funding {funding_pct:+.4f}%; OI 1h +{oi_d1h:.1f}%; "
            f"OI notional {_fmt_oi_day_fraction(st)} of 24h volume; "
            f"taker buy {tp5:.0f}%; basis {st.basis_pct:+.3f}%; {book_note}",
        ),
    )


def _check_flow_capitulation(sym: str, st: SymbolState) -> None:
    """Sell-pressure exhaustion proxy when liquidations are not public.

    Two trigger paths mirror _check_capitulation: early cascade-onset divergence
    (15s CVD deep red, 5m still green) fires before the classic lagging signal.
    """
    cvd_15s = st.trades_15s.cvd()
    cvd_5m = st.trades_5m.cvd()
    tp5 = st.trades_5m.taker_pct()
    impact = st.impact_excess_bps
    impact_threshold = _impact_threshold(sym)
    cvd_threshold_5m = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )
    cvd_threshold_15s = -st.volume_scaled_threshold(
        abs(config.ALERT_CVD_15S_SHARP_NEG_USD),
        config.ALERT_CVD_15S_SHARP_NEG_DAY_FRACTION,
    )
    thin_book = impact is not None and impact >= impact_threshold

    if not thin_book or st.basis_pct > config.ALERT_BASIS_CAPITULATION:
        return

    if cvd_15s <= cvd_threshold_15s and cvd_5m > cvd_threshold_5m:
        _fire(
            time.time(), sym, st, "CAPITULATION",
            _detail(
                "close SHORT / open LONG",
                "early — cascade onset",
                "15s CVD diving while 5m still green: forced sell cascade just started",
                f"{_cvd_label(cvd_15s)} (15s); {_cvd_label(cvd_5m)} (5m); "
                f"basis {st.basis_pct:+.3f}%; impact {impact:.1f}bp",
            ),
        )
    elif (
        cvd_5m <= cvd_threshold_5m
        and tp5 is not None and tp5 <= config.ALERT_TAKER_LOW_PCT
    ):
        _fire(
            time.time(), sym, st, "CAPITULATION",
            _detail(
                "close SHORT / open LONG",
                "strong (lagging)",
                "aggressive selling into negative basis and thin impact",
                f"{_cvd_label(cvd_5m)} vs {_cvd_label(cvd_threshold_5m)}; "
                f"taker buy {tp5:.0f}%; basis {st.basis_pct:+.3f}%; impact {impact:.1f}bp",
            ),
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
        time.time(), sym, st, "GRINDING_TRAP",
        _detail(
            "close LONG / open SHORT",
            "moderate",
            "↑ price without buyer support",
            f"price 15m +{px_d15:.2f}% ({px_sigma or 0:.1f} sigma); "
            f"{_cvd_label(cvd5)}; funding {st.funding*100:+.4f}%; "
            f"funding 1h {_fmt_pp(funding_delta)}; OI 15m +{oi_d15:.2f}%",
        ),
    )


# ------------------------------------------------------------------ #
# Internals

def _impact_threshold(sym: str) -> float:
    return config.ALERT_IMPACT_EXCESS_BPS_OVERRIDES.get(
        sym, config.ALERT_IMPACT_EXCESS_BPS
    )


def _oi_delta_day_fraction(st: SymbolState, lookback_ms: int) -> float | None:
    delta_oi = st.oi_history.delta_abs(lookback_ms)
    ref_price = st.mark or st.mid
    if delta_oi is None or not ref_price or st.day_ntl_vlm <= 0:
        return None
    return delta_oi * ref_price / st.day_ntl_vlm


def _oi_delta_alert_hit(
    oi_delta_pct: float | None,
    oi_day_fraction: float | None,
) -> bool:
    return (
        oi_delta_pct is not None
        and abs(oi_delta_pct) >= config.ALERT_OI_DELTA_1H_PCT
    ) or (
        oi_day_fraction is not None
        and abs(oi_day_fraction) >= config.ALERT_OI_DELTA_1H_DAY_FRACTION
    )


def _oi_rising_alert_hit(st: SymbolState, oi_delta_pct: float | None) -> bool:
    oi_day_fraction = _oi_delta_day_fraction(st, 3_600_000)
    return (
        oi_delta_pct is not None
        and oi_delta_pct > 0
        and (
            oi_delta_pct >= config.ALERT_OI_DELTA_1H_PCT
            or (
                oi_day_fraction is not None
                and oi_day_fraction >= config.ALERT_OI_DELTA_1H_DAY_FRACTION
            )
        )
    )


def _volume_scaled_threshold(
    st: SymbolState,
    cap_usd: float,
    day_fraction: float,
    floor_usd: float,
) -> float:
    if st.day_ntl_vlm <= 0 or day_fraction <= 0:
        return cap_usd
    return max(floor_usd, min(cap_usd, st.day_ntl_vlm * day_fraction))


def _detail(move: str, strength: str, why: str, evidence: str) -> str:
    return f"▸ {move} | {strength} | {why} ({evidence})"


def _funding_bias(funding_pct: float) -> str:
    if funding_pct > 0:
        return "short watch / close LONG"
    if funding_pct < 0:
        return "long watch / close SHORT"
    return "no directional edge"


def _funding_why(funding_pct: float) -> str:
    if funding_pct > 0:
        return "longs paying → long crowding potential"
    if funding_pct < 0:
        return "shorts paying → short crowding potential"
    return "neutral funding"


def _fmt_pp(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.4f}pp"


def _fmt_fraction_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def _fmt_oi_day_fraction(st: SymbolState) -> str:
    return _fmt_fraction_pct(_oi_delta_day_fraction(st, 3_600_000))


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}${amount / 1_000:.0f}k"
    return f"{sign}${amount:.0f}"


def _cvd_label(cvd: float) -> str:
    if cvd >= 0:
        return f"net buy {_money(cvd)}"
    return f"net sell {_money(abs(cvd))}"


def _fire(
    ts: float,
    sym: str,
    st: SymbolState,
    kind: str,
    message: str,
    *,
    dedup_key: str | None = None,
    dedup_window: float = _DEDUP_WINDOW,
) -> None:
    key = dedup_key or f"{sym}:{kind}"
    cutoff = ts - dedup_window
    _prune_dedup(ts)
    if _last_fired_by_key.get(key, 0.0) >= cutoff:
        return
    _last_fired_by_key[key] = ts
    _log.appendleft(Alert(ts=ts, sym=sym, kind=kind, message=message))
    ts_ms = int(ts * 1000)
    persistence.enqueue_alert(
        ts_ms=ts_ms,
        sym=sym,
        kind=kind,
        message=message,
        snapshot=persistence.state_snapshot(sym, st, ts_ms),
    )


def _prune_dedup(ts: float) -> None:
    retention = max(
        _DEDUP_WINDOW,
        config.ALERT_FUNDING_DEDUP_WINDOW_SEC,
        config.TAKER_CLUSTER_ALERT_DEDUP_WINDOW_SEC,
    )
    cutoff = ts - retention * 2
    stale = [key for key, fired_ts in _last_fired_by_key.items() if fired_ts < cutoff]
    for key in stale:
        _last_fired_by_key.pop(key, None)
