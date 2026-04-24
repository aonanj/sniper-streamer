"""Binance USDT-M futures feed — WebSocket ingestion and REST polling.

Public streams only; no API key required.

WS streams consumed:
  <sym>@markPrice@1s   — mark price + predicted funding rate
  <sym>@aggTrade       — aggregated trades (for CVD)
  !forceOrder@arr      — all-market liquidation orders (throttled to 1/sym/s)

REST endpoints polled:
  /fapi/v1/openInterest            — current open interest (coins)
  /futures/data/openInterestHist   — 5-min bucketed OI history (seeded on startup)
  api.binance.com/api/v3/ticker/price  — spot price for basis calc
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

import config
from state import SymbolState

# Shared state — read by dashboard and alerts modules
state: dict[str, SymbolState] = defaultdict(SymbolState)


# ------------------------------------------------------------------ #
# Message handlers

def _handle(stream: str, data: dict) -> None:
    stream_key = stream.lower()

    if "markprice" in stream_key:
        sym = data.get("s", "").lower()
        if sym not in config.WATCHLIST:
            return
        st = state[sym]
        st.mark            = float(data["p"])
        st.funding         = float(data["r"])
        st.next_funding_ts = int(data["T"])
        st.record_mark(int(data["E"]))

    elif "aggtrade" in stream_key:
        sym = data.get("s", "").lower()
        if sym not in config.WATCHLIST:
            return
        state[sym].add_trade(
            ts_ms=int(data["T"]),
            is_buyer_maker=bool(data["m"]),
            qty=float(data["q"]),
            price=float(data["p"]),
        )

    elif stream_key == "!forceorder@arr":
        o = data.get("o", {})
        sym = o.get("s", "").lower()
        if sym not in config.WATCHLIST:
            return
        # ap = average fill price; fall back to order price p if missing/zero
        price = float(o.get("ap") or o.get("p") or 0)
        if price:
            state[sym].add_liq(
                ts_ms=int(o["T"]),
                side=o["S"],
                qty=float(o["q"]),
                price=price,
            )

# ------------------------------------------------------------------ #
# WebSocket coroutine

async def _run_combined_ws(streams: list[str], label: str) -> None:
    url = f"{config.WS_URL}?streams={'/'.join(streams)}"

    backoff = 1.0
    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=20
            ) as ws:
                backoff = 1.0  # reset on successful connect
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        _handle(msg.get("stream", ""), msg.get("data", {}))
                    except Exception:
                        pass  # never let a bad message kill the connection
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            pass  # reconnect immediately on clean close
        except Exception as e:
            print(f"[WS {label}] {type(e).__name__}: {e}  retrying in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def run_ws() -> None:
    core_streams = []
    trade_streams = []
    for sym in config.WATCHLIST:
        core_streams.append(f"{sym}@markPrice@1s")
        trade_streams.append(f"{sym}@aggTrade")
    core_streams.append("!forceOrder@arr")

    await asyncio.gather(
        _run_combined_ws(core_streams, "market-core"),
        _run_combined_ws(trade_streams, "trades"),
    )


# ------------------------------------------------------------------ #
# REST polling coroutine

async def _seed_oi_history(client: httpx.AsyncClient) -> None:
    """Pre-load 12 hours of OI history so delta metrics are available immediately."""
    for sym in config.WATCHLIST:
        try:
            r = await client.get(
                f"{config.REST_BASE}/futures/data/openInterestHist",
                params={"symbol": sym.upper(), "period": "5m", "limit": 144},
            )
            for entry in r.json():
                state[sym].oi_history.record(
                    int(entry["timestamp"]),
                    float(entry["sumOpenInterest"]),
                )
        except Exception as e:
            print(f"[SEED OI] {sym}: {e}")


async def poll_rest() -> None:
    """Poll OI and spot price every OI_POLL_INTERVAL seconds."""
    async with httpx.AsyncClient(timeout=10) as client:
        await _seed_oi_history(client)
        while True:
            ts_now = int(time.time() * 1000)
            for sym in config.WATCHLIST:
                try:
                    r = await client.get(
                        f"{config.REST_BASE}/fapi/v1/openInterest",
                        params={"symbol": sym.upper()},
                    )
                    oi = float(r.json()["openInterest"])
                    st = state[sym]
                    st.oi = oi
                    st.oi_history.record(ts_now, oi)

                    r2 = await client.get(
                        f"{config.SPOT_BASE}/api/v3/ticker/price",
                        params={"symbol": sym.upper()},
                    )
                    st.spot = float(r2.json()["price"])
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[REST] {sym}: {e}")

            await asyncio.sleep(config.OI_POLL_INTERVAL)
