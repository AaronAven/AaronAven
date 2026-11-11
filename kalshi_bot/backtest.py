"""Backtest: what did buying each side of real Kalshi trades actually return, after fees?

For every trade in recently settled markets there is a YES buyer (at yes_price) and a NO buyer
(at no_price). One of them was the taker (crossed the spread), the other the maker (resting order).
We know how each market settled, so we can compute the realised return of every fill, bucketed by
the price paid and by maker/taker role. This tells us whether a "buy the favourite" or any other
price-band strategy had an edge after fees, on real fills.

Usage:  python3 backtest.py --days 3 --max-markets 1500
"""
import argparse
import random
import time
from collections import defaultdict
from datetime import datetime

from kalshi import Client, MAKER_RATE, TAKER_RATE, f, fee

BUCKETS = [(0.01, 0.10), (0.10, 0.30), (0.30, 0.50), (0.50, 0.70), (0.70, 0.85),
           (0.85, 0.90), (0.90, 0.95), (0.95, 0.99), (0.99, 1.00)]


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def bucket(p):
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return (lo, hi)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--max-markets", type=int, default=1500)
    ap.add_argument("--max-trades-per-market", type=int, default=3000)
    ap.add_argument("--maker-fee", action="store_true",
                    help="charge the maker fee on maker fills (conservative; many series charge none)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    c = Client()
    now = int(time.time())
    ms = c.markets(status="settled", min_close_ts=now - int(a.days * 86400))
    ms = [m for m in ms if m.get("result") in ("yes", "no") and f(m.get("volume_fp")) > 0]
    random.Random(a.seed).shuffle(ms)
    ms = ms[: a.max_markets]
    print(f"{len(ms)} settled binary markets with volume, last {a.days} days")

    # stats[(role, bucket)] = [contracts, cost, payout, fees, set_of_markets]
    stats = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, set()])
    # per_mkt[(role, bucket)][ticker] = [cost, net] -> equal-weight-per-market return with a CI
    per_mkt = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    hours_stats = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, set()])
    for i, m in enumerate(ms):
        if i % 100 == 0:
            print(f"  ...{i}/{len(ms)} markets")
        result = m["result"]
        settle_t = ts(m["settlement_ts"]) if m.get("settlement_ts") else ts(m["close_time"])
        for t in c.trades(m["ticker"], max_items=a.max_trades_per_market):
            n = f(t.get("count_fp"))
            if n <= 0:
                continue
            yp = f(t.get("yes_price_dollars"))
            hrs = (settle_t - ts(t["created_time"])) / 3600
            taker = t.get("taker_side")
            for side, p in (("yes", yp), ("no", 1 - yp)):
                b = bucket(round(p, 4))
                if not b:
                    continue
                role = "taker" if side == taker else "maker"
                fe = fee(n, p, TAKER_RATE) if role == "taker" else (fee(n, p, MAKER_RATE) if a.maker_fee else 0.0)
                payout = n if side == result else 0.0
                for d, key in ((stats, (role, b)),):
                    s = d[key]; s[0] += n; s[1] += n * p; s[2] += payout; s[3] += fe; s[4].add(m["ticker"])
                pm = per_mkt[(role, b)][m["ticker"]]; pm[0] += n * p; pm[1] += payout - n * p - fe
                if role == "maker" and 0.85 <= p < 0.99:
                    hb = "<1h" if hrs < 1 else "1-6h" if hrs < 6 else "6-24h" if hrs < 24 else ">24h"
                    s = hours_stats[hb]; s[0] += n; s[1] += n * p; s[2] += payout; s[3] += fe; s[4].add(m["ticker"])

    def row(label, s, pm=None):
        n, cost, pay, fe, mk = s
        if cost == 0:
            return
        net = pay - cost - fe
        extra = ""
        if pm:
            rs = [v[1] / v[0] for v in pm.values() if v[0] > 0]
            mean = sum(rs) / len(rs)
            sd = (sum((r - mean) ** 2 for r in rs) / max(len(rs) - 1, 1)) ** 0.5
            ci = 1.96 * sd / len(rs) ** 0.5
            extra = f"{100 * mean:>9.2f}% ±{100 * ci:.1f}"
        print(f"{label:<22}{len(mk):>8}{n:>12.0f}{cost / n:>9.3f}{pay / n:>9.3f}"
              f"{100 * (pay - cost) / cost:>9.2f}%{100 * net / cost:>9.2f}%{extra}")

    hdr = (f"{'':<22}{'markets':>8}{'contracts':>12}{'avg_px':>9}{'win%':>9}{'gross':>10}{'net':>10}"
           f"{'per-mkt net (95% CI)':>24}")
    for role in ("taker", "maker"):
        print(f"\n=== {role.upper()} fills: return on money spent, by price paid ===")
        print(hdr)
        for b in BUCKETS:
            row(f"{b[0]:.2f}-{b[1]:.2f}", stats[(role, b)], per_mkt[(role, b)])
    print("\n=== MAKER buys at 0.85-0.99, by time before settlement ===")
    print(hdr)
    for hb in ("<1h", "1-6h", "6-24h", ">24h"):
        row(hb, hours_stats[hb])
    print("\n'gross'/'net' are contract-weighted (big markets dominate). 'per-mkt net' weights every market"
          " equally and gives a 95% confidence interval: if the interval spans 0, there is no proven edge.")


if __name__ == "__main__":
    main()
