"""Hyperliquid USDC perpetual futures feed.

Public data only; no API key required.

WebSocket subscriptions consumed:
  activeAssetCtx  - mark price, funding rate, oracle price, open interest
  trades          - executed trades for CVD/taker flow
  l2Book          - top-of-book depth, spread, imbalance, resting walls
  allMids         - cross-asset mids for beta/correlation and spot-basis refresh

Info endpoint polled:
  metaAndAssetCtxs - current asset contexts across perpetual markets
  spotMetaAndAssetCtxs - spot markets used for true perp-vs-spot basis

Hyperliquid's official public market subscriptions do not expose a Binance
`!forceOrder@arr` equivalent, so liquidation-derived signals stay disabled
unless a separate liquidation source is added.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

import config
import persistence
from state import SymbolState

# Shared state - read by dashboard and alerts modules
state: dict[str, SymbolState] = defaultdict(SymbolState)

_QUOTE_SUFFIXES = ("USDC", "USDT", "USD")
_WARNED_MISSING: set[str] = set()
_WARNED_SPOT_FALLBACK: set[str] = set()
_SPOT_COIN_TO_SYMBOL: dict[str, str] = {}


# ------------------------------------------------------------------ #
# Symbol helpers

def _coin_from_watch_symbol(sym: str) -> str:
    value = sym.strip()
    upper = value.upper()

    for sep in ("-", "/", "_"):
        if sep in upper:
            base, suffix = upper.rsplit(sep, 1)
            if suffix in _QUOTE_SUFFIXES or suffix == "PERP":
                return base

    for suffix in (*_QUOTE_SUFFIXES, "PERP"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]

    return upper


_SYMBOL_BY_COIN = {
    # Hyperliquid perps use the coin name ("BTC"), while the local config keeps
    # the quote suffix visible ("btc-usdc").
    coin.upper(): sym
    for sym in config.WATCHLIST
    if (coin := _coin_from_watch_symbol(sym))
}


def _symbol_for_coin(coin: str | None) -> str | None:
    if not coin:
        return None
    return _SYMBOL_BY_COIN.get(coin.upper())


def _watch_coins() -> list[str]:
    return list(_SYMBOL_BY_COIN.keys())


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _asset_ctx_payload() -> dict[str, str]:
    payload = {"type": "metaAndAssetCtxs"}
    if config.HYPERLIQUID_DEX:
        payload["dex"] = config.HYPERLIQUID_DEX
    return payload


def _spot_asset_ctx_payload() -> dict[str, str]:
    return {"type": "spotMetaAndAssetCtxs"}


def _canonical_spot_base(base: str | None) -> str:
    if not base:
        return ""
    upper = base.upper()
    if upper in _SYMBOL_BY_COIN:
        return upper
    if upper.startswith("U") and upper[1:] in _SYMBOL_BY_COIN:
        return upper[1:]
    if upper.endswith("0") and upper[:-1] in _SYMBOL_BY_COIN:
        return upper[:-1]
    return upper


# ------------------------------------------------------------------ #
# Message handlers

def _apply_asset_ctx(
    coin: str | None,
    ctx: dict[str, Any],
    ts_ms: int | None = None,
    force_oi_sample: bool = False,
) -> None:
    sym = _symbol_for_coin(coin)
    if sym is None:
        return

    ts_ms = ts_ms or int(time.time() * 1000)
    st = state[sym]

    mark = _to_float(ctx.get("markPx") or ctx.get("midPx"))
    if mark:
        st.mark = mark

    mid = _to_float(ctx.get("midPx"))
    if mid:
        st.mid = mid

    if "funding" in ctx:
        st.record_funding(ts_ms, _to_float(ctx.get("funding")))

    oracle = _to_float(ctx.get("oraclePx"))
    if oracle:
        st.oracle = oracle

    if "dayNtlVlm" in ctx:
        st.day_ntl_vlm = _to_float(ctx.get("dayNtlVlm"))

    if "premium" in ctx and ctx.get("premium") is not None:
        st.premium = _to_float(ctx.get("premium"))

    if "prevDayPx" in ctx:
        st.prev_day_px = _to_float(ctx.get("prevDayPx"))

    impact = ctx.get("impactPxs")
    if isinstance(impact, list) and len(impact) >= 2:
        st.impact_bid_px = _to_float(impact[0])
        st.impact_ask_px = _to_float(impact[1])

    if "openInterest" in ctx:
        min_interval_ms = None if force_oi_sample else config.OI_POLL_INTERVAL * 1000
        st.record_oi(ts_ms, _to_float(ctx.get("openInterest")), min_interval_ms)

    if mark:
        st.record_mark(ts_ms)


def _handle_trade(trade: dict[str, Any]) -> None:
    sym = _symbol_for_coin(trade.get("coin"))
    if sym is None:
        return

    side = str(trade.get("side", "")).upper()
    if side not in {"A", "B"}:
        return

    ts_ms = int(trade.get("time") or time.time() * 1000)
    qty = _to_float(trade.get("sz"))
    price = _to_float(trade.get("px"))
    if qty <= 0 or price <= 0:
        return

    # Hyperliquid trade side is the aggressing side: B = buy, A = sell.
    state[sym].add_trade(
        ts_ms=ts_ms,
        is_buyer_maker=(side == "A"),
        qty=qty,
        price=price,
    )
    persistence.enqueue_trade(
        ts_ms=ts_ms,
        sym=sym,
        side="SELL" if side == "A" else "BUY",
        qty=qty,
        price=price,
        raw=trade,
    )

    liquidation = trade.get("liquidation")
    if isinstance(liquidation, dict):
        liq_side = "SELL" if side == "A" else "BUY"
        state[sym].add_liq(
            ts_ms=ts_ms,
            side=liq_side,
            qty=qty,
            price=price,
        )
        persistence.enqueue_liquidation(
            ts_ms=ts_ms,
            sym=sym,
            side=liq_side,
            qty=qty,
            price=price,
            raw=trade,
        )


def _handle_l2_book(data: dict[str, Any]) -> None:
    sym = _symbol_for_coin(data.get("coin"))
    if sym is None:
        return

    levels = data.get("levels")
    if not (
        isinstance(levels, list)
        and len(levels) >= 2
        and isinstance(levels[0], list)
        and isinstance(levels[1], list)
    ):
        return

    state[sym].record_book(
        ts_ms=int(data.get("time") or time.time() * 1000),
        bids=levels[0],
        asks=levels[1],
    )


def _handle_all_mids(data: dict[str, Any]) -> None:
    mids = data.get("mids") if isinstance(data.get("mids"), dict) else data
    if not isinstance(mids, dict):
        return

    ts_ms = int(time.time() * 1000)
    for coin, raw_mid in mids.items():
        mid = _to_float(raw_mid)
        sym = _symbol_for_coin(str(coin))
        if sym is not None:
            state[sym].record_mid(ts_ms, mid)
            continue

        spot_sym = _SPOT_COIN_TO_SYMBOL.get(str(coin))
        if spot_sym is not None:
            state[spot_sym].record_hl_spot(str(coin), mid)


def _handle(msg: dict[str, Any]) -> None:
    channel = msg.get("channel")
    data = msg.get("data")

    if channel in {"subscriptionResponse", "pong"}:
        return

    if channel == "activeAssetCtx" and isinstance(data, dict):
        _apply_asset_ctx(data.get("coin"), data.get("ctx") or {})
        return

    if channel == "trades":
        trades = data if isinstance(data, list) else [data]
        for trade in trades:
            if isinstance(trade, dict):
                _handle_trade(trade)
        return

    if channel == "l2Book" and isinstance(data, dict):
        _handle_l2_book(data)
        return

    if channel == "allMids" and isinstance(data, dict):
        _handle_all_mids(data)


# ------------------------------------------------------------------ #
# WebSocket coroutine

async def _run_subscription_ws(
    subscriptions: list[dict[str, Any]], label: str
) -> None:
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(
                config.WS_URL, ping_interval=20, ping_timeout=20
            ) as ws:
                for subscription in subscriptions:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": subscription,
                    }))

                backoff = 1.0  # reset on successful connect
                async for raw in ws:
                    try:
                        _handle(json.loads(raw))
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
    market_subs = [
        {"type": "activeAssetCtx", "coin": coin}
        for coin in _watch_coins()
    ]
    trade_subs = [
        {"type": "trades", "coin": coin}
        for coin in _watch_coins()
    ]
    book_subs = [
        {"type": "l2Book", "coin": coin}
        for coin in _watch_coins()
    ]
    all_mids_subs = [{"type": "allMids"}]

    await asyncio.gather(
        _run_subscription_ws(market_subs, "market-core"),
        _run_subscription_ws(trade_subs, "trades"),
        _run_subscription_ws(book_subs, "l2-book"),
        _run_subscription_ws(all_mids_subs, "all-mids"),
    )


# ------------------------------------------------------------------ #
# Info polling coroutine

async def _poll_asset_contexts(
    client: httpx.AsyncClient, force_oi_sample: bool = True
) -> None:
    response = await client.post(config.INFO_URL, json=_asset_ctx_payload())
    response.raise_for_status()
    meta, contexts = response.json()

    found: set[str] = set()
    for asset, ctx in zip(meta.get("universe", []), contexts, strict=False):
        coin = asset.get("name")
        sym = _symbol_for_coin(coin)
        if sym is None or asset.get("isDelisted"):
            continue
        found.add(str(coin).upper())
        _apply_asset_ctx(coin, ctx, force_oi_sample=force_oi_sample)

    missing = set(_SYMBOL_BY_COIN) - found
    new_missing = missing - _WARNED_MISSING
    if new_missing:
        print(
            "[INFO] watchlist coin(s) not found on Hyperliquid: "
            + ", ".join(sorted(new_missing))
        )
        _WARNED_MISSING.update(new_missing)


def _apply_spot_contexts(meta: dict[str, Any], contexts: list[dict[str, Any]]) -> None:
    tokens = {
        token.get("index"): str(token.get("name", "")).upper()
        for token in meta.get("tokens", [])
        if isinstance(token, dict)
    }
    universe = {
        str(asset.get("name")): asset
        for asset in meta.get("universe", [])
        if isinstance(asset, dict)
    }

    found: set[str] = set()
    _SPOT_COIN_TO_SYMBOL.clear()
    for ctx in contexts:
        if not isinstance(ctx, dict):
            continue
        spot_coin = str(ctx.get("coin") or "")
        asset = universe.get(spot_coin)
        if not asset:
            continue

        asset_tokens = asset.get("tokens")
        if not isinstance(asset_tokens, list) or len(asset_tokens) < 2:
            continue
        quote = tokens.get(asset_tokens[1], "")
        if quote != "USDC":
            continue

        base = _canonical_spot_base(tokens.get(asset_tokens[0], ""))
        sym = _SYMBOL_BY_COIN.get(base)
        if sym is None:
            continue

        spot_px = _to_float(ctx.get("midPx") or ctx.get("markPx"))
        if not spot_px:
            continue

        _SPOT_COIN_TO_SYMBOL[spot_coin] = sym
        state[sym].record_hl_spot(spot_coin, spot_px)
        found.add(base)

    missing = set(_SYMBOL_BY_COIN) - found
    new_missing = missing - _WARNED_SPOT_FALLBACK
    if new_missing:
        print(
            "[INFO] no Hyperliquid spot market for watchlist coin(s); "
            "using oracle basis fallback: " + ", ".join(sorted(new_missing))
        )
        _WARNED_SPOT_FALLBACK.update(new_missing)


async def _poll_spot_contexts(client: httpx.AsyncClient) -> None:
    response = await client.post(config.INFO_URL, json=_spot_asset_ctx_payload())
    response.raise_for_status()
    meta, contexts = response.json()
    _apply_spot_contexts(meta, contexts)


async def poll_rest() -> None:
    """Poll current asset contexts every OI_POLL_INTERVAL seconds."""
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                await _poll_asset_contexts(client)
                await _poll_spot_contexts(client)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[INFO] {type(e).__name__}: {e}")

            await asyncio.sleep(config.OI_POLL_INTERVAL)
