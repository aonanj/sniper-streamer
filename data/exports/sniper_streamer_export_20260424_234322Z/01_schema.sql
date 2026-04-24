CREATE TABLE alerts (
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

CREATE TABLE liquidations (
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

CREATE TABLE market_snapshots (
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

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE trades (
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

CREATE INDEX idx_alerts_symbol_ts
                ON alerts(symbol, ts_ms);

CREATE INDEX idx_liquidations_symbol_ts
                ON liquidations(symbol, ts_ms);

CREATE INDEX idx_market_snapshots_symbol_ts
                ON market_snapshots(symbol, ts_ms);

CREATE INDEX idx_trades_symbol_ts
                ON trades(symbol, ts_ms);
