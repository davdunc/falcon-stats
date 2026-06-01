"""Round-trip identification — DEPRECATED legacy shim.

This module is preserved for backward compatibility with existing CLI
subcommands (`ingest`, `summary`, `trades`, `week`, `backfill`,
`ingest-broker`) that pass `list[Trade]` from DAS CSV parsing.

New code should use `falcon_stats.pairing.pair_executions` directly,
which operates on signed-quantity `ExecutionRow` instances from the
SQLite canonical store.

The shim converts `list[Trade]` → `list[ExecutionRow]`, runs the canonical
walker, then re-builds `RoundTrip(entries=..., exits=...)` objects by
mapping exec_ids back to the original Trades. Stop prices from `orders`
are matched via the existing `_build_stop_lookup` lookup.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .models import Order, RoundTrip, Side, Trade
from .pairing import pair_executions
from .sqlite_db import ExecutionRow, compute_exec_id


def _trades_to_execution_rows(trades: list[Trade]) -> tuple[list[ExecutionRow], dict[str, Trade]]:
    """Convert legacy Trade objects to ExecutionRow + lookup by exec_id."""
    rows: list[ExecutionRow] = []
    lookup: dict[str, Trade] = {}
    for t in trades:
        signed_qty = t.quantity if t.side == Side.BUY else -t.quantity
        trade_datetime = t.time.isoformat(timespec="seconds")
        trade_date = t.time.strftime("%Y-%m-%d")
        amount = float(signed_qty) * float(t.price)
        exec_id = compute_exec_id(
            account=t.account,
            trade_datetime=trade_datetime,
            symbol=t.symbol,
            quantity=signed_qty,
            price=float(t.price),
            amount=amount,
        )
        rows.append(
            ExecutionRow(
                exec_id=exec_id,
                account=t.account,
                trade_date=trade_date,
                trade_datetime=trade_datetime,
                quantity=signed_qty,
                symbol=t.symbol,
                description=None,
                price=float(t.price),
                trans_fee=0.0,
                ecn_taker=0.0,
                ecn_maker=0.0,
                orf_fee=0.0,
                taf_fee=0.0,
                sec_fee=0.0,
                cat_fee=0.0,
                amount=amount,
                type="Short" if t.is_short else None,
                commissions=0.0,
                source_file="<das-csv-legacy>",
            )
        )
        lookup[exec_id] = t
    return rows, lookup


def identify_round_trips(
    trades: list[Trade],
    orders: list[Order] | None = None,
) -> list[RoundTrip]:
    """DEPRECATED legacy API. Delegates to `pairing.pair_executions`.

    Preserved signature: takes legacy Trade list, optional Orders. Returns
    a list of legacy RoundTrip dataclass instances.
    """
    if not trades:
        return []

    rows, lookup = _trades_to_execution_rows(trades)
    results = pair_executions(rows)

    stop_lookup = _build_stop_lookup(orders) if orders else {}

    rts: list[RoundTrip] = []
    for r in results:
        entries = [lookup[eid] for eid in r.entry_exec_ids if eid in lookup]
        exits = [lookup[eid] for eid in r.exit_exec_ids if eid in lookup]
        side = Side.BUY if r.side == "LONG" else Side.SELL
        planned_stop = _find_stop(r.account, r.symbol, entries, stop_lookup)
        rts.append(
            RoundTrip(
                symbol=r.symbol,
                account=r.account,
                side=side,
                entries=entries,
                exits=exits,
                planned_stop=planned_stop,
            )
        )

    return sorted(rts, key=lambda rt: rt.entry_time if rt.entries else datetime.min)


def _build_stop_lookup(orders: list[Order]) -> dict[tuple[str, str], list[float]]:
    lookup: dict[tuple[str, str], list[float]] = defaultdict(list)
    for order in orders:
        if order.stop_price is not None:
            lookup[(order.account, order.symbol)].append(order.stop_price)
    return lookup


def _find_stop(
    account: str,
    symbol: str,
    entries: list[Trade],
    stop_lookup: dict[tuple[str, str], list[float]],
) -> float | None:
    stops = stop_lookup.get((account, symbol), [])
    if not stops:
        return None
    return stops[0]
