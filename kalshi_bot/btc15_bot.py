"""Paper-trading bot: Kalshi "BTC price up in next 15 mins?" (series KXBTC15M), late-favourite strategy.

Every 15 minutes Kalshi opens a market asking whether BTC's average price over the final 60 seconds will
be at or above its average over the 60 seconds before the window opened. This bot waits until late in
the window, then buys the favoured side (YES = up, NO = down) at the real order-book ask, if that ask is
inside the price band. One $50 buy per market, held to settlement. Paper only: no account or keys.

    python3 btc15_bot.py                 # research version: 3:00-2:00 left, 92-98c, $50, $1,000 bankroll
    python3 btc15_bot.py --name btc15_late --entry-start 60 --entry-end 3 --min-price 0.90 --max-price 0.99
                                         # "as late as possible" version, for comparison
    python3 btc15_bot.py --report        # summary
    python3 btc15_bot.py --reset         # start over

Paper fills walk the live order book at the moment of the decision. A real order would arrive a few
hundred milliseconds later, and in the final seconds prices move fast, so live fills could be worse.
"""
import argparse
import csv
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone

from kalshi import Client, TAKER_RATE, f, fee

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES = "KXBTC15M"
STATE = LOG = STATUS = None


def set_paths(name):
    global STATE, LOG, STATUS
    STATE = os.path.join(HERE, f"paper_state_{name}.json")
    LOG = os.path.join(HERE, f"paper_trades_{name}.csv")
    STATUS = os.path.join(HERE, f"live_status_{name}.json")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["time", "event", "ticker", "side", "contracts", "price", "fee",
                                           "pnl", "cash", "title"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in w.fieldnames})


def asks_from_book(book, side):
    """Kalshi books list bids only. Asks for YES come from NO bids (price 1 - p), and vice versa.
    Returns [(price, size)] cheapest first."""
    ob = book.get("orderbook_fp") or {}
    other = ob.get("no_dollars" if side == "yes" else "yes_dollars") or []
    asks = [(round(1 - f(p), 4), f(q)) for p, q in other]
    return sorted(asks)


def walk(asks, stake, max_price):
    """Buy up to $stake walking the asks, never paying above max_price. Returns (contracts, avg_price)."""
    n, cost = 0, 0.0
    for p, q in asks:
        if p > max_price + 1e-9:
            break
        take = min(q, math.floor((stake - cost) / p))
        if take <= 0:
            break
        n += take; cost += take * p
    return (int(n), cost / n) if n else (0, 0.0)


