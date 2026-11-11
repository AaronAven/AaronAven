"""Read-only web dashboard for the Kalshi paper bot. Standard library only.

    python3 dashboard.py                 # serves http://127.0.0.1:8787
    tailscale serve --bg 8787            # share it privately on your tailnet over HTTPS

It only reads paper_state_*.json and paper_trades_*.csv from this folder; it cannot place trades or
change bot settings. It binds to 127.0.0.1 so nothing outside the Mac can reach it except through
`tailscale serve` (tailnet only). Do NOT use `tailscale funnel`, which would make it public.
"""
import argparse
import csv
import glob
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "dashboard.html")


def run_names():
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "paper_state_*.json"))):
        out.append(os.path.basename(p)[len("paper_state_"):-len(".json")])
    return out


def read_csv_tail(path, n):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-n:]


def summarize(name):
    with open(os.path.join(HERE, f"paper_state_{name}.json")) as fh:
        st = json.load(fh)
    closed = st.get("closed", [])
    positions = list(st.get("positions", {}).values())
    orders = list(st.get("orders", {}).values())
    in_pos = sum(p["cost"] for p in positions)
    in_orders = sum(o["reserved"] for o in orders)
    wins = sum(1 for c in closed if c["pnl"] > 0)
    curve, cum = [], 0.0
    for c in sorted(closed, key=lambda c: c["closed"]):
        cum += c["pnl"]
        curve.append([c["closed"], round(cum, 4), c["ticker"], round(c["pnl"], 4)])
    return {
        "name": name,
        "started": st.get("started"),
        "start_cash": st.get("start_cash"),
        "cash": st.get("cash"),
        "in_positions": in_pos,
        "in_orders": in_orders,
        "equity": st.get("cash", 0) + in_pos + in_orders,
        "realised": cum,
        "fees": st.get("fees", 0.0),
        "settled": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "worst": min((c["pnl"] for c in closed), default=None),
        "positions": sorted(positions, key=lambda p: p.get("opened", 0), reverse=True),
        "orders": orders,
        "curve": curve,
        "recent": list(reversed(read_csv_tail(os.path.join(HERE, f"paper_trades_{name}.csv"), 60))),
        "updated": os.path.getmtime(os.path.join(HERE, f"paper_state_{name}.json")),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(PAGE, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if self.path.startswith("/api/runs"):
            runs = []
            for n in run_names():
                try:
                    runs.append(summarize(n))
                except (OSError, ValueError, KeyError) as e:  # state mid-write or malformed: skip this poll
                    runs.append({"name": n, "error": str(e)})
            return self._send(200, json.dumps({"now": time.time(), "runs": runs}).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"Dashboard on http://{a.host}:{a.port}  (runs found: {', '.join(run_names()) or 'none yet'})")
    print(f"Share on your tailnet:  tailscale serve --bg {a.port}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
