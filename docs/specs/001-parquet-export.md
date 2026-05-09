# Spec 001 — Round-Trip Parquet Export

**Status:** Draft
**Owner:** davdunc
**Issue:** TBD (link after `gh issue create`)
**Spec template version:** 1

## Status Checklist

- [ ] Spec drafted
- [ ] Spec reviewed
- [ ] Implementation complete
- [ ] Tests passing on `pytest tests/ -q`
- [ ] Merged to `main`

## Problem

Round-trip data for the falcon-stats project is canonical in the
`falcon-trades` DynamoDB table and raw in DAS exports under
`~/Trade_Review/`. Training data and downstream analysis (ML, backtests,
notebook EDA) benefit from a portable columnar format with a stable schema.
Today there is no export path from DDB to a portable analysis format —
each consumer would have to write its own boto3 query and column mapping.

## Goal

Add a `falcon-stats export-parquet` CLI command that writes round-trip
data from `falcon-trades` to a single parquet file with a stable schema
suitable for ML training and historical analysis.

## Non-goals

- Trade-level (execution) parquet — round-trips are the unit; trade-level
  is a separate spec if/when needed
- Daily-stats parquet — separate concern, separate spec
- Two-way sync with Google Drive — out of scope; user can copy the parquet
  file there manually
- Live streaming export — batch only

## CLI Surface

```
falcon-stats export-parquet \
    [--start YYYY-MM-DD] \
    [--end YYYY-MM-DD] \
    [--account ACCT] \
    [--out PATH]
```

Defaults:
- `--start` / `--end`: full range available in DDB (no filter)
- `--account`: no filter (writes all accounts; column distinguishes them)
- `--out`: `~/Trade_Review/parquet/round_trips_{start}_{end}.parquet`

## Schema (round-trip grain)

| Column | pyarrow type | Source | Notes |
|--------|--------------|--------|-------|
| `trade_date` | `date32` | DDB `trade_date` | YYYY-MM-DD |
| `account` | `string` | DDB `account` | e.g. `<LIVE_ACCOUNT>`, `<SIM_ACCOUNT>` |
| `symbol` | `string` | DDB `symbol` | uppercase |
| `side` | `string` | DDB `side` | `LONG` / `SHORT` |
| `total_shares` | `int32` | DDB `shares` | sum of entries |
| `avg_entry` | `float64` | DDB `avg_entry` | qty-weighted |
| `avg_exit` | `float64` | DDB `avg_exit` | qty-weighted; null if open |
| `pnl` | `float64` | DDB `pnl` | dollars; 0.0 if open |
| `r_multiple` | `float64` | DDB `r_multiple` | nullable |
| `planned_stop` | `float64` | DDB `planned_stop` | nullable |
| `is_winner` | `bool` | DDB `is_winner` | |
| `is_closed` | `bool` | DDB `is_closed` | |
| `entry_time` | `timestamp[ns]` | DDB `entry_time` | tz-aware UTC |
| `exit_time` | `timestamp[ns]` | DDB `exit_time` | nullable |
| `entry_count` | `int16` | DDB `entry_count` | scaling-in count |
| `exit_count` | `int16` | DDB `exit_count` | scaling-out count |

DynamoDB returns `Decimal` for numeric fields — converter must coerce to
Python `float` / `int` before parquet write.

## Acceptance Criteria

Each box maps to one Ralph iteration target.

- [ ] `pyarrow` added to `pyproject.toml` `[project.dependencies]`
- [ ] New module `falcon_stats/parquet_export.py` exposing
      `export_round_trips(start: str | None, end: str | None,
       account: str | None, out_path: Path) -> int` (returns row count)
- [ ] Module uses `db.get_round_trips_range()` when both start/end set,
      falls back to a date-walk over DDB when bounds are open
- [ ] Decimal → float coercion implemented and unit-tested
- [ ] `cli.py` adds subparser `export-parquet` with the four flags above
- [ ] CLI prints: `row count`, resolved `out_path`, file size in bytes
- [ ] Output directory created with `Path.mkdir(parents=True, exist_ok=True)`
      if missing
- [ ] Empty range produces a parquet file with the schema above and zero
      rows (not an error, not a missing file)
- [ ] `tests/test_parquet_export.py` with moto-mocked DDB writes 5 known
      round-trips (mix of LIVE/SIM, long/short, closed/open) and reads them
      back via `pyarrow.parquet.read_table` — schema equality plus row-count
      and `pnl` sum assertions
- [ ] Open round-trips round-trip cleanly: `is_closed=False`,
      `exit_time=NULL`, `avg_exit=NULL`, `pnl=0.0`
- [ ] README section added (or docstring example) showing one CLI
      invocation and one pyarrow read example
- [ ] Pytest gate green locally: `pytest tests/ -q` exits 0
- [ ] No regressions in existing tests (`tests/test_roundtrips.py`)

## Open Questions

- **Compression:** default snappy keeps reads cheap; zstd compresses better
  for archival. Pick snappy now, revisit if file size matters.
- **Partitioning:** single file is simpler. Revisit at >1M rows or when
  consumers want partition-pruning.
- **Polars vs pandas:** neither is required — pyarrow direct keeps deps
  minimal. Defer until a consumer asks.

## References

- `falcon_stats/db.py:1-12` — DDB source-of-truth doc
- `falcon_stats/db.py:173-198` — `get_round_trips_range()`
- `falcon_stats/models.py:54-163` — `RoundTrip.to_dict()` schema baseline
- DAS export root: `~/Trade_Review/` (per `cli.py:21-24`)

## Spec Template Notes (for future specs)

This file is the template seed for `docs/specs/NNN-feature.md`. Copy it,
renumber, replace fields. Required sections:

1. **Status Checklist** — drives progress visibility
2. **Problem** — why this exists
3. **Goal** — one-line success statement
4. **Non-goals** — explicit scope fence
5. **CLI/API surface** — concrete interface
6. **Acceptance Criteria** — checkbox-per-iteration; this is what Ralph
   reads each loop to pick the next task
7. **Open Questions** — known unknowns; not blocking
8. **References** — file:line cites for context
