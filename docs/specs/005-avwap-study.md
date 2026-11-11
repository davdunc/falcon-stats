# Spec 005 — Event-anchored VWAP study (`avwap-study`)

**Status:** Implemented (merged in PR #18, 2026-10-14)
**Owner:** davdunc
**Spec template version:** 1

## Status Checklist

- [x] Spec drafted (written after implementation, to make the study reproducible)
- [x] Spec reviewed
- [x] Implementation complete (`falcon_stats/avwap.py`, `cli.py` → `avwap-study`)
- [x] Tests passing on `pytest tests/ -q` (`tests/test_avwap.py`, 8 cases, no network)
- [x] Merged to `main`

## Problem

A common chart practice is to anchor a VWAP to a macro release (CPI) and treat the line as support or
resistance for the following sessions. Before putting such a line on a trading plan, we need to know
whether it holds **more often than a line with no event behind it**. A hold rate on its own is meaningless:
any line drawn through a price series gets touched and turned away a fair share of the time.

## Goal

A reproducible command that answers, for any symbol: **do VWAPs anchored on event days hold as
support/resistance more often than a baseline?** Answer it at two horizons:

1. **The sessions after each release** (daily bars).
2. **The release window itself:** event day plus the next session (intraday bars).

## Definitions

| Term | Definition |
|---|---|
| Anchored VWAP | Σ(typical price × volume) / Σ volume from the anchor bar forward; typical price = (H + L + C) / 3 |
| Touch | A bar whose range spans the AVWAP: `low ≤ AVWAP ≤ high` |
| Hold | That bar closes back on the side the **prior** close was on (relative to the prior bar's AVWAP) |
| Hold rate | holds ÷ touches |
| `min_age` | Bars after the anchor before touches count (the line is still forming). Default 3 |
| `window` | Bars after the anchor that are evaluated. Default 250 (daily mode) |

## Data

| Input | Source | Requests |
|---|---|---|
| Event dates | FRED `release/dates`, `release_id=10` (CPI), `include_release_dates_with_no_data=true` | 1 |
| Daily bars | Massive (Polygon) `/v2/aggs/ticker/{SYM}/range/1/day/{since}/{until}`, adjusted | 1 |
| Intraday bars | Massive `/range/{minutes}/minute/{day}/{day+5}`, includes extended hours, timestamps converted to ET | 2 per event (event + control), spaced 0.15 s (≤ ~7 req/s) |

**FRED revision dates:** release 10 also lists annual seasonal-revision dates (e.g. 2022-02-08 alongside the
2022-02-10 release). `last_per_month()` keeps the **last date in each month**, which is the release itself.
This also handles the delayed releases (2025-10-24 and 2025-12-18 in this history).

**Keys:** `FRED_API_KEY` and `POLYGON_API_KEY`, read from `process.env` first, then from `~/.claude/.env`
read directly (the LifeOS secrets rule). Nothing retries or bursts.

## Method

### Daily mode (default)

1. Anchor an AVWAP on each event day in the bar history.
2. Count touches and holds from `min_age` to `window` bars after each anchor.
3. **Baseline:** the same count for AVWAPs anchored on **every non-event day** from the first event onward.
   Hold rate `p0` = baseline holds ÷ baseline touches.
4. **Pooled test:** two-proportion z of event-anchor holds against `p0`. Significant at |z| ≥ 1.96.
   `pooled_z()` returns NaN when undefined (no touches, or p0 ∈ {0, 1}).
5. **Per-anchor test:** one-sided binomial P(X ≥ holds | n = touches, p = p0). Flagged only with
   ≥ 8 touches. The report prints the number of anchors expected under p < 0.05 by chance (0.05 × anchors),
   so a single flagged anchor isn't mistaken for an effect.

### Intraday mode (`--intraday`)

1. For each event day E, fetch E through E+5 calendar days of `--minutes` bars.
2. `window_bars()` keeps **08:30–16:00 ET** on the first two sessions only; overnight extended hours are
   dropped as too thin to define a level.
3. Anchor at the first bar at or after the release time (CPI = **08:30 ET**). Count touches and holds through
   16:00 ET of the next session, split into event day (day 0) and next session (day 1).
4. **Control:** the same weekday **7 calendar days earlier**, anchored at the same clock time. This holds
   time of day and session structure fixed and isolates the release.
5. **The pair is strict:** the control runs first. If it has no session (a holiday) or is itself an event
   day, the event is skipped entirely and listed under `skipped`.
6. Report z for both days pooled, and separately for day 0 and day 1.

## CLI

```bash
falcon-stats avwap-study SYMBOL [--event cpi] [--since 2022-01-01] [--until YYYY-MM-DD]
                                [--window 250] [--min-age 3] [--ref PRICE] [--json]
                                [--intraday] [--minutes 5]
```

- `--until` is exclusive for event days (an event on or after it isn't anchored). Default: today.
- `--ref` sets the reference price for the "distance to AVWAP" column. Default: the last close.
- `--json` emits the full `StudyResult` / `IntradayResult` dataclass.

## Reproducing the first result

The original run was BAC on 2026-10-14, the CPI morning. Using the code at the merge of PR #18:

```bash
falcon-stats avwap-study BAC --since 2022-01-01 --until 2026-10-14                 # daily, window 250
falcon-stats avwap-study BAC --since 2022-01-01 --until 2026-10-14 --window 60
falcon-stats avwap-study BAC --since 2022-01-01 --until 2026-10-14 --window 20
falcon-stats avwap-study BAC --since 2022-01-01 --until 2026-10-14 --intraday      # 5-min bars
```

Recorded aggregates. **Only aggregates are recorded here.** Per-anchor AVWAP price levels are licensed-data
derivatives and are not published.

| Run | Events | Baseline hold | Event hold | z | Verdict |
|---|---|---|---|---|---|
| Daily, window 250 | 56 | 54.3% (22,498 touches) | 55.0% (1,119) | +0.43 | not significant |
| Daily, window 60 | 56 | 52.5% | 54.3% (549) | +0.80 | not significant |
| Daily, window 20 | 56 | 52.7% | 56.3% (268) | +1.17 | not significant |
| Intraday, both days | 54 | 52.5% (1,314) | 52.0% (1,241) | −0.27 | not significant |
| Intraday, event day | 54 | (same control) | 52.4% (881) | −0.60 | not significant |
| Intraday, next session | 54 | (same control) | 50.8% (360) | +0.57 | not significant |

- Intraday skipped 2024-07-11 (control 2024-07-04 was a holiday) and 2026-04-10 (control 2026-04-03 was a
  holiday).
- Per-anchor (daily, window 60): 1 anchor at p < 0.05 against ~2.8 expected by chance.

**Conclusion:** on BAC, CPI-anchored VWAPs hold no better than arbitrary anchors, in the sessions after the
release or in the release window. Write-up: https://davidduncan.org/cpi-anchored-vwap-study.html

Results can drift slightly on re-run if the data vendor revises bars or FRED revises its release calendar.
Pin `--until` to reproduce a past run.

## Tests

`tests/test_avwap.py` (no network):
- the AVWAP volume-weighting math, and starting at the anchor;
- touch/hold counting (hold vs break);
- `min_age`;
- binomial tail edges;
- the FRED revision-date filter;
- error paths (events outside the history);
- result shape;
- the intraday window bounds (keeps 08:30–16:00 ET on two sessions, drops overnight bars and the third day).

## Limitations

- The **definition of "hold"** is one of several reasonable ones. Others: an N × ATR bounce, or holding for
  K bars. Results may differ under them.
- **One event type** (`cpi`). Adding an event means adding its FRED release id to `FRED_RELEASES` and its
  release time to `RELEASE_TIME_ET`.
- **Daily mode uses daily bars**, so intraday reactions to the line are only measured in `--intraday`.
- The control week can itself carry other events (FOMC, earnings). That's accepted as noise; it isn't modeled.

## Follow-up candidates (not implemented)

**`--atr` / `atr-study`: event-day price inefficiency in ATR units.** Measured ad hoc on 2026-10-14 for BAC
(56 CPI days vs 1,114 baseline sessions, ATR14 through the prior session, 10,000-shuffle permutation test):

| Metric ÷ ATR | Baseline | CPI day | Next session |
|---|---|---|---|
| Range | 0.92 | 1.03 (p=0.04) | 1.06 (p=0.01) |
| Gap | 0.28 | 0.39 (p=0.01) | 0.36 (p=0.06) |
| Net move | 0.51 | 0.60 (p=0.22) | 0.58 (p=0.36) |
| Gap drift (continue/fade) | −0.01 | 0.00 (p=0.88) | −0.04 (p=0.76) |

Sessions with a range ≥ 2 ATR: 2% baseline, 4% CPI day, 9% next session. The reading: CPI widens the range
and gap but gives no direction, and the next session carries the fatter tail. That's 8 tests on 56 events,
so it's not significant after correction. Implement it as a sibling mode with the same event and control
plumbing.

Other candidates:
- More events (FOMC, PPI, jobs).
- A symbol batch (SPY, TLT, sector ETFs).
- A configurable hold definition.
