"""
Factor #9 — MEMORY CANARY (memory-glut sub-mechanism; WHEN factor). Rank 9.

Watches memory-market HEALTH, not HBM alone (DDR5 strength is AI-CAUSED — HBM
diverted capacity starved commodity DRAM; a real crack = HBM AND DDR5 rolling
TOGETHER).

PRIMARY METRIC: of the last 5 forward-EPS revisions POOLED across MU + SK Hynix,
count the DOWNWARD ones:
  RED    <= 1 down   : estimates holding/rising = bubble-supportive
  YELLOW 2-3 down
  GREEN  >= 4 down   : estimates cracking = pro-burst

BASKET (load-bearing): MU (~90% commodity — the DDR5 read) + SK Hynix 000660.KS
(56% HBM share — the HBM read; the KOREAN line, which carries analyst coverage —
NOT SKHYV/ADRs). MU alone hides HBM softness under DDR5 strength. NVDA out
(commoditization target, not memory); Samsung out (too diversified).

MECHANICS: yfinance eps_revisions = true EPS estimate DIRECTION counts (NOT
upgrades_downgrades = rating-action noise). Counts come as 7d/30d windows, not
a timestamped list, so "last 5" is APPROXIMATED from the 7d down-share (30d
fallback when <5 revisions in 7d). The scheduler's daily snapshot log turns
these counts into a real event stream over time (diff recovers events).
Label matching is orientation-agnostic (yfinance frames vary).

Reference (2026-07-18 spec): RED, 0-of-5 down — pooled ~31 up / 0-1 down, a
live DDR5 UP-burst. Earnings: SK Hynix ~07-28, MU ~09-23.
"""
import yfinance as yf

TICKERS = ["MU", "000660.KS"]


def _pool_counts(frame):
    """Sum up/down revision counts for 7d and 30d windows from an eps_revisions
    frame, tolerant of orientation and label casing."""
    up7 = down7 = up30 = down30 = 0
    for axis_labels, get in ((frame.index, lambda l: frame.loc[l]),
                             (frame.columns, lambda l: frame[l])):
        for label in axis_labels:
            key = str(label).lower()
            if "up" not in key and "down" not in key:
                continue
            vals = get(label)
            total = float(vals.sum()) if hasattr(vals, "sum") else float(vals)
            if "up" in key and "7" in key:
                up7 += total
            elif "up" in key and "30" in key:
                up30 += total
            elif "down" in key and "7" in key:
                down7 += total
            elif "down" in key and "30" in key:
                down30 += total
        if up7 or down7 or up30 or down30:   # matched on this axis — done
            break
    return up7, down7, up30, down30


def compute():
    up7 = down7 = up30 = down30 = 0
    per_ticker = {}
    for sym in TICKERS:
        er = yf.Ticker(sym).get_eps_revisions()
        if er is None or er.empty:
            raise ValueError(f"{sym}: eps_revisions unavailable")
        u7, d7, u30, d30 = _pool_counts(er)
        per_ticker[sym] = {"up7": u7, "down7": d7, "up30": u30, "down30": d30}
        up7 += u7
        down7 += d7
        up30 += u30
        down30 += d30

    if up7 + down7 >= 5:
        window, downs_share = "7d", down7 / (up7 + down7)
    elif up30 + down30 >= 5:
        window, downs_share = "30d", down30 / (up30 + down30)
    else:
        window, downs_share = "30d", (down30 / (up30 + down30)) if (up30 + down30) else 0.0

    downs_of_5 = round(downs_share * 5)
    if downs_of_5 <= 1:
        light, state = "red", "estimates_holding"
    elif downs_of_5 <= 3:
        light, state = "yellow", "cracking_partial"
    else:
        light, state = "green", "estimates_cracking"

    import datetime
    return {
        "id": "memory_canary",
        "light": light,
        "value": downs_of_5,
        "metric": f"{downs_of_5}/5 dn",
        "state": state,
        "asof": datetime.date.today().isoformat(),
        "extras": {"window": window, "pooled_up7": up7, "pooled_down7": down7,
                   "pooled_up30": up30, "pooled_down30": down30,
                   "per_ticker": per_ticker,
                   "source": "yfinance eps_revisions MU+000660.KS"},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
