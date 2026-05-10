"""Tests for round-trip identification, especially flip-through-zero handling."""

from datetime import datetime, timedelta

import pytest

from falcon_stats.models import Trade, Side
from falcon_stats.roundtrips import identify_round_trips


def _t(idx: int, side: str, qty: int, price: float, symbol: str = "TEST", account: str = "ACCT_SIM") -> Trade:
    """Build a Trade for tests. idx orders trades chronologically."""
    return Trade(
        trade_id=idx,
        order_id=idx,
        account=account,
        symbol=symbol,
        side=Side.BUY if side == "B" else Side.SELL,
        quantity=qty,
        price=price,
        time=datetime(2026, 5, 4, 9, 0) + timedelta(seconds=idx),
    )


# --------------------------------------------------------------------------
# Baseline behavior — no flips
# --------------------------------------------------------------------------

def test_simple_long_round_trip():
    trades = [_t(1, "B", 5, 100.0), _t(2, "S", 5, 105.0)]
    rts = identify_round_trips(trades)
    assert len(rts) == 1
    assert rts[0].side == Side.BUY
    assert rts[0].is_closed
    assert rts[0].pnl == pytest.approx(25.0)


def test_simple_short_round_trip():
    trades = [_t(1, "S", 5, 100.0), _t(2, "B", 5, 95.0)]
    rts = identify_round_trips(trades)
    assert len(rts) == 1
    assert rts[0].side == Side.SELL
    assert rts[0].pnl == pytest.approx(25.0)


def test_scale_in_then_full_exit():
    trades = [_t(1, "B", 5, 100.0), _t(2, "B", 5, 102.0), _t(3, "S", 10, 105.0)]
    rts = identify_round_trips(trades)
    assert len(rts) == 1
    assert rts[0].total_shares == 10
    # avg_entry = (5*100 + 5*102) / 10 = 101; avg_exit = 105; pnl = 4 * 10 = 40
    assert rts[0].pnl == pytest.approx(40.0)


def test_partial_exit_then_full_exit():
    trades = [_t(1, "B", 10, 100.0), _t(2, "S", 4, 102.0), _t(3, "S", 6, 105.0)]
    rts = identify_round_trips(trades)
    assert len(rts) == 1
    # avg_exit = (4*102 + 6*105) / 10 = 103.8; pnl = (103.8 - 100) * 10 = 38
    assert rts[0].pnl == pytest.approx(38.0)


def test_two_separate_round_trips_same_symbol():
    trades = [
        _t(1, "B", 5, 100.0), _t(2, "S", 5, 102.0),
        _t(3, "B", 5, 99.0),  _t(4, "S", 5, 101.0),
    ]
    rts = identify_round_trips(trades)
    assert len(rts) == 2
    assert rts[0].pnl == pytest.approx(10.0)
    assert rts[1].pnl == pytest.approx(10.0)


# --------------------------------------------------------------------------
# Flip-through-zero — the bug this fix addresses
# --------------------------------------------------------------------------

def test_long_to_short_flip_creates_two_round_trips():
    """Position +5, then SELL 15 -> position -10. Then BUY 10 covers."""
    trades = [
        _t(1, "B",  5, 100.0),
        _t(2, "S", 15, 102.0),  # closes long, opens short -10
        _t(3, "B", 10,  99.0),  # covers short
    ]
    rts = identify_round_trips(trades)
    assert len(rts) == 2

    # First RT: long 5 sh, in 100, out 102 -> +10
    long_rt = rts[0]
    assert long_rt.side == Side.BUY
    assert long_rt.total_shares == 5
    assert long_rt.pnl == pytest.approx(10.0)

    # Second RT: short 10 sh, in 102, covered 99 -> +30
    short_rt = rts[1]
    assert short_rt.side == Side.SELL
    assert short_rt.total_shares == 10
    assert short_rt.pnl == pytest.approx(30.0)


