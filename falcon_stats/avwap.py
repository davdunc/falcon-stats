"""Event-anchored VWAP study: do VWAPs anchored on event days act as support/resistance?

Anchors an AVWAP on each event day (default: CPI release days from FRED), then
measures how often price *holds* the line when it touches it, against the same
measurement on VWAPs anchored to every non-event day. An event anchor only
matters if it beats that baseline.

Definitions (daily bars, typical price (H+L+C)/3 weighted by volume):
  touch  a session whose range spans the AVWAP, after the line is MIN_AGE sessions old
  hold   that session closes back on the side the prior close was on
  null   hold rate over AVWAPs anchored on every non-event day in the study window

Significance:
  pooled     two-proportion z of event-anchor holds vs the null hold rate
  per anchor one-sided binomial P(X >= holds) at the null rate; flagged only with
             enough touches, and read against the number of anchors tested

Data: FRED release dates (release 10 = CPI) and Massive (Polygon) daily aggregates.
One request each; nothing here retries or bursts.
"""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FRED_RELEASE_DATES = "https://api.stlouisfed.org/fred/release/dates"
MASSIVE_BASE = "https://api.polygon.io"
FRED_RELEASES = {"cpi": 10}  # event name -> FRED release id


def _secret(key: str) -> str:
    """process.env first, then ~/.claude/.env read directly (LifeOS secrets rule)."""
    value = os.environ.get(key)
    if value:
        return value
    env = Path.home() / ".claude" / ".env"
    try:
        for line in env.read_text().splitlines():
            name, sep, raw = line.partition("=")
            if sep and not name.lstrip().startswith("#") and name.strip() == key:
                return raw.strip().strip("'\"")
    except OSError:
        pass
    raise ValueError(f"{key} not set in the environment or ~/.claude/.env")


def _get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=30) as resp:
        return json.load(resp)


@dataclass(frozen=True)
class Bar:
    day: str
    high: float
    low: float
    close: float
    volume: float

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3


def last_per_month(dates: list[str]) -> list[str]:
    """FRED lists revision dates alongside releases (e.g. CPI seasonal factors in Feb).
    Keep the last date in each month, which is the release itself."""
    by_month: dict[str, list[str]] = defaultdict(list)
    for d in dates:
        by_month[d[:7]].append(d)
    return sorted(max(v) for v in by_month.values())


def fetch_event_dates(event: str, since: str) -> list[str]:
    if event not in FRED_RELEASES:
        raise ValueError(f"unknown event {event!r}; known: {', '.join(FRED_RELEASES)}")
    data = _get_json(FRED_RELEASE_DATES, {
        "release_id": FRED_RELEASES[event], "api_key": _secret("FRED_API_KEY"), "file_type": "json",
        "realtime_start": since, "include_release_dates_with_no_data": "true", "limit": 1000,
    })
    return last_per_month([r["date"] for r in data.get("release_dates", [])])


def fetch_daily_bars(symbol: str, since: str, until: str) -> list[Bar]:
    data = _get_json(f"{MASSIVE_BASE}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{since}/{until}", {
        "adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": _secret("POLYGON_API_KEY"),
    })
    return [
        Bar(datetime.fromtimestamp(r["t"] / 1000, timezone.utc).strftime("%Y-%m-%d"),
            r["h"], r["l"], r["c"], r["v"])
        for r in data.get("results", [])
    ]


def anchored_vwap(bars: list[Bar], anchor: int) -> list[float]:
    """AVWAP values for bars[anchor:], one per session."""
    pv = vol = 0.0
    out = []
    for b in bars[anchor:]:
        pv += b.typical * b.volume
        vol += b.volume
        out.append(pv / vol)
    return out


def touch_events(bars: list[Bar], anchor: int, min_age: int, window: int) -> list[tuple[int, bool]]:
    """(bar index, held) for every touch of the AVWAP anchored at `anchor`."""
    line = anchored_vwap(bars, anchor)
    out = []
    for k in range(min_age, min(len(line), window)):
        i = anchor + k
        level = line[k]
        if not (bars[i].low <= level <= bars[i].high):
            continue
        side = 1 if bars[i - 1].close > line[k - 1] else -1
        out.append((i, (bars[i].close - level) * side > 0))
    return out


def touch_holds(bars: list[Bar], anchor: int, min_age: int, window: int) -> tuple[int, int, float]:
    """(touches, holds, current AVWAP) for one anchor."""
    events = touch_events(bars, anchor, min_age, window)
    return len(events), sum(h for _, h in events), anchored_vwap(bars, anchor)[-1]


