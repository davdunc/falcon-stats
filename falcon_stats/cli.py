"""CLI interface for falcon-stats.

Usage:
    falcon-stats ingest <path>              Ingest a day's DAS CSV exports
    falcon-stats summary [--date DATE]      Show daily statistics
    falcon-stats week                       Show weekly aggregate
    falcon-stats trades [--date DATE]       List round-trips
    falcon-stats sanitized [--date DATE]    Show sanitized view (R-multiples only)
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from .parser import load_day
from .roundtrips import identify_round_trips
from .models import DailyStats

TRADE_REVIEW_PATH = Path(os.getenv(
    "TRADE_REVIEW_PATH",
    "/mnt/c/Users/davdunc/OneDrive/Desktop/Trade_Review",
))


def cmd_ingest(args):
    """Ingest a day's DAS CSV exports and compute statistics."""
    directory = Path(args.path)
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    trades_file = directory / "Trades.csv"
    if not trades_file.exists():
        print(f"Error: No Trades.csv found in {directory}", file=sys.stderr)
        sys.exit(1)

    print(f"Ingesting trades from {directory}...")
    trades, orders = load_day(directory)
    print(f"  Parsed {len(trades)} trades, {len(orders)} orders")

    round_trips = identify_round_trips(trades, orders)
    print(f"  Identified {len(round_trips)} round-trips")

    # Determine date from first trade
    if trades:
        date_str = trades[0].time.strftime("%Y-%m-%d")
    else:
        date_str = directory.name

    # Group by account
    accounts = set(rt.account for rt in round_trips)
    for account in sorted(accounts):
        account_rts = [rt for rt in round_trips if rt.account == account]
        stats = DailyStats(date=date_str, account=account, round_trips=account_rts)
        _print_summary(stats)

    # Write to DynamoDB (source of truth)
    try:
        from . import db
        count = db.put_round_trips(round_trips, date_str)
        print(f"\n  DynamoDB: {count} round-trips written")

        for account in sorted(accounts):
            account_rts = [rt for rt in round_trips if rt.account == account]
            stats = DailyStats(date=date_str, account=account, round_trips=account_rts)
            db.put_daily_stats(stats)
        print(f"  DynamoDB: {len(accounts)} daily stats written")
    except Exception as e:
        print(f"\n  DynamoDB write failed: {e}", file=sys.stderr)
        print(f"  Data is still available locally from CSV.", file=sys.stderr)


def cmd_summary(args):
    """Show summary statistics for a date."""
    # For now, re-ingest from the standard Trade_Review path
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    base = TRADE_REVIEW_PATH

    # Try to find the date directory
    year_month = date[:7]
    day_dir = base / year_month / date
    if not day_dir.exists():
        print(f"No trade data found for {date} at {day_dir}", file=sys.stderr)
        sys.exit(1)

    trades, orders = load_day(day_dir)
    round_trips = identify_round_trips(trades, orders)

    accounts = set(rt.account for rt in round_trips)
    for account in sorted(accounts):
        account_rts = [rt for rt in round_trips if rt.account == account]
        stats = DailyStats(date=date, account=account, round_trips=account_rts)
        _print_summary(stats)


def cmd_sanitized(args):
    """List round-trips in sanitized R-multiples view."""
    args.sanitized = True
    cmd_trades(args)


def cmd_trades(args):
    """List individual round-trips."""
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    sanitized = getattr(args, "sanitized", False)

    base = TRADE_REVIEW_PATH
    year_month = date[:7]
    day_dir = base / year_month / date
    if not day_dir.exists():
        print(f"No trade data found for {date}", file=sys.stderr)
        sys.exit(1)

    trades, orders = load_day(day_dir)
    round_trips = identify_round_trips(trades, orders)

    for rt in round_trips:
        d = rt.to_dict(sanitized=sanitized)
        side_label = d["side"]
        r_str = f"{d['r_multiple']:+.1f}R" if d["r_multiple"] is not None else "N/A"

        if sanitized:
            print(f"  {d['symbol']:6s} {side_label:5s} {d['shares']:3d}sh "
                  f"{r_str:>7s}  {'W' if d['is_winner'] else 'L'}")
        else:
            pnl_str = f"${d['pnl']:+.2f}"
            print(f"  {d['symbol']:6s} {side_label:5s} {d['shares']:3d}sh "
                  f"entry ${d['avg_entry']:.2f} → exit ${d['avg_exit']:.2f}  "
                  f"{pnl_str:>10s}  {r_str:>7s}  {'W' if d['is_winner'] else 'L'}")


