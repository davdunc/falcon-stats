"""Trade cost calculator — estimate fees, R-multiples, and breakeven before entry.

Uses actual fee data from your Cobra broker history to model real costs.
Answers: "If I take this trade, what's my real R after fees?"

Fee model (from 847 trades on a Cobra live account):
- Commission: ~$0.0015/share (route-dependent, rebates offset)
- ECN Maker rebate: ~$0.0006/share (you GET paid for adding liquidity)
- SEC Fee: ~$0.0000278 × notional (sells only)
- TAF Fee: $0.000166/share (sells only)
- CAT Fee: ~$0.000011/share
- Effective cost: ~$0.003-0.01/share round-trip depending on route and price
"""

from dataclasses import dataclass


# Fee rates derived from actual Cobra broker data (847 trades, June 2025 - April 2026)
# These are averages — actual rates vary by route (SMAT vs REB25 vs direct)
DEFAULT_FEE_RATES = {
    "commission_per_share": 0.0015,     # ~$0.77/trade avg on ~500sh avg
    "ecn_net_per_share": 0.0004,        # Net ECN (taker - maker rebate)
    "sec_rate": 0.0000278,              # SEC fee rate on sell notional
    "taf_per_share": 0.000166,          # TAF on sells
    "cat_per_share": 0.000011,          # CAT fee
}


@dataclass
class TradeEstimate:
    """Estimated costs and R-multiple for a planned trade."""

    symbol: str
    side: str
    shares: int
    entry: float
    target: float
    stop: float

    # Calculated fields
    notional: float = 0
    risk_per_share: float = 0
    reward_per_share: float = 0
    total_risk_dollars: float = 0
    total_reward_dollars: float = 0

    # Fees (round-trip: entry + exit)
    entry_fees: float = 0
    exit_fees: float = 0
    total_fees: float = 0
    fee_as_pct_of_risk: float = 0

    # Real R after fees
    gross_r: float = 0
    net_r_win: float = 0
    net_r_loss: float = 0
    breakeven_move: float = 0

    def summary(self) -> str:
        """Human-readable trade estimate."""
        lines = [
            f"{'='*55}",
            f"  TRADE ESTIMATE: {self.symbol} {self.side}",
            f"{'='*55}",
            f"  Shares:       {self.shares}",
            f"  Entry:        ${self.entry:.2f}",
            f"  Target:       ${self.target:.2f} ({'+' if self.reward_per_share > 0 else ''}{self.reward_per_share:.2f}/sh)",
            f"  Stop:         ${self.stop:.2f} ({self.risk_per_share:+.2f}/sh)",
            f"  Notional:     ${self.notional:,.2f}",
            f"",
            f"  Risk:         ${self.total_risk_dollars:.2f} ({self.risk_per_share * self.shares:.2f})",
            f"  Reward:       ${self.total_reward_dollars:.2f} ({self.reward_per_share * self.shares:.2f})",
            f"  Gross R:      {self.gross_r:.2f}R",
            f"",
            f"  FEES (round-trip):",
            f"  Entry fees:   ${self.entry_fees:.4f}",
            f"  Exit fees:    ${self.exit_fees:.4f}",
            f"  Total fees:   ${self.total_fees:.4f}",
            f"  Fee % of risk: {self.fee_as_pct_of_risk:.1f}%",
            f"",
            f"  NET R (win):  {self.net_r_win:.2f}R  (after fees on winning exit)",
            f"  NET R (loss): {self.net_r_loss:.2f}R  (after fees on losing exit)",
            f"  Breakeven:    ${self.breakeven_move:.4f}/sh move to cover fees",
            f"{'='*55}",
        ]
        return "\n".join(lines)


def estimate_trade(
    symbol: str,
    side: str,
    shares: int,
    entry: float,
    target: float,
    stop: float,
    fee_rates: dict | None = None,
) -> TradeEstimate:
    """Calculate estimated costs and real R-multiple for a planned trade.

    Args:
        symbol: Ticker symbol
        side: "LONG" or "SHORT"
        shares: Number of shares
        entry: Planned entry price
        target: Profit target price
        stop: Stop loss price
        fee_rates: Custom fee rates (default: Cobra historical averages)

    Returns:
        TradeEstimate with all calculated fields
    """
    rates = fee_rates or DEFAULT_FEE_RATES

    est = TradeEstimate(
        symbol=symbol,
        side=side.upper(),
        shares=shares,
        entry=entry,
        target=target,
        stop=stop,
    )

    est.notional = shares * entry

    # Risk and reward per share
    if side.upper() == "LONG":
        est.risk_per_share = entry - stop
        est.reward_per_share = target - entry
    else:  # SHORT
        est.risk_per_share = stop - entry
        est.reward_per_share = entry - target

    est.total_risk_dollars = est.risk_per_share * shares
    est.total_reward_dollars = est.reward_per_share * shares
    est.gross_r = est.reward_per_share / est.risk_per_share if est.risk_per_share > 0 else 0

    # Fee calculation (round-trip)
    comm = rates["commission_per_share"]
    ecn = rates["ecn_net_per_share"]
    sec_rate = rates["sec_rate"]
    taf = rates["taf_per_share"]
    cat = rates["cat_per_share"]

    # Entry fees (buy side for longs, sell side for shorts)
    entry_per_share = comm + ecn + cat
    if side.upper() == "SHORT":
        # Selling on entry — SEC + TAF apply
        entry_per_share += (entry * sec_rate) + taf
    est.entry_fees = entry_per_share * shares

    # Exit fees (sell side for longs, buy side for shorts)
    exit_per_share = comm + ecn + cat
    if side.upper() == "LONG":
        # Selling on exit — SEC + TAF apply on both win and loss exit
        avg_exit = (target + stop) / 2  # Use average for estimation
        exit_per_share += (avg_exit * sec_rate) + taf
    est.exit_fees = exit_per_share * shares

    est.total_fees = est.entry_fees + est.exit_fees
    est.fee_as_pct_of_risk = (est.total_fees / est.total_risk_dollars * 100) if est.total_risk_dollars > 0 else 0

    # Net R after fees
    est.net_r_win = (est.total_reward_dollars - est.total_fees) / est.total_risk_dollars if est.total_risk_dollars > 0 else 0
    est.net_r_loss = -(est.total_risk_dollars + est.total_fees) / est.total_risk_dollars if est.total_risk_dollars > 0 else 0

    # Breakeven move (how much price must move to cover fees)
    est.breakeven_move = est.total_fees / shares if shares > 0 else 0

    return est
