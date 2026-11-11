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
| **Maker 95–99¢, resolving within 1h, $10–50 orders** | **+1.0% to +1.5% (±1%)**, positive in both halves |

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
- Defaults: $500 bankroll, $20 per order (4% of bankroll), up to 25 orders/positions open at once.
  A +1% edge is about 20¢ per filled order. A single loss at 97¢ costs about $19.40.
  Even if the edge holds, expect roughly tens of dollars a month at most, depending on fill rates.

## Quick start on a Mac (bots + dashboard)

```bash
cd kalshi_bot
chmod +x run_all.sh
./run_all.sh --reset      # first time: both runs start fresh with $500 each
./run_all.sh              # later: continue where they left off
```

This starts both paper runs and the dashboard at http://127.0.0.1:8787, and keeps the Mac awake.

### Follow along from your phone with Tailscale

1. Install Tailscale on the Mac and your phone, signed into the same account.
2. On the Mac, run `tailscale serve --bg 8787`. If you use the App Store version and `tailscale` isn't on
   your PATH, run `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8787` instead.
   The first time, it may ask you to enable HTTPS certificates for your tailnet; follow the link it prints.
3. Open the `https://<your-mac>.<tailnet>.ts.net` address it prints on your phone.

Only devices on your tailnet can open it. The dashboard is read-only and binds to 127.0.0.1. Don't use
`tailscale funnel`, which would put it on the public internet. To stop sharing:
`tailscale serve --https=443 off`.

## Run it manually

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