def cmd_week(args):
    """Show weekly aggregate statistics."""
    base = TRADE_REVIEW_PATH
    # Find all date directories in the current month
    now = datetime.now()
    month_dir = base / now.strftime("%Y-%m")
    if not month_dir.exists():
        print(f"No data for {now.strftime('%Y-%m')}", file=sys.stderr)
        sys.exit(1)

    all_round_trips = []
    dates = sorted(d.name for d in month_dir.iterdir() if d.is_dir() and d.name.startswith("20"))

    # Get last 5 trading days
    recent_dates = dates[-5:]
    for date in recent_dates:
        day_dir = month_dir / date
        trades_file = day_dir / "Trades.csv"
        if not trades_file.exists():
            continue
        trades, orders = load_day(day_dir)
        rts = identify_round_trips(trades, orders)
        all_round_trips.extend(rts)

    if not all_round_trips:
        print("No trades found in recent days.")
        return

    # Compute weekly stats
    stats = DailyStats(
        date=f"{recent_dates[0]} → {recent_dates[-1]}",
        account="ALL",
        round_trips=all_round_trips,
    )

    print(f"\n{'='*50}")
    print(f"  WEEKLY SUMMARY: {stats.date}")
    print(f"{'='*50}")
    _print_summary(stats)


def cmd_backfill(args):
    """Backfill all historical CSV data into DynamoDB."""
    from . import db

    base = TRADE_REVIEW_PATH
    if not base.exists():
        print(f"Trade review path not found: {base}", file=sys.stderr)
        sys.exit(1)

    total_rts = 0
    total_stats = 0

    for month_dir in sorted(base.iterdir()):
        if not month_dir.is_dir() or not month_dir.name.startswith("20"):
            continue
        for day_dir in sorted(month_dir.iterdir()):
            if not day_dir.is_dir() or not day_dir.name.startswith("20"):
                continue
            trades_file = day_dir / "Trades.csv"
            if not trades_file.exists():
                continue

            try:
                trades, orders = load_day(day_dir)
                if not trades:
                    continue
                rts = identify_round_trips(trades, orders)
                date_str = day_dir.name

                count = db.put_round_trips(rts, date_str)
                total_rts += count

                accounts = set(rt.account for rt in rts)
                for account in sorted(accounts):
                    account_rts = [rt for rt in rts if rt.account == account]
                    stats = DailyStats(date=date_str, account=account, round_trips=account_rts)
                    db.put_daily_stats(stats)
                    total_stats += 1

                print(f"  {date_str}: {count} round-trips, {len(accounts)} stats")
            except Exception as e:
                print(f"  {day_dir.name}: ERROR — {e}", file=sys.stderr)

    print(f"\nBackfill complete: {total_rts} round-trips, {total_stats} daily stats written to DynamoDB")


def cmd_rebuild_notion(args):
    """Rebuild Notion databases from DynamoDB source of truth."""
    print("Rebuild Notion from DynamoDB — not yet implemented.")
    print("This will read all data from falcon-trades DynamoDB table")
    print("and recreate Notion pages in the Live/Paper/Daily Stats databases.")
    print("\nTo implement: add Notion API integration to falcon_stats/notion.py")


def cmd_ingest_broker(args):
    """Ingest Cobra broker Excel export into DynamoDB."""
    from . import db
    from .broker_parser import parse_broker_excel
    from collections import defaultdict

    path = Path(args.path)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing broker export: {path.name}...")
    trades = parse_broker_excel(path)
    print(f"  Parsed {len(trades)} trades")

    # Group by date for round-trip identification
    by_date = defaultdict(list)
    for t in trades:
        by_date[t.time.strftime("%Y-%m-%d")].append(t)

    total_rts = 0
    total_stats = 0

    for date_str in sorted(by_date.keys()):
        day_trades = by_date[date_str]
        rts = identify_round_trips(day_trades)

        if not rts:
            continue

        count = db.put_round_trips(rts, date_str)
        total_rts += count

        accounts = set(rt.account for rt in rts)
        for account in sorted(accounts):
            account_rts = [rt for rt in rts if rt.account == account]
            stats = DailyStats(date=date_str, account=account, round_trips=account_rts)
            db.put_daily_stats(stats)
            total_stats += 1

        closed = sum(1 for rt in rts if rt.is_closed)
        pnl = sum(rt.pnl for rt in rts)
        print(f"  {date_str}: {len(day_trades)} executions → {count} round-trips ({closed} closed, P&L ${pnl:+.2f})")

    print(f"\nBroker ingest complete: {total_rts} round-trips, {total_stats} daily stats → DynamoDB")


