"""Paper-trading bot for Kalshi: makes many small simulated trades on live market data. No real money.

Strategy ("near-expiry favourites"): every few seconds, scan markets expected to resolve soon, and buy
small amounts of the heavily-favoured side (default 85-95c) where the market is liquid and the spread is
tight. Hold to settlement. Kalshi research and backtest.py both suggest favourites have been slightly
underpriced (the favourite-longshot bias); the risk is that one loss at 95c wipes out ~19 wins.

Fill model
  taker (default): buy at the current best ask, pay Kalshi's taker fee. Close to what a real
                   market order would get for small sizes.
  maker:           post a simulated bid at the best bid; it only counts as filled if a later public
                   trade prints *below* our price (strictly through us, so queue position can't
                   flatter results). Maker fee charged conservatively.

State is saved to paper_state.json, every fill/settlement appended to paper_trades.csv.

Usage:  python3 paper_bot.py                  # defaults: $100 bankroll, $2 per trade
        python3 paper_bot.py --mode maker --stake 1 --min-price 0.90 --max-price 0.96
        python3 paper_bot.py --report         # print stats from saved state and exit
"""
import argparse
import csv
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone

from kalshi import Client, MAKER_RATE, TAKER_RATE, f, fee

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_state.json")
LOG = os.path.join(HERE, "paper_trades.csv")


def now():
    return time.time()


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_state(bankroll):
    if os.path.exists(STATE):
        with open(STATE) as fh:
            return json.load(fh)
    return {"start_cash": bankroll, "cash": bankroll, "orders": {}, "positions": {}, "closed": [],
            "fees": 0.0, "started": now()}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=1)
    os.replace(tmp, STATE)


def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["time", "event", "ticker", "side", "contracts", "price", "fee",
                                           "pnl", "cash", "title"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in w.fieldnames})


def report(st):
    closed = st["closed"]
    wins = [c for c in closed if c["pnl"] > 0]
    pnl = sum(c["pnl"] for c in closed)
    tied = sum(p["cost"] for p in st["positions"].values()) + sum(o["reserved"] for o in st["orders"].values())
    hrs = (now() - st["started"]) / 3600
    print(f"\n--- paper P&L after {hrs:.1f}h ---")
    print(f"cash ${st['cash']:.2f} | in open positions/orders ${tied:.2f} | "
          f"equity at cost ${st['cash'] + tied:.2f} (started ${st['start_cash']:.2f})")
    print(f"settled {len(closed)} | won {len(wins)} | lost {len(closed) - len(wins)} | "
          f"realised P&L ${pnl:+.2f} | fees paid ${st['fees']:.2f}")
    if closed:
        worst = min(closed, key=lambda c: c["pnl"])
        print(f"worst trade ${worst['pnl']:+.2f} ({worst['ticker']})")
    print(f"open positions {len(st['positions'])} | resting orders {len(st['orders'])}\n")


