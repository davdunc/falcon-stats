"""SQLite canonical store for falcon-stats.

Owns all SQL — raw sqlite3 stdlib, no ORM. Mirrors broker XLS columns 1:1
in `executions`, plus derived `round_trips` and `execution_to_roundtrip`
junction. See `db/migrations/001_initial.sql` for the full DDL.

Round-trip pairing is "blow away and rebuild" per (account, symbol):
`replace_round_trips` deletes affected rows and re-inserts. Executions
are append-only via `INSERT OR IGNORE` against the exec_id PRIMARY KEY.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB_PATH = Path(os.path.expanduser("~/Projects/Falcon/trades.db"))
MIGRATIONS_DIR = Path(__file__).parent / "db" / "migrations"


@dataclass
class ExecutionRow:
    """A single broker execution row, signed quantity preserved."""

    exec_id: str
    account: str
    trade_date: str
    trade_datetime: str
    quantity: int  # signed: +buy, -sell
    symbol: str
    description: str | None
    price: float
    trans_fee: float
    ecn_taker: float
    ecn_maker: float
    orf_fee: float
    taf_fee: float
    sec_fee: float
    cat_fee: float
    amount: float
    type: str | None
    commissions: float
    source_file: str

    @property
    def fees(self) -> float:
        return (
            abs(self.trans_fee)
            + abs(self.ecn_taker)
            + abs(self.ecn_maker)
            + abs(self.orf_fee)
            + abs(self.taf_fee)
            + abs(self.sec_fee)
            + abs(self.cat_fee)
            + abs(self.commissions)
        )


def get_db_path(override: str | Path | None = None) -> Path:
    """Resolve DB path: explicit override > $FALCON_DB > default."""
    if override:
        return Path(os.path.expanduser(str(override)))
    env = os.getenv("FALCON_DB")
    if env:
        return Path(os.path.expanduser(env))
    return DEFAULT_DB_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys + row factory enabled."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in numeric order. Idempotent.

    Returns the latest schema version after applying.
    """
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    current = cur.fetchone()[0] or 0
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        version = int(f.name.split("_", 1)[0])
        if version <= current:
            continue
        sql = f.read_text()
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        current = version
    return current


def compute_exec_id(
    account: str,
    trade_datetime: str,
    symbol: str,
    quantity: int,
    price: float,
    amount: float,
) -> str:
    """Stable hash for idempotent ingest. Contract §1.1."""
    key = f"{account}|{trade_datetime}|{symbol}|{quantity}|{price:.4f}|{amount:.2f}"
    return hashlib.sha1(key.encode()).hexdigest()


