"""Day-trading bot for Alpaca PAPER accounts. Long-only, fractional shares, always flat by the close.

Hard-wired to Alpaca's paper endpoint: it cannot trade real money.

Setup (free): create an Alpaca account, switch to Paper Trading, generate API keys, then:
    export APCA_API_KEY_ID=...        # never commit these or paste them into chat
    export APCA_API_SECRET_KEY=...
    python3 alpaca_bot.py                         # ORB-5 on the default symbols, $100 budget
    python3 alpaca_bot.py --strategy orb30 --budget 100 --per-trade 20

Risk controls: total budget cap (even if the paper account holds more), max $ per trade, one trade per
symbol per day, a daily loss stop that flattens everything, and a forced flatten 5 minutes before the close.
Stops/targets are watched by the bot (checked every few seconds) rather than as resting orders.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from strategies import STRATEGIES

TRADE_BASE = "https://paper-api.alpaca.markets"   # paper only, deliberately
DATA_BASE = "https://data.alpaca.markets"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "alpaca_trades.csv")
DEFAULT_SYMBOLS = "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA,AMD,AVGO"


def iso_ts(s):
    s = s.replace("Z", "+00:00")
    # Alpaca sends nanoseconds; Python's fromisoformat accepts at most 6 fractional digits.
    s = re.sub(r"\.(\d{1,6})\d*", r".\1", s)
    s = re.sub(r"\.(\d{1,5})(?=[+-]|$)", lambda m: "." + m.group(1).ljust(6, "0"), s)
    return datetime.fromisoformat(s).timestamp()


class Alpaca:
    def __init__(self):
        k, s = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
        if not k or not s:
            sys.exit("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY (paper keys) first.")
        self.h = {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s, "Content-Type": "application/json"}

    def req(self, method, url, params=None, body=None):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            try:
                r = urllib.request.Request(url, data=data, headers=self.h, method=method)
                with urllib.request.urlopen(r, timeout=20) as resp:
                    txt = resp.read()
                    return json.loads(txt) if txt else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt); continue
                raise RuntimeError(f"{method} {url} -> {e.code} {msg}")
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(2 ** attempt); continue
                raise RuntimeError(f"{method} {url} -> {e}")

    def clock(self):            return self.req("GET", TRADE_BASE + "/v2/clock")
    def account(self):          return self.req("GET", TRADE_BASE + "/v2/account")
    def positions(self):        return {p["symbol"]: p for p in self.req("GET", TRADE_BASE + "/v2/positions")}
    def close(self, sym):       return self.req("DELETE", TRADE_BASE + f"/v2/positions/{sym}")
    def close_all(self):        return self.req("DELETE", TRADE_BASE + "/v2/positions", {"cancel_orders": "true"})

    def calendar_today(self, date):
        c = self.req("GET", TRADE_BASE + "/v2/calendar", {"start": date, "end": date})
        return c[0] if c else None

    def buy_notional(self, sym, dollars):
        return self.req("POST", TRADE_BASE + "/v2/orders", body={
            "symbol": sym, "notional": f"{dollars:.2f}", "side": "buy", "type": "market", "time_in_force": "day"})

    def bars_5m(self, syms, start_iso):
        out, token = {}, None
        while True:
            p = {"symbols": ",".join(syms), "timeframe": "5Min", "start": start_iso, "feed": "iex",
                 "limit": 10000, "adjustment": "raw"}
            if token:
                p["page_token"] = token
            d = self.req("GET", DATA_BASE + "/v2/stocks/bars", p)
            for s, bs in (d.get("bars") or {}).items():
                out.setdefault(s, []).extend(
                    {"t": iso_ts(b["t"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]} for b in bs)
            token = d.get("next_page_token")
            if not token:
                return out

    def latest_prices(self, syms):
        d = self.req("GET", DATA_BASE + "/v2/stocks/trades/latest", {"symbols": ",".join(syms), "feed": "iex"})
        return {s: t["p"] for s, t in (d.get("trades") or {}).items()}


def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["time", "action", "symbol", "dollars", "price", "stop", "target",
                                           "pnl", "reason", "equity"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in w.fieldnames})


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def run(a):
    api = Alpaca()
    strat = STRATEGIES[a.strategy]
    syms = a.symbols.split(",")
    acct = api.account()
    print(f"Paper account {acct.get('account_number')} | equity ${float(acct['equity']):.2f} | "
          f"strategy {a.strategy} | budget ${a.budget} | per trade ${a.per_trade} | daily loss stop ${a.max_daily_loss}")

    day = None
    while True:
        clk = api.clock()
        if not clk["is_open"]:
            nxt = iso_ts(clk["next_open"])
            wait = max(30, min(600, nxt - time.time()))
            print(f"{now_iso()} market closed; next open {clk['next_open']} (sleeping {wait / 60:.0f} min)")
            day = None
            time.sleep(wait)
            continue

        today = clk["timestamp"][:10]
        if day != today:  # new session: reset daily state
            cal = api.calendar_today(today)
            close_ts = iso_ts(clk["next_close"])
            open_ts = close_ts - (_hm(cal["close"]) - _hm(cal["open"])) * 60
            start_eq = float(api.account()["equity"])
            st = {"traded": set(), "plans": {}, "deployed": 0.0, "halted": False}
            day = today
            print(f"{now_iso()} session {today}: open {cal['open']} close {cal['close']} ET, start equity ${start_eq:.2f}")

        t = time.time()
        pos = api.positions()
        eq = float(api.account()["equity"])

        # 1) daily loss stop / end-of-day flatten
        if not st["halted"] and start_eq - eq >= a.max_daily_loss:
            print(f"{now_iso()} DAILY LOSS STOP hit (equity ${eq:.2f}); flattening and halting for today")
            api.close_all(); st["halted"] = True
            log({"time": now_iso(), "action": "HALT", "reason": "daily loss stop", "equity": f"{eq:.2f}"})
        if t >= close_ts - a.flatten_min * 60:
            if pos:
                print(f"{now_iso()} end of day: flattening {list(pos)}")
                for s, p in pos.items():
                    log({"time": now_iso(), "action": "SELL", "symbol": s, "pnl": p.get("unrealized_pl"),
                         "reason": "eod", "equity": f"{eq:.2f}"})
                api.close_all()
            time.sleep(30)
            continue

        # 2) manage stops / targets on open positions
        if pos:
            px = api.latest_prices(list(pos))
            for s, p in pos.items():
                plan = st["plans"].get(s)
                if not plan or s not in px:
                    continue
                reason = "stop" if px[s] <= plan["stop"] else "target" if plan["target"] and px[s] >= plan["target"] else None
                if reason:
                    api.close(s)
                    print(f"{now_iso()} SELL {s} @~{px[s]:.2f} ({reason}) P&L ${float(p['unrealized_pl']):+.2f}")
                    log({"time": now_iso(), "action": "SELL", "symbol": s, "price": px[s], "pnl": p["unrealized_pl"],
                         "reason": reason, "equity": f"{eq:.2f}"})
                    st["plans"].pop(s, None)

        # 3) new entries on completed bars
        if not st["halted"]:
            start_iso = datetime.fromtimestamp(open_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            bars = api.bars_5m([s for s in syms if s not in st["traded"]], start_iso)
            for s, bs in bars.items():
                done = [b for b in bs if b["t"] + 300 <= t and b["t"] >= open_ts]
                if s in st["traded"] or not done or done[0]["t"] > open_ts + 1:
                    continue  # need the session's first bar to be present
                sig = strat(done)
                if not sig:
                    continue
                dollars = min(a.per_trade, a.budget - st["deployed"])
                if dollars < 1:
                    break
                last = done[-1]["c"]
                if sig["stop"] >= last:
                    continue
                o = api.buy_notional(s, dollars)
                st["traded"].add(s); st["deployed"] += dollars
                st["plans"][s] = {"stop": sig["stop"], "target": sig["target"]}
                tgt = f"{sig['target']:.2f}" if sig["target"] else "close"
                print(f"{now_iso()} BUY ${dollars:.2f} {s} ~{last:.2f} stop {sig['stop']:.2f} "
                      f"target {tgt} (order {o.get('id', '')[:8]})")
                log({"time": now_iso(), "action": "BUY", "symbol": s, "dollars": f"{dollars:.2f}", "price": last,
                     "stop": sig["stop"], "target": sig["target"] or "", "equity": f"{eq:.2f}"})

        time.sleep(a.poll)


def _hm(s):
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", choices=list(STRATEGIES), default="orb5")
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--budget", type=float, default=100.0, help="max $ deployed per day")
    ap.add_argument("--per-trade", type=float, default=20.0)
    ap.add_argument("--max-daily-loss", type=float, default=5.0, help="flatten and stop for the day after losing $N")
    ap.add_argument("--flatten-min", type=float, default=5.0, help="close everything N minutes before the close")
    ap.add_argument("--poll", type=float, default=10.0, help="seconds between checks")
    a = ap.parse_args()
    try:
        run(a)
    except KeyboardInterrupt:
        print("\nstopped (open paper positions, if any, are left as-is; they will not be auto-flattened)")


if __name__ == "__main__":
    main()
