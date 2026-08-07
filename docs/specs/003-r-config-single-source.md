# Spec 003 — R-CONFIG as the Single Runtime Source of Risk

**Status:** Draft
**Owner:** davdunc
**Spec template version:** 1

## Status Checklist

- [ ] Spec drafted
- [ ] Spec reviewed
- [ ] Implementation complete
- [ ] Tests passing on `pytest tests/ -q`
- [ ] Merged to `main`

## Problem

`R` is the operator-declared **maximum dollar risk per trade**. It is defined per account
in the `R-CONFIG` block of
`~/.claude/LifeOS/USER/SKILLCUSTOMIZATIONS/Trading/PREFERENCES.md`, which declares itself
the single source of truth and states *"Do NOT hard-code R values anywhere else."*

**No code reads it.** `grep -riE "PREFERENCES|R_VALUE|R-CONFIG|r_dollars" falcon_stats/`
returns nothing. The value is instead hard-coded in two places:

```
falcon_stats/sizer.py:147   max_risk: float = 280.0,
falcon_stats/cli.py:454     default=280.0, help="Max risk in dollars (default: $280)"
```

`280.0` is stale. It derives from "1% of a ~$28K account"; the R-CONFIG has said
**$28 (0.1%)** since 2026-07-24. Consequences observed:

- `falcon-stats size SYMBOL long ENTRY` with no `--risk` flag sizes for **10× the intended
  maximum risk**, silently. A forgotten flag produces a plausible-looking position.
- The same 1% vs 0.1% discrepancy propagated into `SKILL.md`,
  `RulesOfEngagement.md` (three places) and a `MorningGamePlan.md` worked example, where it
  made a **−$219 single-symbol loss on 2026-08-04 read as within the −1R per-symbol stop**.
  It was a **7.8R breach**. Those documents were corrected on 2026-08-05; the code was not.

Editing `PREFERENCES.md` today changes what LifeOS *workflows* do and nothing that
*programs* do. A configuration file with no runtime consumers is documentation.

## Goal

Make `PREFERENCES.md` R-CONFIG the **only** place any R value exists, and make every
program read it at runtime. After this spec, the answer to "where do I change my max risk
per trade?" is unambiguously "that file, and nowhere else."

## Non-goals

- Changing the R **values** themselves — this spec only changes where they are read from.
- Position-sizing algorithm changes. ATR scenario logic is untouched.
- Per-trade *realised* R (`abs(entry − planned_stop) × shares`). That is derived from
  `Orders.csv` via `roundtrips._find_stop()` and is a separate concern from the declared
  maximum. See `ReportingSchema.md` Rule 3.
- Enforcement of the limit at order-entry time. This spec makes the number available and
  correct; enforcement is broker-side and out of scope.

## Design

New module `falcon_stats/r_config.py`:

```python
@dataclass(frozen=True)
class RConfig:
    r_value: float          # 1R in dollars, for one account
    daily_max_r: float      # derived: 3 x r_value
    per_symbol_max_r: float # derived: 1 x r_value
    account: str
    source_path: Path       # provenance, for error messages and audit
```

```python
def load_r_config(account: str = "LIVE", path: Path | None = None) -> RConfig
```

- Parses the markdown table inside the `R-CONFIG` block of `PREFERENCES.md`.
- Path resolution order: explicit `path` argument → `$LIFEOS_PREFERENCES` →
  `~/.claude/LifeOS/USER/SKILLCUSTOMIZATIONS/Trading/PREFERENCES.md`.
- `account` accepts `LIVE` / `SIM` or a literal account id, matched case-insensitively
  against the table's Account column.

### Failure behaviour — loud, never defaulted

**If the file is missing, the `R-CONFIG` block is absent, or the account row cannot be
parsed, raise `RConfigError`.** Do **not** fall back to a literal.

This is the crux of the spec. A numeric fallback is what produced the current defect: the
stale `280.0` was a fallback nobody revisited, and it failed *silently* in the direction of
more risk. **An unusable config must stop the program, not quietly size a position.**

### Call-site changes

| Site | Before | After |
|---|---|---|
| `sizer.size_trade()` | `max_risk: float = 280.0` | `max_risk: float \| None = None` — resolved from `load_r_config()` when `None` |
| `cli.py` `size` subcommand | `--risk` default `280.0` | `--risk` default `None`; new `--account {LIVE,SIM}` default `LIVE`; help text names the source file |

`--risk` remains as an explicit override for what-if sizing. It never silently supplies a
value; omitting it resolves from the R-CONFIG.

## CLI Surface

```
falcon-stats size SYMBOL {long,short} ENTRY [--risk RISK] [--account {LIVE,SIM}]
```

Output must state the resolved R and its provenance, so a wrong value is visible at the
point of use rather than discovered in a review weeks later:

```
Sizing SOXL long @ 24.15
R = $28.00 (LIVE, per PREFERENCES.md R-CONFIG)
```

## Acceptance criteria

1. `grep -rnE "\b280(\.0)?\b" falcon_stats/` returns **no** risk-related hits.
2. `load_r_config("LIVE").r_value == 28.0` and `load_r_config("SIM").r_value == 75.0`
   against the live `PREFERENCES.md`.
3. Editing the LIVE `R_VALUE` in `PREFERENCES.md` to an arbitrary test value changes
   `falcon-stats size` output on the next invocation, with **no code change**.
4. `load_r_config` raises `RConfigError` — not a default — when the file is absent, the
   block is missing, or the account row is unparseable. Three separate tests.
5. `falcon-stats size` with no `--risk` prints the resolved R **and** its source path.
6. `daily_max_r == 3 * r_value` and `per_symbol_max_r == 1 * r_value` are derived, never
   parsed independently, so they cannot drift from `r_value`.
7. `pytest tests/ -q` passes.

## Rationale for the strictness

From `ReportingSchema.md` Rule 0:

> A rule with no live enforcer is ASPIRATIONAL and MUST NOT be used to score a review.

The R-CONFIG currently calls itself SINGLE SOURCE OF TRUTH while nothing sources from it.
This spec is what makes that claim true. Until it ships, any statement that "R is defined
in PREFERENCES" is accurate for documents and false for code — and the gap between those
two is exactly where the 10× error lived for twelve days.
