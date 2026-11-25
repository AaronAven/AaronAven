# Paper results from the Mac

The bots run on Aaron's Mac, so the nightly research session can't see their trades. To include them in
the morning brief, copy the trade journals here and push. Run from `~/trading` on the Mac:

```bash
cp kalshi_bot/trades_btc15*.csv fund/paper_results/ && git add fund/paper_results && git commit -m "Paper results" && git push
```
