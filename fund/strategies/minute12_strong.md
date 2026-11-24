# Strategy card: minute 12, strong trends only (`btc15_strong`)

**One-line idea:** same as minute 12, but bet only when the trending side already costs 92c or more.
Skip the window otherwise.

- **Edge:** the hypothesis is that strong trends at 3:00 left reverse less often than a 92-99c price
  implies. Who would be paying: late reversal bettors, and market makers quoting slightly wide near
  expiry. **Unproven:** this filter was chosen after looking at the same data it was tested on.
- **Rules:** entry at 180-165s left if the favourite's ask is 92-99c, at the live order-book ask. Exit is
  settlement. Stop: none possible, so the most a bet can lose is its stake. Size: $10.
- **Results (backtest B2, `kalshi_bot/btc_minute12_results_2026-11-19.txt`), $50 bets, after fees:**

  | price at 12:00 | bets | win rate | result |
  |---|---|---|---|
  | 92-96c | 70 | 100% | +$208 |
  | 96-99c | 311 | 99.4% | +$70 |

  Combined: 381 bets, about +$0.73 per $50 bet (an estimate from bucket totals).
- **Related test (B1, `kalshi_bot/btc_research_results_2026-11-19.txt`):** buying the favourite at 92-98c
  between 3:00 and 2:00 left was positive in both halves of the week (+1.6% to +2.6% per trade). But the
  2:00-1:00 window was negative, so this may be noise.
- **Expected R per trade:** +0.015 (estimate).

**Why this could fail:** one loss costs about 24x a typical win at 96c. The sample had 2 losses in 381
bets; 4-5 losses would have erased the profit. One week of data, one market regime, and the filter was
picked after seeing the results (look-ahead in strategy selection). A volatile week with late reversals
kills it.
