# Strategy card: minute 12, follow the trend (`btc15`)

**One-line idea:** at the 12:00 mark of each 15-minute BTC window (3:00 left), bet $10 on the side BTC is
currently trending (UP if the market prices UP above 50c, otherwise DOWN). Hold to settlement.

- **Edge:** the hypothesis is that short-term BTC trends persist for the last 3 minutes, and that the
  60-second settlement average locks in part of the move. Who would be paying: traders betting on a
  reversal. The backtest says this hypothesis is **not supported** for weak trends.
- **Rules:** entry is the first check at or after 180s left, up to 165s left, at the live order-book ask,
  capped at 99c. Exit is settlement at $1 or $0. Stop: none possible, so the most a bet can lose is its
  stake. Size: $10.
- **Results (backtest B2, `kalshi_bot/btc_minute12_results_2026-11-19.txt`):** 664 markets from
  Nov 12-19, 2026, $50 bets after fees. 88.4% win rate, **−$0.43 per bet (±$1.56)**, total −$287.
  The bankroll low was $531 from $1,000, and the biggest drop from a high was $569.
- **Walk-forward:** first half of the week −$1.09/bet, second half +$0.22/bet. Not consistent.
- **Expected R per trade:** −0.009 (−$0.43 / $50).

**Why this could fail:** it is already failing in the backtest. A 50-85c favourite at minute 12 reverses
too often (only 56-76% wins) for the price paid. It stays on paper as the baseline because it's Aaron's
rule and live paper data costs nothing.

**Live paper log:** first bet on 2026-11-19 lost $49.77 at the old $50 stake. A 97c DOWN favourite
reversed in the final 3 minutes (KXBTC15M-26NOV191845-45).
