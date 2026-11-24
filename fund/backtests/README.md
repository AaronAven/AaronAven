# Backtest index

Every research run, with its ID, settings and saved output. Scripts and outputs live in `../../kalshi_bot/`.

| ID | date | script | data | question | output | verdict |
|---|---|---|---|---|---|---|
| A1 | 2026-11-11 | `backtest.py` | 1,200 settled Kalshi markets, 7 days, all fills | Favourite-longshot bias by price band | `backtest_results_2026-11-11.txt` | Bias exists in aggregate, but averaging over all fills flattered it |
| A2 | 2026-11-11 | `research.py` | 2,998 markets, 14 days, one fill per market | Which price band and role survives realistic sizing? | `research_results_2026-11-11.txt` | Taker strategies lose 1-3%. Maker 95-99c within 1h about +1% (retired strategy) |
| B1 | 2026-11-19 | `btc_research.py` | 664 BTC 15-min markets, Nov 12-19, final 3 min of trades | Best entry time and price band for late favourites | `btc_research_results_2026-11-19.txt` | Last minute negative. 3:00-2:00 at 92-98c positive in both halves (possible noise) |
| B2 | 2026-11-19 | `btc_minute12.py` | same as B1 | Minute-12 trend rule, by trend strength | `btc_minute12_results_2026-11-19.txt` | Plain rule −$287 on $50 bets. Strong trends (92c+) +$278 |

Known limits of every test so far:
- Histories are short (1-2 weeks), not the playbook's 4+ years. Kalshi's BTC 15-minute markets don't
  have that much history.
- Fills are simulated at traded prices. Live fills arrive later and can be worse.
- Several variants were tried on the same data, so treat a single "pass" with suspicion.
