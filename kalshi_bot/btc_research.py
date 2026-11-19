"""Research for the BTC 15-minute "late favourite" strategy.

Question: in Kalshi's KXBTC15M markets ("BTC price up in next 15 mins?"), if you buy the favoured side
late in the window, at whatever the market is charging, do you win more often than the price implies,
after fees?

    python3 btc_research.py fetch --days 14     # slow: trades from the final 5 minutes of each market
    python3 btc_research.py analyze             # fast, offline

Simulation: for each market, the bot buys the FIRST time the favoured side trades inside the price
band during the entry window, at that trade's price, as a taker, with a $50 stake, Kalshi taker fee
included. One trade per market. Early vs late halves are reported separately as an out-of-sample check.
"""
import argparse
import json
import os
import statistics
import time
from datetime import datetime

from kalshi import Client, TAKER_RATE, MAKER_RATE, f, fee

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "btc_research_cache.jsonl")
SERIES = "KXBTC15M"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def fetch(a):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    done = set()
    if os.path.exists(CACHE):
        with open(CACHE) as fh:
            done = {json.loads(l)["ticker"] for l in fh}
    now = int(time.time())
    ms = Client().markets(series_ticker=SERIES, status="settled", min_close_ts=now - int(a.days * 86400))
    ms = [m for m in ms if m.get("result") in ("yes", "no") and m["ticker"] not in done]
    print(f"{len(ms)} markets to fetch ({len(done)} cached), {a.workers} workers")
    local = threading.local()
    lock = threading.Lock()

    def one(m):
        if not hasattr(local, "c"):
            local.c = Client(max_rps=a.rps / a.workers)
        close = ts(m["close_time"])
        trades = local.c.trades(m["ticker"], min_ts=int(close - a.window), max_ts=int(close) + 5)
        return {"ticker": m["ticker"], "close": close, "result": m["result"],
                "trades": [[ts(t["created_time"]), f(t.get("yes_price_dollars")), t.get("taker_side"),
                            f(t.get("count_fp"))] for t in trades]}

    with open(CACHE, "a") as out, ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(one, m) for m in ms]
        for i, fu in enumerate(as_completed(futs)):
            try:
                rec = fu.result()
            except Exception as e:
                print(f"  skip: {e}"); continue
            with lock:
                out.write(json.dumps(rec) + "\n")
            if i % 50 == 0:
                print(f"  {i}/{len(ms)}"); out.flush()


def load():
    with open(CACHE) as fh:
        ms = [json.loads(l) for l in fh]
    return sorted(ms, key=lambda m: m["close"])


def simulate(ms, lo, hi, start_s, end_s, stake=50.0, role="taker"):
    """Buy the favourite the first time it trades in [lo, hi] between start_s and end_s seconds before close."""
    rs, entries = [], []
    for m in ms:
        for t, yp, taker, n in sorted(m["trades"]):
            left = m["close"] - t
            if not (end_s <= left <= start_s):
                continue
            side, p = ("yes", yp) if yp >= 0.5 else ("no", round(1 - yp, 4))
            if not (lo <= p <= hi):
                continue
            if role == "maker" and taker == side:   # maker: a seller hit a resting bid on our side
                continue
            if role == "taker" and taker != side:
                continue
            k = int(stake // p)
            fe = fee(k, p, TAKER_RATE if role == "taker" else MAKER_RATE)
            cost = k * p + fe
            pnl = (k if side == m["result"] else 0) - cost
            rs.append(pnl / cost); entries.append(p)
            break
    if len(rs) < 5:
        return None
    mean = statistics.mean(rs)
    return {"n": len(rs), "mean": mean, "ci": 1.96 * statistics.stdev(rs) / len(rs) ** 0.5,
            "win": sum(r > 0 for r in rs) / len(rs), "avg_px": statistics.mean(entries),
            "pnl50": mean * 50 * len(rs)}


def analyze(a):
    ms = load()
    half = len(ms) // 2
    A, B = ms[:half], ms[half:]
    d0, d1 = (datetime.fromtimestamp(ms[i]["close"]).strftime("%Y-%m-%d %H:%M") for i in (0, -1))
    print(f"{len(ms)} BTC 15-min markets, {d0} to {d1}. $50 stake, one buy per market, net of fees.\n")

    def fmt(r):
        return f"{100 * r['mean']:+6.2f}% ±{100 * r['ci']:4.1f}  n={r['n']:<4}" if r else f"{'n/a':<22}"

    windows = [(180, 120, "3:00-2:00 left"), (120, 60, "2:00-1:00 left"),
               (60, 30, "1:00-0:30 left"), (30, 10, "0:30-0:10 left"), (10, 0, "last 10 s")]
    bands = [(0.70, 0.85), (0.85, 0.92), (0.92, 0.96), (0.96, 0.98), (0.98, 0.99)]
    for role in ("taker", "maker"):
        print(f"=== {role.upper()}: first {role} fill on the favourite in the window ===")
        print(f"{'window':<16}{'price':<11}{'early half':<24}{'late half':<24}{'all':<24}{'win%':>6}{'  $ total on $50s':>18}")
        for s, e, lab in windows:
            for lo, hi in bands:
                ra, rb, r = (simulate(x, lo, hi, s, e, role=role) for x in (A, B, ms))
                ok = ra and rb and ra["mean"] > 0 and rb["mean"] > 0 and r["mean"] - r["ci"] > 0
                print(f"{lab:<16}{lo:.2f}-{hi:.2f}  {fmt(ra)}  {fmt(rb)}  {fmt(r)}"
                      f"{100 * r['win'] if r else 0:6.1f}{(r['pnl50'] if r else 0):>12.2f}  {'PASS' if ok else ''}")
            print()
    print("PASS = positive in both halves AND the 95% interval on all data is above zero.")
    print("Many combinations are tested, so expect an occasional false PASS; neighbours should agree.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--days", type=float, default=14)
    p.add_argument("--window", type=int, default=300, help="seconds before close to fetch trades for")
    p.add_argument("--rps", type=float, default=15, help="total requests/second across workers")
    p.add_argument("--workers", type=int, default=6)
    sub.add_parser("analyze")
    a = ap.parse_args()
    fetch(a) if a.cmd == "fetch" else analyze(a)


if __name__ == "__main__":
    main()