class Bot:
    def __init__(self, a):
        self.a = a
        self.c = Client(max_rps=a.max_rps)
        self.st = load_state(a.bankroll)
        self.seen_trade_cursor = {}

    # ---- helpers -------------------------------------------------------------------------------
    def exposure_by_event(self):
        ev = {}
        for p in list(self.st["positions"].values()) + list(self.st["orders"].values()):
            ev[p["event"]] = ev.get(p["event"], 0) + 1
        return ev

    def held(self, ticker):
        return ticker in self.st["positions"] or any(o["ticker"] == ticker for o in self.st["orders"].values())

    def fill(self, ticker, event, side, n, price, fe, title):
        pos = self.st["positions"].get(ticker)
        if pos:
            pos["contracts"] += n; pos["cost"] += n * price + fe
        else:
            self.st["positions"][ticker] = {"ticker": ticker, "event": event, "side": side, "contracts": n,
                                            "cost": n * price + fe, "title": title, "opened": now()}
        self.st["fees"] += fe
        log({"time": iso(now()), "event": "FILL", "ticker": ticker, "side": side, "contracts": n,
             "price": f"{price:.4f}", "fee": f"{fe:.2f}", "cash": f"{self.st['cash']:.2f}", "title": title})
        print(f"  FILL   {side.upper():3} {n:>3} @ {price:.2f} +fee {fe:.2f}  {ticker}  {title[:60]}")

    # ---- loop steps ------------------------------------------------------------------------------
    def settle_positions(self):
        for tk in list(self.st["positions"]):
            p = self.st["positions"][tk]
            try:
                m = self.c.market(tk)
            except Exception as e:  # network hiccup: try next loop
                print(f"  warn: could not refresh {tk}: {e}")
                continue
            res = m.get("result")
            if res not in ("yes", "no"):
                continue
            payout = p["contracts"] if res == p["side"] else 0.0
            pnl = payout - p["cost"]
            self.st["cash"] += payout
            self.st["closed"].append({"ticker": tk, "side": p["side"], "result": res, "pnl": round(pnl, 4),
                                      "cost": p["cost"], "closed": now()})
            del self.st["positions"][tk]
            log({"time": iso(now()), "event": "SETTLE", "ticker": tk, "side": p["side"],
                 "contracts": p["contracts"], "pnl": f"{pnl:+.2f}", "cash": f"{self.st['cash']:.2f}",
                 "title": p["title"]})
            print(f"  SETTLE {'WIN ' if pnl > 0 else 'LOSS'} {pnl:+.2f}  {tk}  (result {res})")

    def check_maker_orders(self):
        for oid in list(self.st["orders"]):
            o = self.st["orders"][oid]
            age = now() - o["placed"]
            try:
                trades = self.c.trades(o["ticker"], min_ts=int(o["placed"]), max_items=1000)
            except Exception as e:
                print(f"  warn: trades {o['ticker']}: {e}")
                continue
            # Our bid on side S at price p fills only if someone traded S strictly below p after we posted.
            through = 0.0
            for t in trades:
                if ts(t["created_time"]) <= o["placed"]:
                    continue
                yp = f(t.get("yes_price_dollars"))
                sp = yp if o["side"] == "yes" else 1 - yp
                if sp < o["price"] - 1e-9:
                    through += f(t.get("count_fp"))
            n = min(o["remaining"], int(through))
            if n > 0:
                fe = fee(n, o["price"], MAKER_RATE)
                o["remaining"] -= n
                o["reserved"] -= n * o["price"] + fe  # cash was already set aside at placement
                self.fill(o["ticker"], o["event"], o["side"], n, o["price"], fe, o["title"])
            if o["remaining"] <= 0 or age > self.a.order_ttl:
                self.st["cash"] += max(o["reserved"], 0.0)  # release unfilled reservation
                del self.st["orders"][oid]

    def candidates(self):
        t = now()
        ms = self.c.markets(status="open", max_close_ts=int(t + self.a.max_close_hours * 3600))
        out = []
        for m in ms:
            exp = ts(m.get("expected_expiration_time")) or ts(m.get("close_time"))
            if not exp or exp - t > self.a.max_hours * 3600 or exp < t:
                continue
            if f(m.get("volume_24h_fp")) < self.a.min_volume:
                continue
            for side in ("yes", "no"):
                ask = f(m.get(f"{side}_ask_dollars"), 1.0)
                bid = f(m.get(f"{side}_bid_dollars"), 0.0)
                if not (self.a.min_price <= ask <= self.a.max_price):
                    continue
                if ask - bid > self.a.max_spread + 1e-9:
                    continue
                out.append((m, side, bid, ask, exp))
        out.sort(key=lambda x: x[4])  # soonest to resolve first: recycles capital fastest
        return out

    def place(self):
        ev_count = self.exposure_by_event()
        open_n = len(self.st["positions"]) + len(self.st["orders"])
        try:
            cands = self.candidates()
        except Exception as e:
            print(f"  warn: scan failed: {e}")
            return
        placed = 0
        for m, side, bid, ask, exp in cands:
            if open_n >= self.a.max_open or placed >= self.a.max_new_per_loop:
                break
            tk, ev = m["ticker"], m["event_ticker"]
            if self.held(tk) or ev_count.get(ev, 0) >= self.a.max_per_event:
                continue
            price = ask if self.a.mode == "taker" else bid
            if price <= 0:
                continue
            n = int(self.a.stake // price)
            if n < 1:
                continue
            rate = TAKER_RATE if self.a.mode == "taker" else MAKER_RATE
            fe = fee(n, price, rate)
            cost = n * price + fe
            if cost > self.st["cash"] - self.a.cash_floor:
                break
            title = m.get("title", "")
            if self.a.mode == "taker":
                # YES ask depth is yes_ask_size; NO ask depth is the YES bid depth (same orders).
                depth = f(m.get("yes_ask_size_fp" if side == "yes" else "yes_bid_size_fp"), 0.0)
                if depth < n:
                    continue
                self.st["cash"] -= cost
                self.fill(tk, ev, side, n, price, fe, title)
            else:
                oid = uuid.uuid4().hex[:10]
                self.st["cash"] -= cost
                self.st["orders"][oid] = {"ticker": tk, "event": ev, "side": side, "price": price, "remaining": n,
                                          "reserved": cost, "placed": now(), "title": title}
                print(f"  BID    {side.upper():3} {n:>3} @ {price:.2f}  {tk}  {title[:60]}")
            ev_count[ev] = ev_count.get(ev, 0) + 1
            open_n += 1
            placed += 1

    def run(self):
        print(f"Paper bot | mode={self.a.mode} stake=${self.a.stake} band={self.a.min_price}-{self.a.max_price} "
              f"resolve<= {self.a.max_hours}h | state: {STATE}")
        report(self.st)
        last_report = now()
        while True:
            t0 = now()
            self.settle_positions()
            if self.a.mode == "maker":
                self.check_maker_orders()
            self.place()
            save_state(self.st)
            if now() - last_report > self.a.report_every:
                report(self.st); last_report = now()
            time.sleep(max(0.0, self.a.interval - (now() - t0)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["taker", "maker"], default="taker")
    ap.add_argument("--bankroll", type=float, default=100.0)
    ap.add_argument("--stake", type=float, default=2.0, help="max $ per trade")
    ap.add_argument("--min-price", type=float, default=0.85)
    ap.add_argument("--max-price", type=float, default=0.95)
    ap.add_argument("--max-spread", type=float, default=0.02)
    ap.add_argument("--max-hours", type=float, default=6.0, help="only markets expected to resolve within N hours")
    ap.add_argument("--max-close-hours", type=float, default=72.0, help="pre-filter on scheduled close time")
    ap.add_argument("--min-volume", type=float, default=200.0, help="min 24h contracts traded")
    ap.add_argument("--max-open", type=int, default=40)
    ap.add_argument("--max-per-event", type=int, default=1, help="avoid stacking correlated bets on one game")
    ap.add_argument("--max-new-per-loop", type=int, default=5)
    ap.add_argument("--cash-floor", type=float, default=0.0)
    ap.add_argument("--order-ttl", type=float, default=600.0, help="maker: cancel unfilled bids after N s")
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between scans")
    ap.add_argument("--report-every", type=float, default=600.0)
    ap.add_argument("--max-rps", type=float, default=8.0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reset", action="store_true", help="delete saved paper state and start fresh")
    a = ap.parse_args()

    if a.reset:
        for p in (STATE, LOG):
            if os.path.exists(p):
                os.remove(p)
    bot = Bot(a)
    if a.report:
        report(bot.st); return

    def stop(*_):
        save_state(bot.st); report(bot.st); sys.exit(0)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bot.run()


if __name__ == "__main__":
    main()
