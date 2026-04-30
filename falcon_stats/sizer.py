"""Pre-trade position sizer — ATR-based stop width and share calculation.

Pulls recent OHLCV from Polygon to compute ATR, then shows sizing scenarios
at different stop widths so you enter with stops calibrated to actual volatility.

Usage:
    falcon-stats size NEXR long 3.75
    falcon-stats size POET short 8.42 --risk 280
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests


POLYGON_BASE = "https://api.polygon.io"


@dataclass
class SizeResult:
    """Pre-trade sizing analysis for a ticker."""

    symbol: str
    side: str
    entry: float
    current_price: float
    atr_14: float
    atr_pct: float  # ATR as % of price
    max_risk: float

    # Sizing scenarios: list of (stop_width_atr_multiple, stop_price, shares, risk_dollars, min_move_for_1r)
    scenarios: list

    def summary(self) -> str:
        lines = [
            f"{'='*62}",
            f"  PRE-TRADE SIZER: {self.symbol} {self.side}",
            f"{'='*62}",
            f"  Entry:          ${self.entry:.2f}",
            f"  Current Price:  ${self.current_price:.2f}",
            f"  14-day ATR:     ${self.atr_14:.2f} ({self.atr_pct:.1f}% of price)",
            f"  Max Risk:       ${self.max_risk:.2f}",
            f"",
            f"  {'Stop Width':<14s} {'Stop':>8s} {'Shares':>8s} {'Risk $':>8s} {'1R Target':>10s}",
            f"  {'-'*14:<14s} {'-'*8:>8s} {'-'*8:>8s} {'-'*8:>8s} {'-'*10:>10s}",
        ]

        for label, stop, shares, risk, target_1r in self.scenarios:
            lines.append(
                f"  {label:<14s} ${stop:>7.2f} {shares:>8d} ${risk:>7.2f} ${target_1r:>9.2f}"
            )

        lines.extend([
            f"",
            f"  RECOMMENDATION:",
        ])

        # Find the 1.0 ATR scenario
        atr_1_scenario = next((s for s in self.scenarios if "1.0" in s[0]), None)
        if atr_1_scenario:
            _, stop, shares, risk, target = atr_1_scenario
            lines.append(
                f"  Use 1.0 ATR stop (${self.atr_14:.2f} wide) → {shares} shares, "
                f"stop at ${stop:.2f}, 1R target ${target:.2f}"
            )

        # Warn if entry is far from current price
        dist = abs(self.entry - self.current_price) / self.current_price * 100
        if dist > 5:
            lines.append(f"")
            lines.append(
                f"  ⚠ Entry ${self.entry:.2f} is {dist:.1f}% from current ${self.current_price:.2f}"
            )

        lines.append(f"{'='*62}")
        return "\n".join(lines)


def _get_polygon_key() -> str:
    """Get Polygon API key from environment."""
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        # Try loading from .claude/.env
        env_path = os.path.expanduser("~/.claude/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("POLYGON_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    if not key:
        raise ValueError("POLYGON_API_KEY not found in environment or ~/.claude/.env")
    return key


def _fetch_ohlcv(symbol: str, days: int = 30) -> list[dict]:
    """Fetch daily OHLCV bars from Polygon."""
    api_key = _get_polygon_key()
    end = datetime.now()
    start = end - timedelta(days=days + 10)  # extra buffer for weekends/holidays

    url = (
        f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/1/day/"
        f"{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&apiKey={api_key}"
    )

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") not in ("OK", "DELAYED") or not data.get("results"):
        raise ValueError(f"No OHLCV data from Polygon for {symbol}")

    return data["results"]


def compute_atr(bars: list[dict], period: int = 14) -> float:
    """Compute Average True Range from OHLCV bars."""
    if len(bars) < period + 1:
        raise ValueError(f"Need at least {period + 1} bars, got {len(bars)}")

    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i]["h"]
        low = bars[i]["l"]
        prev_close = bars[i - 1]["c"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    # Use simple average of last `period` true ranges
    return sum(true_ranges[-period:]) / period


def size_trade(
    symbol: str,
    side: str,
    entry: float,
    max_risk: float = 280.0,
) -> SizeResult:
    """Calculate position sizing scenarios based on ATR.

    Args:
        symbol: Ticker symbol
        side: "long" or "short"
        entry: Planned entry price
        max_risk: Maximum dollar risk per trade (default: 1% of ~$28K)

    Returns:
        SizeResult with sizing scenarios at 0.5x, 0.75x, 1.0x, 1.5x, 2.0x ATR
    """
    bars = _fetch_ohlcv(symbol)
    atr = compute_atr(bars)
    current_price = bars[-1]["c"]
    side_upper = side.upper()

    multipliers = [
        ("0.5 ATR", 0.5),
        ("0.75 ATR", 0.75),
        ("1.0 ATR ★", 1.0),
        ("1.5 ATR", 1.5),
        ("2.0 ATR", 2.0),
    ]

    scenarios = []
    for label, mult in multipliers:
        stop_width = atr * mult

        if side_upper == "LONG":
            stop_price = entry - stop_width
            target_1r = entry + stop_width
        else:
            stop_price = entry + stop_width
            target_1r = entry - stop_width

        shares = int(max_risk / stop_width) if stop_width > 0 else 0
        actual_risk = shares * stop_width

        scenarios.append((label, stop_price, shares, actual_risk, target_1r))

    return SizeResult(
        symbol=symbol.upper(),
        side=side_upper,
        entry=entry,
        current_price=current_price,
        atr_14=atr,
        atr_pct=(atr / current_price) * 100,
        max_risk=max_risk,
        scenarios=scenarios,
    )
