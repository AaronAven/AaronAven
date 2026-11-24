"""Paper-trading bot: Kalshi "BTC price up in next 15 mins?" (series KXBTC15M), late-favourite strategy.

Every 15 minutes Kalshi opens a market asking whether BTC's average price over the final 60 seconds will
be at or above its average over the 60 seconds before the window opened. This bot waits until late in
the window, then buys the favoured side (YES = up, NO = down) at the real order-book ask, if that ask is
inside the price band. One $50 buy per market, held to settlement. Paper only: no account or keys.

    python3 btc15_bot.py                 # minute-12 rule: at 3:00 left bet $50 on the trend, $1,000 bankroll
    python3 btc15_bot.py --name btc15_strong --min-price 0.92
                                         # same, but only when the trend is strong (favourite >= 92c)
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
STATE = LOG = STATUS = JOURNAL = None
MODE = "PAPER"  # this bot has no live mode
JOURNAL_FIELDS = ["trade_id", "strategy", "mode", "market", "side", "entry_time", "entry_price", "size", "stop",
                  "target", "exit_time", "exit_price", "fees", "funding", "slippage", "pnl", "r_multiple",
                  "reason_in", "reason_out", "regime", "backtest_expected_r", "notes"]


def set_paths(name):
    global STATE, LOG, STATUS, JOURNAL
    STATE = os.path.join(HERE, f"paper_state_{name}.json")
    LOG = os.path.join(HERE, f"paper_trades_{name}.csv")
    STATUS = os.path.join(HERE, f"live_status_{name}.json")
    JOURNAL = os.path.join(HERE, f"trades_{name}.csv")


def journal(row):
    """Trade journal in the fund playbook's format (fund/playbook.md, learning loop)."""
    new = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=JOURNAL_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


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
        mark = 15 - a.entry_start / 60
        trend = "any trend" if a.min_price <= 0.5 else f"only if the favourite costs {a.min_price * 100:.0f}c or more"
        return (f"At the {mark:g}:00 mark ({a.entry_start / 60:g} min left), bet ${a.stake:.0f} on the way BTC is "
                f"trending (UP if above the start price, else DOWN); {trend}. Limits: stop for the day at "
                f"-${a.daily_loss:.0f}, halt at -${a.kill_drawdown:.0f} from the high")

    def equity(self):
        return self.st["cash"] + sum(p["cost"] for p in self.st["positions"].values())

    def risk_block(self):
        """Return a reason string if new bets are blocked by the playbook's risk rules, else None."""
        a = self.a
        if self.st.get("halted"):
            return f"HALTED: {self.st['halted']} (restart with --clear-halt after review)"
        eq = self.equity()
        peak = self.st.setdefault("peak_equity", self.st["start_cash"])
        if eq > peak:
            self.st["peak_equity"] = peak = eq
        if peak - eq >= a.kill_drawdown:
            self.st["halted"] = f"equity ${eq:.2f} is ${peak - eq:.2f} below its high of ${peak:.2f}"
            self.save()
            print(f"{iso(time.time())} KILL SWITCH: {self.st['halted']}")
            return f"HALTED: {self.st['halted']}"
        today = datetime.now(timezone.utc).date()
        day_pnl = sum(c["pnl"] for c in self.st["closed"]
                      if datetime.fromtimestamp(c["closed"], timezone.utc).date() == today)
        if day_pnl <= -a.daily_loss:
            return f"daily loss limit hit ({day_pnl:+.2f} today, limit -{a.daily_loss:.0f}); no bets until 00:00 UTC"
        return None

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
            journal({"trade_id": tk, "strategy": self.a.name, "mode": MODE, "market": tk, "side": p["side"],
                     "entry_time": iso(p["opened"]), "entry_price": f"{p['price']:.4f}", "size": p["contracts"],
                     "stop": "0 (binary: max loss = stake)", "target": "1.00",
                     "exit_time": iso(time.time()), "exit_price": "1.00" if payout else "0.00",
                     "fees": f"{p['cost'] - p['contracts'] * p['price']:.2f}", "funding": "", "slippage": "",
                     "pnl": f"{pnl:+.2f}", "r_multiple": f"{pnl / p['cost']:+.3f}",
                     "reason_in": p.get("reason_in", ""),
                     "reason_out": f"settled {res.upper()}: BTC avg {m.get('expiration_value')} vs start {m.get('floor_strike')}",
                     "regime": "", "backtest_expected_r": self.a.expected_r, "notes": ""})
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
            return f"trend {('UP' if side == 'yes' else 'DOWN')} but weak ({ask * 100:.0f}c < {a.min_price * 100:.0f}c): no bet unless it firms up"
        if ask > a.max_price:
            return f"trend {('UP' if side == 'yes' else 'DOWN')} at {ask * 100:.0f}c, above {a.max_price * 100:.0f}c cap: skipping"
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
                                    "opened": time.time(),
                                    "reason_in": f"trend {'UP' if side == 'yes' else 'DOWN'}, best ask {ask:.2f}, "
                                                 f"{left:.0f}s left"}
        self.done.add(tk)
        log({"time": iso(time.time()), "event": "FILL", "ticker": tk, "side": side, "contracts": n,
             "price": f"{avg:.4f}", "fee": f"{fe:.2f}", "cash": f"{self.st['cash']:.2f}",
             "title": self.st["positions"][tk]["title"]})
        print(f"{iso(time.time())} BUY {side.upper()} {n} @ {avg:.3f} (+fee {fe:.2f}) with {left:.0f}s left  {tk}")
        self.save()
        return f"BOUGHT {side.upper()} {n} @ {avg:.3f}"

    def run(self):
        a = self.a
        print(f"MODE: {MODE}")
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
                note = ("bet placed this window, waiting for settlement" if m["ticker"] in self.st["positions"]
                        else "no bet this window (trend too weak); waiting for the next one")
            elif a.entry_end <= left <= a.entry_start:
                block = self.risk_block()
                if block:
                    note = block
                else:
                    try:
                        note = self.try_enter(m, left)
                    except Exception as e:
                        note = f"error: {e}"
                if left <= a.entry_end + a.poll and m["ticker"] not in self.done:
                    self.done.add(m["ticker"])  # window passed without a qualifying price: skip it
                    self.save()
            elif left > a.entry_start:
                note = f"waiting for the {15 - a.entry_start / 60:g}:00 mark"
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
    ap.add_argument("--stake", type=float, default=10.0, help="$ per bet (playbook: 1%% of bankroll)")
    ap.add_argument("--daily-loss", type=float, default=30.0, help="no new bets for the UTC day after losing $N")
    ap.add_argument("--kill-drawdown", type=float, default=150.0, help="halt everything $N below the equity high")
    ap.add_argument("--clear-halt", action="store_true", help="resume after a kill-switch halt (after review)")
    ap.add_argument("--expected-r", default="", help="backtest expected R per trade, for the journal")
    ap.add_argument("--entry-start", type=float, default=180.0, help="bet at this many seconds before close (180 = the 12:00 mark)")
    ap.add_argument("--entry-end", type=float, default=165.0, help="give up if no bet placed by N seconds before close")
    ap.add_argument("--min-price", type=float, default=0.50, help="only bet if the favourite costs at least this (0.50 = any trend)")
    ap.add_argument("--max-price", type=float, default=0.99, help="never pay more than this")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between checks inside the entry window")
    ap.add_argument("--max-rps", type=float, default=8.0)
    ap.add_argument("--report-every", type=float, default=1800.0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    set_paths(a.name)
    if a.reset:
        for p in (STATE, LOG, STATUS, JOURNAL):
            if os.path.exists(p):
                os.remove(p)
    bot = Bot(a)
    if a.clear_halt and bot.st.get("halted"):
        print(f"clearing halt: {bot.st.pop('halted')}"); bot.st["peak_equity"] = bot.equity(); bot.save()
    if a.report:
        report(bot.st); return

    def stop(*_):
        bot.save(); report(bot.st); sys.exit(0)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bot.run()


if __name__ == "__main__":
    main()
