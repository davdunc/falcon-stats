# falcon-stats

Trading statistics manager for DAS Trader users: ingest the day's exports, pair fills into round trips,
compute discipline and R-multiple statistics, store them in DynamoDB, and publish summaries.

```bash
pip install -e '.[dev]'          # Python ≥ 3.11
falcon-stats --help
```

Selected commands:

| Command | What it does |
|---|---|
| `ingest DATE` | Ingest a day's DAS CSV exports |
| `summary DATE` / `trades DATE` / `sanitized DATE` | Daily stats, round trips, R-multiples only |
| `week` / `backfill` | Weekly aggregate; backfill history into DynamoDB |
| `size SYMBOL SIDE ENTRY` | Pre-trade ATR-based stop and share count |
| `avwap-study SYMBOL [--intraday]` | Do event-anchored (CPI) VWAPs act as support/resistance? |

Configuration comes from environment variables, falling back to `~/.claude/.env`: `TRADE_REVIEW_PATH`,
`FALCON_TRADES_TABLE`, and, for market data, `POLYGON_API_KEY` and `FRED_API_KEY`.

Design records live in `docs/adr/`, and feature specs in `docs/specs/`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
