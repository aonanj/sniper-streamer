#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402


TABLES = ("market_snapshots", "trades", "liquidations", "alerts")

SNAPSHOT_METRICS = (
    "mark",
    "mid",
    "funding_pct",
    "funding_delta_1h_pct",
    "basis_pct",
    "premium_pct",
    "oi",
    "oi_notional",
    "day_ntl_vlm",
    "prev_day_change_pct",
    "cvd_1m",
    "cvd_5m",
    "cvd_15m",
    "cvd_1h",
    "taker_buy_pct_5m",
    "taker_notional_5m",
    "avg_trade_notional_5m",
    "book_spread_bps",
    "book_imbalance_pct",
    "bid_depth10",
    "ask_depth10",
    "impact_excess_bps",
    "wall_notional",
    "wall_ratio",
    "wall_dist_bps",
    "liq_notional_5m",
)

LATEST_SNAPSHOT_COLUMNS = (
    "id",
    "ts_ms",
    "ts_utc",
    "symbol",
    "mark",
    "mid",
    "funding",
    "funding_pct",
    "funding_delta_1h_pct",
    "oracle",
    "hl_spot",
    "basis_pct",
    "basis_source",
    "premium_pct",
    "oi",
    "oi_notional",
    "day_ntl_vlm",
    "prev_day_change_pct",
    "cvd_1m",
    "cvd_5m",
    "cvd_15m",
    "cvd_1h",
    "taker_buy_pct_5m",
    "taker_notional_5m",
    "avg_trade_notional_5m",
    "best_bid",
    "best_ask",
    "book_spread_bps",
    "book_imbalance_pct",
    "bid_depth10",
    "ask_depth10",
    "impact_excess_bps",
    "wall_side",
    "wall_px",
    "wall_notional",
    "wall_ratio",
    "wall_dist_bps",
    "liq_notional_5m",
    "last_context_ts_ms",
    "last_trade_ts_ms",
    "last_book_ts_ms",
    "last_event_ts_ms",
)