def test_short_to_long_flip_creates_two_round_trips():
    """Position -5, then BUY 15 -> position +10. Then SELL 10 closes long."""
    trades = [
        _t(1, "S",  5, 100.0),
        _t(2, "B", 15,  98.0),  # covers short, opens long +10
        _t(3, "S", 10, 101.0),
    ]
    rts = identify_round_trips(trades)
    assert len(rts) == 2

    short_rt = rts[0]
    assert short_rt.side == Side.SELL
    assert short_rt.total_shares == 5
    assert short_rt.pnl == pytest.approx(10.0)  # (100 - 98) * 5

    long_rt = rts[1]
    assert long_rt.side == Side.BUY
    assert long_rt.total_shares == 10
    assert long_rt.pnl == pytest.approx(30.0)  # (101 - 98) * 10


def test_flip_synthetic_trades_have_parent_trade_id():
    """Audit: synthetic split fills must reference the original trade."""
    trades = [
        _t(1, "B",  5, 100.0),
        _t(2, "S", 15, 102.0),  # the flipping trade
        _t(3, "B", 10,  99.0),
    ]
    rts = identify_round_trips(trades)

    # The exit in the long RT is a synthetic from trade 2
    long_exit = rts[0].exits[0]
    assert long_exit.is_synthetic
    assert long_exit.parent_trade_id == 2
    assert long_exit.quantity == 5

    # The entry in the short RT is the other synthetic from trade 2
    short_entry = rts[1].entries[0]
    assert short_entry.is_synthetic
    assert short_entry.parent_trade_id == 2
    assert short_entry.quantity == 10


def test_flip_does_not_affect_non_flipping_trades_in_same_symbol():
    """Mixed sequence: clean RT, then flip, then another clean RT."""
    trades = [
        _t(1, "B", 5, 100.0), _t(2, "S", 5, 102.0),       # clean long RT (+10)
        _t(3, "B", 5, 100.0), _t(4, "S", 15, 102.0),      # flip
        _t(5, "B", 10, 99.0),                              # close short
        _t(6, "S", 5, 100.0), _t(7, "B", 5, 99.0),        # clean short RT (+5)
    ]
    rts = identify_round_trips(trades)
    assert len(rts) == 4
    # Clean long
    assert rts[0].side == Side.BUY and rts[0].pnl == pytest.approx(10.0)
    # Long portion of flip
    assert rts[1].side == Side.BUY and rts[1].pnl == pytest.approx(10.0)
    # Short portion of flip
    assert rts[2].side == Side.SELL and rts[2].pnl == pytest.approx(30.0)
    # Clean short
    assert rts[3].side == Side.SELL and rts[3].pnl == pytest.approx(5.0)


# --------------------------------------------------------------------------
# Regression — May 4 GOOGL flip from real data
# --------------------------------------------------------------------------

def test_may4_googl_flip_regression():
    """The actual May 4 GOOGL 11:11 flip that triggered the $9.17 reconciliation gap.

    Pre-flip context: position is +5 from earlier scaling. The flipping trade is
    SELL 15 @ 381.93. Then BUY 10 @ 381.42 covers the short.

    Expected post-fix:
      LONG RT: 10 sh entry (382.80, 382.52) avg 382.66; exits 5 @ 382.64 + 5 @ 381.93
               avg_exit = (5*382.64 + 5*381.93)/10 = 382.285; pnl = -3.75
      SHORT RT: 10 sh from flip @ 381.93; covered @ 381.42; pnl = +5.10
    """
    trades = [
        _t(1, "B", 5, 382.80, symbol="GOOGL"),
        _t(2, "B", 5, 382.52, symbol="GOOGL"),  # pos +10
        _t(3, "S", 5, 382.64, symbol="GOOGL"),  # pos +5
        _t(4, "S", 15, 381.93, symbol="GOOGL"), # flip: pos -> -10
        _t(5, "B", 10, 381.42, symbol="GOOGL"), # cover short
    ]
    rts = identify_round_trips(trades)
    assert len(rts) == 2

    long_rt, short_rt = rts
    assert long_rt.side == Side.BUY
    assert long_rt.total_shares == 10
    assert long_rt.pnl == pytest.approx(-3.75, abs=0.01)

    assert short_rt.side == Side.SELL
    assert short_rt.total_shares == 10
    assert short_rt.pnl == pytest.approx(5.10, abs=0.01)

    # Net of the flip cluster = +1.35 (vs the pre-fix buggy -7.82, $9.17 delta)
    assert (long_rt.pnl + short_rt.pnl) == pytest.approx(1.35, abs=0.01)
