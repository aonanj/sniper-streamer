from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import persistence


app = FastAPI(
    title="sniper-streamer API",
    version="0.1.0",
    description="Read-only live signal API for margin-sniping context.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Authorization", "X-API-Token", "Content-Type"],
)


async def require_api_token(
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
) -> None:
    """Validate optional bearer or X-API-Token authentication."""
    if not config.API_TOKEN:
        return

    bearer = f"Bearer {config.API_TOKEN}"
    if authorization == bearer or x_api_token == config.API_TOKEN:
        return

    raise HTTPException(status_code=401, detail="Invalid API token")


@app.get("/api/health", dependencies=[Depends(require_api_token)])
async def health() -> dict:
    """Return service and persistence health."""
    health_payload = await persistence.fetch_health()
    storage_report = await persistence.fetch_latest_storage_report()
    if storage_report is not None:
        health_payload["storage"] = storage_report
    return health_payload


@app.get("/api/symbols", dependencies=[Depends(require_api_token)])
async def symbols() -> dict:
    """Return the latest persisted snapshot for each watched symbol."""
    return {"symbols": await persistence.fetch_latest_symbols()}


@app.get("/api/signals", dependencies=[Depends(require_api_token)])
async def signals() -> dict:
    """Return current active structured signals across the watchlist."""
    return {"signals": await persistence.fetch_latest_signals()}


@app.get("/api/signals/{symbol}", dependencies=[Depends(require_api_token)])
async def symbol_signals(symbol: str) -> dict:
    """Return current active structured signals for one symbol."""
    normalized = symbol.lower()
    if normalized not in config.WATCHLIST:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Unknown symbol: {symbol}"},
        )
    return {
        "symbol": normalized,
        "signals": await persistence.fetch_latest_signals(normalized),
    }


@app.get("/api/storage", dependencies=[Depends(require_api_token)])
async def storage() -> dict:
    """Return the latest persisted storage-size report."""
    return {"storage": await persistence.fetch_latest_storage_report()}


@app.websocket("/ws/signals")
async def signals_ws(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    header_token = websocket.headers.get("x-api-token")
    bearer = websocket.headers.get("authorization")
    if config.API_TOKEN and not (
        token == config.API_TOKEN
        or header_token == config.API_TOKEN
        or bearer == f"Bearer {config.API_TOKEN}"
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {"signals": await persistence.fetch_latest_signals()}
            )
            await asyncio.sleep(config.API_POLL_INTERVAL_SEC)
    except asyncio.CancelledError:
        raise
    except Exception:
        await websocket.close()