def pooled_z(holds: int, touches: int, base_holds: int, base_touches: int) -> float:
    """Two-proportion z of an event hold rate against a baseline; nan when undefined."""
    if not touches or not base_touches:
        return float("nan")
    p0 = base_holds / base_touches
    var = p0 * (1 - p0) * (1 / touches + 1 / base_touches)
    return (holds / touches - p0) / math.sqrt(var) if var > 0 else float("nan")


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


@dataclass
class AnchorResult:
    day: str
    touches: int
    holds: int
    p_value: float
    avwap_now: float

    @property
    def hold_rate(self) -> float:
        return self.holds / self.touches if self.touches else float("nan")


@dataclass
class StudyResult:
    symbol: str
    first_day: str
    last_day: str
    last_close: float
    null_rate: float
    null_touches: int
    event_rate: float
    event_touches: int
    z: float
    anchors: list[AnchorResult]


def study(symbol: str, bars: list[Bar], event_days: list[str], min_age: int = 3, window: int = 250) -> StudyResult:
    index = {b.day: i for i, b in enumerate(bars)}
    anchors = [index[d] for d in event_days if d in index]
    if not anchors:
        raise ValueError("no event day falls inside the bar history")
    anchor_set = set(anchors)

    null_t = null_h = 0
    for a in range(anchors[0], len(bars) - min_age - 1):
        if a in anchor_set:
            continue
        t, h, _ = touch_holds(bars, a, min_age, window)
        null_t += t
        null_h += h
    if not null_t:
        raise ValueError("baseline has no touches; history too short for this window")
    p0 = null_h / null_t

    results, ev_t, ev_h = [], 0, 0
    for a in anchors:
        t, h, now = touch_holds(bars, a, min_age, window)
        ev_t += t
        ev_h += h
        results.append(AnchorResult(bars[a].day, t, h, binom_sf(h, t, p0) if t else 1.0, now))

    pe = ev_h / ev_t if ev_t else float("nan")
    return StudyResult(symbol.upper(), bars[0].day, bars[-1].day, bars[-1].close,
                       p0, null_t, pe, ev_t, pooled_z(ev_h, ev_t, null_h, null_t), results)


