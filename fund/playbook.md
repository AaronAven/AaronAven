# Playbook

Last updated: 2026-11-24. Changes to anything here need Aaron's approval.

## Mandate

Paper-trade Kalshi's BTC 15-minute up/down markets with a $1,000 paper bankroll and $10 per bet. Stop for
the day at −$30, halt everything at −$150 from the equity high, and never trade real money without a
written "go live".

## Markets and accounts

| item | setting |
|---|---|
| Venue | Kalshi (CFTC-regulated, US) |
| Market | `KXBTC15M`: "BTC price up in next 15 mins?" Settles on the 60-second average of CF Benchmarks BRTI at the close vs the same average at the open |
| Account | none. Paper only, using Kalshi's public market data. No API keys exist |
| Mode | `MODE: PAPER`. The bot has no live mode in its code |

## Limits (section 14 defaults, accepted 2026-11-24)

| rule | value | how it works in the bot |
|---|---|---|
| Bankroll | $1,000 paper | `--bankroll 1000` |
| Risk per trade | $10 (1%) | `--stake 10`. A Kalshi contract can't have a stop, so the most a bet can lose is its $10 stake |
| Daily loss limit | −$30 (3%) | no new bets until 00:00 UTC once the day's realised P&L reaches −$30. The last bet can push it to about −$40 |
| Kill switch | −$150 (15%) from equity high | halts all new bets until restarted with `--clear-halt` after review |
| Leverage | none | Kalshi has no leverage. Betting DOWN plays the role of shorting |
| Trades | max 1 per 15-minute market (96/day) | |

## Needs Aaron's approval

Going live, any size increase, new markets or venues, strategy swaps, rule changes, any purchase or plan
upgrade, and anything outside these rules.

## Time zone

Aaron is on Pacific time (PST, UTC−8; PDT, UTC−7 from March to November). Data and logs stay in UTC.
Reports to Aaron show Pacific time. The daily loss limit resets at 00:00 UTC, which is 4:00 pm PST.

## Current strategies

| name | status | card |
|---|---|---|
| `btc15`: minute 12, follow the trend | paper, champion | [strategies/minute12.md](strategies/minute12.md) |
| `btc15_strong`: minute 12, strong trends only | paper, challenger | [strategies/minute12_strong.md](strategies/minute12_strong.md) |

## Where things live

- Bot code: `../kalshi_bot/` (`btc15_bot.py`, `dashboard.py`, `run_all.sh`)
- Trade journal (section 13 format): `../kalshi_bot/trades_<run>.csv`, written by the bot at each settlement
- Backtests: `backtests/README.md` indexes every research run and its saved output
- Lessons: `learning.md`. Problems: `incidents.md`. Data sources: `data/sources.md`

## Golden rules

- No backtest with full costs, no bot.
- No 30+ paper trades that match the backtest, no real money.
- No "go live" from Aaron, no live mode.
- Every number comes from a logged test or trade. Estimates are labelled as estimates.
