"""Shared test fixtures.

The broker XLS fixture path resolves in this order:
  1. $FALCON_TEST_FIXTURE (explicit override)
  2. /tmp/broker-fixture-2026-06-01.xls (default for the architect's seed)

Account label is `os.getenv("FALCON_ACCOUNT", "ACCT")` per the security
hardening guidance — the real account string lives only in the runtime
env, never in committed code.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


DEFAULT_FIXTURE = Path("/tmp/broker-fixture-2026-06-01.xls")


@pytest.fixture(scope="session")
def broker_xls_path() -> Path:
    p = Path(os.getenv("FALCON_TEST_FIXTURE", str(DEFAULT_FIXTURE)))
    if not p.exists():
        pytest.skip(f"broker fixture not present at {p}")
    return p


@pytest.fixture(scope="session")
def test_account() -> str:
    return os.getenv("FALCON_ACCOUNT", "ACCT")


@pytest.fixture()
def tmp_db_path(tmp_path) -> Path:
    return tmp_path / "trades.db"
