from __future__ import annotations

import asyncio
import json
import logging
import math
import queue
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import config
import signals as signal_model

if TYPE_CHECKING:
    from state import SymbolState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PersistEvent:
    kind: str
    payload: dict[str, Any]


_EVENTS: queue.Queue[PersistEvent] = queue.Queue()
_last_snapshot_by_symbol: dict[str, tuple[int, float | None]] = {}
_last_signal_digest = ""
_last_signal_write_ts_ms = 0


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


def enqueue_signals_if_due(
    states: Mapping[str, SymbolState],
    ts_ms: int | None = None,
) -> bool:
    global _last_signal_digest, _last_signal_write_ts_ms

    ts_ms = ts_ms or int(time.time() * 1000)
    signals = [
        signal.to_dict()
        for signal in signal_model.evaluate_signal_set(states, now_ms=ts_ms)
    ]
    digest = _json(signals)
    due = (
        digest != _last_signal_digest
        or ts_ms - _last_signal_write_ts_ms >= config.SIGNAL_MIN_INTERVAL_MS
    )
    _last_signal_digest = digest

    if not signals:
        return False
    if not due:
        return False

    _last_signal_write_ts_ms = ts_ms
    _EVENTS.put_nowait(PersistEvent("signals", {"signals": signals}))
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
    writer = create_writer()
    await asyncio.to_thread(writer.open)
    try:
        await asyncio.to_thread(writer.initialize)
        await asyncio.to_thread(writer.purge_stale)
        await asyncio.to_thread(writer.write_storage_report)

        pending: list[PersistEvent] = []
        last_snapshot_scan = 0.0
        last_signal_scan = 0.0
        last_purge = time.monotonic()
        last_storage_report = time.monotonic()

        while True:
            now = time.monotonic()
            if now - last_snapshot_scan >= config.PERSIST_SNAPSHOT_SCAN_INTERVAL_SEC:
                ts_ms = int(time.time() * 1000)
                for sym in config.WATCHLIST:
                    st = states.get(sym)
                    if st is not None:
                        enqueue_snapshot_if_due(sym, st, ts_ms)
                last_snapshot_scan = now

            if now - last_signal_scan >= config.SIGNAL_SCAN_INTERVAL_SEC:
                enqueue_signals_if_due(states, int(time.time() * 1000))
                last_signal_scan = now

            if not pending:
                pending = _drain_events(config.PERSIST_BATCH_SIZE)

            if pending:
                try:
                    await asyncio.to_thread(writer.write_batch, pending)
                    pending = []
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Persistence write failed; retrying.")
                    await asyncio.sleep(config.PERSIST_FLUSH_INTERVAL_SEC)
                    continue
            else:
                await asyncio.sleep(config.PERSIST_FLUSH_INTERVAL_SEC)

            if now - last_purge >= config.PERSIST_PURGE_INTERVAL_SEC:
                await asyncio.to_thread(writer.purge_stale)
                last_purge = now

            if now - last_storage_report >= config.STORAGE_REPORT_INTERVAL_SEC:
                await asyncio.to_thread(writer.write_storage_report)
                last_storage_report = now
    finally:
        await asyncio.to_thread(writer.close)