def main() -> int:
    args = parse_args()
    db_path = resolve_path(args.db)
    if not db_path.exists():
        print(f"SQLite database not found: {db_path}", file=sys.stderr)
        return 1

    out_dir = resolve_out_dir(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    conn = connect_readonly(db_path)
    try:
        conn.execute("BEGIN")
        time_filter = build_time_filter(args.since_hours)

        context = {
            "generated_at_utc": started_at.isoformat(),
            "database": str(db_path),
            "output_directory": str(out_dir),
            "selected_window": time_filter.describe(),
            "cluster_bucket_pct": args.cluster_bucket_pct,
            "include_raw_rows": not args.no_raw,
            "include_api_payloads": args.include_api_payloads,
        }

        files: list[dict[str, str]] = []
        files.append(write_manifest(out_dir, context))
        files.append(write_schema(conn, out_dir))
        files.append(write_config(out_dir))
        files.append(write_table_counts(conn, out_dir, time_filter))
        files.append(write_snapshot_symbol_summary(conn, out_dir, time_filter))
        files.append(write_snapshot_metric_summary(conn, out_dir, time_filter))
        files.append(write_latest_snapshots(conn, out_dir, time_filter))
        files.append(write_trade_flow_minutes(conn, out_dir, time_filter))
        files.append(
            write_flow_cluster_candidates(
                conn,
                out_dir,
                time_filter,
                args.cluster_bucket_pct,
                args.top_clusters_per_hour,
            )
        )
        files.append(write_alert_summary(conn, out_dir, time_filter))
        files.append(write_alerts(conn, out_dir, time_filter))
        files.append(write_llm_prompt(out_dir))

        if not args.no_raw:
            files.extend(write_raw_exports(conn, out_dir, time_filter, args.include_api_payloads))

        conn.execute("COMMIT")
    finally:
        conn.close()

    write_export_index(out_dir, context, files)
    print(f"Exported persisted data to {out_dir}")
    print(f"Start with: {out_dir / '00_manifest.md'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export sniper-streamer SQLite persistence into LLM-readable "
            "summaries plus optional raw CSV files."
        )
    )
    parser.add_argument(
        "--db",
        default=config.SQLITE_PATH,
        help=f"SQLite database path. Default: {config.SQLITE_PATH}",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Output directory. Default: data/exports/"
            "sniper_streamer_export_<utc timestamp>"
        ),
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=None,
        help="Only export rows from the last N hours. Default: all retained rows.",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Skip raw table CSV exports and write only summaries.",
    )
    parser.add_argument(
        "--include-api-payloads",
        action="store_true",
        help="Include raw_json/snapshot_json columns in raw exports.",
    )
    parser.add_argument(
        "--cluster-bucket-pct",
        type=float,
        default=0.25,
        help=(
            "Fixed bucket width, as percent of hourly reference price, for "
            "derived flow-cluster candidates. Default: 0.25."
        ),
    )
    parser.add_argument(
        "--top-clusters-per-hour",
        type=int,
        default=5,
        help="Flow-cluster candidate rows to keep per symbol per hour. Default: 5.",
    )
    return parser.parse_args()


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def resolve_out_dir(path: str | None) -> Path:
    if path:
        return resolve_path(path)
    stamp = utc_now().strftime("%Y%m%d_%H%M%SZ")
    return REPO_ROOT / "data" / "exports" / f"sniper_streamer_export_{stamp}"


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class TimeFilter:
    def __init__(self, start_ms: int | None) -> None:
        self.start_ms = start_ms

    def where(self, table_alias: str | None = None) -> tuple[str, list[Any]]:
        if self.start_ms is None:
            return "", []
        prefix = f"{table_alias}." if table_alias else ""
        return f"WHERE {prefix}ts_ms >= ?", [self.start_ms]

    def and_clause(self, table_alias: str | None = None) -> tuple[str, list[Any]]:
        if self.start_ms is None:
            return "", []
        prefix = f"{table_alias}." if table_alias else ""
        return f"AND {prefix}ts_ms >= ?", [self.start_ms]

    def describe(self) -> str:
        if self.start_ms is None:
            return "all retained rows"
        return f"rows with ts_ms >= {self.start_ms} ({ts_utc(self.start_ms)})"


def build_time_filter(since_hours: float | None) -> TimeFilter:
    if since_hours is None:
        return TimeFilter(None)
    if since_hours <= 0:
        raise SystemExit("--since-hours must be greater than 0")
    start_ms = int((utc_now().timestamp() - since_hours * 3600) * 1000)
    return TimeFilter(start_ms)


