from __future__ import annotations

import asyncio
import json
import math
import queue
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import config

if TYPE_CHECKING:
    from state import SymbolState


@dataclass(slots=True)
class PersistEvent:
    kind: str
    payload: dict[str, Any]


_EVENTS: queue.Queue[PersistEvent] = queue.Queue()
_last_snapshot_by_symbol: dict[str, tuple[int, float | None]] = {}


def enqueue_trade(
    *,
    ts_ms: int,
    sym: str,
    side: str,
    qty: float,
    price: float,
    raw: dict[str, Any],
) -> None:
    _EVENTS.put_nowait(
        PersistEvent(
            "trade",
            {
                "ts_ms": ts_ms,
                "ts_utc": _ts_utc(ts_ms),
                "symbol": sym,
                "side": side,
                "qty": _finite(qty),
                "price": _finite(price),
                "notional": _finite(qty * price),
                "raw": raw,
            },
        )
    )


def enqueue_liquidation(
    *,
    ts_ms: int,
    sym: str,
    side: str,
    qty: float,
    price: float,
    raw: dict[str, Any],
) -> None:
    _EVENTS.put_nowait(
        PersistEvent(
            "liquidation",
            {
                "ts_ms": ts_ms,
                "ts_utc": _ts_utc(ts_ms),
                "symbol": sym,
                "side": side,
                "qty": _finite(qty),
                "price": _finite(price),
                "notional": _finite(qty * price),
                "raw": raw,
            },
        )
    )


def enqueue_alert(
    *,
    ts_ms: int,
    sym: str,
    kind: str,
    message: str,
    snapshot: dict[str, Any],
) -> None:
    _EVENTS.put_nowait(
        PersistEvent(
            "alert",
            {
                "ts_ms": ts_ms,
                "ts_utc": _ts_utc(ts_ms),
                "symbol": sym,
                "kind": kind,
                "message": message,
                "snapshot": snapshot,
            },
        )
    )


def enqueue_snapshot_if_due(sym: str, st: SymbolState, ts_ms: int | None = None) -> bool:
    if not st.last_event_ts:
        return False

    ts_ms = ts_ms or int(time.time() * 1000)
    snapshot = state_snapshot(sym, st, ts_ms)
    funding_pct = snapshot.get("funding_pct")
    last = _last_snapshot_by_symbol.get(sym)

    due = last is None
    if last is not None:
        last_ts, last_funding_pct = last
        enough_time = ts_ms - last_ts >= config.PERSIST_SNAPSHOT_MIN_INTERVAL_MS
        funding_changed = (
            isinstance(funding_pct, float)
            and isinstance(last_funding_pct, float)
            and abs(funding_pct - last_funding_pct)
            >= config.PERSIST_SNAPSHOT_FUNDING_DELTA_PCT
        )
        due = enough_time or funding_changed

    if not due:
        return False

    _last_snapshot_by_symbol[sym] = (
        ts_ms,
        funding_pct if isinstance(funding_pct, float) else None,
    )
    _EVENTS.put_nowait(PersistEvent("snapshot", snapshot))
    return True


def state_snapshot(sym: str, st: SymbolState, ts_ms: int | None = None) -> dict[str, Any]:
    ts_ms = ts_ms or int(time.time() * 1000)
    liq_notional_5m = sum(qty * price for _, _, qty, price in st.recent_liqs(300_000))

    return {
        "ts_ms": ts_ms,
        "ts_utc": _ts_utc(ts_ms),
        "symbol": sym,
        "mark": _finite(st.mark),
        "mid": _finite(st.mid),
        "funding": _finite(st.funding),
        "funding_pct": _finite(st.funding * 100),
        "funding_delta_1h_pct": _finite(st.funding_delta_pct()),
        "oracle": _finite(st.oracle),
        "hl_spot": _finite(st.hl_spot),
        "basis_pct": _finite(st.basis_pct),
        "basis_source": st.basis_source,
        "premium_pct": _finite(st.premium_pct),
        "oi": _finite(st.oi),
        "oi_notional": _finite(st.oi_notional),
        "day_ntl_vlm": _finite(st.day_ntl_vlm),
        "prev_day_change_pct": _finite(st.prev_day_change_pct),
        "cvd_1m": _finite(st.trades_1m.cvd()),
        "cvd_5m": _finite(st.trades_5m.cvd()),
        "cvd_15m": _finite(st.trades_15m.cvd()),
        "cvd_1h": _finite(st.trades_1h.cvd()),
        "taker_buy_pct_5m": _finite(st.trades_5m.taker_pct()),
        "taker_notional_5m": _finite(st.trades_5m.total_notional()),
        "avg_trade_notional_5m": _finite(st.trades_5m.average_trade_notional()),
        "best_bid": _finite(st.best_bid),
        "best_ask": _finite(st.best_ask),
        "book_spread_bps": _finite(st.book_spread_bps),
        "book_imbalance_pct": _finite(st.book_imbalance_pct),
        "bid_depth10": _finite(st.bid_depth10),
        "ask_depth10": _finite(st.ask_depth10),
        "impact_excess_bps": _finite(st.impact_excess_bps),
        "wall_side": st.wall_side,
        "wall_px": _finite(st.wall_px),
        "wall_notional": _finite(st.wall_notional),
        "wall_ratio": _finite(st.wall_ratio),
        "wall_dist_bps": _finite(st.wall_dist_bps),
        "liq_notional_5m": _finite(liq_notional_5m),
        "last_context_ts_ms": st.last_context_ts or None,
        "last_trade_ts_ms": st.last_trade_ts or None,
        "last_book_ts_ms": st.last_book_ts or None,
        "last_event_ts_ms": st.last_event_ts or None,
    }


