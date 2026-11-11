"""Backtest the intraday strategies on free Yahoo Finance 5-minute bars (about the last 60 days).

Costs: --cost-bps per side (default 3 bps = 0.03%) to cover the bid/ask spread and slippage on
liquid US stocks/ETFs at commission-free brokers. Regulatory sell fees are tiny and are included in that.

Usage:  python3 backtest.py
        python3 backtest.py --symbols SPY,QQQ,NVDA --cost-bps 5
"""
import argparse
import json
import statistics
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from strategies import STRATEGIES

DEFAULT_SYMBOLS = "SPY,QQQ,IWM,DIA,AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA,AMD,AVGO,NFLX"


def fetch(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=60d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    days = defaultdict(list)
    for i, t in enumerate(d["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        # Yahoo timestamps are UTC; convert to NY wall time. Determine DST per bar from US rules.
        ny = ny_time(t)
        mins = ny.hour * 60 + ny.minute
        if not (570 <= mins < 960):  # 09:30-16:00 regular session
            continue
        days[ny.date()].append({"t": t, "o": q["open"][i], "h": q["high"][i], "l": q["low"][i],
                                "c": q["close"][i], "v": q["volume"][i] or 0})
    # keep only complete-ish sessions (>= 70 of 78 bars) so half days/data gaps don't distort results
    return {k: v for k, v in sorted(days.items()) if len(v) >= 70}


def ny_time(t):
    utc = datetime.fromtimestamp(t, timezone.utc)
    y = utc.year
    # DST: second Sunday of March 07:00 UTC to first Sunday of November 06:00 UTC
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc); mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc); nov += timedelta(days=(6 - nov.weekday()) % 7)
    return utc + timedelta(hours=-4 if mar <= utc < nov else -5)


def simulate_day(bars, strat, cost):
    """Return the net % return of the day's trade (or None if no trade)."""
    for i in range(1, len(bars) - 1):
        sig = strat(bars[:i])
        if not sig:
            continue
        entry = bars[i]["o"]
        stop, target = sig["stop"], sig["target"]
        if stop >= entry:
            return None
        exit_px = bars[-1]["c"]
        for b in bars[i:]:
            if b["o"] <= stop:          # gapped through the stop
                exit_px = b["o"]; break
            if b["l"] <= stop:          # assume the stop fills first if both are hit in one bar (conservative)
                exit_px = stop; break
            if target and b["h"] >= target:
                exit_px = target; break
        gross = exit_px / entry - 1
        return gross - 2 * cost, gross
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--cost-bps", type=float, default=3.0)
    a = ap.parse_args()
    cost = a.cost_bps / 10000
    syms = a.symbols.split(",")

    data = {}
    for s in syms:
        try:
            data[s] = fetch(s)
        except Exception as e:
            print(f"skip {s}: {e}")
    alldays = sorted({d for v in data.values() for d in v})
    print(f"{len(data)} symbols, {len(alldays)} sessions ({alldays[0]} to {alldays[-1]}), cost {a.cost_bps} bps/side\n")

    # Buy-and-hold over the window for context
    bh = [v[max(v)][-1]["c"] / v[min(v)][0]["o"] - 1 for v in data.values()]
    print(f"buy & hold over window (avg of symbols): {100 * statistics.mean(bh):+.2f}%\n")

    print(f"{'strategy':<15}{'trades':>7}{'win%':>7}{'avg net/trade':>15}{'95% CI':>10}{'avg gross':>11}"
          f"{'portfolio total':>17}{'worst day':>11}")
    for name, strat in STRATEGIES.items():
        trades, daily = [], defaultdict(list)
        for s, days in data.items():
            for d, bars in days.items():
                r = simulate_day(bars, strat, cost)
                if r:
                    trades.append(r); daily[d].append(r[0])
        if not trades:
            print(f"{name:<15} no trades"); continue
        nets = [t[0] for t in trades]
        m = statistics.mean(nets)
        ci = 1.96 * statistics.stdev(nets) / len(nets) ** 0.5 if len(nets) > 1 else 0
        # Portfolio: each day split capital equally across that day's trades; days with no trade earn 0.
        eq = 1.0; worst = 0.0
        for d in alldays:
            r = statistics.mean(daily[d]) if daily.get(d) else 0.0
            eq *= 1 + r; worst = min(worst, r)
        print(f"{name:<15}{len(nets):>7}{100 * sum(n > 0 for n in nets) / len(nets):>6.1f}%"
              f"{100 * m:>14.3f}%{100 * ci:>9.3f}%{100 * statistics.mean(t[1] for t in trades):>10.3f}%"
              f"{100 * (eq - 1):>16.2f}%{100 * worst:>10.2f}%")
    print("\nIf the 95% CI is wider than the average, the result is indistinguishable from luck.")
    print("Trades on the same day are correlated (the whole market moves together), so the true uncertainty is larger.")


if __name__ == "__main__":
    main()
