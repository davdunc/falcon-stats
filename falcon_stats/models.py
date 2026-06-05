"""Core data models for the trading statistics engine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(Enum):
    BUY = "B"
    SELL = "S"


@dataclass
class Trade:
    """A single execution from DAS Trades.csv."""

    trade_id: int
    order_id: int
    account: str
    symbol: str
    side: Side
    quantity: int
    price: float
    time: datetime
    route: str = ""
    is_short: bool = False
    parent_trade_id: int | None = None

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def is_synthetic(self) -> bool:
        return self.parent_trade_id is not None


@dataclass
class Order:
    """An order from DAS Orders.csv, includes stop price if set."""

    order_id: int
    account: str
    symbol: str
    side: Side
    quantity: int
    price: float
    stop_price: float | None
    trail_price: float | None
    time: datetime
    market_type: str = ""


@dataclass
class RoundTrip:
    """A complete position: entry → (optional adds) → exit.

    A round-trip is the atomic unit of trading analysis.
    All statistics are computed from round-trips, not individual trades.
    """

    symbol: str
    account: str
    side: Side  # BUY = long round-trip, SELL = short round-trip
    entries: list[Trade] = field(default_factory=list)
    exits: list[Trade] = field(default_factory=list)
    planned_stop: float | None = None

    @property
    def entry_time(self) -> datetime:
        return min(t.time for t in self.entries)

    @property
    def exit_time(self) -> datetime | None:
        if not self.exits:
            return None
        return max(t.time for t in self.exits)

    @property
    def total_shares(self) -> int:
        return sum(t.quantity for t in self.entries)

    @property
    def shares_exited(self) -> int:
        return sum(t.quantity for t in self.exits)

    @property
    def is_closed(self) -> bool:
        return self.shares_exited >= self.total_shares

    @property
    def avg_entry(self) -> float:
        total_cost = sum(t.quantity * t.price for t in self.entries)
        return total_cost / self.total_shares if self.total_shares else 0.0

    @property
    def avg_exit(self) -> float:
        if not self.exits:
            return 0.0
        total_proceeds = sum(t.quantity * t.price for t in self.exits)
        return total_proceeds / self.shares_exited if self.shares_exited else 0.0

    @property
    def pnl(self) -> float:
        """Realized P&L in dollars."""
        if not self.is_closed:
            return 0.0
        if self.side == Side.BUY:
            return (self.avg_exit - self.avg_entry) * self.total_shares
        else:  # short
            return (self.avg_entry - self.avg_exit) * self.total_shares

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def risk_per_share(self) -> float | None:
        """Risk per share based on planned stop."""
        if self.planned_stop is None:
            return None
        return abs(self.avg_entry - self.planned_stop)

    @property
    def r_multiple(self) -> float | None:
        """Profit/loss expressed as a multiple of planned risk.

        +2.0R = made 2x what you risked
        -1.0R = lost exactly what you planned to risk
        -1.5R = lost 1.5x planned risk (stop not honored)
        """
        risk = self.risk_per_share
        if risk is None or risk == 0:
            return None
        pnl_per_share = self.pnl / self.total_shares
        return pnl_per_share / risk

    def to_dict(self, sanitized: bool = False) -> dict:
        """Convert to dictionary for storage or display.

        If sanitized=True, omits dollar amounts, account IDs, and uses
        R-multiples only. Safe for public sharing.
        """
        base = {
            "symbol": self.symbol,
            "side": "LONG" if self.side == Side.BUY else "SHORT",
            "shares": self.total_shares,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "is_winner": self.is_winner,
            "r_multiple": round(self.r_multiple, 2) if self.r_multiple is not None else None,
        }

        if not sanitized:
            base.update({
                "account": self.account,
                "avg_entry": round(self.avg_entry, 4),
                "avg_exit": round(self.avg_exit, 4),
                "pnl": round(self.pnl, 2),
                "planned_stop": self.planned_stop,
            })

        return base


@dataclass
class DailyStats:
    """Aggregated statistics for a single trading day."""

    date: str
    account: str
    round_trips: list[RoundTrip] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.round_trips)

    @property
    def winners(self) -> list[RoundTrip]:
        return [rt for rt in self.round_trips if rt.is_winner]

    @property
    def losers(self) -> list[RoundTrip]:
        return [rt for rt in self.round_trips if rt.is_closed and not rt.is_winner]

    @property
    def win_rate(self) -> float:
        closed = [rt for rt in self.round_trips if rt.is_closed]
        if not closed:
            return 0.0
        return len(self.winners) / len(closed)

    @property
    def total_pnl(self) -> float:
        return sum(rt.pnl for rt in self.round_trips)

    @property
    def gross_profit(self) -> float:
        return sum(rt.pnl for rt in self.winners)

    @property
    def gross_loss(self) -> float:
        return abs(sum(rt.pnl for rt in self.losers))

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss

    @property
    def avg_winner(self) -> float:
        if not self.winners:
            return 0.0
        return sum(rt.pnl for rt in self.winners) / len(self.winners)

    @property
    def avg_loser(self) -> float:
        if not self.losers:
            return 0.0
        return sum(rt.pnl for rt in self.losers) / len(self.losers)

    @property
    def expectancy(self) -> float:
        """Expected value per trade: (win_rate × avg_win) - (loss_rate × avg_loss)."""
        if not self.round_trips:
            return 0.0
        return (self.win_rate * self.avg_winner) + ((1 - self.win_rate) * self.avg_loser)

    @property
    def r_multiples(self) -> list[float]:
        return [rt.r_multiple for rt in self.round_trips if rt.r_multiple is not None]

    @property
    def avg_r(self) -> float | None:
        """Average R-multiple per trade — the systematic trader's key metric."""
        rs = self.r_multiples
        if not rs:
            return None
        return sum(rs) / len(rs)

    def _equity_curve_stats(self) -> dict:
        """Walk the cumulative P&L curve once, return peak/trough/drawdown stats.

        Cached per access — small N, cheap to recompute.
        Returns: {peak, peak_time, trough, trough_time, max_drawdown, max_drawdown_time}.
        Peak/trough are vs. session start (0.0). Trough may be negative.
        max_drawdown is peak-to-trough; max_drawdown_time is when the post-peak trough hit.
        """
        if not self.round_trips:
            return {
                "peak": 0.0, "peak_time": None,
                "trough": 0.0, "trough_time": None,
                "max_drawdown": 0.0, "max_drawdown_time": None,
            }

        cumulative = 0.0
        peak = 0.0
        peak_time = None
        trough = 0.0
        trough_time = None
        running_peak = 0.0
        max_dd = 0.0
        max_dd_time = None

        for rt in sorted(self.round_trips, key=lambda r: r.entry_time):
            cumulative += rt.pnl
            mark_time = rt.exit_time or rt.entry_time

            if cumulative > peak:
                peak = cumulative
                peak_time = mark_time
            if cumulative < trough:
                trough = cumulative
                trough_time = mark_time

            running_peak = max(running_peak, cumulative)
            dd = running_peak - cumulative
            if dd > max_dd:
                max_dd = dd
                max_dd_time = mark_time

        return {
            "peak": peak, "peak_time": peak_time,
            "trough": trough, "trough_time": trough_time,
            "max_drawdown": max_dd, "max_drawdown_time": max_dd_time,
        }

    @property
    def peak_equity(self) -> float:
        """Highest cumulative P&L reached during the day (high-water mark)."""
        return self._equity_curve_stats()["peak"]

    @property
    def peak_equity_time(self) -> datetime | None:
        """When the peak equity was hit."""
        return self._equity_curve_stats()["peak_time"]

    @property
    def trough_equity(self) -> float:
        """Lowest cumulative P&L reached during the day (deepest red, can be negative)."""
        return self._equity_curve_stats()["trough"]

    @property
    def trough_equity_time(self) -> datetime | None:
        """When the trough equity was hit."""
        return self._equity_curve_stats()["trough_time"]

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown on the cumulative P&L curve."""
        return self._equity_curve_stats()["max_drawdown"]

    @property
    def max_drawdown_time(self) -> datetime | None:
        """When the max drawdown bottomed (the trough after the running peak)."""
        return self._equity_curve_stats()["max_drawdown_time"]

    @property
    def streak(self) -> tuple[int, str]:
        """Current streak: (count, 'W' or 'L')."""
        if not self.round_trips:
            return (0, "")
        sorted_rts = sorted(self.round_trips, key=lambda r: r.entry_time)
        current = "W" if sorted_rts[-1].is_winner else "L"
        count = 0
        for rt in reversed(sorted_rts):
            if (rt.is_winner and current == "W") or (not rt.is_winner and current == "L"):
                count += 1
            else:
                break
        return (count, current)

    def to_dict(self, sanitized: bool = False) -> dict:
        streak_count, streak_type = self.streak
        curve = self._equity_curve_stats()
        base = {
            "date": self.date,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "avg_r": round(self.avg_r, 2) if self.avg_r is not None else None,
            "max_drawdown_r": None,  # TODO: compute in R terms
            "streak": f"{streak_count}{streak_type}",
            "round_trips": [rt.to_dict(sanitized=sanitized) for rt in self.round_trips],
        }

        if not sanitized:
            base.update({
                "account": self.account,
                "total_pnl": round(self.total_pnl, 2),
                "gross_profit": round(self.gross_profit, 2),
                "gross_loss": round(self.gross_loss, 2),
                "avg_winner": round(self.avg_winner, 2),
                "avg_loser": round(self.avg_loser, 2),
                "expectancy": round(self.expectancy, 2),
                "peak_equity": round(curve["peak"], 2),
                "peak_equity_time": curve["peak_time"].isoformat() if curve["peak_time"] else None,
                "trough_equity": round(curve["trough"], 2),
                "trough_equity_time": curve["trough_time"].isoformat() if curve["trough_time"] else None,
                "max_drawdown": round(curve["max_drawdown"], 2),
                "max_drawdown_time": curve["max_drawdown_time"].isoformat() if curve["max_drawdown_time"] else None,
            })

        return base
