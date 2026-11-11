"""Intraday strategies shared by backtest.py and alpaca_bot.py. Long-only, flat by the close.

Each strategy looks at today's completed 5-minute bars (oldest first, regular hours only) and returns
either None or an entry signal: {"stop": price, "target": price or None}. The entry is taken at the
next bar's open. Bars are dicts with keys t (epoch s), o, h, l, c, v.
"""


def orb5(bars, target_r=10.0):
    """5-minute opening range breakout (after Zarattini & Aziz, 2023), long side only.

    If the first 5-minute bar closes up, buy at the second bar's open with the stop at the first bar's
    low. The target is target_r times the risk; anything still open exits at the close.
    """
    if len(bars) != 1:
        return None
    b = bars[0]
    if b["c"] <= b["o"]:
        return None
    risk = b["c"] - b["l"]
    if risk <= 0:
        return None
    return {"stop": b["l"], "target": b["c"] + target_r * risk if target_r else None}


def orb30(bars):
    """30-minute opening range breakout: buy when a 5-minute bar closes above the first 30 minutes'
    high (before 11:30 ET). The stop is the opening range low; exit at the close."""
    if len(bars) < 7 or len(bars) > 24:  # bars 1-6 = range; only signal 10:00-11:30 ET
        return None
    rng = bars[:6]
    hi, lo = max(x["h"] for x in rng), min(x["l"] for x in rng)
    last, prev = bars[-1], bars[-2]
    if last["c"] > hi and (len(bars) == 7 or prev["c"] <= hi):
        return {"stop": lo, "target": None}
    return None


def open_to_close(bars):
    """Baseline: buy at the open (second bar), sell at the close. Does an 'edge' beat just holding the day?"""
    if len(bars) != 1:
        return None
    return {"stop": 0.0, "target": None}


STRATEGIES = {"orb5": orb5, "orb30": orb30, "open_to_close": open_to_close}
