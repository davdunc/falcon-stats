"""Shared pytest fixtures for falcon-stats tests.

See docs/specs/002-moto-ddb-fixture.md for the moto-mocked DynamoDB
fixtures planned here.
"""

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dynamodb_table():
    """Creates an empty falcon-trades table in moto's mock DDB.

    Yields the boto3 Table resource. The mock_aws context manager
    cleans up the table on fixture teardown.
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-2")
        table = ddb.create_table(
            TableName="falcon-trades",
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
        yield table
