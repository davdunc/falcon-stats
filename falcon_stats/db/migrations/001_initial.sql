-- Falcon-stats canonical SQLite schema.
-- Applied by falcon_stats.sqlite_db.apply_migrations().
-- Schema version 1.

CREATE TABLE IF NOT EXISTS executions (
    exec_id          TEXT PRIMARY KEY,
    account          TEXT NOT NULL,
    trade_date       TEXT NOT NULL,
    trade_datetime   TEXT NOT NULL,
    quantity         INTEGER NOT NULL,
    symbol           TEXT NOT NULL,
    description      TEXT,
    price            NUMERIC NOT NULL,
    trans_fee        NUMERIC DEFAULT 0,
    ecn_taker        NUMERIC DEFAULT 0,
    ecn_maker        NUMERIC DEFAULT 0,
    orf_fee          NUMERIC DEFAULT 0,
    taf_fee          NUMERIC DEFAULT 0,
    sec_fee          NUMERIC DEFAULT 0,
    cat_fee          NUMERIC DEFAULT 0,
    amount           NUMERIC NOT NULL,
    type             TEXT,
    commissions      NUMERIC DEFAULT 0,
    source_file      TEXT NOT NULL,
    ingested_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exec_acct_sym_dt
    ON executions(account, symbol, trade_datetime);
CREATE INDEX IF NOT EXISTS idx_exec_date
    ON executions(trade_date);

CREATE TABLE IF NOT EXISTS round_trips (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account          TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
    shares           INTEGER NOT NULL,
    avg_entry        NUMERIC NOT NULL,
    avg_exit         NUMERIC,
    entry_count      INTEGER NOT NULL,
    exit_count       INTEGER NOT NULL,
    open_date        TEXT NOT NULL,
    close_date       TEXT,
    open_time        TEXT NOT NULL,
    close_time       TEXT,
    pnl              NUMERIC,
    fees             NUMERIC NOT NULL,
    is_swing         INTEGER NOT NULL DEFAULT 0,
    is_winner        INTEGER,
    is_closed        INTEGER NOT NULL DEFAULT 0,
    computed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rt_acct_date ON round_trips(account, open_date);
CREATE INDEX IF NOT EXISTS idx_rt_symbol ON round_trips(symbol);
CREATE INDEX IF NOT EXISTS idx_rt_close_date ON round_trips(close_date);
CREATE INDEX IF NOT EXISTS idx_rt_swing ON round_trips(is_swing) WHERE is_swing = 1;

CREATE TABLE IF NOT EXISTS execution_to_roundtrip (
    exec_id          TEXT NOT NULL,
    round_trip_id    INTEGER NOT NULL,
    role             TEXT NOT NULL CHECK(role IN ('open','close')),
    PRIMARY KEY (exec_id, round_trip_id),
    FOREIGN KEY (exec_id) REFERENCES executions(exec_id) ON DELETE CASCADE,
    FOREIGN KEY (round_trip_id) REFERENCES round_trips(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_e2r_rtid ON execution_to_roundtrip(round_trip_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