async def run_persistence(states: Mapping[str, SymbolState]) -> None:
    writer = SQLiteWriter(Path(config.SQLITE_PATH))
    await asyncio.to_thread(writer.open)
    try:
        await asyncio.to_thread(writer.initialize)
        await asyncio.to_thread(writer.purge_stale)

        pending: list[PersistEvent] = []
        last_snapshot_scan = 0.0
        last_purge = time.monotonic()

        while True:
            now = time.monotonic()
            if now - last_snapshot_scan >= config.PERSIST_SNAPSHOT_SCAN_INTERVAL_SEC:
                ts_ms = int(time.time() * 1000)
                for sym in config.WATCHLIST:
                    st = states.get(sym)
                    if st is not None:
                        enqueue_snapshot_if_due(sym, st, ts_ms)
                last_snapshot_scan = now

            if not pending:
                pending = _drain_events(config.PERSIST_BATCH_SIZE)

            if pending:
                try:
                    await asyncio.to_thread(writer.write_batch, pending)
                    pending = []
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f"[DB] {type(exc).__name__}: {exc}  retrying write")
                    await asyncio.sleep(config.PERSIST_FLUSH_INTERVAL_SEC)
                    continue
            else:
                await asyncio.sleep(config.PERSIST_FLUSH_INTERVAL_SEC)

            if now - last_purge >= config.PERSIST_PURGE_INTERVAL_SEC:
                await asyncio.to_thread(writer.purge_stale)
                last_purge = now
    finally:
        await asyncio.to_thread(writer.close)


class SQLiteWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA temp_store=MEMORY")

    def initialize(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                mark REAL,
                mid REAL,
                funding REAL,
                funding_pct REAL,
                funding_delta_1h_pct REAL,
                oracle REAL,
                hl_spot REAL,
                basis_pct REAL,
                basis_source TEXT,
                premium_pct REAL,
                oi REAL,
                oi_notional REAL,
                day_ntl_vlm REAL,
                prev_day_change_pct REAL,
                cvd_1m REAL,
                cvd_5m REAL,
                cvd_15m REAL,
                cvd_1h REAL,
                taker_buy_pct_5m REAL,
                taker_notional_5m REAL,
                avg_trade_notional_5m REAL,
                best_bid REAL,
                best_ask REAL,
                book_spread_bps REAL,
                book_imbalance_pct REAL,
                bid_depth10 REAL,
                ask_depth10 REAL,
                impact_excess_bps REAL,
                wall_side TEXT,
                wall_px REAL,
                wall_notional REAL,
                wall_ratio REAL,
                wall_dist_bps REAL,
                liq_notional_5m REAL,
                last_context_ts_ms INTEGER,
                last_trade_ts_ms INTEGER,
                last_book_ts_ms INTEGER,
                last_event_ts_ms INTEGER,
                snapshot_json TEXT NOT NULL,
                UNIQUE(symbol, ts_ms)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL,
                price REAL,
                notional REAL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL,
                price REAL,
                notional REAL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                mark REAL,
                funding_pct REAL,
                oi REAL,
                cvd_5m REAL,
                basis_pct REAL,
                taker_buy_pct_5m REAL,
                snapshot_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_ts
                ON market_snapshots(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
                ON trades(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_ts
                ON liquidations(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol_ts
                ON alerts(symbol, ts_ms);

            PRAGMA user_version = 1;
            """
        )

    def write_batch(self, events: list[PersistEvent]) -> None:
        conn = self._conn()
        with conn:
            for event in events:
                if event.kind == "snapshot":
                    self._insert_snapshot(event.payload)
                elif event.kind == "trade":
                    self._insert_trade(event.payload)
                elif event.kind == "liquidation":
                    self._insert_liquidation(event.payload)
                elif event.kind == "alert":
                    self._insert_alert(event.payload)

    def purge_stale(self) -> None:
        cutoff_ms = int(
            (time.time() - config.PERSIST_RETENTION_DAYS * 24 * 60 * 60) * 1000
        )
        conn = self._conn()
        with conn:
            for table in ("market_snapshots", "trades", "liquidations", "alerts"):
                conn.execute(f"DELETE FROM {table} WHERE ts_ms < ?", (cutoff_ms,))

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _insert_snapshot(self, payload: dict[str, Any]) -> None:
        self._conn().execute(
            """
            INSERT OR IGNORE INTO market_snapshots (
                ts_ms, ts_utc, symbol, mark, mid, funding, funding_pct,
                funding_delta_1h_pct, oracle, hl_spot, basis_pct, basis_source,
                premium_pct, oi, oi_notional, day_ntl_vlm, prev_day_change_pct,
                cvd_1m, cvd_5m, cvd_15m, cvd_1h, taker_buy_pct_5m,
                taker_notional_5m, avg_trade_notional_5m, best_bid, best_ask,
                book_spread_bps, book_imbalance_pct, bid_depth10, ask_depth10,
                impact_excess_bps, wall_side, wall_px, wall_notional, wall_ratio,
                wall_dist_bps, liq_notional_5m, last_context_ts_ms,
                last_trade_ts_ms, last_book_ts_ms, last_event_ts_ms, snapshot_json
            ) VALUES (
                :ts_ms, :ts_utc, :symbol, :mark, :mid, :funding, :funding_pct,
                :funding_delta_1h_pct, :oracle, :hl_spot, :basis_pct,
                :basis_source, :premium_pct, :oi, :oi_notional, :day_ntl_vlm,
                :prev_day_change_pct, :cvd_1m, :cvd_5m, :cvd_15m, :cvd_1h,
                :taker_buy_pct_5m, :taker_notional_5m, :avg_trade_notional_5m,
                :best_bid, :best_ask, :book_spread_bps, :book_imbalance_pct,
                :bid_depth10, :ask_depth10, :impact_excess_bps, :wall_side,
                :wall_px, :wall_notional, :wall_ratio, :wall_dist_bps,
                :liq_notional_5m, :last_context_ts_ms, :last_trade_ts_ms,
                :last_book_ts_ms, :last_event_ts_ms, :snapshot_json
            )
            """,
            {**payload, "snapshot_json": _json(payload)},
        )

    def _insert_trade(self, payload: dict[str, Any]) -> None:
        self._conn().execute(
            """
            INSERT INTO trades (
                ts_ms, ts_utc, symbol, side, qty, price, notional, raw_json
            ) VALUES (
                :ts_ms, :ts_utc, :symbol, :side, :qty, :price, :notional, :raw_json
            )
            """,
            {**payload, "raw_json": _json(payload["raw"])},
        )

    def _insert_liquidation(self, payload: dict[str, Any]) -> None:
        self._conn().execute(
            """
            INSERT INTO liquidations (
                ts_ms, ts_utc, symbol, side, qty, price, notional, raw_json
            ) VALUES (
                :ts_ms, :ts_utc, :symbol, :side, :qty, :price, :notional, :raw_json
            )
            """,
            {**payload, "raw_json": _json(payload["raw"])},
        )

    def _insert_alert(self, payload: dict[str, Any]) -> None:
        snapshot = payload["snapshot"]
        self._conn().execute(
            """
            INSERT INTO alerts (
                ts_ms, ts_utc, symbol, kind, message, mark, funding_pct, oi,
                cvd_5m, basis_pct, taker_buy_pct_5m, snapshot_json
            ) VALUES (
                :ts_ms, :ts_utc, :symbol, :kind, :message, :mark, :funding_pct,
                :oi, :cvd_5m, :basis_pct, :taker_buy_pct_5m, :snapshot_json
            )
            """,
            {
                "ts_ms": payload["ts_ms"],
                "ts_utc": payload["ts_utc"],
                "symbol": payload["symbol"],
                "kind": payload["kind"],
                "message": payload["message"],
                "mark": snapshot.get("mark"),
                "funding_pct": snapshot.get("funding_pct"),
                "oi": snapshot.get("oi"),
                "cvd_5m": snapshot.get("cvd_5m"),
                "basis_pct": snapshot.get("basis_pct"),
                "taker_buy_pct_5m": snapshot.get("taker_buy_pct_5m"),
                "snapshot_json": _json(snapshot),
            },
        )

    def _conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("SQLite writer is not open")
        return self.conn


def _drain_events(limit: int) -> list[PersistEvent]:
    events: list[PersistEvent] = []
    for _ in range(limit):
        try:
            events.append(_EVENTS.get_nowait())
        except queue.Empty:
            break
    return events


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ts_utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
