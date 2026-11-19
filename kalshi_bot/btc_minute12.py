"""Backtest the "minute 12" rule on the cached BTC 15-minute data (run btc_research.py fetch first).

Rule: at the 12:00 mark of each 15-minute window (3:00 left), bet $50 on whichever side the market
favours (UP if YES trades above 50c, otherwise DOWN), at the first trade at or after that moment,
paying Kalshi's taker fee. Hold to settlement.

    python3 btc_minute12.py
"""
import statistics
from collections import defaultdict

from btc_research import load
from kalshi import TAKER_RATE, fee

STAKE = 50.0


def entry(m, secs_left=180, slack=15):
    """First trade within [secs_left - slack, secs_left] seconds before close."""
    for t, yp, taker, n in sorted(m["trades"]):
        left = m["close"] - t
        if secs_left - slack <= left <= secs_left:
            return yp
    return None


def main():
    ms = load()
    rows = []
    for m in ms:
        yp = entry(m)
        if yp is None:
            continue
        side, p = ("yes", yp) if yp >= 0.5 else ("no", round(1 - yp, 4))
        if p >= 1.0:
            continue  # nothing to buy at $1
        k = int(STAKE // p)
        fe = fee(k, p, TAKER_RATE)
        cost = k * p + fe
        pnl = (k if side == m["result"] else 0) - cost
        rows.append((m["close"], p, pnl, side == m["result"]))
    rows.sort()
    half = len(rows) // 2

    def summary(rs, label):
        if not rs:
            return
        pnls = [r[2] for r in rs]
        m = statistics.mean(pnls)
        ci = 1.96 * statistics.stdev(pnls) / len(pnls) ** 0.5 if len(pnls) > 1 else 0
        wins = sum(r[3] for r in rs)
        print(f"{label:<22}{len(rs):>6}{100 * wins / len(rs):>8.1f}%{m:>+10.2f} ±{ci:4.2f}{sum(pnls):>+11.2f}"
              f"{min(pnls):>+10.2f}")

    print(f"{len(ms)} markets in cache; {len(rows)} had a trade at the 12:00 mark. $50 per bet, after fees.\n")
    print(f"{'':<22}{'bets':>6}{'win%':>9}{'avg $/bet':>11}{'':>6}{'total $':>11}{'worst $':>10}")
    summary(rows, "all")
    summary(rows[:half], "first half of week")
    summary(rows[half:], "second half of week")
    print("\nby the favourite's price at 12:00:")
    buckets = defaultdict(list)
    for r in rows:
        p = r[1]
        b = "50-70c" if p < 0.7 else "70-85c" if p < 0.85 else "85-92c" if p < 0.92 else "92-96c" if p < 0.96 else "96-99c"
        buckets[b].append(r)
    for b in ("50-70c", "70-85c", "85-92c", "92-96c", "96-99c"):
        summary(buckets[b], b)

    # equity path from $1,000
    eq, low, peak, dd = 1000.0, 1000.0, 1000.0, 0.0
    for r in rows:
        eq += r[2]; low = min(low, eq); peak = max(peak, eq); dd = max(dd, peak - eq)
    print(f"\n$1,000 bankroll path: ends ${eq:.2f}, lowest ${low:.2f}, biggest drop from a high ${dd:.2f}")


if __name__ == "__main__":
    main()
