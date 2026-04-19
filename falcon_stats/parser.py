"""DAS Trader CSV parser — reads Trades.csv and Orders.csv into Trade/Order models."""

import csv
from datetime import datetime
from pathlib import Path

from .models import Trade, Order, Side


def parse_trades(path: Path) -> list[Trade]:
    """Parse DAS Trades.csv into Trade objects.

    Expected columns: TradeID,OrderID,Trader,Account,Branch,route,bkrsym,rrno,
                      B/S,SHORT,Market,symb,qty,price,time
    """
    trades = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(Trade(
                trade_id=int(row["TradeID"]),
                order_id=int(row["OrderID"]),
                account=row["Account"],
                symbol=row["symb"],
                side=Side.BUY if row["B/S"] == "B" else Side.SELL,
                quantity=int(row["qty"]),
                price=float(row["price"]),
                time=_parse_time(row["time"]),
                route=row.get("route", ""),
                is_short=row.get("SHORT", "N") == "Y",
            ))
    return sorted(trades, key=lambda t: t.time)


def parse_orders(path: Path) -> list[Order]:
    """Parse DAS Orders.csv into Order objects.

    Expected columns: OrderID,Trader,Account,Branch,route,bkrsym,rrno,
                      B/S,SHORT,Market,stop,symb,qty,lvsqty,price,stopprice,
                      trailprice,time
    """
    orders = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stop = float(row.get("stopprice", "0") or "0")
            trail = float(row.get("trailprice", "0") or "0")
            orders.append(Order(
                order_id=int(row["OrderID"]),
                account=row["Account"],
                symbol=row["symb"],
                side=Side.BUY if row["B/S"] == "B" else Side.SELL,
                quantity=int(row["qty"]),
                price=float(row["price"]),
                stop_price=stop if stop > 0 else None,
                trail_price=trail if trail > 0 else None,
                time=_parse_time(row["time"]),
                market_type=row.get("Market", ""),
            ))
    return orders


def load_day(directory: Path) -> tuple[list[Trade], list[Order]]:
    """Load all trade data from a daily export directory.

    Expects: directory/Trades.csv and directory/Orders.csv
    """
    trades_path = directory / "Trades.csv"
    orders_path = directory / "Orders.csv"

    trades = parse_trades(trades_path) if trades_path.exists() else []
    orders = parse_orders(orders_path) if orders_path.exists() else []

    return trades, orders


def _parse_time(time_str: str) -> datetime:
    """Parse DAS time format: '04/16/26 07:57:41'."""
    return datetime.strptime(time_str.strip(), "%m/%d/%y %H:%M:%S")
