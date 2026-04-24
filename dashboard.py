"""Rich terminal dashboard — three-panel layout:
  Top:         main screener table (one row per symbol)
  Bottom-left: recent alerts
  Bottom-right: liquidation clusters (1h window)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from rich.console import Console
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


# ------------------------------------------------------------------ #
# Formatting helpers

def _signed(val: float, decimals: int = 2, suffix: str = "") -> Text:
    s = f"{val:+.{decimals}f}{suffix}"
    style = "green" if val > 0 else "red" if val < 0 else "dim"
    return Text(s, style=style)


def _fmt_funding(pct: float) -> Text:
    s = f"{pct:+.4f}%"
    if pct > config.ALERT_FUNDING_PCT:
        return Text(s, style="bold red")
    if pct < -config.ALERT_FUNDING_PCT:
        return Text(s, style="bold green")
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


def _fmt_taker_pct(pct: float | None) -> Text:
    if pct is None:
        return Text("-", style="dim")
    s = f"{pct:.1f}%"
    if pct >= config.ALERT_TAKER_HIGH_PCT:
        return Text(s, style="bold red")    # crowded buying
    if pct <= config.ALERT_TAKER_LOW_PCT:
        return Text(s, style="bold green")  # crowded selling
    if pct >= 55:
        return Text(s, style="red")
    if pct <= 45:
        return Text(s, style="green")
    return Text(s, style="dim")             # balanced


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


def _fmt_drift(last_ts: int) -> Text:
    if not last_ts:
        return Text("-", style="dim")
    ms = int(time.time() * 1000) - last_ts
    style = "red" if ms > 5000 else "yellow" if ms > 2000 else "dim"
    return Text(str(ms), style=style)


def _fmt_liq_vol(usd: float) -> Text:
    if not usd:
        return Text("-", style="dim")
    if usd >= config.ALERT_LIQ_VOL_5M_USD:
        return Text(f"${usd:,.0f}", style="bold red")
    return Text(f"${usd:,.0f}", style="white")


# ------------------------------------------------------------------ #
# Panel builders

def _build_screener_table() -> Table:
    now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
    t = Table(
        title=f"[bold]Hyperliquid USDC Perp Screener[/bold]  [{now_utc} UTC]",
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
    )
    for name, justify in [
        ("Symbol",      "left"),
        ("Mark $",      "right"),
        ("Funding%",    "right"),
        ("Basis%",      "right"),
        ("OI Δ15m%",   "right"),
        ("OI Δ1h%",    "right"),
        ("CVD 5m $",   "right"),
        ("Taker% 5m",  "right"),
        ("Top Cluster", "right"),
        ("Liqs 5m L/S", "right"),
        ("Liq $ 5m",    "right"),
        ("Drift ms",    "right"),
    ]:
        t.add_column(name, justify=justify)

    for sym in config.WATCHLIST:
        st = state[sym]
        funding_pct = st.funding * 100
        oi_d15 = st.oi_history.delta_pct(900_000)
        oi_d1h = st.oi_history.delta_pct(3_600_000)

        if config.LIQUIDATION_FEED_ENABLED:
            recent = st.recent_liqs(300_000)
            longs_liq  = sum(1 for _, s, _, _ in recent if s == "SELL")
            shorts_liq = sum(1 for _, s, _, _ in recent if s == "BUY")
            liq_usd    = sum(q * p for _, _, q, p in recent)
            liq_counts = Text.assemble(
                (str(longs_liq),  "red"),
                ("/",             "dim"),
                (str(shorts_liq), "green"),
            )
            liq_vol = _fmt_liq_vol(liq_usd)
        else:
            liq_counts = Text("off", style="dim")
            liq_vol = Text("off", style="dim")

        alerts.check(sym, st)

        t.add_row(
            f"[bold]{sym.upper()}[/bold]",
            f"{st.mark:,.4f}" if st.mark else Text("-", style="dim"),
            _fmt_funding(funding_pct),
            _signed(st.basis_pct, 3, "%"),
            _signed(oi_d15, 2, "%") if oi_d15 is not None else Text("-", style="dim"),
            _signed(oi_d1h, 2, "%") if oi_d1h is not None else Text("-", style="dim"),
            _fmt_cvd(st.trades_5m.cvd()),
            _fmt_taker_pct(st.trades_5m.taker_pct()),
            _fmt_top_cluster(st),
            liq_counts,
            liq_vol,
            _fmt_drift(st.last_event_ts),
        )
    return t


_ALERT_STYLES: dict[str, str] = {
    "FUNDING":       "yellow",
    "LIQ_VOL":       "bold red",
    "OI_1H":         "magenta",
    "CLUSTER":       "cyan",
    "LONG_SQUEEZE":  "bold red",
    "CAPITULATION":  "bold green",
    "GRINDING_TRAP": "bold yellow",
}


def _build_alert_panel() -> Panel:
    recent = alerts.recent(10)
    if not recent:
        body = Text("No alerts.", style="dim")
    else:
        lines = []
        for a in recent:
            ts_str = datetime.fromtimestamp(a.ts, tz=timezone.utc).strftime("%H:%M:%S")
            kind_style = _ALERT_STYLES.get(a.kind, "white")
            lines.append(Text.assemble(
                (f"[{ts_str}] ", "dim"),
                (f"{a.sym.upper()} ", "bold white"),
                (f"{a.kind} ",        kind_style),
                (a.message,           "white"),
            ))
        body = Text("\n").join(lines)
    return Panel(body, title="[bold yellow]Alerts[/bold yellow]", border_style="yellow")


def _build_cluster_panel() -> Panel:
    """Top-2 liq clusters per symbol over the past hour."""
    if not config.LIQUIDATION_FEED_ENABLED:
        return Panel(
            Text("Unavailable on the official public Hyperliquid market feed.", style="dim"),
            title="[bold cyan]Liq Clusters (1h)[/bold cyan]",
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
                (f"{sym.upper()} ",             "bold white"),
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
        title="[bold cyan]Liq Clusters (1h)[/bold cyan]",
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
