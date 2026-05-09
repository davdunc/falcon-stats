# Spec 002 — moto-mocked DynamoDB Fixture

**Status:** Draft
**Owner:** davdunc
**Issue:** [#9](https://github.com/davdunc/falcon-stats/issues/9)
**Spec template version:** 1
**Depends on:** none (foundational)
**Unblocks:** #1, #2, #3, #4, #5, #6, #7, #10, #11, #14

## Status Checklist

- [ ] Spec drafted
- [ ] Spec reviewed
- [ ] Implementation complete
- [ ] Tests passing on `pytest tests/ -q`
- [ ] Merged to `main`

## Problem

`falcon_stats/db.py` is the canonical DynamoDB I/O layer for falcon-trades.
It has zero test coverage today because tests would have to either (a) hit
real AWS (slow, costly, contaminates the prod table) or (b) skip DDB paths
entirely (no coverage of the source-of-truth code path). Every other
issue that touches DDB read/write is blocked on this.

## Goal

Add a pytest fixture using `moto` (mock AWS) that spins up an in-memory
DynamoDB with the exact schema of the production `falcon-trades` table,
plus a second fixture pre-populated with a known sample of round-trips
and daily stats. All other DDB-touching tests build on this foundation.

## Non-goals

- Real AWS integration tests — separate concern, would live under a
  different marker (e.g. `pytest -m aws`)
- Mocking other AWS services (S3, SQS, etc.) — only DynamoDB is in
  scope here
- Refactoring `db.py` itself — the existing module is the contract;
  the fixture must work against it as-is
- Test data for non-trading entities (Notion sync state, etc.)

## API Surface

Two fixtures exposed in `tests/conftest.py`:

### `dynamodb_table` (empty)

```python
@pytest.fixture
def dynamodb_table(monkeypatch):
    """Creates an empty falcon-trades table in moto's mock DDB.

    Resets the falcon_stats.db module-level _table cache so callers
    of db._get_table() pick up the mock automatically.

    Yields the boto3 Table resource for direct fixture-data setup.
    """
```

### `populated_table` (sample data loaded)

```python
@pytest.fixture
def populated_table(dynamodb_table):
    """Empty table + 5 round-trips and 2 daily-stats records loaded.

    Built on dynamodb_table; tests needing canonical sample data
    use this fixture, tests setting up their own use the empty one.
    """
```

## Schema (must match `falcon-trades` exactly)

From `falcon_stats/db.py:7-12`:

| Element | Value |
|---------|-------|
| Table name | `falcon-trades` (or `os.getenv("FALCON_TRADES_TABLE")`) |
| Region | `us-east-2` (from `os.getenv("AWS_DEFAULT_REGION")`) |
| Partition key | `PK` (string) |
| Sort key | `SK` (string) |
| GSI | `account-date-index` |
| GSI partition key | `account` (string) |
| GSI sort key | `trade_date` (string) |
| GSI projection | `ALL` |
| Billing mode | `PAY_PER_REQUEST` (matches prod, no provisioned throughput needed in moto) |

PK formats:
- Round-trips: `TRADE#{YYYY-MM-DD}`
- Daily stats: `STATS#{YYYY-MM-DD}`

SK formats:
- Round-trips: `{account}#{symbol}#{HHMMSS}#{idx:03d}`
- Daily stats: `{account}` (just the account ID)

## Sample Data (`populated_table`)

5 round-trips across 2 dates, 2 accounts. Mix of LIVE/SIM, long/short,
closed/open. Modeled on real session data so tests are recognizable.

| # | Date | Account | Account Type | Symbol | Side | Shares | Avg Entry | Avg Exit | P&L | Closed |
|---|------|---------|--------------|--------|------|-------:|----------:|---------:|-----:|:------:|
| 1 | 2026-05-04 | <SIM_ACCOUNT> | SIM | NVDA | LONG | 50 | 197.90 | 198.00 | +$5.00 | ✅ |
| 2 | 2026-05-04 | <SIM_ACCOUNT> | SIM | GOOGL | SHORT | 5 | 384.00 | 384.50 | -$2.50 | ✅ |
| 3 | 2026-05-05 | <LIVE_ACCOUNT> | LIVE | CYTK | LONG | 5 | 87.00 | 92.00 | +$25.00 | ✅ |
| 4 | 2026-05-05 | <SIM_ACCOUNT> | SIM | DOCN | SHORT | 5 | 127.42 | 126.00 | +$7.10 | ✅ |
| 5 | 2026-05-05 | <SIM_ACCOUNT> | SIM | SHOP | LONG | 260 | 110.79 | — | $0.00 | ❌ (open) |

2 daily-stats records, one per `(date, account)` actually represented by
closed RTs (skip <SIM_ACCOUNT> 2026-05-05 stats if SHOP being open changes the
aggregation — a test of how stats handle open positions, leave that for
a separate test):

| # | Date | Account | Total Trades | Win Rate | Total P&L |
|---|------|---------|-------------:|---------:|----------:|
| 1 | 2026-05-04 | <SIM_ACCOUNT> | 2 | 0.50 | +$2.50 |
| 2 | 2026-05-05 | <LIVE_ACCOUNT> | 1 | 1.00 | +$25.00 |

Item shapes follow the exact `db.put_round_trip()` / `db.put_daily_stats()`
output in `db.py:55-149` — `Decimal` for floats, no `None` values, etc.

## Acceptance Criteria

Each box is one Ralph iteration target.

- [x] `moto[dynamodb] >= 5.0` added to `[project.optional-dependencies] dev` in `pyproject.toml`
- [x] `tests/conftest.py` exists (currently no conftest in tests/)
- [x] `dynamodb_table` fixture in `conftest.py` creates the table with the exact schema above using `moto.mock_aws` context manager
- [x] Fixture resets `falcon_stats.db._table` to `None` via `monkeypatch.setattr` so cached client doesn't leak across tests
- [x] Fixture uses table name `os.getenv("FALCON_TRADES_TABLE", "falcon-trades")` (matches `db.py:24`)
- [x] `populated_table` fixture loads the 5 round-trips and 2 daily-stats records exactly as specified
- [x] Item shapes match `db.put_round_trip()` output (`Decimal` types, no `None` values stripped)
- [ ] One smoke test in `tests/test_db_fixture.py` asserting:
  - `dynamodb_table` returns an empty table (`scan` returns 0 items)
  - `populated_table` returns 7 items total (5 RTs + 2 stats)
  - `db.get_round_trips("2026-05-04")` returns 2 items when called against the populated fixture
- [ ] Existing test suite still passes: `pytest tests/test_roundtrips.py -q`
- [ ] New tests pass: `pytest tests/test_db_fixture.py -q`
- [ ] Pytest gate green: `pytest tests/ -q` exits 0

## Open Questions

- **moto v4 vs v5:** v5 (released 2024) changed the import path from
  `from moto import mock_dynamodb` to `from moto import mock_aws`.
  Pin `moto >= 5.0` and use `mock_aws`. v4 deprecated.
- **Region pinning:** prod uses `us-east-2`. The fixture should respect
  the `AWS_DEFAULT_REGION` env var like `db.py:25` does, defaulting to
  `us-east-2` when unset. Tests should not depend on the host's
  `~/.aws/config`.
- **GSI projection:** `ALL` matches what `db.get_round_trips_range`
  needs (it queries by `account` + `trade_date BETWEEN`). If we ever
  switch to `KEYS_ONLY` for cost, it's a separate spec.
- **Cleanup:** `mock_aws` context manager cleans up automatically on
  fixture teardown. No explicit `delete_table` needed.

## Implementation Sketch (informational, not normative)

```python
# tests/conftest.py
import os
import boto3
import pytest
from decimal import Decimal
from moto import mock_aws


SAMPLE_RTS = [
    # ... five dicts shaped like db.put_round_trip() output ...
]
SAMPLE_STATS = [
    # ... two dicts shaped like db.put_daily_stats() output ...
]


@pytest.fixture
def dynamodb_table(monkeypatch):
    with mock_aws():
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
        table_name = os.getenv("FALCON_TRADES_TABLE", "falcon-trades")
        ddb = boto3.resource("dynamodb", region_name=region)
        table = ddb.create_table(
            TableName=table_name,
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
        from falcon_stats import db
        monkeypatch.setattr(db, "_table", None)
        yield table


@pytest.fixture
def populated_table(dynamodb_table):
    with dynamodb_table.batch_writer() as batch:
        for rt in SAMPLE_RTS:
            batch.put_item(Item=rt)
        for stat in SAMPLE_STATS:
            batch.put_item(Item=stat)
    yield dynamodb_table
```

## References

- `falcon_stats/db.py:1-12` — table doc
- `falcon_stats/db.py:24-35` — table name / region resolution + `_table` cache
- `falcon_stats/db.py:51-149` — write item shapes the fixture must mirror
- moto docs: https://docs.getmoto.org/en/latest/docs/services/dynamodb.html
- moto v4→v5 migration: https://docs.getmoto.org/en/latest/docs/configuration/recorder/index.html
