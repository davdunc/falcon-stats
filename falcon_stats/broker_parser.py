"""Cobra broker Excel parser — reads Account Activity exports into Trade models.

Different from DAS CSV parser:
- Buys are positive quantity, sells are negative
- Includes full fee breakdown (commissions, ECN, SEC, TAF, CAT)
- Includes non-trade entries (marks to market, wires) that we filter out
- .xls extension but actually .xlsx format (broker quirk)
"""

import os
from datetime import datetime
from pathlib import Path

import openpyxl

from .models import Trade, Side


def parse_broker_excel(path: Path) -> list[Trade]:
    """Parse Cobra broker Account Activity Excel into Trade objects.

    Expected columns (0-indexed):
    0: Date, 1: Quantity, 2: Symbol, 3: Description, 4: Price,
    5: TransFee, 6: ECNTaker, 7: ECNMaker, 8: ORFFee, 9: TAFFee,
    10: SECFee, 11: CATFee, 12: Amount, 13: Type, 14: Commissions
    """
    # Handle .xls files that are actually .xlsx
    wb = openpyxl.load_workbook(path)
    sheet = wb[wb.sheetnames[0]]

    trades = []
    trade_id = 0

    for row in sheet.iter_rows(min_row=2, values_only=True):
        date, qty, symbol, desc, price, transfee, ecn_taker, ecn_maker, orf, taf, sec, cat, amount, type_, commission = row

        # Skip non-trade entries (marks to market, wires, dividends, etc.)
        if qty is None or symbol is None or not symbol.strip() or not price or price == 0:
            continue

        trade_id += 1
        shares = abs(int(qty))
        side = Side.BUY if qty > 0 else Side.SELL

        # Calculate total fees for this execution
        fees = sum(abs(f or 0) for f in [commission, ecn_taker, ecn_maker, orf, taf, sec, cat, transfee])

        trades.append(Trade(
            trade_id=trade_id,
            order_id=trade_id,  # Broker data doesn't have order IDs
            account=os.getenv("FALCON_LIVE_ACCOUNT", "ACCT_LIVE"),
            symbol=symbol.strip(),
            side=side,
            quantity=shares,
            price=float(price),
            time=date if isinstance(date, datetime) else datetime.strptime(str(date), "%Y-%m-%d"),
            route="COBRA",
            is_short=(type_ == "Short"),
        ))

    wb.close()
    return sorted(trades, key=lambda t: (t.time, t.symbol))


def parse_broker_fees(path: Path) -> dict:
    """Extract fee summary from broker data for cost modeling.

    Returns fee rates per share and per trade for use in the trade calculator.
    """
    wb = openpyxl.load_workbook(path)
    sheet = wb[wb.sheetnames[0]]

    total_shares = 0
    total_trades = 0
    fee_totals = {
        "commission": 0, "ecn_taker": 0, "ecn_maker": 0,
        "orf": 0, "taf": 0, "sec": 0, "cat": 0, "transfee": 0,
    }

    for row in sheet.iter_rows(min_row=2, values_only=True):
        date, qty, symbol, desc, price, transfee, ecn_taker, ecn_maker, orf, taf, sec, cat, amount, type_, commission = row

        if qty is None or symbol is None or not symbol.strip() or not price or price == 0:
            continue

        shares = abs(int(qty))
        total_shares += shares
        total_trades += 1
        fee_totals["commission"] += abs(commission or 0)
        fee_totals["ecn_taker"] += abs(ecn_taker or 0)
        fee_totals["ecn_maker"] += abs(ecn_maker or 0)
        fee_totals["orf"] += abs(orf or 0)
        fee_totals["taf"] += abs(taf or 0)
        fee_totals["sec"] += abs(sec or 0)
        fee_totals["cat"] += abs(cat or 0)
        fee_totals["transfee"] += abs(transfee or 0)

    wb.close()

    total_fees = sum(fee_totals.values())

    return {
        "total_trades": total_trades,
        "total_shares": total_shares,
        "total_fees": total_fees,
        "avg_fee_per_trade": total_fees / total_trades if total_trades else 0,
        "avg_fee_per_share": total_fees / total_shares if total_shares else 0,
        "fee_breakdown": fee_totals,
        "per_share_rates": {
            k: v / total_shares if total_shares else 0
            for k, v in fee_totals.items()
        },
    }
