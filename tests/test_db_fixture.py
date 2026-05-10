"""Smoke tests for the moto DynamoDB fixtures in conftest.py.

Verifies that the empty `dynamodb_table` and pre-populated
`populated_table` fixtures behave per docs/specs/002-moto-ddb-fixture.md.
"""

from falcon_stats import db


def test_empty_fixture_has_zero_items(dynamodb_table):
    assert dynamodb_table.scan()["Count"] == 0


def test_populated_fixture(populated_table):
    assert populated_table.scan()["Count"] == 7
    assert len(db.get_round_trips("2026-05-04")) == 2
