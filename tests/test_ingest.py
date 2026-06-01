"""XLS → SQLite ingest tests: idempotency, schema, and contract reference."""

from __future__ import annotations

from falcon_stats.ingest_xls import parse_broker_excel_rows, refresh_from_paths
from falcon_stats.pairing import pair_executions
from falcon_stats.sqlite_db import (
    apply_migrations,
    connect,
    insert_executions,
    read_round_trips_for_date,
)


def test_parse_extracts_rows(broker_xls_path, test_account):
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    assert len(rows) > 100, f"only parsed {len(rows)} rows"
    assert all(r.account == test_account for r in rows)
    assert all(r.exec_id for r in rows)
    assert all(r.source_file == broker_xls_path.name for r in rows)
    assert all(r.quantity != 0 for r in rows)


def test_exec_id_is_stable(broker_xls_path, test_account):
    a = parse_broker_excel_rows(broker_xls_path, account=test_account)
    b = parse_broker_excel_rows(broker_xls_path, account=test_account)
    assert [r.exec_id for r in a] == [r.exec_id for r in b]


def test_schema_apply_idempotent(tmp_db_path):
    conn = connect(tmp_db_path)
    v1 = apply_migrations(conn)
    v2 = apply_migrations(conn)
    assert v1 == v2 == 1
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"executions", "round_trips", "execution_to_roundtrip", "schema_version"} <= tables
    conn.close()


def test_insert_idempotent(broker_xls_path, test_account, tmp_db_path):
    conn = connect(tmp_db_path)
    apply_migrations(conn)
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    attempted_1, new_1 = insert_executions(conn, rows)
    attempted_2, new_2 = insert_executions(conn, rows)
    assert new_1 == len(rows)
    assert new_2 == 0
    total = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    assert total == new_1
    conn.close()


def test_refresh_from_paths_end_to_end(broker_xls_path, test_account, tmp_db_path):
    stats = refresh_from_paths(
        paths=[str(broker_xls_path)],
        account=test_account,
        db_path=tmp_db_path,
    )
    assert stats["executions_parsed"] > 0
    assert stats["executions_new"] == stats["executions_parsed"]
    assert stats["round_trips_computed"] > 0

    stats2 = refresh_from_paths(
        paths=[str(broker_xls_path)],
        account=test_account,
        db_path=tmp_db_path,
    )
    assert stats2["executions_new"] == 0
    assert stats2["round_trips_computed"] == stats["round_trips_computed"]


def test_refresh_dry_run_writes_nothing(broker_xls_path, test_account, tmp_db_path):
    stats = refresh_from_paths(
        paths=[str(broker_xls_path)],
        account=test_account,
        db_path=tmp_db_path,
        dry_run=True,
    )
    assert stats["dry_run"] is True
    assert stats["executions_parsed"] > 0
    assert not tmp_db_path.exists()


def test_soxl_round_trip(broker_xls_path, test_account, tmp_db_path):
    """One SOXL round-trip should land near +$5.55 (±$0.10 fees tolerance).

    Per team-lead message; contract §7.2 enumerates only MU + USO assertions
    with ±$0.05 tolerance — SOXL is auxiliary verification of small-pnl
    fee accounting and uses a wider window to absorb broker fee rounding.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    soxl = [r for r in results if r.symbol == "SOXL" and r.is_closed]
    assert soxl, "no closed SOXL round-trip"
    pnls = [r.pnl for r in soxl]
    assert any(abs(p - 5.55) < 0.10 for p in pnls), f"SOXL pnls: {pnls}"


def test_round_trips_persisted_to_db(broker_xls_path, test_account, tmp_db_path):
    """Fixture-truth DB round-trip: MU SHORT 186 ≈ -239.93, ≥1 swing present."""
    refresh_from_paths(
        paths=[str(broker_xls_path)],
        account=test_account,
        db_path=tmp_db_path,
    )
    conn = connect(tmp_db_path)
    try:
        may27 = read_round_trips_for_date(conn, "2026-05-27", account=test_account)
        assert may27, "expected round-trips closed on 2026-05-27"
        mu_short_186 = [
            r for r in may27
            if r["symbol"] == "MU" and r["side"] == "SHORT" and r["shares"] == 186
        ]
        assert mu_short_186, "no MU SHORT 186-share in DB for 2026-05-27"
        assert abs(mu_short_186[0]["pnl"] - (-239.93)) < 0.10

        swings = conn.execute(
            "SELECT COUNT(*) FROM round_trips WHERE is_swing = 1"
        ).fetchone()[0]
        assert swings >= 1
    finally:
        conn.close()