def render(r: StudyResult, event: str, window: int, ref: float | None, min_touches: int = 8) -> str:
    ref_price = ref if ref is not None else r.last_close
    expected_false = 0.05 * len(r.anchors)
    sig = [a for a in r.anchors if a.p_value < 0.05 and a.touches >= min_touches]
    verdict = ("SIGNIFICANT" if abs(r.z) >= 1.96 else "not significant")
    lines = [
        f"{r.symbol} — {event.upper()}-anchored VWAP study ({r.first_day}..{r.last_day}, window {window} sessions)",
        f"baseline (non-{event} anchors): hold {r.null_rate:.1%} over {r.null_touches} touches",
        f"{event} anchors ({len(r.anchors)}): hold {r.event_rate:.1%} over {r.event_touches} touches  "
        f"z={r.z:+.2f} → {verdict}",
        f"per-anchor p<0.05 (≥{min_touches} touches): {len(sig)} found vs ~{expected_false:.1f} expected by chance",
        "",
        f"{'anchor':10} {'touch':>5} {'hold':>5} {'rate':>5} {'p':>6} {'AVWAP':>8} {'vs ' + format(ref_price, '.2f'):>9}",
    ]
    for a in r.anchors:
        flag = " *" if a in sig else ""
        lines.append(f"{a.day:10} {a.touches:5d} {a.holds:5d} {a.hold_rate:5.2f} {a.p_value:6.3f} "
                     f"{a.avwap_now:8.2f} {a.avwap_now - ref_price:+9.2f}{flag}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Intraday mode: the announcement window itself (event day + the next session).
#
# Anchor: the first bar at/after the release time (CPI = 08:30 ET) on the event day.
# Touches are counted from 08:30 ET on the event day through 16:00 ET on the next
# session; overnight extended-hours bars are skipped as too thin to define a level.
# Baseline: the same weekday one week earlier (same clock times, no release), so the
# comparison holds time-of-day and session structure fixed and isolates the event.
# --------------------------------------------------------------------------------------

from datetime import date as _date, timedelta
from time import sleep
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RELEASE_TIME_ET = {"cpi": "08:30"}
REQUEST_SPACING_S = 0.15  # stay under ~10 requests/second on Massive


def fetch_intraday_bars(symbol: str, start: str, end: str, minutes: int = 5) -> list[Bar]:
    """Massive minute aggregates (incl. extended hours); Bar.day is 'YYYY-MM-DD HH:MM' ET."""
    data = _get_json(f"{MASSIVE_BASE}/v2/aggs/ticker/{symbol.upper()}/range/{minutes}/minute/{start}/{end}", {
        "adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": _secret("POLYGON_API_KEY"),
    })
    return [
        Bar(datetime.fromtimestamp(r["t"] / 1000, timezone.utc).astimezone(ET).strftime("%Y-%m-%d %H:%M"),
            r["h"], r["l"], r["c"], r["v"])
        for r in data.get("results", [])
    ]


def window_bars(bars: list[Bar], start_hhmm: str) -> list[Bar]:
    """Bars from start_hhmm on the first session through 16:00 on the second session,
    keeping only 08:30–16:00 ET (drops overnight extended hours)."""
    days = sorted({b.day[:10] for b in bars})[:2]
    if len(days) < 2:
        return []
    keep = []
    for b in bars:
        d, t = b.day[:10], b.day[11:]
        if d not in days or not ("08:30" <= t < "16:00"):
            continue
        if d == days[0] and t < start_hhmm:
            continue
        keep.append(b)
    return keep


@dataclass
class IntradayResult:
    symbol: str
    minutes: int
    events: int
    event_holds: int
    event_touches: int
    base_holds: int
    base_touches: int
    day0: tuple[int, int]   # (holds, touches) on the event day
    day1: tuple[int, int]   # (holds, touches) on the next session
    z: float
    z_day0: float
    z_day1: float
    skipped: list[str]


def intraday_study(symbol: str, event: str, event_days: list[str], minutes: int = 5,
                   min_age: int = 3) -> IntradayResult:
    start = RELEASE_TIME_ET[event]
    event_set = set(event_days)
    tot = {"ev": [0, 0], "base": [0, 0], "d0": [0, 0], "d1": [0, 0], "b0": [0, 0], "b1": [0, 0]}
    skipped = []

    def run(day: str, tag: str, split: tuple[str, str]):
        d = _date.fromisoformat(day)
        bars = window_bars(fetch_intraday_bars(symbol, day, (d + timedelta(days=5)).isoformat(), minutes), start)
        sleep(REQUEST_SPACING_S)
        if not bars or bars[0].day[:10] != day:
            return False
        first_day = bars[0].day[:10]
        for i, held in touch_events(bars, 0, min_age, len(bars)):
            key = split[0] if bars[i].day[:10] == first_day else split[1]
            for k in (tag, key):
                tot[k][0] += held
                tot[k][1] += 1
        return True

    for day in event_days:
        control = (_date.fromisoformat(day) - timedelta(days=7)).isoformat()
        # Control first: an event without its control is dropped, so both sides stay paired.
        if control in event_set or not run(control, "base", ("b0", "b1")):
            skipped.append(f"{day} (no control session {control})")
            continue
        if not run(day, "ev", ("d0", "d1")):
            skipped.append(f"{day} (no event bars)")  # control already counted; reported for transparency

    z = pooled_z(*tot["ev"], *tot["base"])
    return IntradayResult(symbol.upper(), minutes, len(event_days) - len(skipped),
                          tot["ev"][0], tot["ev"][1], tot["base"][0], tot["base"][1],
                          tuple(tot["d0"]), tuple(tot["d1"]), z,
                          pooled_z(*tot["d0"], *tot["b0"]), pooled_z(*tot["d1"], *tot["b1"]), skipped)


def render_intraday(r: IntradayResult, event: str) -> str:
    rate = lambda h, t: f"{h / t:.1%} ({h}/{t})" if t else "n/a"
    verdict = lambda z: "SIGNIFICANT" if abs(z) >= 1.96 else "not significant"
    return "\n".join([
        f"{r.symbol} — {event.upper()}-anchored VWAP, announcement window ({r.minutes}-min bars, "
        f"anchor {RELEASE_TIME_ET[event]} ET, event day + next session), {r.events} events",
        f"control (same weekday, 1 week earlier): hold {rate(r.base_holds, r.base_touches)}",
        f"{event} windows                          : hold {rate(r.event_holds, r.event_touches)}  "
        f"z={r.z:+.2f} → {verdict(r.z)}",
        f"  event day   : hold {rate(*r.day0)}  z={r.z_day0:+.2f} → {verdict(r.z_day0)}",
        f"  next session: hold {rate(*r.day1)}  z={r.z_day1:+.2f} → {verdict(r.z_day1)}",
        f"skipped: {', '.join(r.skipped) if r.skipped else 'none'}",
    ])
