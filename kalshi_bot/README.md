# Kalshi near-expiry favourites bot (paper trading)

The bot posts small resting buy orders on the heavily-favoured side (95–99¢) of Kalshi markets that
resolve within the next hour, holds each one to settlement, and recycles the cash. **Paper trading only.**
It reads live public market data and simulates fills and fees. It cannot place real orders.

## How the strategy was chosen

`research.py` downloaded every trade in 2,998 random settled markets (Oct 28 – Nov 11, 2026). It then
simulated what a small bot would actually get: **one $2–10 order per market, the first fill available,
net of Kalshi fees including their round-up-to-the-cent rule.** Each result was checked separately on
the earlier and later halves of the data. Full output is in `research_results_2026-11-11.txt`.

| approach | result per filled order |
|---|---|
| **Taker** (buy at the ask), any band 50–99¢, any time window | **−1% to −3%**, consistently negative |
| Maker (resting bid) 85–95¢ | about 0%, noise |
| **Maker 95–99¢, resolving within 1h, $10 orders** | **+1.0% to +1.5% (±1%)**, positive in both halves |

Neighbouring settings (93–99¢, 96–99¢, under 30 minutes) were also positive, which suggests this isn't
a single lucky slice. It's still only two weeks of data, and about 60 combinations were tested, so some
false positives are expected. Treat it as the best available hypothesis, not a proven edge.

An earlier version of this bot bought 85–95¢ favourites at the ask. Its first backtest looked positive
because it averaged over every fill, including large late ones. Simulated at realistic bot scale, it loses.

Why maker orders and $10 sizes:
- Kalshi's taker fee is four times the maker fee, and many series charge makers nothing.
- Fees round up to the cent per order, so $2 orders lose an extra ~0.5%.

## Risk

- At 97¢ a win pays 3¢ and a loss costs 97¢, so one loss cancels about 32 wins. Expect long winning
  streaks broken by sudden drops.
- Related markets can lose together, e.g. several crypto 15-minute markets in one sharp move.
- On $100 with $10 orders, a +1% edge is about 10¢ per filled order. Even if it holds, that's maybe a
  few dollars a week, depending on fill rates.

## Run it

Requires Python 3.9+ and no other packages.

```bash
cd kalshi_bot
python3 paper_bot.py --name through                       # conservative fill model (default)
python3 paper_bot.py --name touch --fill-rule touch       # optimistic fill model, in a second terminal
python3 paper_bot.py --name through --report              # P&L summary
```

On a Mac, prefix with `caffeinate -i` so it doesn't sleep. Every bid, fill and settlement is logged to
`paper_trades_<name>.csv`.

About the fill models: a simulated resting order can't know where it sits in the queue.
- `through` only counts a fill when a later trade prints *below* the bid, so we'd definitely have been
  filled. This undercounts fills, and the fills it does count skew toward bad moments.
- `touch` also counts sellers hitting bids at our price, which ignores the queue.

A real order should land between the two runs.

Other tools:
- `research.py fetch` / `research.py analyze`: re-run the research on fresh data. Do this before ever
  going live.
- `backtest.py`: the original all-fills calibration table, by price band.

## Going live (not built)

Only consider it after a few weeks in which both paper runs and a fresh `research.py` agree. Live
trading needs a Kalshi account, an API key, testing on Kalshi's demo exchange (`demo-api.kalshi.co`),
and hard limits: max $ per order, a daily loss stop and a kill switch.

Not financial advice. Prediction-market winnings are taxable.
