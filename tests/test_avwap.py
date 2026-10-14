"""Unit tests for the event-anchored VWAP study (no network)."""

import math

import pytest

from falcon_stats.avwap import Bar, anchored_vwap, binom_sf, last_per_month, study, touch_holds


def bar(day, h, l, c, v=100.0):
    return Bar(day, h, l, c, v)


def test_last_per_month_drops_revision_dates():
    dates = ["2022-02-08", "2022-02-10", "2022-03-10"]
    assert last_per_month(dates) == ["2022-02-10", "2022-03-10"]


def test_anchored_vwap_is_volume_weighted_typical_price():
    bars = [bar("d0", 12, 9, 9, 100), bar("d1", 21, 18, 18, 300)]
    line = anchored_vwap(bars, 0)
    assert line[0] == pytest.approx(10.0)
    assert line[1] == pytest.approx((10 * 100 + 19 * 300) / 400)


def test_anchored_vwap_starts_at_anchor():
    bars = [bar("d0", 100, 100, 100), bar("d1", 12, 9, 9)]
    assert anchored_vwap(bars, 1) == [pytest.approx(10.0)]


def test_touch_holds_counts_hold_and_break():
    # Flat line at 10; price above, then two touches: one holds (closes above), one breaks.
    bars = [bar(f"d{i}", 10, 10, 10, 1e9) for i in range(4)]  # heavy volume pins AVWAP at 10
    bars += [bar("d4", 11.0, 10.5, 10.8, 1), bar("d5", 10.9, 9.9, 10.4, 1),
             bar("d6", 10.5, 9.8, 10.2, 1), bar("d7", 10.3, 9.5, 9.7, 1)]
    touches, holds, now = touch_holds(bars, 0, min_age=4, window=100)
    assert touches == 3           # d5, d6, d7 span ~10
    assert holds == 2             # d5, d6 close above; d7 closes below
    assert now == pytest.approx(10.0, abs=1e-6)


def test_touch_holds_respects_min_age():
    bars = [bar("d0", 11, 9, 10), bar("d1", 11, 9, 10), bar("d2", 11, 9, 10)]
    assert touch_holds(bars, 0, min_age=3, window=100)[0] == 0


def test_binom_sf_edges():
    assert binom_sf(0, 10, 0.5) == pytest.approx(1.0)
    assert binom_sf(10, 10, 0.5) == pytest.approx(0.5**10)
    assert binom_sf(6, 10, 0.5) == pytest.approx(sum(math.comb(10, j) for j in range(6, 11)) / 1024)


def test_study_rejects_events_outside_history():
    bars = [bar(f"2026-01-{d:02d}", 11, 9, 10) for d in range(1, 20)]
    with pytest.raises(ValueError):
        study("XYZ", bars, ["2025-06-01"])


def test_study_shapes_result():
    bars = [bar(f"2026-01-{d:02d}", 10 + (d % 3), 9 + (d % 3), 9.5 + (d % 3)) for d in range(1, 29)]
    r = study("xyz", bars, ["2026-01-05", "2026-01-12"], min_age=2, window=20)
    assert r.symbol == "XYZ"
    assert [a.day for a in r.anchors] == ["2026-01-05", "2026-01-12"]
    assert 0.0 <= r.null_rate <= 1.0


def test_window_bars_spans_event_day_and_next_session_only():
    from falcon_stats.avwap import window_bars
    stamps = ["2026-10-14 04:00", "2026-10-14 08:30", "2026-10-14 15:55", "2026-10-14 17:00",
              "2026-10-15 07:00", "2026-10-15 09:30", "2026-10-15 15:55", "2026-10-16 09:30"]
    kept = [b.day for b in window_bars([bar(s, 1, 1, 1) for s in stamps], "08:30")]
    assert kept == ["2026-10-14 08:30", "2026-10-14 15:55", "2026-10-15 09:30", "2026-10-15 15:55"]
