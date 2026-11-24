# Data sources

All timestamps are stored in UTC.

| dataset | source | how fetched | when | local file |
|---|---|---|---|---|
| Kalshi settled markets + trades (all series), 7 days | Kalshi public API `api.elections.kalshi.com/trade-api/v2` (`/markets`, `/markets/trades`) | `kalshi_bot/backtest.py` | 2026-11-11 | not cached (streamed) |
| Kalshi settled markets + trades, 14 days, 2,998 markets | Kalshi public API | `kalshi_bot/research.py fetch` | 2026-11-11 | `kalshi_bot/research_cache.jsonl` (gitignored) |
| Kalshi `KXBTC15M` settled markets, trades from the final 3-5 min, 664 markets (Nov 12-19) | Kalshi public API | `kalshi_bot/btc_research.py fetch --days 7 --window 180` | 2026-11-19 | `kalshi_bot/btc_research_cache.jsonl` (gitignored) |
| Live order books and market state | Kalshi public API (`/markets/{ticker}/orderbook`, `/markets`) | `kalshi_bot/btc15_bot.py`, polled every 1-5s | ongoing | `kalshi_bot/live_status_*.json` |

Integrity notes:
- Settlement values (`expiration_value`) and results come from Kalshi's own market records.
- The BTC cache includes 18 markets with 5-minute trade windows and 646 with 3-minute windows. Analyses
  only use the final 3 minutes, so this doesn't bias them.
- No paid data, no scraping. Cached files can be rebuilt with the commands above.
