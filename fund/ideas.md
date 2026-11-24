# Ideas waiting for tests

Each idea needs a reason (who pays) before it gets a backtest. All are Kalshi paper-only for now.

| # | idea | why it might pay | status |
|---|---|---|---|
| 1 | Minute-12 strong-trend filter at other thresholds (88c, 90c, 94c) | Check that neighbouring settings agree with 92c | to test |
| 2 | Minute-12 with momentum: require the favourite's price to have risen over the prior 60s | Separates firming trends from fading ones | needs data from earlier in the window |
| 3 | Same rule on Kalshi ETH 15-minute markets | Same mechanism, different crowd. Checks whether this is BTC-only noise | to test |
| 4 | Maker version: rest a bid 1c under the ask at minute 12 instead of buying at the ask | Maker fees are lower, and A2 showed makers beat takers | to test |
| 5 | Skip windows around scheduled US data releases (CPI, FOMC) | Big moves in the final minutes cause reversals | needs `calendar.md` dates |
| 6 | Longer history: re-run B1/B2 on 4+ weeks as it accumulates | One week is a single regime | collecting |
