"""Minimal read-only Kalshi API client and fee helpers (standard library only).

Public market data needs no account or API key. Nothing in this module places orders.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

LIVE_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"

TAKER_RATE = 0.07    # Kalshi standard taker multiplier
MAKER_RATE = 0.0175  # maker multiplier on series that charge maker fees (many charge 0)


def fee(contracts, price, rate):
    """Kalshi fee for one order: ceil to the cent of rate * C * P * (1 - P)."""
    raw = rate * contracts * price * (1.0 - price)
    return math.ceil(round(raw * 100, 6)) / 100.0


def f(x, default=0.0):
    """Parse Kalshi's string decimals ("0.9300", "12.00") to float."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class Client:
    def __init__(self, base=LIVE_BASE, max_rps=8.0):
        self.base = base
        self.min_gap = 1.0 / max_rps
        self._last = 0.0

    def get(self, path, params=None):
        qs = ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})) if params else ""
        url = self.base + path + qs
        for attempt in range(5):
            wait = self.min_gap - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except urllib.error.URLError:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"GET failed after retries: {url}")

    def paged(self, path, key, params=None, max_items=None):
        params = dict(params or {})
        out = []
        while True:
            d = self.get(path, params)
            out.extend(d.get(key) or [])
            cur = d.get("cursor")
            if not cur or (max_items and len(out) >= max_items):
                return out[:max_items] if max_items else out
            params["cursor"] = cur

    def markets(self, **params):
        params.setdefault("limit", 1000)
        params.setdefault("mve_filter", "exclude")  # skip multi-leg parlay markets
        max_items = params.pop("max_items", None)
        return self.paged("/markets", "markets", params, max_items)

    def market(self, ticker):
        return self.get(f"/markets/{ticker}")["market"]

    def trades(self, ticker, min_ts=None, max_ts=None, max_items=None):
        return self.paged("/markets/trades", "trades",
                          {"ticker": ticker, "limit": 1000, "min_ts": min_ts, "max_ts": max_ts}, max_items)
