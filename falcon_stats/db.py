"""DynamoDB persistence for falcon-stats.

DynamoDB is the SOURCE OF TRUTH for all trading data. Notion is a
rebuildable view. If Notion databases are deleted, they can be
fully recreated from DynamoDB using `falcon-stats rebuild-notion`.

Table: falcon-trades (us-east-2)
PK/SK Schema:
  - Round-trip: PK=TRADE#YYYY-MM-DD  SK=ACCOUNT#SYMBOL#HHMMSS
  - Daily stats: PK=STATS#YYYY-MM-DD  SK=ACCOUNT
GSI: account-date-index (account → trade_date)
"""

import json
import os
from datetime import datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer

from .models import RoundTrip, DailyStats, Side

TABLE_NAME = os.getenv("FALCON_TRADES_TABLE", "falcon-trades")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

_table = None


def _get_table():
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def _to_decimal(val):
    """Convert float to Decimal for DynamoDB (floats not supported)."""
    if val is None:
        return None
    if isinstance(val, float):
        return Decimal(str(round(val, 6)))
    return val


# ============================================================
# WRITE — Round-Trips
# ============================================================

def put_round_trip(rt: RoundTrip, date_str: str, idx: int = 0) -> dict:
    """Write a single round-trip to DynamoDB."""
    entry_time = rt.entry_time.strftime("%H%M%S")

    item = {
        "PK": f"TRADE#{date_str}",
        "SK": f"{rt.account}#{rt.symbol}#{entry_time}#{idx:03d}",
        "account": rt.account,
        "trade_date": date_str,
        "symbol": rt.symbol,
        "side": "LONG" if rt.side == Side.BUY else "SHORT",
        "shares": rt.total_shares,
        "avg_entry": _to_decimal(rt.avg_entry),
        "avg_exit": _to_decimal(rt.avg_exit),
        "pnl": _to_decimal(rt.pnl),
        "r_multiple": _to_decimal(rt.r_multiple),
        "planned_stop": _to_decimal(rt.planned_stop),
        "is_winner": rt.is_winner,
        "is_closed": rt.is_closed,
        "entry_time": rt.entry_time.isoformat(),
        "exit_time": rt.exit_time.isoformat() if rt.exit_time else None,
        "entry_count": len(rt.entries),
        "exit_count": len(rt.exits),
    }

    # Remove None values (DynamoDB doesn't allow them)
    item = {k: v for k, v in item.items() if v is not None}

    _get_table().put_item(Item=item)
    return item


def put_round_trips(round_trips: list[RoundTrip], date_str: str) -> int:
    """Write multiple round-trips to DynamoDB. Returns count written."""
    table = _get_table()
    count = 0
    with table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for idx, rt in enumerate(round_trips):
            entry_time = rt.entry_time.strftime("%H%M%S")
            item = {
                "PK": f"TRADE#{date_str}",
                "SK": f"{rt.account}#{rt.symbol}#{entry_time}#{idx:03d}",
                "account": rt.account,
                "trade_date": date_str,
                "symbol": rt.symbol,
                "side": "LONG" if rt.side == Side.BUY else "SHORT",
                "shares": rt.total_shares,
                "avg_entry": _to_decimal(rt.avg_entry),
                "avg_exit": _to_decimal(rt.avg_exit),
                "pnl": _to_decimal(rt.pnl),
                "r_multiple": _to_decimal(rt.r_multiple),
                "planned_stop": _to_decimal(rt.planned_stop),
                "is_winner": rt.is_winner,
                "is_closed": rt.is_closed,
                "entry_time": rt.entry_time.isoformat(),
                "exit_time": rt.exit_time.isoformat() if rt.exit_time else None,
                "entry_count": len(rt.entries),
                "exit_count": len(rt.exits),
            }
            item = {k: v for k, v in item.items() if v is not None}
            batch.put_item(Item=item)
            count += 1
    return count


# ============================================================
# WRITE — Daily Stats
# ============================================================

def put_daily_stats(stats: DailyStats) -> dict:
    """Write daily aggregate stats to DynamoDB."""
    streak_count, streak_type = stats.streak
    pf = stats.profit_factor
    pf_val = _to_decimal(pf) if pf != float("inf") else Decimal("999999")

    item = {
        "PK": f"STATS#{stats.date}",
        "SK": stats.account,
        "account": stats.account,
        "trade_date": stats.date,
        "total_trades": stats.total_trades,
        "win_rate": _to_decimal(stats.win_rate),
        "total_pnl": _to_decimal(stats.total_pnl),
        "gross_profit": _to_decimal(stats.gross_profit),
        "gross_loss": _to_decimal(stats.gross_loss),
        "avg_winner": _to_decimal(stats.avg_winner),
        "avg_loser": _to_decimal(stats.avg_loser),
        "expectancy": _to_decimal(stats.expectancy),
        "profit_factor": pf_val,
        "avg_r": _to_decimal(stats.avg_r),
        "max_drawdown": _to_decimal(stats.max_drawdown),
        "winners": len(stats.winners),
        "losers": len(stats.losers),
        "streak": f"{streak_count}{streak_type}",
    }

    item = {k: v for k, v in item.items() if v is not None}
    _get_table().put_item(Item=item)
    return item


# ============================================================
# READ — Round-Trips
# ============================================================

def get_round_trips(date_str: str, account: str | None = None) -> list[dict]:
    """Get all round-trips for a given date, optionally filtered by account."""
    table = _get_table()

    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"TRADE#{date_str}"},
    )

    items = response.get("Items", [])

    if account:
        items = [i for i in items if i.get("account") == account]

    return sorted(items, key=lambda x: x.get("entry_time", ""))


def get_round_trips_range(start_date: str, end_date: str, account: str | None = None) -> list[dict]:
    """Get round-trips across a date range using the GSI."""
    table = _get_table()

    if account:
        response = table.query(
            IndexName="account-date-index",
            KeyConditionExpression="account = :acct AND trade_date BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":acct": account,
                ":start": start_date,
                ":end": end_date,
            },
        )
        return response.get("Items", [])
    else:
        # Without account filter, scan by date prefix (less efficient but works)
        all_items = []
        from datetime import date, timedelta
        current = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        while current <= end:
            items = get_round_trips(current.isoformat())
            all_items.extend(items)
            current += timedelta(days=1)
        return all_items


# ============================================================
# READ — Daily Stats
# ============================================================

def get_daily_stats(date_str: str, account: str | None = None) -> list[dict]:
    """Get daily stats for a given date."""
    table = _get_table()

    if account:
        response = table.get_item(
            Key={"PK": f"STATS#{date_str}", "SK": account},
        )
        item = response.get("Item")
        return [item] if item else []
    else:
        response = table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"STATS#{date_str}"},
        )
        return response.get("Items", [])


def get_stats_range(start_date: str, end_date: str, account: str | None = None) -> list[dict]:
    """Get daily stats across a date range."""
    all_items = []
    from datetime import date, timedelta
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while current <= end:
        items = get_daily_stats(current.isoformat(), account)
        all_items.extend(items)
        current += timedelta(days=1)
    return sorted(all_items, key=lambda x: x.get("trade_date", ""))
