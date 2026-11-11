# Kalshi favourites bot (paper trading)

Makes lots of small trades on Kalshi prediction markets. It buys the heavily-favoured side (85–95¢)
of liquid markets that are about to resolve, holds each position to settlement, and recycles the cash.
**This is paper trading only.** It reads live public market data and simulates fills with Kalshi's fees.
It cannot place real orders.

## Why this strategy

- Kalshi contracts pay $1 if right and $0 if wrong. Prices are probabilities.
- Published research on Kalshi trade data (Bürgi, Deng & Whelan, *Makers and Takers*) finds a
  *favourite-longshot bias*: cheap longshots lose badly, while expensive favourites earn small positive
  returns. Makers (resting orders) do better than takers. The authors also report that the bias has
  been shrinking over time.
- None of this needs speed. Positions are held to settlement, so a home internet connection is fine.

## Backtest (`backtest.py`)

The script pulls recently settled markets and every real trade in them, then computes what each buyer
earned after fees, grouped by the price they paid. Results for 1,200 random markets from the 7 days to
2026-11-11 are in `backtest_results_2026-11-11.txt`. Per-market net return, 95% CI:

| price paid | taker      | maker      |
|------------|------------|------------|
| 1–10¢      | −130% ±50  | −60% ±20   |
| 10–30¢     | −54% ±12   | −48% ±9    |
| 85–90¢     | +5.4% ±2.1 | +7.4% ±2.4 |
| 90–95¢     | +2.0% ±1.6 | +3.3% ±1.9 |
| 95–99¢     | +0.6% ±0.9 | +1.6% ±1.3 |

How to read this:
- Only 85–95¢ shows a margin clearly above zero. Above 95¢ the edge is too small to separate from noise.
- The data covers one week. Markets on the same game or the same crypto move together, so the real
  uncertainty is wider than these intervals show. Re-run it before trusting it:
  `python3 backtest.py --days 14 --max-markets 2000`
- The payoff is asymmetric. At 90¢ a win pays 10¢ and a loss costs 90¢, so a single loss cancels about
  nine wins. Expect long runs of small gains broken by sharp drops.

## Run the paper bot

Requires Python 3.9+ and no other packages.

```bash
cd kalshi_bot
python3 paper_bot.py            # $100 bankroll, $2 per trade, 85-95c, resolving within 6h
python3 paper_bot.py --report   # P&L summary from saved state
python3 paper_bot.py --reset    # start over
python3 paper_bot.py --help     # all settings (stake, price band, max open, maker mode...)
```

Every fill and settlement is written to `paper_trades.csv`. Let it run for at least 1–2 weeks and
several hundred settled trades before drawing conclusions. Ten wins in a row prove nothing at these odds.

Known limitations:
- Taker fills are assumed at the displayed best ask. That's realistic for $1–2 sizes, but not guaranteed.
- `--mode maker` only counts a fill when a later public trade prints *below* the bid. That's
  conservative, but it can't model fills a real order would get at its own price level.
- Related markets can lose together, e.g. several crypto 15-minute markets in one sharp move.
  `--max-per-event` only limits bets within a single event.

## Going live (not built yet)

Only consider this if the paper results stay positive over hundreds of settled trades. Live trading
needs a Kalshi account and an API key, should be tested first on Kalshi's demo exchange
(`demo-api.kalshi.co`), and needs hard limits: max $ per trade, a daily loss stop and a kill switch.

Not financial advice. Prediction-market winnings are taxable.