class Bot:
    def __init__(self, a):
        self.a = a
        self.c = Client(max_rps=a.max_rps)
        if os.path.exists(STATE):
            with open(STATE) as fh:
                self.st = json.load(fh)
        else:
            self.st = {"start_cash": a.bankroll, "cash": a.bankroll, "orders": {}, "positions": {}, "closed": [],
                       "fees": 0.0, "started": time.time(), "strategy": self.describe()}
        self.done = set(self.st.get("done", []))  # markets already traded or skipped

    def describe(self):
        a = self.a
        return (f"BTC 15-min late favourite: buy the favoured side between {a.entry_start}s and {a.entry_end}s "
                f"before close when its ask is {a.min_price:.2f}-{a.max_price:.2f}; ${a.stake:.0f} per trade")

    def save(self):
        self.st["done"] = sorted(self.done)[-500:]
        atomic_json(STATE, self.st)

    def status(self, **kw):
        kw["time"] = time.time()
        kw["strategy"] = self.describe()
        try:
            atomic_json(STATUS, kw)
        except OSError:
            pass

    # ----------------------------------------------------------------------------------------------
    def settle(self):
        for tk in list(self.st["positions"]):
            p = self.st["positions"][tk]
            try:
                m = self.c.market(tk)
            except Exception as e:
                print(f"  warn: refresh {tk}: {e}"); continue
            res = m.get("result")
            if res not in ("yes", "no"):
                continue
            payout = p["contracts"] if res == p["side"] else 0.0
            pnl = payout - p["cost"]
            self.st["cash"] += payout
            self.st["closed"].append({"ticker": tk, "side": p["side"], "result": res, "pnl": round(pnl, 4),
                                      "cost": p["cost"], "closed": time.time(), "price": p["price"],
                                      "secs_left": p["secs_left"], "settle_value": m.get("expiration_value"),
                                      "strike": m.get("floor_strike")})
            del self.st["positions"][tk]
            log({"time": iso(time.time()), "event": "SETTLE", "ticker": tk, "side": p["side"],
                 "contracts": p["contracts"], "pnl": f"{pnl:+.2f}", "cash": f"{self.st['cash']:.2f}",
                 "title": p["title"]})
            print(f"{iso(time.time())} SETTLE {'WIN ' if pnl > 0 else 'LOSS'} {pnl:+.2f}  {tk} "
                  f"(result {res}, BTC avg {m.get('expiration_value')} vs target {m.get('floor_strike')})")
            self.save()

    def current_market(self):
        ms = self.c.markets(series_ticker=SERIES, status="open")
        now = time.time()
        ms = [m for m in ms if ts(m["close_time"]) > now]
        return min(ms, key=lambda m: ts(m["close_time"])) if ms else None

    def try_enter(self, m, left):
        a = self.a
        tk = m["ticker"]
        book = self.c.get(f"/markets/{tk}/orderbook")
        best = {}
        for side in ("yes", "no"):
            asks = asks_from_book(book, side)
            best[side] = asks[0][0] if asks else None
        # favourite = the side the market prices above 50c
        cands = [s for s in ("yes", "no") if best[s] is not None and best[s] >= 0.5]
        if not cands:
            return "no clear favourite"
        side = max(cands, key=lambda s: best[s])
        ask = best[side]
        if ask < a.min_price:
            return f"favourite {side.upper()} at {ask:.2f}, below {a.min_price:.2f}: too uncertain, waiting"
        if ask > a.max_price:
            return f"favourite {side.upper()} at {ask:.2f}, above {a.max_price:.2f}: too little profit, waiting"
        stake = min(a.stake, self.st["cash"])
        n, avg = walk(asks_from_book(book, side), stake, a.max_price)
        if n < 1:
            return "not enough depth"
        fe = fee(n, avg, TAKER_RATE)
        cost = n * avg + fe
        if cost > self.st["cash"]:
            n = int((self.st["cash"] - fe) // avg)
            if n < 1:
                return "out of cash"
            fe = fee(n, avg, TAKER_RATE); cost = n * avg + fe
        self.st["cash"] -= cost
        self.st["fees"] += fe
        self.st["positions"][tk] = {"ticker": tk, "event": m["event_ticker"], "side": side, "contracts": n,
                                    "cost": cost, "price": avg, "secs_left": round(left, 1),
                                    "title": f"BTC {'UP' if side == 'yes' else 'DOWN'} vs {m.get('yes_sub_title', '')}",
                                    "opened": time.time()}
        self.done.add(tk)
        log({"time": iso(time.time()), "event": "FILL", "ticker": tk, "side": side, "contracts": n,
             "price": f"{avg:.4f}", "fee": f"{fe:.2f}", "cash": f"{self.st['cash']:.2f}",
             "title": self.st["positions"][tk]["title"]})
        print(f"{iso(time.time())} BUY {side.upper()} {n} @ {avg:.3f} (+fee {fe:.2f}) with {left:.0f}s left  {tk}")
        self.save()
        return f"BOUGHT {side.upper()} {n} @ {avg:.3f}"

    def run(self):
        a = self.a
        print(self.describe()); print(f"state: {STATE}")
        self.save()
        report(self.st)
        last_settle, last_report = 0.0, time.time()
        m, m_fetched = None, 0.0
        while True:
            now = time.time()
            if now - last_settle > 20:
                self.settle(); last_settle = now
            if not m or now - m_fetched > 60 or ts(m["close_time"]) <= now:
                try:
                    m = self.current_market(); m_fetched = now
                except Exception as e:
                    print(f"  warn: market lookup: {e}"); time.sleep(5); continue
            if not m:
                self.status(state="no open BTC 15-min market"); time.sleep(10); continue
            close = ts(m["close_time"]); left = close - now
            note = ""
            if m["ticker"] in self.done:
                note = "already traded this window"
            elif a.entry_end <= left <= a.entry_start:
                try:
                    note = self.try_enter(m, left)
                except Exception as e:
                    note = f"error: {e}"
                if left <= a.entry_end + a.poll and m["ticker"] not in self.done:
                    self.done.add(m["ticker"])  # window passed without a qualifying price: skip it
                    self.save()
            elif left > a.entry_start:
                note = f"waiting for the last {a.entry_start}s"
            try:  # fresh prices for the dashboard
                mm = self.c.market(m["ticker"])
            except Exception:
                mm = m
            self.status(state="running", ticker=m["ticker"], target=m.get("floor_strike"), close=close,
                        secs_left=round(left, 1), yes_bid=f(mm.get("yes_bid_dollars")), yes_ask=f(mm.get("yes_ask_dollars")),
                        note=note)
            if now - last_report > a.report_every:
                report(self.st); last_report = now
            # poll fast inside the entry window, slowly otherwise
            if left > a.entry_start + 5:
                time.sleep(min(5.0, left - a.entry_start - 4))
            else:
                time.sleep(a.poll)


def report(st):
    closed = st["closed"]
    wins = sum(1 for c in closed if c["pnl"] > 0)
    pnl = sum(c["pnl"] for c in closed)
    open_cost = sum(p["cost"] for p in st["positions"].values())
    print(f"\n--- BTC 15-min paper: {(time.time() - st['started']) / 3600:.1f}h ---")
    print(f"cash ${st['cash']:.2f} | open ${open_cost:.2f} | equity ${st['cash'] + open_cost:.2f} "
          f"(started ${st['start_cash']:.2f})")
    print(f"trades {len(closed)} | won {wins} | lost {len(closed) - wins} | P&L ${pnl:+.2f} | fees ${st['fees']:.2f}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="btc15")
    ap.add_argument("--bankroll", type=float, default=1000.0)
    ap.add_argument("--stake", type=float, default=50.0)
    ap.add_argument("--entry-start", type=float, default=180.0, help="start looking N seconds before close")
    ap.add_argument("--entry-end", type=float, default=120.0, help="stop looking N seconds before close")
    ap.add_argument("--min-price", type=float, default=0.92, help="only buy if the favourite costs at least this")
    ap.add_argument("--max-price", type=float, default=0.98, help="never pay more than this")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between checks inside the entry window")
    ap.add_argument("--max-rps", type=float, default=8.0)
    ap.add_argument("--report-every", type=float, default=1800.0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    set_paths(a.name)
    if a.reset:
        for p in (STATE, LOG, STATUS):
            if os.path.exists(p):
                os.remove(p)
    bot = Bot(a)
    if a.report:
        report(bot.st); return

    def stop(*_):
        bot.save(); report(bot.st); sys.exit(0)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bot.run()


if __name__ == "__main__":
    main()
