"""Strategy research on cached Kalshi trade data.

Step 1 (slow, network):  python3 research.py fetch --days 14 --max-markets 3000
Step 2 (fast, offline):  python3 research.py analyze

fetch saves every settled market and its trades to research_cache.jsonl. analyze slices taker fills
(what the bot actually does) by price band, time to settlement, market category and week. A strategy
only counts if it is positive after fees in BOTH halves of the data (out-of-sample check).
"""
import argparse
import json
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime

from kalshi import Client, TAKER_RATE, MAKER_RATE, f, fee

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "research_cache.jsonl")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def category(series):
    s = series.upper()
    if "15M" in s:
        return "crypto/fx 15-min"
    if any(k in s for k in ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE")):
        return "crypto daily/hourly"
    if any(k in s for k in ("NBA", "NFL", "NHL", "MLB", "NCAA", "SOCCER", "ATP", "WTA", "ITF", "UFC", "CS2",
                            "LOL", "VALORANT", "DOTA", "EPL", "MLS", "GOLF", "PGA", "F1", "BASKETBALL",
                            "TENNIS", "R6", "CRICKET", "WNBA", "NASCAR", "BOXING")):
        return "sports/esports"
    if any(k in s for k in ("TEMP", "HIGH", "LOW", "RAIN", "SNOW", "WEATHER")):
        return "weather"
    if any(k in s for k in ("INX", "NASDAQ", "SPX", "WTI", "GOLD", "USDJPY", "EURUSD", "NATGAS", "TREAS", "OIL")):
        return "markets/commodities"
    return "other"


def fetch(a):
    c = Client(max_rps=a.rps)
    now = int(time.time())
    done = set()
    if os.path.exists(CACHE):
        with open(CACHE) as fh:
            done = {json.loads(l)["ticker"] for l in fh}
    ms = c.markets(status="settled", min_close_ts=now - int(a.days * 86400))
    ms = [m for m in ms if m.get("result") in ("yes", "no") and f(m.get("volume_fp")) >= a.min_volume
          and m["ticker"] not in done]
    random.Random(a.seed).shuffle(ms)
    ms = ms[: max(0, a.max_markets - len(done))]
    print(f"fetching trades for {len(ms)} markets ({len(done)} already cached)")
    with open(CACHE, "a") as out:
        for i, m in enumerate(ms):
            try:
                trades = c.trades(m["ticker"], max_items=a.max_trades)
            except Exception as e:
                print(f"  skip {m['ticker']}: {e}"); continue
            rec = {"ticker": m["ticker"], "event": m["event_ticker"], "series": m["event_ticker"].split("-")[0],
                   "result": m["result"], "settle": ts(m.get("settlement_ts") or m["close_time"]),
                   "vol": f(m.get("volume_fp")),
                   "trades": [[ts(t["created_time"]), f(t.get("yes_price_dollars")), t.get("taker_side"),
                               f(t.get("count_fp"))] for t in trades]}
            out.write(json.dumps(rec) + "\n")
            if i % 200 == 0:
                print(f"  {i}/{len(ms)}"); out.flush()


def load():
    with open(CACHE) as fh:
        return [json.loads(l) for l in fh]


def evaluate(mkts, lo, hi, max_h, min_h=0.0, role="taker", cats=None, first_only=True, stake=2.0, maker_fee=True):
    """Equal-weight-per-market net return of buying the side priced in [lo,hi) within max_h hours of
    settlement. first_only: take only the first qualifying fill per market (what a bot that buys once
    per market would get), sized 1 contract-equivalent of $2 stake."""
    rs = []
    for m in mkts:
        if cats and category(m["series"]) not in cats:
            continue
        for t, yp, taker, n in sorted(m["trades"]):
            hrs = (m["settle"] - t) / 3600
            if not (min_h <= hrs <= max_h):
                continue
            for side, p in (("yes", yp), ("no", round(1 - yp, 4))):
                if not (lo <= p < hi):
                    continue
                is_taker = side == taker
                if (role == "taker") != is_taker:
                    continue
                k = max(1, int(stake // p))  # contracts the stake buys
                fe = fee(k, p, TAKER_RATE) if role == "taker" else (fee(k, p, MAKER_RATE) if maker_fee else 0.0)
                pay = k if side == m["result"] else 0
                rs.append((pay - k * p - fe) / (k * p + fe))
                break
            else:
                continue
            if first_only:
                break
    if len(rs) < 2:
        return None
    mean = statistics.mean(rs)
    return mean, 1.96 * statistics.stdev(rs) / len(rs) ** 0.5, len(rs), sum(r > 0 for r in rs) / len(rs)


def analyze(a):
    mkts = load()
    mkts.sort(key=lambda m: m["settle"])
    half = len(mkts) // 2
    A, B = mkts[:half], mkts[half:]
    d0 = datetime.fromtimestamp(mkts[0]["settle"]).date(); d1 = datetime.fromtimestamp(mkts[-1]["settle"]).date()
    print(f"{len(mkts)} markets, {d0} to {d1}; split into early/late halves of {half}\n")
    cnt = defaultdict(int)
    for m in mkts:
        cnt[category(m["series"])] += 1
    print("markets by category:", dict(cnt), "\n")

    def show(label, **kw):
        ra, rb, rall = evaluate(A, **kw), evaluate(B, **kw), evaluate(mkts, **kw)
        def fmt(r):
            return f"{100 * r[0]:+6.2f}% ±{100 * r[1]:4.1f} n={r[2]:<5}" if r else f"{'n/a':<22}"
        ok = ra and rb and ra[0] > 0 and rb[0] > 0 and rall[0] - rall[1] > 0
        print(f"{label:<44}{fmt(ra)}  {fmt(rb)}  {fmt(rall)}  win {100 * rall[3] if rall else 0:5.1f}%  {'PASS' if ok else ''}")

    hdr = f"{'':<44}{'early half':<24}{'late half':<24}{'all':<24}"
    for role in ("taker", "maker"):
        print(f"=== {role} buys, first qualifying fill per market, $2 stake, net of fees ===")
        print(hdr)
        for max_h in (1, 6, 24, 1e9):
            for lo, hi in ((0.50, 0.70), (0.70, 0.85), (0.85, 0.90), (0.90, 0.95), (0.85, 0.95), (0.95, 0.99)):
                show(f"{lo:.2f}-{hi:.2f}  within {'any' if max_h > 1e8 else str(max_h) + 'h'}",
                     lo=lo, hi=hi, max_h=max_h, role=role)
            print()
    print("=== sizing and fee sensitivity (within 6h) ===")
    print(hdr)
    for role, lo, hi in (("taker", 0.85, 0.95), ("maker", 0.90, 0.99), ("maker", 0.85, 0.95)):
        for stake in (2.0, 10.0, 50.0):
            show(f"{role} {lo:.2f}-{hi:.2f} ${stake:.0f} stake", lo=lo, hi=hi, max_h=6, role=role, stake=stake)
        if role == "maker":
            show(f"{role} {lo:.2f}-{hi:.2f} $10, no maker fee", lo=lo, hi=hi, max_h=6, role=role, stake=10,
                 maker_fee=False)
    print()
    print("=== taker 0.70-0.95, within 24h, by category ===")
    print(hdr)
    for cat in sorted(cnt):
        show(cat, lo=0.70, hi=0.95, max_h=24, cats={cat})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--days", type=float, default=14)
    p.add_argument("--max-markets", type=int, default=3000)
    p.add_argument("--max-trades", type=int, default=3000)
    p.add_argument("--min-volume", type=float, default=50)
    p.add_argument("--rps", type=float, default=9)
    p.add_argument("--seed", type=int, default=7)
    sub.add_parser("analyze")
    a = ap.parse_args()
    fetch(a) if a.cmd == "fetch" else analyze(a)


if __name__ == "__main__":
    main()