def create_writer() -> Any:
    if config.DATABASE_BACKEND == "postgres":
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required for postgres persistence")
        return PostgresWriter(config.DATABASE_URL)
    if config.DATABASE_BACKEND != "sqlite":
        raise RuntimeError(f"Unsupported DATABASE_BACKEND: {config.DATABASE_BACKEND}")
    return SQLiteWriter(Path(config.SQLITE_PATH))


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

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                expires_at_utc TEXT NOT NULL,
                signal_key TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                title TEXT NOT NULL,
                strength TEXT NOT NULL,
                confirmations_json TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                signal_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS storage_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                backend TEXT NOT NULL,
                total_bytes INTEGER NOT NULL,
                warning_bytes INTEGER NOT NULL,
                report_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_ts
                ON market_snapshots(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
                ON trades(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_ts
                ON liquidations(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol_ts
                ON alerts(symbol, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_signals_key_ts
                ON signals(signal_key, ts_ms);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol_expires
                ON signals(symbol, expires_at_ms);
            CREATE INDEX IF NOT EXISTS idx_storage_reports_ts
                ON storage_reports(ts_ms);

            PRAGMA user_version = 2;
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
                elif event.kind == "signals":
                    self._insert_signals(event.payload)

    def purge_stale(self) -> None:
        persist_cutoff_ms = int(
            (time.time() - config.PERSIST_RETENTION_DAYS * 24 * 60 * 60) * 1000
        )
        signal_cutoff_ms = int(
            (time.time() - config.SIGNAL_RETENTION_DAYS * 24 * 60 * 60) * 1000
        )
        conn = self._conn()
        with conn:
            for table in ("market_snapshots", "trades", "liquidations", "alerts"):
                conn.execute(
                    f"DELETE FROM {table} WHERE ts_ms < ?",
                    (persist_cutoff_ms,),
                )
            conn.execute("DELETE FROM signals WHERE ts_ms < ?", (signal_cutoff_ms,))

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

    def _insert_signals(self, payload: dict[str, Any]) -> None:
        for signal in payload["signals"]:
            self._conn().execute(
                """
                INSERT INTO signals (
                    ts_ms, ts_utc, expires_at_ms, expires_at_utc, signal_key,
                    symbol, action, title, strength, confirmations_json,
                    risks_json, signal_json
                ) VALUES (
                    :ts_ms, :ts_utc, :expires_at_ms, :expires_at_utc, :signal_key,
                    :symbol, :action, :title, :strength, :confirmations_json,
                    :risks_json, :signal_json
                )
                """,
                {
                    "ts_ms": signal["updated_at_ms"],
                    "ts_utc": signal["updated_at"],
                    "expires_at_ms": signal["expires_at_ms"],
                    "expires_at_utc": signal["expires_at"],
                    "signal_key": signal["signal_key"],
                    "symbol": signal["symbol"],
                    "action": signal["action"],
                    "title": signal["title"],
                    "strength": signal["strength"],
                    "confirmations_json": _json(signal["confirmations"]),
                    "risks_json": _json(signal["risks"]),
                    "signal_json": _json(signal),
                },
            )

    def write_storage_report(self) -> None:
        conn = self._conn()
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        file_paths = [
            self.path,
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
        ]
        files = [
            {"path": str(path), "bytes": path.stat().st_size}
            for path in file_paths
            if path.exists()
        ]
        total_bytes = sum(item["bytes"] for item in files) or page_count * page_size
        report = {
            "backend": "sqlite",
            "database": str(self.path),
            "page_count": page_count,
            "page_size": page_size,
            "files": files,
            "total_bytes": total_bytes,
            "warning_bytes": config.STORAGE_WARNING_BYTES,
            "over_warning": total_bytes >= config.STORAGE_WARNING_BYTES,
        }
        ts_ms = int(time.time() * 1000)
        with conn:
            conn.execute(
                """
                INSERT INTO storage_reports (
                    ts_ms, ts_utc, backend, total_bytes, warning_bytes, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_ms,
                    _ts_utc(ts_ms),
                    "sqlite",
                    total_bytes,
                    config.STORAGE_WARNING_BYTES,
                    _json(report),
                ),
            )

    def _conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("SQLite writer is not open")
        return self.conn


class PostgresWriter:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.conn: Any = None

    def open(self) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for postgres persistence"
            ) from exc

        self.conn = psycopg.connect(self.database_url)

    def initialize(self) -> None:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    mark DOUBLE PRECISION,
                    mid DOUBLE PRECISION,
                    funding DOUBLE PRECISION,
                    funding_pct DOUBLE PRECISION,
                    funding_delta_1h_pct DOUBLE PRECISION,
                    oracle DOUBLE PRECISION,
                    hl_spot DOUBLE PRECISION,
                    basis_pct DOUBLE PRECISION,
                    basis_source TEXT,
                    premium_pct DOUBLE PRECISION,
                    oi DOUBLE PRECISION,
                    oi_notional DOUBLE PRECISION,
                    day_ntl_vlm DOUBLE PRECISION,
                    prev_day_change_pct DOUBLE PRECISION,
                    cvd_1m DOUBLE PRECISION,
                    cvd_5m DOUBLE PRECISION,
                    cvd_15m DOUBLE PRECISION,
                    cvd_1h DOUBLE PRECISION,
                    taker_buy_pct_5m DOUBLE PRECISION,
                    taker_notional_5m DOUBLE PRECISION,
                    avg_trade_notional_5m DOUBLE PRECISION,
                    best_bid DOUBLE PRECISION,
                    best_ask DOUBLE PRECISION,
                    book_spread_bps DOUBLE PRECISION,
                    book_imbalance_pct DOUBLE PRECISION,
                    bid_depth10 DOUBLE PRECISION,
                    ask_depth10 DOUBLE PRECISION,
                    impact_excess_bps DOUBLE PRECISION,
                    wall_side TEXT,
                    wall_px DOUBLE PRECISION,
                    wall_notional DOUBLE PRECISION,
                    wall_ratio DOUBLE PRECISION,
                    wall_dist_bps DOUBLE PRECISION,
                    liq_notional_5m DOUBLE PRECISION,
                    last_context_ts_ms BIGINT,
                    last_trade_ts_ms BIGINT,
                    last_book_ts_ms BIGINT,
                    last_event_ts_ms BIGINT,
                    snapshot_json JSONB NOT NULL,
                    UNIQUE(symbol, ts_ms)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty DOUBLE PRECISION,
                    price DOUBLE PRECISION,
                    notional DOUBLE PRECISION,
                    raw_json JSONB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS liquidations (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty DOUBLE PRECISION,
                    price DOUBLE PRECISION,
                    notional DOUBLE PRECISION,
                    raw_json JSONB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    mark DOUBLE PRECISION,
                    funding_pct DOUBLE PRECISION,
                    oi DOUBLE PRECISION,
                    cvd_5m DOUBLE PRECISION,
                    basis_pct DOUBLE PRECISION,
                    taker_buy_pct_5m DOUBLE PRECISION,
                    snapshot_json JSONB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    expires_at_ms BIGINT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    signal_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    title TEXT NOT NULL,
                    strength TEXT NOT NULL,
                    confirmations_json JSONB NOT NULL,
                    risks_json JSONB NOT NULL,
                    signal_json JSONB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS storage_reports (
                    id BIGSERIAL PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    total_bytes BIGINT NOT NULL,
                    warning_bytes BIGINT NOT NULL,
                    report_json JSONB NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_ts
                    ON market_snapshots(symbol, ts_ms);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
                    ON trades(symbol, ts_ms);
                CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_ts
                    ON liquidations(symbol, ts_ms);
                CREATE INDEX IF NOT EXISTS idx_alerts_symbol_ts
                    ON alerts(symbol, ts_ms);
                CREATE INDEX IF NOT EXISTS idx_signals_key_ts
                    ON signals(signal_key, ts_ms);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_expires
                    ON signals(symbol, expires_at_ms);
                CREATE INDEX IF NOT EXISTS idx_storage_reports_ts
                    ON storage_reports(ts_ms);
                """
            )
        conn.commit()

    def write_batch(self, events: list[PersistEvent]) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for event in events:
                    if event.kind == "snapshot":
                        self._insert_snapshot(cur, event.payload)
                    elif event.kind == "trade":
                        self._insert_trade(cur, event.payload)
                    elif event.kind == "liquidation":
                        self._insert_liquidation(cur, event.payload)
                    elif event.kind == "alert":
                        self._insert_alert(cur, event.payload)
                    elif event.kind == "signals":
                        self._insert_signals(cur, event.payload)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def purge_stale(self) -> None:
        persist_cutoff_ms = int(
            (time.time() - config.PERSIST_RETENTION_DAYS * 24 * 60 * 60) * 1000
        )
        signal_cutoff_ms = int(
            (time.time() - config.SIGNAL_RETENTION_DAYS * 24 * 60 * 60) * 1000
        )
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for table in ("market_snapshots", "trades", "liquidations", "alerts"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE ts_ms < %s",
                        (persist_cutoff_ms,),
                    )
                cur.execute(
                    "DELETE FROM signals WHERE ts_ms < %s",
                    (signal_cutoff_ms,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _insert_snapshot(self, cur: Any, payload: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO market_snapshots (
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
                %(ts_ms)s, %(ts_utc)s, %(symbol)s, %(mark)s, %(mid)s, %(funding)s,
                %(funding_pct)s, %(funding_delta_1h_pct)s, %(oracle)s,
                %(hl_spot)s, %(basis_pct)s, %(basis_source)s, %(premium_pct)s,
                %(oi)s, %(oi_notional)s, %(day_ntl_vlm)s,
                %(prev_day_change_pct)s, %(cvd_1m)s, %(cvd_5m)s, %(cvd_15m)s,
                %(cvd_1h)s, %(taker_buy_pct_5m)s, %(taker_notional_5m)s,
                %(avg_trade_notional_5m)s, %(best_bid)s, %(best_ask)s,
                %(book_spread_bps)s, %(book_imbalance_pct)s, %(bid_depth10)s,
                %(ask_depth10)s, %(impact_excess_bps)s, %(wall_side)s,
                %(wall_px)s, %(wall_notional)s, %(wall_ratio)s,
                %(wall_dist_bps)s, %(liq_notional_5m)s, %(last_context_ts_ms)s,
                %(last_trade_ts_ms)s, %(last_book_ts_ms)s,
                %(last_event_ts_ms)s, %(snapshot_json)s::jsonb
            )
            ON CONFLICT (symbol, ts_ms) DO NOTHING
            """,
            {**payload, "snapshot_json": _json(payload)},
        )

    def _insert_trade(self, cur: Any, payload: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO trades (
                ts_ms, ts_utc, symbol, side, qty, price, notional, raw_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                payload["ts_ms"],
                payload["ts_utc"],
                payload["symbol"],
                payload["side"],
                payload["qty"],
                payload["price"],
                payload["notional"],
                _json(payload["raw"]),
            ),
        )

    def _insert_liquidation(self, cur: Any, payload: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO liquidations (
                ts_ms, ts_utc, symbol, side, qty, price, notional, raw_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                payload["ts_ms"],
                payload["ts_utc"],
                payload["symbol"],
                payload["side"],
                payload["qty"],
                payload["price"],
                payload["notional"],
                _json(payload["raw"]),
            ),
        )

    def _insert_alert(self, cur: Any, payload: dict[str, Any]) -> None:
        snapshot = payload["snapshot"]
        cur.execute(
            """
            INSERT INTO alerts (
                ts_ms, ts_utc, symbol, kind, message, mark, funding_pct, oi,
                cvd_5m, basis_pct, taker_buy_pct_5m, snapshot_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                payload["ts_ms"],
                payload["ts_utc"],
                payload["symbol"],
                payload["kind"],
                payload["message"],
                snapshot.get("mark"),
                snapshot.get("funding_pct"),
                snapshot.get("oi"),
                snapshot.get("cvd_5m"),
                snapshot.get("basis_pct"),
                snapshot.get("taker_buy_pct_5m"),
                _json(snapshot),
            ),
        )

    def _insert_signals(self, cur: Any, payload: dict[str, Any]) -> None:
        for signal in payload["signals"]:
            cur.execute(
                """
                INSERT INTO signals (
                    ts_ms, ts_utc, expires_at_ms, expires_at_utc, signal_key,
                    symbol, action, title, strength, confirmations_json,
                    risks_json, signal_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (
                    signal["updated_at_ms"],
                    signal["updated_at"],
                    signal["expires_at_ms"],
                    signal["expires_at"],
                    signal["signal_key"],
                    signal["symbol"],
                    signal["action"],
                    signal["title"],
                    signal["strength"],
                    _json(signal["confirmations"]),
                    _json(signal["risks"]),
                    _json(signal),
                ),
            )

    def write_storage_report(self) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.relname,
                        pg_relation_size(c.oid) AS table_bytes,
                        pg_indexes_size(c.oid) AS index_bytes,
                        pg_total_relation_size(c.oid) AS total_bytes
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p')
                      AND c.relname = ANY(%s)
                    ORDER BY c.relname
                    """,
                    (
                        [
                            "market_snapshots",
                            "trades",
                            "liquidations",
                            "alerts",
                            "signals",
                            "storage_reports",
                        ],
                    ),
                )
                rows = cur.fetchall()
                tables = [
                    {
                        "table": row[0],
                        "table_bytes": int(row[1] or 0),
                        "index_bytes": int(row[2] or 0),
                        "total_bytes": int(row[3] or 0),
                    }
                    for row in rows
                ]
                total_bytes = sum(row["total_bytes"] for row in tables)
                report = {
                    "backend": "postgres",
                    "tables": tables,
                    "total_bytes": total_bytes,
                    "warning_bytes": config.STORAGE_WARNING_BYTES,
                    "over_warning": total_bytes >= config.STORAGE_WARNING_BYTES,
                }
                ts_ms = int(time.time() * 1000)
                cur.execute(
                    """
                    INSERT INTO storage_reports (
                        ts_ms, ts_utc, backend, total_bytes, warning_bytes, report_json
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        ts_ms,
                        _ts_utc(ts_ms),
                        "postgres",
                        total_bytes,
                        config.STORAGE_WARNING_BYTES,
                        _json(report),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _conn(self) -> Any:
        if self.conn is None:
            raise RuntimeError("Postgres writer is not open")
        return self.conn


async def fetch_health() -> dict[str, Any]:
    return await asyncio.to_thread(_fetch_health_sync)


async def fetch_latest_symbols() -> list[dict[str, Any]]:
    return await asyncio.to_thread(_fetch_latest_symbols_sync)


async def fetch_latest_signals(symbol: str | None = None) -> list[dict[str, Any]]:
    normalized_symbol = symbol.lower() if symbol else None
    return await asyncio.to_thread(_fetch_latest_signals_sync, normalized_symbol)


async def fetch_latest_storage_report() -> dict[str, Any] | None:
    return await asyncio.to_thread(_fetch_latest_storage_report_sync)


def _fetch_health_sync() -> dict[str, Any]:
    base = {
        "status": "ok",
        "backend": config.DATABASE_BACKEND,
        "watchlist": config.WATCHLIST,
        "database_available": False,
        "latest_snapshot_ts_ms": None,
        "latest_signal_ts_ms": None,
    }
    try:
        if config.DATABASE_BACKEND == "postgres":
            with _postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(ts_ms) FROM market_snapshots")
                    base["latest_snapshot_ts_ms"] = cur.fetchone()[0]
                    cur.execute("SELECT MAX(ts_ms) FROM signals")
                    base["latest_signal_ts_ms"] = cur.fetchone()[0]
            base["database_available"] = True
        else:
            db_path = Path(config.SQLITE_PATH)
            if not db_path.exists():
                return base
            with _sqlite_connection(db_path) as conn:
                base["latest_snapshot_ts_ms"] = conn.execute(
                    "SELECT MAX(ts_ms) FROM market_snapshots"
                ).fetchone()[0]
                base["latest_signal_ts_ms"] = conn.execute(
                    "SELECT MAX(ts_ms) FROM signals"
                ).fetchone()[0]
            base["database_available"] = True
    except Exception as exc:
        base["status"] = "degraded"
        base["error"] = f"{type(exc).__name__}: {exc}"
    return base


def _fetch_latest_symbols_sync() -> list[dict[str, Any]]:
    if config.DATABASE_BACKEND == "postgres":
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (symbol) snapshot_json
                    FROM market_snapshots
                    ORDER BY symbol, ts_ms DESC
                    """
                )
                return [_decode_json(row[0]) for row in cur.fetchall()]

    db_path = Path(config.SQLITE_PATH)
    if not db_path.exists():
        return []
    with _sqlite_connection(db_path) as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT symbol, MAX(ts_ms) AS ts_ms
                FROM market_snapshots
                GROUP BY symbol
            )
            SELECT m.snapshot_json
            FROM market_snapshots m
            JOIN latest l ON l.symbol = m.symbol AND l.ts_ms = m.ts_ms
            ORDER BY m.symbol
            """
        ).fetchall()
        return [_decode_json(row["snapshot_json"]) for row in rows]


def _fetch_latest_signals_sync(symbol: str | None = None) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    if config.DATABASE_BACKEND == "postgres":
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT signal_json
                    FROM (
                        SELECT DISTINCT ON (signal_key)
                            signal_json, ts_ms
                        FROM signals
                        WHERE expires_at_ms >= %s
                          AND (%s IS NULL OR symbol = %s)
                        ORDER BY signal_key, ts_ms DESC, id DESC
                    ) latest
                    ORDER BY ts_ms DESC
                    """,
                    (now_ms, symbol, symbol),
                )
                return [_decode_json(row[0]) for row in cur.fetchall()]

    db_path = Path(config.SQLITE_PATH)
    if not db_path.exists():
        return []
    with _sqlite_connection(db_path) as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT signal_key, MAX(id) AS id
                FROM signals
                WHERE expires_at_ms >= ?
                  AND (? IS NULL OR symbol = ?)
                GROUP BY signal_key
            )
            SELECT s.signal_json
            FROM signals s
            JOIN latest l ON l.id = s.id
            ORDER BY s.ts_ms DESC
            """,
            (now_ms, symbol, symbol),
        ).fetchall()
        return [_decode_json(row["signal_json"]) for row in rows]


def _fetch_latest_storage_report_sync() -> dict[str, Any] | None:
    if config.DATABASE_BACKEND == "postgres":
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT report_json
                    FROM storage_reports
                    ORDER BY ts_ms DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                return _decode_json(row[0]) if row else None

    db_path = Path(config.SQLITE_PATH)
    if not db_path.exists():
        return None
    with _sqlite_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT report_json
            FROM storage_reports
            ORDER BY ts_ms DESC
            LIMIT 1
            """
        ).fetchone()
        return _decode_json(row["report_json"]) if row else None


def _sqlite_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _postgres_connection() -> Any:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for postgres reads")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for postgres reads") from exc
    return psycopg.connect(config.DATABASE_URL)


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


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
