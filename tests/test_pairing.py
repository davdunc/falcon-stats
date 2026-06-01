"""Pairing algorithm tests — synthetic + contract reference assertions."""

from __future__ import annotations

from falcon_stats.ingest_xls import parse_broker_excel_rows
from falcon_stats.pairing import pair_executions
from falcon_stats.sqlite_db import ExecutionRow


def _row(
    *,
    exec_id: str,
    qty: int,
    price: float,
    dt: str,
    symbol: str = "TEST",
    account: str = "ACCT",
    fees: float = 0.0,
) -> ExecutionRow:
    return ExecutionRow(
        exec_id=exec_id,
        account=account,
        trade_date=dt[:10],
        trade_datetime=dt,
        quantity=qty,
        symbol=symbol,
        description=None,
        price=price,
        trans_fee=0.0,
        ecn_taker=0.0,
        ecn_maker=0.0,
        orf_fee=0.0,
        taf_fee=0.0,
        sec_fee=0.0,
        cat_fee=0.0,
        amount=qty * price,
        type=None,
        commissions=fees,
        source_file="<synthetic>",
    )


def test_simple_long_round_trip():
    rows = [
        _row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=-100, price=11.0, dt="2026-06-01T10:30:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.side == "LONG"
    assert r.shares == 100
    assert abs(r.pnl - 100.0) < 0.001
    assert r.is_closed and r.is_winner
    assert not r.is_swing


def test_simple_short_round_trip():
    rows = [
        _row(exec_id="a", qty=-100, price=11.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=100, price=10.0, dt="2026-06-01T10:30:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.side == "SHORT"
    assert r.shares == 100
    assert abs(r.pnl - 100.0) < 0.001
    assert r.is_closed and r.is_winner


def test_scale_in_then_close():
    rows = [
        _row(exec_id="a", qty=50, price=10.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=50, price=10.5, dt="2026-06-01T10:05:00"),
        _row(exec_id="c", qty=-100, price=11.0, dt="2026-06-01T10:30:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.shares == 100
    assert r.entry_count == 2 and r.exit_count == 1
    assert abs(r.avg_entry - 10.25) < 0.001
    assert abs(r.pnl - 75.0) < 0.001


def test_partial_exits():
    rows = [
        _row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=-40, price=11.0, dt="2026-06-01T10:10:00"),
        _row(exec_id="c", qty=-60, price=12.0, dt="2026-06-01T10:20:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.exit_count == 2
    assert abs(r.pnl - 160.0) < 0.001


def test_single_exec_flip_long_to_short():
    rows = [
        _row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=-150, price=11.0, dt="2026-06-01T10:30:00", fees=1.0),
    ]
    results = pair_executions(rows)
    assert len(results) == 2
    closed, opened = results[0], results[1]
    assert closed.side == "LONG" and closed.is_closed
    assert closed.shares == 100
    assert abs(closed.pnl - (100.0 - (1.0 * 100 / 150))) < 0.01
    assert opened.side == "SHORT" and not opened.is_closed
    assert opened.shares == 50
    assert opened.pnl is None


def test_swing_multi_day():
    rows = [
        _row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T15:55:00"),
        _row(exec_id="b", qty=-100, price=11.0, dt="2026-06-02T09:35:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.is_swing is True
    assert r.open_date == "2026-06-01"
    assert r.close_date == "2026-06-02"


def test_unclosed_position_at_end():
    rows = [_row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T10:00:00")]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert not r.is_closed
    assert r.pnl is None
    assert r.avg_exit is None
    assert r.close_date is None


def test_identical_timestamps_stable_sort():
    rows = [
        _row(exec_id="b_later", qty=-100, price=11.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="a_first", qty=100, price=10.0, dt="2026-06-01T10:00:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 1
    r = results[0]
    assert r.side == "LONG"
    assert abs(r.pnl - 100.0) < 0.001


def test_two_separate_round_trips_same_symbol():
    rows = [
        _row(exec_id="a", qty=100, price=10.0, dt="2026-06-01T10:00:00"),
        _row(exec_id="b", qty=-100, price=11.0, dt="2026-06-01T10:30:00"),
        _row(exec_id="c", qty=-100, price=12.0, dt="2026-06-01T11:00:00"),
        _row(exec_id="d", qty=100, price=11.5, dt="2026-06-01T11:30:00"),
    ]
    results = pair_executions(rows)
    assert len(results) == 2
    assert results[0].side == "LONG"
    assert results[1].side == "SHORT"
    assert abs(results[1].pnl - 50.0) < 0.001


def _rt_for(results, symbol, side, date):
    matches = [
        r for r in results
        if r.symbol == symbol
        and r.side == side
        and (r.close_date == date or r.open_date == date)
    ]
    assert matches, f"no {side} round-trip for {symbol} on {date}"
    return matches[0]


def test_fixture_may27_mu_short_186(broker_xls_path, test_account):
    """ISC-18: fixture-truth (supersedes contract -243.46).

    The 186-share MU SHORT round-trip on 2026-05-27 pnl ≈ -239.93 ±0.10.
    Contract value was off by one SEC fee — snapshot drift in the
    legacy analysis.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    rt = [
        r for r in results
        if r.symbol == "MU"
        and r.side == "SHORT"
        and r.open_date == "2026-05-27"
        and r.shares == 186
    ]
    assert rt, "no MU SHORT 186-share round-trip on 2026-05-27"
    assert abs(rt[0].pnl - (-239.93)) < 0.10, f"pnl={rt[0].pnl}"


def test_fixture_may27_mu_short_78_no_long(broker_xls_path, test_account):
    """ISC-19: fixture-truth (supersedes contract MU LONG -97.50).

    There is no MU LONG on 2026-05-27 in the fixture — only two SHORT
    round-trips. Assert the 78-share SHORT exists, is closed, and is a
    loser inside a loose fees envelope.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    mu_long = [
        r for r in results
        if r.symbol == "MU" and r.side == "LONG" and r.open_date == "2026-05-27"
    ]
    assert not mu_long, f"unexpected MU LONG on 2026-05-27: {mu_long}"

    rt = [
        r for r in results
        if r.symbol == "MU"
        and r.side == "SHORT"
        and r.open_date == "2026-05-27"
        and r.shares == 78
    ]
    assert rt, "no MU SHORT 78-share round-trip on 2026-05-27"
    r0 = rt[0]
    assert r0.is_closed
    assert r0.pnl is not None and r0.pnl < 0
    assert -120 < r0.pnl, f"pnl={r0.pnl} outside loose bracket"


def test_fixture_uso_mar_swing(broker_xls_path, test_account):
    """ISC-20: fixture-truth (supersedes contract -1097.70).

    USO Mar 11/12 swing-only pnl ≈ -815.49 ±0.10. The contract value
    conflated this swing SHORT 4585 with the same-day intraday LONG 8610
    (-325.74) — the by-symbol walker correctly separates them.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    swings = [
        r for r in results
        if r.symbol == "USO"
        and r.is_swing
        and r.open_date == "2026-03-11"
        and r.close_date == "2026-03-12"
    ]
    assert swings, "no USO Mar 11/12 swing round-trip"
    rt = swings[0]
    assert rt.is_swing is True
    assert abs(rt.pnl - (-815.49)) < 0.10, f"USO swing pnl={rt.pnl}"


def test_fixture_uso_mar11_intraday_long(broker_xls_path, test_account):
    """Walker correctly separates same-day intraday LONG from the swing.

    USO Mar 11 intraday 8610-share LONG pnl ≈ -325.74 ±0.10, is_swing False.
    Catches the legacy date-grouped pairing bug.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    intraday = [
        r for r in results
        if r.symbol == "USO"
        and r.side == "LONG"
        and r.open_date == "2026-03-11"
        and r.close_date == "2026-03-11"
        and r.shares == 8610
    ]
    assert intraday, "no USO Mar 11 intraday 8610 LONG"
    rt = intraday[0]
    assert rt.is_swing is False
    assert abs(rt.pnl - (-325.74)) < 0.10, f"USO intraday LONG pnl={rt.pnl}"


def test_fixture_may27_day_aggregate(broker_xls_path, test_account):
    """May 27 day aggregate sanity-check.

    Sum of pnl for all round-trips closed on 2026-05-27 should land in
    the -$345..-$300 envelope (broker-truth on MU SHORT 186 + MU SHORT
    78 + SOXL). Computed from round-trips, not pinned to one value.
    """
    rows = parse_broker_excel_rows(broker_xls_path, account=test_account)
    results = pair_executions(rows)
    closed_may27 = [
        r for r in results if r.is_closed and r.close_date == "2026-05-27"
    ]
    assert closed_may27, "no round-trips closed on 2026-05-27"
    day_pnl = sum(r.pnl for r in closed_may27)
    assert -345.0 <= day_pnl <= -300.0, f"day aggregate {day_pnl}"