def write_manifest(out_dir: Path, context: dict[str, Any]) -> dict[str, str]:
    path = out_dir / "00_manifest.md"
    lines = [
        "# sniper-streamer Persisted Data Export",
        "",
        "This export is arranged for LLM review of the current Hyperliquid "
        "USDC perp screener setup. Start with the summaries before opening raw "
        "tables.",
        "",
        "## Export Context",
        "",
        f"- Generated at UTC: `{context['generated_at_utc']}`",
        f"- SQLite database: `{context['database']}`",
        f"- Selected window: `{context['selected_window']}`",
        f"- Flow-cluster candidate bucket: `{context['cluster_bucket_pct']}%`",
        f"- Raw table CSVs included: `{context['include_raw_rows']}`",
        f"- API payload JSON included: `{context['include_api_payloads']}`",
        "",
        "## File Order",
        "",
        "- `00_manifest.md` - this guide",
        "- `01_schema.sql` - persisted SQLite schema",
        "- `02_config.json` - current watchlist, thresholds, and persistence knobs",
        "- `03_table_counts.csv` - row counts and time ranges per table",
        "- `04_snapshot_symbol_summary.csv` - per-symbol latest values and threshold hit counts",
        "- `05_snapshot_metric_summary.csv` - per-symbol distributions for persisted snapshot metrics",
        "- `06_latest_snapshots.csv` - latest normalized market snapshot per symbol",
        "- `07_trade_flow_minutes.csv` - one-minute taker-flow buckets from persisted trades",
        "- `08_flow_cluster_candidates.csv` - derived hourly taker-flow price buckets",
        "- `09_alert_summary.csv` - alert counts by symbol and kind",
        "- `10_alerts.csv` - alert event rows with normalized snapshot fields",
        "- `11_llm_review_prompt.md` - ready-to-use review prompt",
        "- `raw_*.csv` - complete normalized table rows when raw export is enabled",
        "",
        "## Review Notes",
        "",
        "- Liquidation rows come from the configured external liquidation source "
        "(Bybit allLiquidation by default), mapped onto the Hyperliquid watchlist.",
        "- `basis_source` is `spot` when Hyperliquid spot is available and `oracle` "
        "when the dashboard falls back to oracle basis.",
        "- `impact_excess_bps`, `book_imbalance_pct`, taker-flow buckets, and "
        "volume-scaled thresholds are the main current tuning surfaces.",
        "- `08_flow_cluster_candidates.csv` is derived from trades for offline review; "
        "it is not an exact replay of the live dashboard's volatility-scaled buckets.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return describe_file(path, "export guide")


def write_export_index(
    out_dir: Path, context: dict[str, Any], files: list[dict[str, str]]
) -> None:
    path = out_dir / "export_index.json"
    payload = {
        **context,
        "files": files,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_schema(conn: sqlite3.Connection, out_dir: Path) -> dict[str, str]:
    path = out_dir / "01_schema.sql"
    rows = conn.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
        ORDER BY
            CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,
            name
        """
    ).fetchall()
    statements = [row["sql"].rstrip(";") + ";" for row in rows]
    path.write_text("\n\n".join(statements) + "\n", encoding="utf-8")
    return describe_file(path, "SQLite schema")


def write_config(out_dir: Path) -> dict[str, str]:
    path = out_dir / "02_config.json"
    payload: dict[str, Any] = {}
    for name in sorted(dir(config)):
        if not name.isupper():
            continue
        value = getattr(config, name)
        if is_jsonable(value):
            payload[name] = value
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return describe_file(path, "current config constants")


def write_table_counts(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "03_table_counts.csv"
    rows = []
    for table in TABLES:
        where, params = time_filter.where()
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                MIN(ts_utc) AS first_ts_utc,
                MAX(ts_utc) AS last_ts_utc
            FROM {table}
            {where}
            """,
            params,
        ).fetchone()
        rows.append(
            {
                "table": table,
                "row_count": row["row_count"],
                "first_ts_utc": row["first_ts_utc"],
                "last_ts_utc": row["last_ts_utc"],
            }
        )
    write_dicts_csv(path, rows)
    return describe_file(path, "table counts and time ranges")


def write_snapshot_symbol_summary(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "04_snapshot_symbol_summary.csv"
    rows = load_snapshots(conn, time_filter)
    by_symbol: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)

    output = []
    for symbol in sorted(by_symbol):
        symbol_rows = by_symbol[symbol]
        latest = symbol_rows[-1]
        count = len(symbol_rows)
        funding_hits = count_matching(
            symbol_rows,
            lambda row: abs_num(row["funding_pct"]) >= config.ALERT_FUNDING_PCT,
        )
        impact_hits = count_matching(
            symbol_rows,
            lambda row: (impact_val := as_num(row["impact_excess_bps"])) is not None
            and impact_val >= config.ALERT_IMPACT_EXCESS_BPS,
        )
        book_imbalance_hits = count_matching(
            symbol_rows,
            lambda row: abs_num(row["book_imbalance_pct"])
            >= config.ALERT_BOOK_IMBALANCE_PCT,
        )
        taker_high_hits = count_matching(
            symbol_rows,
            lambda row: (taker_val := as_num(row["taker_buy_pct_5m"])) is not None
            and taker_val >= config.ALERT_TAKER_HIGH_PCT,
        )
        taker_low_hits = count_matching(
            symbol_rows,
            lambda row: (taker_val := as_num(row["taker_buy_pct_5m"])) is not None
            and taker_val <= config.ALERT_TAKER_LOW_PCT,
        )
        cap_basis_hits = count_matching(
            symbol_rows,
            lambda row: (basis_val := as_num(row["basis_pct"])) is not None
            and basis_val <= config.ALERT_BASIS_CAPITULATION,
        )
        cvd_cap_hits = count_matching(
            symbol_rows,
            lambda row: cvd_capitulation_hit(
                as_num(row["cvd_5m"]), as_num(row["day_ntl_vlm"])
            ),
        )

        output.append(
            {
                "symbol": symbol,
                "snapshot_count": count,
                "first_ts_utc": symbol_rows[0]["ts_utc"],
                "last_ts_utc": latest["ts_utc"],
                "latest_mark": latest["mark"],
                "latest_funding_pct": latest["funding_pct"],
                "latest_funding_delta_1h_pct": latest["funding_delta_1h_pct"],
                "latest_basis_pct": latest["basis_pct"],
                "latest_basis_source": latest["basis_source"],
                "latest_premium_pct": latest["premium_pct"],
                "latest_oi": latest["oi"],
                "latest_oi_notional": latest["oi_notional"],
                "latest_day_ntl_vlm": latest["day_ntl_vlm"],
                "latest_cvd_5m": latest["cvd_5m"],
                "latest_taker_buy_pct_5m": latest["taker_buy_pct_5m"],
                "latest_taker_notional_5m": latest["taker_notional_5m"],
                "latest_avg_trade_notional_5m": latest["avg_trade_notional_5m"],
                "latest_book_spread_bps": latest["book_spread_bps"],
                "latest_book_imbalance_pct": latest["book_imbalance_pct"],
                "latest_impact_excess_bps": latest["impact_excess_bps"],
                "latest_wall_side": latest["wall_side"],
                "latest_wall_notional": latest["wall_notional"],
                "latest_wall_ratio": latest["wall_ratio"],
                "avg_abs_cvd_5m": mean_abs(metric_values(symbol_rows, "cvd_5m")),
                "p95_abs_cvd_5m": percentile_abs(metric_values(symbol_rows, "cvd_5m"), 0.95),
                "avg_taker_notional_5m": mean(metric_values(symbol_rows, "taker_notional_5m")),
                "p95_taker_notional_5m": percentile(metric_values(symbol_rows, "taker_notional_5m"), 0.95),
                "avg_impact_excess_bps": mean(metric_values(symbol_rows, "impact_excess_bps")),
                "p95_impact_excess_bps": percentile(metric_values(symbol_rows, "impact_excess_bps"), 0.95),
                "funding_abs_ge_threshold_count": funding_hits,
                "funding_abs_ge_threshold_pct": pct(funding_hits, count),
                "impact_ge_threshold_count": impact_hits,
                "impact_ge_threshold_pct": pct(impact_hits, count),
                "book_imbalance_abs_ge_threshold_count": book_imbalance_hits,
                "book_imbalance_abs_ge_threshold_pct": pct(book_imbalance_hits, count),
                "taker_high_count": taker_high_hits,
                "taker_high_pct": pct(taker_high_hits, count),
                "taker_low_count": taker_low_hits,
                "taker_low_pct": pct(taker_low_hits, count),
                "basis_capitulation_count": cap_basis_hits,
                "basis_capitulation_pct": pct(cap_basis_hits, count),
                "cvd_capitulation_scaled_count": cvd_cap_hits,
                "cvd_capitulation_scaled_pct": pct(cvd_cap_hits, count),
            }
        )

    write_dicts_csv(path, output)
    return describe_file(path, "per-symbol snapshot and threshold summary")


def write_snapshot_metric_summary(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "05_snapshot_metric_summary.csv"
    rows = load_snapshots(conn, time_filter)
    by_symbol: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)

    output = []
    for symbol in sorted(by_symbol):
        symbol_rows = by_symbol[symbol]
        latest = symbol_rows[-1]
        for metric in SNAPSHOT_METRICS:
            values = metric_values(symbol_rows, metric)
            missing_count = len(symbol_rows) - len(values)
            output.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "sample_count": len(values),
                    "missing_count": missing_count,
                    "missing_pct": pct(missing_count, len(symbol_rows)),
                    "min": min(values) if values else None,
                    "p05": percentile(values, 0.05),
                    "p25": percentile(values, 0.25),
                    "median": percentile(values, 0.50),
                    "mean": mean(values),
                    "p75": percentile(values, 0.75),
                    "p95": percentile(values, 0.95),
                    "max": max(values) if values else None,
                    "latest": latest[metric],
                    "latest_ts_utc": latest["ts_utc"],
                }
            )

    write_dicts_csv(path, output)
    return describe_file(path, "snapshot metric distributions")