def insert_executions(
    conn: sqlite3.Connection,
    rows: list[ExecutionRow],
) -> tuple[int, int]:
    """INSERT OR IGNORE executions. Returns (attempted, newly_inserted)."""
    ingested_at = datetime.now(timezone.utc).isoformat()
    before = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    conn.executemany(
        """
        INSERT OR IGNORE INTO executions (
            exec_id, account, trade_date, trade_datetime, quantity, symbol,
            description, price, trans_fee, ecn_taker, ecn_maker, orf_fee,
            taf_fee, sec_fee, cat_fee, amount, type, commissions,
            source_file, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.exec_id,
                r.account,
                r.trade_date,
                r.trade_datetime,
                r.quantity,
                r.symbol,
                r.description,
                r.price,
                r.trans_fee,
                r.ecn_taker,
                r.ecn_maker,
                r.orf_fee,
                r.taf_fee,
                r.sec_fee,
                r.cat_fee,
                r.amount,
                r.type,
                r.commissions,
                r.source_file,
                ingested_at,
            )
            for r in rows
        ],
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    return (len(rows), after - before)


def affected_symbols_for_file(
    conn: sqlite3.Connection, source_file: str
) -> list[tuple[str, str]]:
    """Return all (account, symbol) tuples touched by a given source file."""
    cur = conn.execute(
        "SELECT DISTINCT account, symbol FROM executions WHERE source_file = ?",
        (source_file,),
    )
    return [(r["account"], r["symbol"]) for r in cur]


def read_executions_for_symbol(
    conn: sqlite3.Connection, account: str, symbol: str
) -> list[ExecutionRow]:
    """Read all executions for an (account, symbol) ordered by time, exec_id."""
    cur = conn.execute(
        """
        SELECT * FROM executions
        WHERE account = ? AND symbol = ?
        ORDER BY trade_datetime, exec_id
        """,
        (account, symbol),
    )
    out = []
    for r in cur:
        out.append(
            ExecutionRow(
                exec_id=r["exec_id"],
                account=r["account"],
                trade_date=r["trade_date"],
                trade_datetime=r["trade_datetime"],
                quantity=r["quantity"],
                symbol=r["symbol"],
                description=r["description"],
                price=float(r["price"]),
                trans_fee=float(r["trans_fee"] or 0),
                ecn_taker=float(r["ecn_taker"] or 0),
                ecn_maker=float(r["ecn_maker"] or 0),
                orf_fee=float(r["orf_fee"] or 0),
                taf_fee=float(r["taf_fee"] or 0),
                sec_fee=float(r["sec_fee"] or 0),
                cat_fee=float(r["cat_fee"] or 0),
                amount=float(r["amount"]),
                type=r["type"],
                commissions=float(r["commissions"] or 0),
                source_file=r["source_file"],
            )
        )
    return out


def replace_round_trips(
    conn: sqlite3.Connection,
    account: str,
    symbol: str,
    results: list,
) -> int:
    """Delete + re-insert all round_trips for (account, symbol).

    `results` is a list of `RoundTripResult` from pairing.pair_executions.
    Junction rows in `execution_to_roundtrip` cascade-delete via FK.
    Returns the number of round-trips inserted.
    """
    computed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "DELETE FROM round_trips WHERE account = ? AND symbol = ?",
        (account, symbol),
    )
    inserted = 0
    for rt in results:
        cur = conn.execute(
            """
            INSERT INTO round_trips (
                account, symbol, side, shares, avg_entry, avg_exit,
                entry_count, exit_count, open_date, close_date,
                open_time, close_time, pnl, fees, is_swing, is_winner,
                is_closed, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rt.account,
                rt.symbol,
                rt.side,
                rt.shares,
                rt.avg_entry,
                rt.avg_exit,
                rt.entry_count,
                rt.exit_count,
                rt.open_date,
                rt.close_date,
                rt.open_time,
                rt.close_time,
                rt.pnl,
                rt.fees,
                1 if rt.is_swing else 0,
                None if rt.is_winner is None else (1 if rt.is_winner else 0),
                1 if rt.is_closed else 0,
                computed_at,
            ),
        )
        rt_id = cur.lastrowid
        junction = [(eid, rt_id, "open") for eid in rt.entry_exec_ids] + [
            (eid, rt_id, "close") for eid in rt.exit_exec_ids
        ]
        if junction:
            conn.executemany(
                "INSERT OR IGNORE INTO execution_to_roundtrip "
                "(exec_id, round_trip_id, role) VALUES (?, ?, ?)",
                junction,
            )
        inserted += 1
    conn.commit()
    return inserted


def _rt_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "account": r["account"],
        "symbol": r["symbol"],
        "side": r["side"],
        "shares": r["shares"],
        "avg_entry": float(r["avg_entry"]) if r["avg_entry"] is not None else None,
        "avg_exit": float(r["avg_exit"]) if r["avg_exit"] is not None else None,
        "entry_count": r["entry_count"],
        "exit_count": r["exit_count"],
        "open_date": r["open_date"],
        "close_date": r["close_date"],
        "open_time": r["open_time"],
        "close_time": r["close_time"],
        "pnl": float(r["pnl"]) if r["pnl"] is not None else None,
        "fees": float(r["fees"]) if r["fees"] is not None else 0.0,
        "is_swing": bool(r["is_swing"]),
        "is_winner": None if r["is_winner"] is None else bool(r["is_winner"]),
        "is_closed": bool(r["is_closed"]),
    }


def read_round_trips_for_date(
    conn: sqlite3.Connection, date: str, account: str | None = None
) -> list[dict]:
    """Read all round-trips that CLOSED on `date`."""
    if account:
        cur = conn.execute(
            "SELECT * FROM round_trips WHERE close_date = ? AND account = ? "
            "ORDER BY close_time",
            (date, account),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM round_trips WHERE close_date = ? ORDER BY close_time",
            (date,),
        )
    return [_rt_row_to_dict(r) for r in cur]


def read_round_trips_for_range(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    account: str | None = None,
) -> list[dict]:
    """Read all round-trips that CLOSED in [start, end] inclusive."""
    if account:
        cur = conn.execute(
            "SELECT * FROM round_trips WHERE close_date BETWEEN ? AND ? "
            "AND account = ? ORDER BY close_time",
            (start, end, account),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM round_trips WHERE close_date BETWEEN ? AND ? "
            "ORDER BY close_time",
            (start, end),
        )
    return [_rt_row_to_dict(r) for r in cur]
