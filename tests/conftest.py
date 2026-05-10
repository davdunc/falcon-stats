"""Shared pytest fixtures for falcon-stats tests.

See docs/specs/002-moto-ddb-fixture.md for the moto-mocked DynamoDB
fixtures planned here.
"""

import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from falcon_stats import db


SAMPLE_ROUND_TRIPS: list[dict] = [
    {
        "PK": "TRADE#2026-05-04",
        "SK": "ACCT_SIM#NVDA#093000#001",
        "account": "ACCT_SIM",
        "trade_date": "2026-05-04",
        "symbol": "NVDA",
        "side": "LONG",
        "shares": 50,
        "avg_entry": Decimal("197.90"),
        "avg_exit": Decimal("198.00"),
        "pnl": Decimal("5.00"),
        "r_multiple": Decimal("0"),
        "planned_stop": Decimal("0"),
        "is_winner": True,
        "is_closed": True,
        "entry_time": "2026-05-04T09:30:00",
        "exit_time": "2026-05-04T09:35:00",
        "entry_count": 1,
        "exit_count": 1,
    },
    {
        "PK": "TRADE#2026-05-04",
        "SK": "ACCT_SIM#GOOGL#100500#002",
        "account": "ACCT_SIM",
        "trade_date": "2026-05-04",
        "symbol": "GOOGL",
        "side": "SHORT",
        "shares": 5,
        "avg_entry": Decimal("384.00"),
        "avg_exit": Decimal("384.50"),
        "pnl": Decimal("-2.50"),
        "r_multiple": Decimal("0"),
        "planned_stop": Decimal("0"),
        "is_winner": False,
        "is_closed": True,
        "entry_time": "2026-05-04T10:05:00",
        "exit_time": "2026-05-04T10:10:00",
        "entry_count": 1,
        "exit_count": 1,
    },
    {
        "PK": "TRADE#2026-05-05",
        "SK": "ACCT_LIVE#CYTK#093000#001",
        "account": "ACCT_LIVE",
        "trade_date": "2026-05-05",
        "symbol": "CYTK",
        "side": "LONG",
        "shares": 5,
        "avg_entry": Decimal("87.00"),
        "avg_exit": Decimal("92.00"),
        "pnl": Decimal("25.00"),
        "r_multiple": Decimal("0"),
        "planned_stop": Decimal("0"),
        "is_winner": True,
        "is_closed": True,
        "entry_time": "2026-05-05T09:30:00",
        "exit_time": "2026-05-05T09:45:00",
        "entry_count": 1,
        "exit_count": 1,
    },
    {
        "PK": "TRADE#2026-05-05",
        "SK": "ACCT_SIM#DOCN#101500#002",
        "account": "ACCT_SIM",
        "trade_date": "2026-05-05",
        "symbol": "DOCN",
        "side": "SHORT",
        "shares": 5,
        "avg_entry": Decimal("127.42"),
        "avg_exit": Decimal("126.00"),
        "pnl": Decimal("7.10"),
        "r_multiple": Decimal("0"),
        "planned_stop": Decimal("0"),
        "is_winner": True,
        "is_closed": True,
        "entry_time": "2026-05-05T10:15:00",
        "exit_time": "2026-05-05T10:25:00",
        "entry_count": 1,
        "exit_count": 1,
    },
    {
        "PK": "TRADE#2026-05-05",
        "SK": "ACCT_SIM#SHOP#103000#003",
        "account": "ACCT_SIM",
        "trade_date": "2026-05-05",
        "symbol": "SHOP",
        "side": "LONG",
        "shares": 260,
        "avg_entry": Decimal("110.79"),
        "r_multiple": Decimal("0"),
        "planned_stop": Decimal("0"),
        "is_winner": False,
        "is_closed": False,
        "entry_time": "2026-05-05T10:30:00",
        "entry_count": 1,
        "exit_count": 0,
    },
]


SAMPLE_DAILY_STATS: list[dict] = [
    {
        "PK": "STATS#2026-05-04",
        "SK": "ACCT_SIM",
        "account": "ACCT_SIM",
        "trade_date": "2026-05-04",
        "total_trades": 2,
        "win_rate": Decimal("0.50"),
        "total_pnl": Decimal("2.50"),
        "gross_profit": Decimal("5.00"),
        "gross_loss": Decimal("-2.50"),
        "avg_winner": Decimal("5.00"),
        "avg_loser": Decimal("-2.50"),
        "expectancy": Decimal("1.25"),
        "profit_factor": Decimal("2.00"),
        "avg_r": Decimal("0"),
        "max_drawdown": Decimal("-2.50"),
        "winners": 1,
        "losers": 1,
        "streak": "1L",
    },
    {
        "PK": "STATS#2026-05-05",
        "SK": "ACCT_LIVE",
        "account": "ACCT_LIVE",
        "trade_date": "2026-05-05",
        "total_trades": 1,
        "win_rate": Decimal("1.00"),
        "total_pnl": Decimal("25.00"),
        "gross_profit": Decimal("25.00"),
        "gross_loss": Decimal("0"),
        "avg_winner": Decimal("25.00"),
        "avg_loser": Decimal("0"),
        "expectancy": Decimal("25.00"),
        "profit_factor": Decimal("999999"),
        "avg_r": Decimal("0"),
        "max_drawdown": Decimal("0"),
        "winners": 1,
        "losers": 0,
        "streak": "1W",
    },
]


@pytest.fixture
def dynamodb_table(monkeypatch):
    """Creates an empty falcon-trades table in moto's mock DDB.

    Resets the falcon_stats.db module-level _table cache so callers
    of db._get_table() pick up the mock automatically and a cached
    real-AWS client doesn't leak across tests.

    Yields the boto3 Table resource. The mock_aws context manager
    cleans up the table on fixture teardown.
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-2")
        table = ddb.create_table(
            TableName=os.getenv("FALCON_TRADES_TABLE", "falcon-trades"),
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "account", "AttributeType": "S"},
                {"AttributeName": "trade_date", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "account-date-index",
                    "KeySchema": [
                        {"AttributeName": "account", "KeyType": "HASH"},
                        {"AttributeName": "trade_date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setattr(db, "_table", None)
        yield table


@pytest.fixture
def populated_table(dynamodb_table):
    """Empty table seeded with 5 round-trips and 2 daily-stats records.

    Built on dynamodb_table; tests needing canonical sample data use
    this fixture. Tests setting up their own data use the empty one.
    """
    with dynamodb_table.batch_writer() as batch:
        for rt in SAMPLE_ROUND_TRIPS:
            batch.put_item(Item=rt)
        for stat in SAMPLE_DAILY_STATS:
            batch.put_item(Item=stat)
    yield dynamodb_table