def write_latest_snapshots(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "06_latest_snapshots.csv"
    and_clause, params = time_filter.and_clause()
    select_cols = ", ".join(f"ms.{name}" for name in LATEST_SNAPSHOT_COLUMNS)
    rows = conn.execute(
        f"""
        WITH latest AS (
            SELECT symbol, MAX(ts_ms) AS ts_ms
            FROM market_snapshots
            WHERE 1 = 1
            {and_clause}
            GROUP BY symbol
        )
        SELECT {select_cols}
        FROM market_snapshots ms
        JOIN latest
            ON latest.symbol = ms.symbol
           AND latest.ts_ms = ms.ts_ms
        ORDER BY ms.symbol
        """,
        params,
    ).fetchall()
    write_dicts_csv(path, [dict(row) for row in rows])
    return describe_file(path, "latest normalized snapshot per symbol")


def write_trade_flow_minutes(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "07_trade_flow_minutes.csv"
    where, params = time_filter.where()
    rows = conn.execute(
        f"""
        WITH filtered AS (
            SELECT
                symbol,
                CAST(ts_ms / 60000 AS INTEGER) AS minute_bucket,
                side,
                qty,
                price,
                notional
            FROM trades
            {where}
        )
        SELECT
            symbol,
            minute_bucket * 60000 AS bucket_ts_ms,
            strftime('%Y-%m-%dT%H:%M:%SZ', minute_bucket * 60, 'unixepoch')
                AS bucket_start_utc,
            COUNT(*) AS trade_count,
            SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) AS buy_trade_count,
            SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) AS sell_trade_count,
            SUM(CASE WHEN side = 'BUY' THEN notional ELSE 0 END) AS buy_notional,
            SUM(CASE WHEN side = 'SELL' THEN notional ELSE 0 END) AS sell_notional,
            SUM(CASE WHEN side = 'BUY' THEN notional ELSE -notional END) AS cvd,
            SUM(notional) AS total_notional,
            CASE
                WHEN SUM(notional) > 0
                THEN SUM(CASE WHEN side = 'BUY' THEN notional ELSE 0 END)
                    / SUM(notional) * 100.0
            END AS taker_buy_pct,
            AVG(notional) AS avg_trade_notional,
            MAX(notional) AS max_trade_notional,
            CASE WHEN SUM(qty) > 0 THEN SUM(price * qty) / SUM(qty) END AS vwap,
            MIN(price) AS low_price,
            MAX(price) AS high_price
        FROM filtered
        GROUP BY symbol, minute_bucket
        ORDER BY symbol, minute_bucket
        """,
        params,
    ).fetchall()
    write_dicts_csv(path, [dict(row) for row in rows])
    return describe_file(path, "one-minute trade flow buckets")


def write_flow_cluster_candidates(
    conn: sqlite3.Connection,
    out_dir: Path,
    time_filter: TimeFilter,
    bucket_pct: float,
    top_clusters_per_hour: int,
) -> dict[str, str]:
    path = out_dir / "08_flow_cluster_candidates.csv"
    if bucket_pct <= 0:
        raise SystemExit("--cluster-bucket-pct must be greater than 0")
    if top_clusters_per_hour <= 0:
        raise SystemExit("--top-clusters-per-hour must be greater than 0")

    where, params = time_filter.where()
    trades = conn.execute(
        f"""
        SELECT symbol, ts_ms, ts_utc, side, qty, price, notional
        FROM trades
        {where}
        ORDER BY symbol, ts_ms
        """,
        params,
    ).fetchall()

    hourly: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for trade in trades:
        hourly[(trade["symbol"], int(trade["ts_ms"]) // 3_600_000)].append(trade)

    output = []
    for (symbol, hour_bucket), rows in sorted(hourly.items()):
        ref_price = weighted_vwap(rows)
        if not ref_price:
            continue
        bucket_size = ref_price * bucket_pct / 100
        buckets: dict[int, dict[str, Any]] = {}
        for trade in rows:
            price = as_num(trade["price"])
            notional = as_num(trade["notional"])
            if price is None or notional is None or bucket_size <= 0:
                continue
            key = round(price / bucket_size)
            bucket = buckets.setdefault(
                key,
                {
                    "symbol": symbol,
                    "hour_start_utc": ts_utc(hour_bucket * 3_600_000),
                    "bucket_pct": bucket_pct,
                    "ref_price": ref_price,
                    "bucket_price": key * bucket_size,
                    "first_ts_utc": trade["ts_utc"],
                    "last_ts_utc": trade["ts_utc"],
                    "trade_count": 0,
                    "buy_trade_count": 0,
                    "sell_trade_count": 0,
                    "buy_notional": 0.0,
                    "sell_notional": 0.0,
                    "total_notional": 0.0,
                    "max_trade_notional": 0.0,
                },
            )
            bucket["last_ts_utc"] = trade["ts_utc"]
            bucket["trade_count"] += 1
            bucket["total_notional"] += notional
            bucket["max_trade_notional"] = max(bucket["max_trade_notional"], notional)
            if trade["side"] == "BUY":
                bucket["buy_trade_count"] += 1
                bucket["buy_notional"] += notional
            else:
                bucket["sell_trade_count"] += 1
                bucket["sell_notional"] += notional

        ranked = sorted(
            buckets.values(),
            key=lambda row: row["total_notional"],
            reverse=True,
        )[:top_clusters_per_hour]
        for row in ranked:
            total = row["total_notional"]
            buy = row["buy_notional"]
            sell = row["sell_notional"]
            row["cvd"] = buy - sell
            row["taker_buy_pct"] = buy / total * 100 if total else None
            row["dominant_side"] = "BUY" if buy >= sell else "SELL"
            row["avg_trade_notional"] = (
                total / row["trade_count"] if row["trade_count"] else None
            )
            row["dist_from_ref_pct"] = (
                (row["bucket_price"] - ref_price) / ref_price * 100
                if ref_price else None
            )
            output.append(row)

    write_dicts_csv(path, output)
    return describe_file(path, "derived hourly taker-flow cluster candidates")


def write_alert_summary(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "09_alert_summary.csv"
    where, params = time_filter.where()
    rows = conn.execute(
        f"""
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol, kind
                    ORDER BY ts_ms DESC, id DESC
                ) AS rn
            FROM alerts
            {where}
        )
        SELECT
            symbol,
            kind,
            COUNT(*) AS alert_count,
            MIN(ts_utc) AS first_ts_utc,
            MAX(ts_utc) AS last_ts_utc,
            AVG(mark) AS avg_mark,
            AVG(funding_pct) AS avg_funding_pct,
            AVG(oi) AS avg_oi,
            AVG(cvd_5m) AS avg_cvd_5m,
            AVG(basis_pct) AS avg_basis_pct,
            AVG(taker_buy_pct_5m) AS avg_taker_buy_pct_5m,
            MAX(CASE WHEN rn = 1 THEN message END) AS latest_message
        FROM ranked
        GROUP BY symbol, kind
        ORDER BY symbol, alert_count DESC, kind
        """,
        params,
    ).fetchall()
    write_dicts_csv(path, [dict(row) for row in rows])
    return describe_file(path, "alert counts by symbol and kind")


def write_alerts(
    conn: sqlite3.Connection, out_dir: Path, time_filter: TimeFilter
) -> dict[str, str]:
    path = out_dir / "10_alerts.csv"
    where, params = time_filter.where()
    rows = conn.execute(
        f"""
        SELECT
            id,
            ts_ms,
            ts_utc,
            symbol,
            kind,
            message,
            mark,
            funding_pct,
            oi,
            cvd_5m,
            basis_pct,
            taker_buy_pct_5m
        FROM alerts
        {where}
        ORDER BY ts_ms, id
        """,
        params,
    ).fetchall()
    write_dicts_csv(path, [dict(row) for row in rows])
    return describe_file(path, "alert event rows")


def write_llm_prompt(out_dir: Path) -> dict[str, str]:
    path = out_dir / "11_llm_review_prompt.md"
    text = """# Review Prompt

You are reviewing persisted data from a local Hyperliquid USDC perp screener
that uses Bybit allLiquidation as its external liquidation-event source.
Use the files in this export to recommend precise tuning changes to the current
setup.

Focus on:

1. Whether alert thresholds are too noisy or too quiet by symbol.
2. Whether volume-scaled thresholds need different fractions or floors.
3. Whether `ALERT_IMPACT_EXCESS_BPS` and `ALERT_BOOK_IMBALANCE_PCT` match the
   observed book conditions.
4. Whether taker-flow cluster settings need a different minimum notional,
   bucket width, or count.
5. Whether each watchlist symbol should share one global config or need
   symbol-specific overrides.
6. Any persisted metrics that are always missing, stale, or non-discriminating.

Start with:

- `02_config.json`
- `03_table_counts.csv`
- `04_snapshot_symbol_summary.csv`
- `05_snapshot_metric_summary.csv`
- `07_trade_flow_minutes.csv`
- `08_flow_cluster_candidates.csv`
- `09_alert_summary.csv`
- `10_alerts.csv`

Recommend concrete changes as config diffs or exact replacement values, and
explain which rows or distributions support each recommendation.
"""
    path.write_text(text, encoding="utf-8")
    return describe_file(path, "LLM review prompt")


def write_raw_exports(
    conn: sqlite3.Connection,
    out_dir: Path,
    time_filter: TimeFilter,
    include_api_payloads: bool,
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []

    snapshot_columns = raw_columns(conn, "market_snapshots", include_api_payloads)
    files.append(
        write_query_csv(
            conn,
            out_dir / "raw_market_snapshots.csv",
            "market_snapshots",
            snapshot_columns,
            time_filter,
            "symbol, ts_ms",
        )
    )

    trade_columns = raw_columns(conn, "trades", include_api_payloads)
    files.append(
        write_query_csv(
            conn,
            out_dir / "raw_trades.csv",
            "trades",
            trade_columns,
            time_filter,
            "symbol, ts_ms, id",
        )
    )

    liquidation_columns = raw_columns(conn, "liquidations", include_api_payloads)
    files.append(
        write_query_csv(
            conn,
            out_dir / "raw_liquidations.csv",
            "liquidations",
            liquidation_columns,
            time_filter,
            "symbol, ts_ms, id",
        )
    )

    alert_columns = raw_columns(conn, "alerts", include_api_payloads)
    files.append(
        write_query_csv(
            conn,
            out_dir / "raw_alerts.csv",
            "alerts",
            alert_columns,
            time_filter,
            "symbol, ts_ms, id",
        )
    )
    return files


def raw_columns(
    conn: sqlite3.Connection, table: str, include_api_payloads: bool
) -> list[str]:
    excluded = set() if include_api_payloads else {"raw_json", "snapshot_json"}
    return [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        if row["name"] not in excluded
    ]


def write_query_csv(
    conn: sqlite3.Connection,
    path: Path,
    table: str,
    columns: list[str],
    time_filter: TimeFilter,
    order_by: str,
) -> dict[str, str]:
    where, params = time_filter.where()
    column_sql = ", ".join(columns)
    rows = conn.execute(
        f"""
        SELECT {column_sql}
        FROM {table}
        {where}
        ORDER BY {order_by}
        """,
        params,
    ).fetchall()
    write_dicts_csv(path, [dict(row) for row in rows], fieldnames=columns)
    return describe_file(path, f"raw {table} rows")


def load_snapshots(
    conn: sqlite3.Connection, time_filter: TimeFilter
) -> list[sqlite3.Row]:
    where, params = time_filter.where()
    columns = [
        "id",
        "ts_ms",
        "ts_utc",
        "symbol",
        "basis_source",
        "wall_side",
        *SNAPSHOT_METRICS,
    ]
    column_sql = ", ".join(columns)
    return conn.execute(
        f"""
        SELECT {column_sql}
        FROM market_snapshots
        {where}
        ORDER BY symbol, ts_ms
        """,
        params,
    ).fetchall()


def write_dicts_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: format_csv_cell(row.get(key)) for key in fieldnames})


def format_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.12g}"
    return value


def describe_file(path: Path, description: str) -> dict[str, str]:
    return {
        "path": str(path.name),
        "description": description,
    }


def is_jsonable(value: Any) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def metric_values(rows: list[sqlite3.Row], key: str) -> list[float]:
    values = []
    for row in rows:
        value = as_num(row[key])
        if value is not None:
            values.append(value)
    return values


def as_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def abs_num(value: Any) -> float:
    number = as_num(value)
    return abs(number) if number is not None else -math.inf


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def mean_abs(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(abs(value) for value in values) / len(values)


def percentile_abs(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return percentile([abs(value) for value in values], q)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def pct(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return part / total * 100


def count_matching(rows: list[sqlite3.Row], predicate: Any) -> int:
    count = 0
    for row in rows:
        try:
            if predicate(row):
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def cvd_capitulation_hit(cvd_5m: float | None, day_ntl_vlm: float | None) -> bool:
    if cvd_5m is None:
        return False
    threshold = volume_scaled_threshold(
        day_ntl_vlm,
        abs(config.ALERT_CVD_SHARP_NEG_USD),
        config.ALERT_CVD_SHARP_NEG_DAY_FRACTION,
    )
    return cvd_5m <= -threshold


def volume_scaled_threshold(
    day_ntl_vlm: float | None, default_usd: float, day_fraction: float
) -> float:
    if not day_ntl_vlm or day_ntl_vlm <= 0 or day_fraction <= 0:
        return default_usd
    scaled = day_ntl_vlm * day_fraction
    return max(config.ALERT_MIN_NOTIONAL_USD, min(default_usd, scaled))


def weighted_vwap(rows: list[sqlite3.Row]) -> float | None:
    qty_sum = 0.0
    px_qty_sum = 0.0
    for row in rows:
        qty = as_num(row["qty"])
        price = as_num(row["price"])
        if qty is None or price is None:
            continue
        qty_sum += qty
        px_qty_sum += price * qty
    if qty_sum > 0:
        return px_qty_sum / qty_sum
    prices = [value for row in rows if (value := as_num(row["price"])) is not None]
    return mean(prices)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ts_utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
