# Stock day-trading bot (Alpaca paper trading)

Long-only intraday strategies on liquid US stocks and ETFs. Uses fractional shares and is always flat
by the close. `alpaca_bot.py` is hard-wired to Alpaca's **paper** endpoint, so it cannot trade real money.

## Backtest result: no edge found

`python3 backtest.py` replays the last ~60 sessions of free Yahoo 5-minute bars for 14 liquid symbols,
with 0.03% per side for spread and slippage. Results for 2026-08-18 to 2026-11-10 are in
`backtest_results_2026-11-11.txt`:

| strategy | trades | win% | avg net/trade | 95% CI | portfolio total |
|---|---|---|---|---|---|
| orb5 (5-min opening range breakout) | 407 | 30% | −0.02% | ±0.10% | −2.4% |
| orb30 (30-min opening range breakout) | 335 | 39% | −0.19% | ±0.10% | −12.5% |
| open_to_close (baseline) | 840 | 45% | −0.10% | ±0.10% | −6.0% |

- All three lost money after costs. ORB-5 was roughly break-even, which is consistent with no edge.
- The window was a down market (buy & hold averaged −1.9%), and the strategies are long-only, which
  hurts. 60 days is also a short sample. The published ORB-5 research (Zarattini & Aziz, 2023) found
  profits over years, but it also traded the short side, used leverage, and picked "stocks in play".
- On $100 the stakes are cents: a 0.1% move on a $20 position is 2¢.

Treat the paper bot as an experiment. The evidence so far says don't expect it to make money.

## Run the paper bot

1. Create a free account at alpaca.markets, open **Paper Trading**, and optionally reset the paper
   balance to $100 so the numbers feel real.
2. Generate paper API keys. Keep them out of git and chat.
3. Start the bot:

```bash
cd daytrade_bot
export APCA_API_KEY_ID=your_paper_key_id
export APCA_API_SECRET_KEY=your_paper_secret
python3 alpaca_bot.py                      # ORB-5, $100 budget, $20 per trade, $5 daily loss stop
python3 alpaca_bot.py --strategy orb30     # or orb30 / open_to_close
python3 alpaca_bot.py --help
```

Leave it running from before 9:30 ET. It sleeps while the market is closed. Trades are logged to
`alpaca_trades.csv`, and your Alpaca paper dashboard shows the same orders and P&L.

Risk controls:
- Total daily budget cap.
- Max $ per trade.
- One trade per symbol per day.
- A daily loss stop that flattens everything and halts until the next day.
- A forced flatten 5 minutes before the close.

Known limitations:
- Stops and targets are watched by the bot, polling every 10s, rather than placed as exchange orders.
  If the bot is stopped or restarted mid-day, positions it opened lose their stop until the next
  end-of-day check. Restart before the flatten time, or close positions in the Alpaca dashboard.
- It uses Alpaca's free IEX data feed, which is a subset of market volume. OHLC prices are close to
  the full feed but not identical.
- Tested against a simulated Alpaca API replaying real sessions, not against a live Alpaca account,
  because no keys were available. Watch the first session.
