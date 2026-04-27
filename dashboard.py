"""Rich terminal dashboard - three-panel layout:
  Top:         main screener table (one row per symbol)
  Bottom-left: recent alerts
  Bottom-right: taker-flow clusters, or liquidation clusters if enabled
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

from rich.console import Console, JustifyMethod
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import alerts
import config
from feeds import state
from state import SymbolState

console = Console()
_SESSION_STARTED_MONOTONIC = time.monotonic()

_EMPHASIS = "bold underline"
_COLUMN_MIN_WIDTHS = {
    "Book": 23,
    "Drift C/T/B": 15,
}
_SYMBOL_PALETTE = (
    "#ff5fd7",  # magenta
    "#4da3ff",  # blue
    "#ff8000",  # orange
    "#80ff00",  # chartreuse
    "#f8ceb1",  # orange
    "#c0c0c0",  # silver
    "#ff87d7",  # pink
)
_SYMBOL_COLORS = {
    sym.lower(): _SYMBOL_PALETTE[idx % len(_SYMBOL_PALETTE)]
    for idx, sym in enumerate(config.WATCHLIST)
}


# ------------------------------------------------------------------ #
# Formatting helpers

def _emphasis(style: str = "") -> str:
    return f"{_EMPHASIS} {style}".strip()


def _symbol_style(sym: str) -> str:
    key = sym.lower()
    color = _SYMBOL_COLORS.get(key)
    if color is None:
        color = _SYMBOL_PALETTE[sum(ord(ch) for ch in key) % len(_SYMBOL_PALETTE)]
    return _emphasis(color)


def _fmt_symbol(sym: str, suffix: str = "") -> Text:
    return Text(f"{sym.upper()}{suffix}", style=_symbol_style(sym))


def _fmt_runtime() -> str:
    elapsed = int(time.monotonic() - _SESSION_STARTED_MONOTONIC)
    hours, rem = divmod(elapsed, 3_600)
    mins, secs = divmod(rem, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _signed(val: float, decimals: int = 2, suffix: str = "") -> Text:
    s = f"{val:+.{decimals}f}{suffix}"
    style = "green" if val > 0 else "red" if val < 0 else "dim"
    return Text(s, style=style)


def _fmt_funding(pct: float) -> Text:
    s = f"{pct:+.4f}%"
    if pct > config.ALERT_FUNDING_PCT:
        return Text(s, style=_emphasis("red"))
    if pct < -config.ALERT_FUNDING_PCT:
        return Text(s, style=_emphasis("green"))
    return Text(s, style="white")


def _fmt_cvd(val: float) -> Text:
    """CVD colored from a sniping lens: red = aggressive buying (crowded longs),
    green = aggressive selling (potential exhaustion / reversal setup)."""
    if abs(val) >= 1_000_000:
        s = f"{val / 1_000_000:+.2f}M"
    else:
        s = f"{val / 1_000:+.1f}k"
    # Inverted from conventional: positive CVD is a crowded-long warning
    style = "red" if val > 0 else "green" if val < 0 else "dim"
    return Text(s, style=style)


def _fmt_usd_short(val: float | None) -> str:
    if val is None:
        return "-"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:.2f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.1f}k"
    return f"{sign}${abs_val:.0f}"


def _fmt_taker_pct(pct: float | None) -> Text:
    if pct is None:
        return Text("-", style="dim")
    s = f"{pct:.1f}%"
    if pct >= config.ALERT_TAKER_HIGH_PCT:
        return Text(s, style=_emphasis("red"))    # crowded buying
    if pct <= config.ALERT_TAKER_LOW_PCT:
        return Text(s, style=_emphasis("green"))  # crowded selling
    if pct >= 55:
        return Text(s, style="red")
    if pct <= 45:
        return Text(s, style="green")
    return Text(s, style="dim")             # balanced


def _fmt_funding_stack(st: SymbolState) -> Text:
    text = Text()
    text.append_text(_fmt_funding(st.funding * 100))
    delta = st.funding_delta_pct()
    text.append(" / ", style="dim")
    if delta is None:
        text.append("-", style="dim")
    else:
        style = "red" if delta > 0 else "green" if delta < 0 else "dim"
        text.append(f"{delta:+.4f}", style=style)
    return text


def _fmt_basis(st: SymbolState) -> Text:
    text = _signed(st.basis_pct, 3, "")
    if st.basis_source == "oracle":
        text.append(" o", style=_emphasis("dim"))
    return text


def _fmt_24h(st: SymbolState) -> Text:
    change = st.prev_day_change_pct
    return _signed(change, 2, "%") if change is not None else Text("-", style="dim")


def _fmt_oi_vol(st: SymbolState) -> Text:
    ratio = st.oi_volume_ratio
    if ratio is None:
        return Text("-", style="dim")
    style = _emphasis("red") if ratio >= 2.0 else "yellow" if ratio >= 1.0 else "dim"
    return Text(f"{ratio:.2f}x", style=style)


def _fmt_vol(st: SymbolState, window_ms: int = 900_000) -> Text:
    vol = st.realized_vol_pct(window_ms)
    if vol is None:
        return Text("-", style="dim")
    style = "red" if vol >= 1.0 else "yellow" if vol >= 0.5 else "dim"
    return Text(f"{vol:.2f}%", style=style)


def _fmt_cvd_stack(st: SymbolState) -> Text:
    text = Text()
    for idx, val in enumerate((
        st.trades_1m.cvd(),
        st.trades_5m.cvd(),
        st.trades_15m.cvd(),
    )):
        if idx:
            text.append(" / ", style="dim")
        text.append_text(_fmt_cvd(val))
    return text


def _fmt_avg_trade(st: SymbolState) -> Text:
    avg = st.trades_5m.average_trade_notional()
    if avg is None:
        return Text("-", style="dim")
    style = "yellow" if avg >= 50_000 else "dim"
    return Text(_fmt_usd_short(avg), style=style)


def _fmt_book(st: SymbolState) -> Text:
    spread = st.book_spread_bps
    imb = st.book_imbalance_pct
    if spread is None or imb is None:
        return Text("-", style="dim")
    spread_style = "red" if spread >= 5 else "yellow" if spread >= 2 else "dim"
    imb_style = "green" if imb > 0 else "red" if imb < 0 else "dim"
    text = Text(f"{spread:.1f}bp", style=spread_style)
    text.append(" / ", style="dim")
    text.append(f"{imb:+.0f}%", style=imb_style)
    if st.wall_ratio >= 2.5:
        text.append(f" {st.wall_side}{st.wall_ratio:.1f}x", style="yellow")
    return text


def _fmt_impact(st: SymbolState, sym: str = "") -> Text:
    impact = st.impact_excess_bps
    if impact is None:
        return Text("-", style="dim")
    threshold = config.ALERT_IMPACT_EXCESS_BPS_OVERRIDES.get(sym, config.ALERT_IMPACT_EXCESS_BPS)
    style = (
        _emphasis("red")
        if impact >= threshold
        else "yellow" if impact >= threshold / 2
        else "dim"
    )
    return Text(f"{impact:.1f}bp", style=style)


def _fmt_flow_cluster(st: SymbolState) -> Text:
    if not st.mark:
        return Text("-", style="dim")
    clusters = st.taker_flow_clusters()
    if not clusters:
        return Text("-", style="dim")
    top = clusters[0]
    dist = (top["price"] - st.mark) / st.mark * 100
    arrow = "↑" if dist >= 0 else "↓"
    side = "B" if top["buy"] >= top["sell"] else "S"
    style = "red" if side == "B" else "green"
    return Text(
        f"{abs(dist):.2f}% {arrow}{side} {_fmt_usd_short(top['notional'])}",
        style=style,
    )


def _btc_symbol() -> str | None:
    for sym in config.WATCHLIST:
        if sym.upper().startswith("BTC"):
            return sym
    return None


def _fmt_beta_corr(sym: str, st: SymbolState) -> Text:
    btc = _btc_symbol()
    if btc is None or sym == btc:
        return Text("base", style="dim")
    stats = st.beta_correlation(state[btc])
    if stats is None:
        return Text("-", style="dim")
    beta, corr = stats
    corr_style = "red" if corr >= 0.6 else "green" if corr <= 0.2 else "yellow"
    return Text(f"{beta:.2f}/{corr:.2f}", style=corr_style)


def _fmt_top_cluster(st: SymbolState) -> Text:
    """Largest 1h liq cluster: distance from mark + direction + dominant side.

    ↑L = cluster above, longs wiped (resistance on retest)
    ↓S = cluster below, shorts wiped (support on retest)
    Arrow alone without matching side gets yellow (unusual configuration).
    """
    if not config.LIQUIDATION_FEED_ENABLED:
        return Text("off", style="dim")
    if not st.mark:
        return Text("-", style="dim")
    clusters = st.liq_clusters(window_ms=3_600_000, min_count=2)
    if not clusters:
        return Text("-", style="dim")

    top  = clusters[0]
    dist = (top["price"] - st.mark) / st.mark * 100  # + = above, - = below
    above    = dist >= 0
    dominant = "L" if top["longs"] >= top["shorts"] else "S"
    arrow    = "↑" if above else "↓"
    label    = f"{abs(dist):.2f}% {arrow}{dominant}"

    if above and dominant == "L":
        style = "red"     # wiped longs overhead = resistance
    elif not above and dominant == "S":
        style = "green"   # wiped shorts below = support
    else:
        style = "yellow"  # cross-grain cluster (shorts above / longs below)
    return Text(label, style=style)


def _fmt_drift(last_ts: int, warn_ms: int = 2_000, stale_ms: int = 5_000) -> Text:
    if not last_ts:
        return Text("-", style="dim")
    ms = int(time.time() * 1000) - last_ts
    style = "red" if ms > stale_ms else "yellow" if ms > warn_ms else "dim"
    if ms >= 60_000:
        value = f"{ms / 60_000:.1f}m"
    elif ms >= 1_000:
        value = f"{ms / 1_000:.1f}s"
    else:
        value = str(ms)
    return Text(value, style=style)


def _fmt_drift_stack(st: SymbolState) -> Text:
    text = Text()
    for idx, part in enumerate((
        _fmt_drift(st.last_context_ts),
        _fmt_drift(st.last_trade_ts, warn_ms=60_000, stale_ms=300_000),
        _fmt_drift(st.last_book_ts),
    )):
        if idx:
            text.append("/", style="dim")
        text.append_text(part)
    return text


def _fmt_liq_vol(usd: float) -> Text:
    if not usd:
        return Text("-", style="dim")
    if usd >= config.ALERT_LIQ_VOL_5M_USD:
        return Text(f"${usd:,.0f}", style=_emphasis("red"))
    return Text(f"${usd:,.0f}", style="white")


def _flow_cluster_window_label() -> str:
    window_ms = config.TAKER_CLUSTER_WINDOW_MS
    if window_ms <= 0:
        return "session"
    if window_ms % 3_600_000 == 0:
        return f"{window_ms // 3_600_000}h"
    if window_ms % 60_000 == 0:
        return f"{window_ms // 60_000}m"
    return f"{window_ms / 1000:.0f}s"


# ------------------------------------------------------------------ #
# Panel builders

def _build_screener_table() -> Table:
    now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
    mins_to_funding = math.ceil((3_600 - (time.time() % 3_600)) / 60)
    t = Table(
        title=(
            "[bold underline]Hyperliquid USDC Perp Screener[/]  "
            f"[{now_utc} UTC | run {_fmt_runtime()} | funding in {mins_to_funding}m]"
        ),
        header_style=_emphasis("cyan"),
        border_style="dim",
        show_lines=False,
    )
    columns: list[tuple[str, JustifyMethod]] = [
        ("Symbol",      "left"),
        ("Mark $",      "right"),
        ("24h%",        "right"),
        ("Fund/FΔ1h",   "right"),
        ("Basis%",      "right"),
        ("Prem%",       "right"),
        ("OI Δ15m%",   "right"),
        ("OI/Vol",      "right"),
        ("σ15m",        "right"),
        ("CVD 1/5/15",  "right"),
        ("Taker5",      "right"),
        ("AvgTrd",      "right"),
        ("Book",        "right"),
        ("Impact",      "right"),
        ("Flow Clus",   "right"),
        ("β/ρ BTC",     "right"),
        ("Drift C/T/B", "right"),
    ]
    for name, justify in columns:
        t.add_column(name, justify=justify, min_width=_COLUMN_MIN_WIDTHS.get(name))

    for sym in config.WATCHLIST:
        st = state[sym]
        oi_d15 = st.oi_history.delta_pct(900_000)
        alerts.check(sym, st)

        t.add_row(
            _fmt_symbol(sym),
            f"{st.mark:,.4f}" if st.mark else Text("-", style="dim"),
            _fmt_24h(st),
            _fmt_funding_stack(st),
            _fmt_basis(st),
            _signed(st.premium_pct, 3, "%"),
            _signed(oi_d15, 2, "%") if oi_d15 is not None else Text("-", style="dim"),
            _fmt_oi_vol(st),
            _fmt_vol(st),
            _fmt_cvd_stack(st),
            _fmt_taker_pct(st.trades_5m.taker_pct()),
            _fmt_avg_trade(st),
            _fmt_book(st),
            _fmt_impact(st, sym),
            _fmt_flow_cluster(st),
            _fmt_beta_corr(sym, st),
            _fmt_drift_stack(st),
        )
    return t


_ALERT_STYLES: dict[str, str] = {
    "FUNDING":        "yellow",
    "LIQ_VOL":        _emphasis("red"),
    "OI_1H":          "magenta",
    "CLUSTER":        "cyan",
    "LONG_SQUEEZE":   _emphasis("red"),
    "SHORT_SQUEEZE":  _emphasis("green"),
    "CAPITULATION":   _emphasis("green"),
    "GRINDING_TRAP":  _emphasis("yellow"),
    "THIN_BOOK":      _emphasis("red"),
    "FLOW_CLUSTER":   "cyan",
}


_ALERT_DETAIL_LABEL_STYLES = {
    "Bias": "bold cyan",
    "Why": "bold white",
    "Evidence": "bold magenta",
}


def _format_alert_detail(message: str) -> Text:
    parts = message.split(" | ")
    detail = Text()
    for idx, part in enumerate(parts):
        if idx:
            detail.append(" | ", style="dim")
        label, sep, value = part.partition(": ")
        label_style = _ALERT_DETAIL_LABEL_STYLES.get(label)
        if sep and label_style:
            detail.append(f"{label}: ", style=label_style)
            detail.append(value, style="white")
        else:
            detail.append(part, style="white")
    return detail


def _build_alert_panel() -> Panel:
    recent = alerts.recent(10)
    if not recent:
        body = Text("No alerts.", style="dim")
    else:
        lines = []
        for a in recent:
            ts_str = datetime.fromtimestamp(a.ts, tz=timezone.utc).strftime("%H:%M:%S")
            kind_style = _ALERT_STYLES.get(a.kind, "white")
            line = Text.assemble(
                (f"[{ts_str}] ", "dim"),
                _fmt_symbol(a.sym, " "),
                (f"{a.kind} ",        kind_style),
            )
            line.append_text(_format_alert_detail(a.message))
            lines.append(line)
        body = Text("\n").join(lines)
    return Panel(body, title="[bold underline yellow]Alerts[/]", border_style="yellow")


def _build_cluster_panel() -> Panel:
    """Top-2 liq clusters or configured taker-flow clusters per symbol."""
    if not config.LIQUIDATION_FEED_ENABLED:
        lines = []
        for sym in config.WATCHLIST:
            st = state[sym]
            for c in st.taker_flow_clusters()[:2]:
                if not st.mark:
                    continue
                dominant = "BUY" if c["buy"] >= c["sell"] else "SELL"
                above = c["price"] > st.mark
                arrow = "↑" if above else "↓"
                style = "red" if dominant == "BUY" else "green"
                dist_pct = abs(c["price"] - st.mark) / st.mark * 100
                lines.append(Text.assemble(
                    _fmt_symbol(sym, " "),
                    (f"{arrow}{dominant[0]} ", style),
                    (f"@ {c['price']:,.4f}  ", "cyan"),
                    (f"{dist_pct:.2f}% away  ", "dim"),
                    (f"x{c['count']} ", "white"),
                    (_fmt_usd_short(c["notional"]), "white"),
                    (
                        f"  bucket {st.flow_cluster_bucket_pct():.2f}% "
                        f"{c.get('ref_source', 'ref')}",
                        "dim",
                    ),
                ))
        if not lines:
            lines = [
                Text(
                    "No taker-flow clusters yet (needs repeated aggressive flow in a vol-scaled bucket).",
                    style="dim",
                )
            ]
        return Panel(
            Text("\n").join(lines),
            title=f"[bold underline cyan]Flow Clusters ({_flow_cluster_window_label()})[/]",
            border_style="cyan",
        )

    lines = []
    for sym in config.WATCHLIST:
        for c in state[sym].liq_clusters(window_ms=3_600_000, min_count=2)[:2]:
            st        = state[sym]
            dominant  = "LONG" if c["longs"] >= c["shorts"] else "SHORT"
            above     = c["price"] > st.mark if st.mark else True
            arrow     = "↑" if above else "↓"
            style     = "red" if dominant == "LONG" else "green"
            dist_pct  = abs(c["price"] - st.mark) / st.mark * 100 if st.mark else 0
            lines.append(Text.assemble(
                _fmt_symbol(sym, " "),
                (f"{arrow}{dominant[0]} ",       style),
                (f"@ {c['price']:,.4f}  ",       "cyan"),
                (f"{dist_pct:.2f}% away  ",      "dim"),
                (f"×{c['count']} ",              "white"),
                (f"${c['notional']:,.0f}",        "white"),
            ))
    if not lines:
        lines = [Text("No clusters (need ≥2 liqs at same level in past 1h).", style="dim")]
    return Panel(
        Text("\n").join(lines),
        title="[bold underline cyan]Liq Clusters (1h)[/]",
        border_style="cyan",
    )


def _build_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_build_screener_table(), name="main",   ratio=3),
        Layout(name="bottom",                          ratio=1),
    )
    layout["bottom"].split_row(
        Layout(_build_alert_panel(),   name="alerts"),
        Layout(_build_cluster_panel(), name="clusters"),
    )
    return layout


# ------------------------------------------------------------------ #
# Render coroutine

async def render() -> None:
    interval = 1.0 / config.DASHBOARD_REFRESH_HZ
    with Live(
        _build_layout(),
        refresh_per_second=config.DASHBOARD_REFRESH_HZ,
        screen=True,
        console=console,
    ) as live:
        while True:
            live.update(_build_layout())
            await asyncio.sleep(interval)