def cmd_calc(args):
    """Calculate trade cost estimate."""
    from .calculator import estimate_trade

    est = estimate_trade(
        symbol=args.symbol.upper(),
        side=args.side,
        shares=args.shares,
        entry=args.entry,
        target=args.target,
        stop=args.stop,
    )
    print(est.summary())


def _print_summary(stats: DailyStats):
    """Print formatted daily statistics."""
    streak_count, streak_type = stats.streak
    account_label = "SIM" if stats.account.startswith("TR") else "LIVE"

    print(f"\n{'─'*50}")
    print(f"  {stats.date} — {stats.account} ({account_label})")
    print(f"{'─'*50}")
    print(f"  Trades:        {stats.total_trades}")
    print(f"  Win Rate:      {stats.win_rate:.0%}")
    print(f"  Winners:       {len(stats.winners)}")
    print(f"  Losers:        {len(stats.losers)}")
    print(f"  P&L:           ${stats.total_pnl:+.2f}")
    print(f"  Profit Factor: {stats.profit_factor:.2f}")
    print(f"  Avg Winner:    ${stats.avg_winner:+.2f}")
    print(f"  Avg Loser:     ${stats.avg_loser:+.2f}")
    print(f"  Expectancy:    ${stats.expectancy:+.2f}/trade")

    if stats.avg_r is not None:
        print(f"  Avg R:         {stats.avg_r:+.2f}R")
    else:
        print(f"  Avg R:         N/A (no stops found)")

    print(f"  Max Drawdown:  ${stats.max_drawdown:.2f}")
    print(f"  Streak:        {streak_count}{streak_type}")
    print(f"{'─'*50}")


def main():
    parser = argparse.ArgumentParser(
        description="Falcon Stats — Trading Statistics Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  falcon-stats ingest ~/Trade_Review/2026-04/2026-04-16
  falcon-stats summary --date 2026-04-16
  falcon-stats trades --date 2026-04-16
  falcon-stats sanitized --date 2026-04-16
  falcon-stats week
        """,
    )

    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="Ingest a day's DAS CSV exports")
    ingest_p.add_argument("path", help="Path to daily export directory")

    summary_p = sub.add_parser("summary", help="Show daily statistics")
    summary_p.add_argument("--date", "-d", help="Date (YYYY-MM-DD), default today")

    trades_p = sub.add_parser("trades", help="List round-trips with full detail")
    trades_p.add_argument("--date", "-d", help="Date (YYYY-MM-DD), default today")

    sanitized_p = sub.add_parser("sanitized", help="List round-trips in R-multiples only")
    sanitized_p.add_argument("--date", "-d", help="Date (YYYY-MM-DD), default today")

    week_p = sub.add_parser("week", help="Show weekly aggregate")

    backfill_p = sub.add_parser("backfill", help="Backfill all historical CSV data into DynamoDB")

    rebuild_p = sub.add_parser("rebuild-notion", help="Rebuild Notion databases from DynamoDB")
    rebuild_p.add_argument("--date", "-d", help="Rebuild specific date (default: all)")

    broker_p = sub.add_parser("ingest-broker", help="Ingest Cobra broker Excel export into DynamoDB")
    broker_p.add_argument("path", help="Path to broker .xls/.xlsx file")

    calc_p = sub.add_parser("calc", help="Calculate trade cost estimate")
    calc_p.add_argument("symbol", help="Ticker symbol")
    calc_p.add_argument("side", choices=["long", "short"], help="Trade direction")
    calc_p.add_argument("shares", type=int, help="Number of shares")
    calc_p.add_argument("entry", type=float, help="Entry price")
    calc_p.add_argument("target", type=float, help="Target price")
    calc_p.add_argument("stop", type=float, help="Stop loss price")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "ingest": cmd_ingest,
        "summary": cmd_summary,
        "trades": cmd_trades,
        "sanitized": cmd_sanitized,
        "week": cmd_week,
        "backfill": cmd_backfill,
        "rebuild-notion": cmd_rebuild_notion,
        "ingest-broker": cmd_ingest_broker,
        "calc": cmd_calc,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
