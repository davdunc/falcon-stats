"""Round-trip identification engine.

Groups individual trades into complete positions (entry → exit cycles).
Handles partial fills, scaling in/out, and matches stop orders to entries.

The round-trip is the atomic unit of trading analysis. All statistics
are computed from round-trips, not individual trades.
"""

from collections import defaultdict

from .models import Trade, Order, RoundTrip, Side


def identify_round_trips(
    trades: list[Trade],
    orders: list[Order] | None = None,
) -> list[RoundTrip]:
    """Group trades into round-trip positions.

    Algorithm:
    1. Group trades by symbol and account
    2. For each group, walk chronologically
    3. Buys increase position, sells decrease (for longs)
    4. When position returns to zero, close the round-trip
    5. Match stop orders from Orders.csv to determine planned risk

    Handles:
    - Scaling in (multiple entries before exit)
    - Scaling out (partial exits)
    - Multiple round-trips on the same symbol in one day
    - Long and short positions
    """
    # Build stop price lookup from orders
    stop_lookup = _build_stop_lookup(orders) if orders else {}

    # Group trades by (account, symbol)
    groups: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for trade in sorted(trades, key=lambda t: t.time):
        groups[(trade.account, trade.symbol)].append(trade)

    round_trips = []
    for (account, symbol), symbol_trades in groups.items():
        round_trips.extend(
            _process_symbol_trades(account, symbol, symbol_trades, stop_lookup)
        )

    return sorted(round_trips, key=lambda rt: rt.entry_time)


def _process_symbol_trades(
    account: str,
    symbol: str,
    trades: list[Trade],
    stop_lookup: dict,
) -> list[RoundTrip]:
    """Process all trades for a single symbol into round-trips."""
    round_trips = []
    position = 0  # positive = long, negative = short
    current_entries: list[Trade] = []
    current_exits: list[Trade] = []

    for trade in trades:
        if trade.side == Side.BUY:
            delta = trade.quantity
        else:
            delta = -trade.quantity

        new_position = position + delta

        # Determine if this trade is an entry or exit
        if position == 0:
            # Opening a new position
            current_entries.append(trade)
        elif (position > 0 and delta > 0) or (position < 0 and delta < 0):
            # Adding to existing position (scaling in)
            current_entries.append(trade)
        elif (position > 0 and delta < 0) or (position < 0 and delta > 0):
            # Reducing position (exit or partial exit)
            current_exits.append(trade)

        position = new_position

        # Position closed — create round-trip
        if position == 0 and current_entries:
            side = Side.BUY if current_entries[0].side == Side.BUY else Side.SELL
            planned_stop = _find_stop(account, symbol, current_entries, stop_lookup)

            rt = RoundTrip(
                symbol=symbol,
                account=account,
                side=side,
                entries=list(current_entries),
                exits=list(current_exits),
                planned_stop=planned_stop,
            )
            round_trips.append(rt)
            current_entries.clear()
            current_exits.clear()

    # Handle unclosed position (still holding at end of data)
    if current_entries and position != 0:
        side = Side.BUY if current_entries[0].side == Side.BUY else Side.SELL
        planned_stop = _find_stop(account, symbol, current_entries, stop_lookup)
        rt = RoundTrip(
            symbol=symbol,
            account=account,
            side=side,
            entries=list(current_entries),
            exits=list(current_exits),
            planned_stop=planned_stop,
        )
        round_trips.append(rt)

    return round_trips


def _build_stop_lookup(orders: list[Order]) -> dict[tuple[str, str], list[float]]:
    """Build lookup of stop prices by (account, symbol).

    Returns all stop prices for each symbol so we can match them
    to entries by proximity in time.
    """
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
    """Find the planned stop price for a position.

    Uses the first stop order found for this symbol. In practice,
    the stop is usually set with the first entry order.
    """
    stops = stop_lookup.get((account, symbol), [])
    if not stops:
        return None
    # Return the first stop price — typically set with initial entry
    return stops[0]
