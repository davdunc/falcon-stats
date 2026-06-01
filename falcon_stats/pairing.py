"""Round-trip pairing — canonical implementation.

By-symbol position walker per CONTRACT §7. Operates on `ExecutionRow`
(signed-quantity rows from sqlite_db) — no `Trade`/`Side`/`Order` knowledge.

`roundtrips.py` is a thin backward-compat shim that converts the legacy
`list[Trade]` API into this module's inputs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .sqlite_db import ExecutionRow


@dataclass
class RoundTripResult:
    """One round-trip emitted by `pair_executions`."""

    account: str
    symbol: str
    side: str  # 'LONG' | 'SHORT'
    shares: int  # total entered, positive
    avg_entry: float
    avg_exit: float | None
    entry_count: int
    exit_count: int
    open_date: str
    close_date: str | None
    open_time: str
    close_time: str | None
    pnl: float | None
    fees: float
    is_swing: bool
    is_winner: bool | None
    is_closed: bool
    entry_exec_ids: list[str] = field(default_factory=list)
    exit_exec_ids: list[str] = field(default_factory=list)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _emit(
    account: str,
    symbol: str,
    side: str,
    entry_legs: list[tuple[ExecutionRow, int]],
    exit_legs: list[tuple[ExecutionRow, int]],
    cost_basis: float,
    proceeds: float,
    entry_fees: float,
    exit_fees: float,
    is_closed: bool = True,
) -> RoundTripResult:
    """Materialize the accumulated legs into a RoundTripResult.

    `cost_basis` and `proceeds` are BOTH signed by exec.quantity sign per
    contract §7 docstring:
      - LONG entry qty>0 → cost_basis>0; LONG exit qty<0 → proceeds<0
      - SHORT entry qty<0 → cost_basis<0; SHORT exit qty>0 → proceeds>0
      - gross_pnl = -(cost_basis + proceeds)
    """
    total_shares = sum(s for _, s in entry_legs)
    avg_entry = abs(cost_basis) / total_shares if total_shares else 0.0

    if is_closed and exit_legs:
        exited_shares = sum(s for _, s in exit_legs)
        avg_exit: float | None = (
            abs(proceeds) / exited_shares if exited_shares else 0.0
        )
        gross_pnl = -(cost_basis + proceeds)
        total_fees = entry_fees + exit_fees
        pnl: float | None = gross_pnl - total_fees
        is_winner: bool | None = pnl > 0
        close_time = max(e.trade_datetime for e, _ in exit_legs)
        close_date = close_time.split("T")[0] if "T" in close_time else close_time[:10]
    else:
        avg_exit = None
        pnl = None
        is_winner = None
        close_time = None
        close_date = None
        total_fees = entry_fees + exit_fees

    open_time = min(e.trade_datetime for e, _ in entry_legs)
    open_date = open_time.split("T")[0] if "T" in open_time else open_time[:10]
    is_swing = bool(close_date and close_date != open_date)

    return RoundTripResult(
        account=account,
        symbol=symbol,
        side=side,
        shares=total_shares,
        avg_entry=avg_entry,
        avg_exit=avg_exit,
        entry_count=len(entry_legs),
        exit_count=len(exit_legs),
        open_date=open_date,
        close_date=close_date,
        open_time=open_time,
        close_time=close_time,
        pnl=pnl,
        fees=total_fees,
        is_swing=is_swing,
        is_winner=is_winner,
        is_closed=is_closed,
        entry_exec_ids=[e.exec_id for e, _ in entry_legs],
        exit_exec_ids=[e.exec_id for e, _ in exit_legs],
    )


def pair_executions(execs: list[ExecutionRow]) -> list[RoundTripResult]:
    """Walk executions by-symbol and emit round-trips.

    Algorithm verbatim from CONTRACT §7. Handles same-day, swing, scale-in,
    partial exits, and single-exec flips.
    """
    results: list[RoundTripResult] = []
    groups: dict[tuple[str, str], list[ExecutionRow]] = defaultdict(list)
    for e in execs:
        groups[(e.account, e.symbol)].append(e)

    for (account, symbol), group in groups.items():
        sorted_execs = sorted(group, key=lambda e: (e.trade_datetime, e.exec_id))
        position = 0
        entry_legs: list[tuple[ExecutionRow, int]] = []
        exit_legs: list[tuple[ExecutionRow, int]] = []
        cost_basis = 0.0
        proceeds = 0.0
        entry_fees = 0.0
        exit_fees = 0.0
        side: str | None = None

        for e in sorted_execs:
            qty = e.quantity

            if position == 0:
                side = "LONG" if qty > 0 else "SHORT"
                entry_legs.append((e, abs(qty)))
                cost_basis += e.price * qty
                entry_fees += e.fees
                position = qty
                continue

            if _sign(qty) == _sign(position):
                entry_legs.append((e, abs(qty)))
                cost_basis += e.price * qty
                entry_fees += e.fees
                position += qty
                continue

            new_position = position + qty
            if new_position == 0 or _sign(new_position) == _sign(position):
                exit_legs.append((e, abs(qty)))
                proceeds += e.price * qty
                exit_fees += e.fees
                position = new_position
                if position == 0:
                    results.append(
                        _emit(
                            account,
                            symbol,
                            side or "LONG",
                            entry_legs,
                            exit_legs,
                            cost_basis,
                            proceeds,
                            entry_fees,
                            exit_fees,
                        )
                    )
                    entry_legs, exit_legs = [], []
                    cost_basis = proceeds = entry_fees = exit_fees = 0.0
                    side = None
                continue

            close_sh = abs(position)
            open_sh = abs(new_position)
            total = close_sh + open_sh
            close_fee = e.fees * close_sh / total
            open_fee = e.fees * open_sh / total

            exit_legs.append((e, close_sh))
            proceeds += e.price * close_sh * _sign(qty)
            exit_fees += close_fee
            results.append(
                _emit(
                    account,
                    symbol,
                    side or "LONG",
                    entry_legs,
                    exit_legs,
                    cost_basis,
                    proceeds,
                    entry_fees,
                    exit_fees,
                )
            )

            side = "LONG" if new_position > 0 else "SHORT"
            entry_legs = [(e, open_sh)]
            exit_legs = []
            cost_basis = e.price * open_sh * _sign(qty)
            proceeds = 0.0
            entry_fees, exit_fees = open_fee, 0.0
            position = new_position

        if entry_legs:
            results.append(
                _emit(
                    account,
                    symbol,
                    side or "LONG",
                    entry_legs,
                    exit_legs,
                    cost_basis,
                    proceeds,
                    entry_fees,
                    exit_fees,
                    is_closed=False,
                )
            )

    return results
