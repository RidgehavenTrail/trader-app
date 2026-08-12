"""
SILICON E — the earnings-durability MODULE (a number-with-direction gauge below
the ranked 16, not a ranked light). Odometer display.

MEASURE: composite FORWARD NET INCOME of the 5 AI-compute semis
(NVDA AVGO MU AMD MRVL) = sum(forwardEps x sharesOutstanding). Excludes
Mag7/INTC/analog/equipment/TSM/ARM by design. NVDA's ~52% weight is a FEATURE:
NVDA is what commoditization kills, so the composite reads the kill.

CHANGE METRIC (the "+22%"): the composite's roll over ~63 TRADING BARS (one
quarter — same convention as copper/heavy haul). GAIN = GREEN, LOSS = RED
(inverted board: rising forward semi-earnings = the earnings-melt-up that IS
the bubble signal = pro-burst; "it's an EARNINGS bubble, not a multiple
bubble"). The arrow flipping DOWN is the coincident BAIL signal.

ROLL SOURCE — eps_trend reconstruction (PRIMARY, added 2026-07-19):
yfinance's eps_trend exposes the +1y forward-EPS estimate as it stood
90 CALENDAR DAYS ago (~63 trading bars — the spec's exact window). Technique
mirrors the concentration backfill: keep the .info level basis, use eps_trend
only for the per-name revision RATIO (90d-ago est / current est), scale each
name's current forward NI back by it, sum -> composite 90d ago. Available
IMMEDIATELY, no 3-month warm-up. Validated 2026-07-19: reconstructed +21.7%
vs the spec's stated +22%, and .info forwardEps == eps_trend +1y `current`
to the penny (identical basis, not an approximation).

ROLL SOURCE — snapshot log (FALLBACK): if eps_trend is unavailable for the
basket, fall back to today's composite vs the weekday snapshot ROLL_BARS rows
back in our own daily log; warming_up until that history exists.

Reference (2026-07-18 spec): $601B (NVDA 310.8 + AVGO 92.4 + MU 170.3 +
AMD 22.0 + MRVL 5.4), roll +22%.
"""
import datetime

import yfinance as yf

from .. import store

BASKET = ["NVDA", "AVGO", "MU", "AMD", "MRVL"]
ROLL_BARS = 63


def _roll_from_eps_trend(shares_by_name, ni_now_by_name):
    """Reconstruct the ~63-bar composite roll from eps_trend's 90-days-ago +1y
    forward EPS. Returns (roll_pct, composite_90d_b) or None if any name lacks
    a usable 90d-ago estimate (all-or-nothing — a partial basket would understate
    the roll)."""
    comp_90 = 0.0
    for sym in BASKET:
        try:
            et = yf.Ticker(sym).get_eps_trend()
            row = et.loc["+1y"]
            e_now = float(row["current"])
            e_90 = float(row["90daysAgo"])
        except Exception:
            return None
        if not e_now or e_90 != e_90 or e_90 <= 0:   # NaN/0 guard
            return None
        comp_90 += ni_now_by_name[sym] * (e_90 / e_now)
    return comp_90


def compute():
    per_name = {}
    ni_now = {}
    shares = {}
    composite = 0.0
    for sym in BASKET:
        info = yf.Ticker(sym).info
        fwd_eps = info.get("forwardEps")
        sh = info.get("sharesOutstanding")
        if not fwd_eps or not sh:
            raise ValueError(f"{sym}: forwardEps/sharesOutstanding missing")
        fwd_ni_b = fwd_eps * sh / 1e9
        per_name[sym] = round(fwd_ni_b, 1)
        ni_now[sym] = fwd_ni_b
        shares[sym] = sh
        composite += fwd_ni_b

    composite_b = round(composite, 1)
    display_b = round(composite)

    light = None
    roll_pct = None
    # ASCII-only metric (cp1252 console logs); frontend renders the arrow glyph
    # from extras["arrow"].
    extras = {"per_name_fwd_ni_b": per_name, "arrow": None,
              "source": "yfinance forwardEps x sharesOutstanding"}

    # PRIMARY: eps_trend reconstruction (available immediately)
    comp_90 = _roll_from_eps_trend(shares, ni_now)
    if comp_90 and comp_90 > 0:
        roll_pct = round((composite_b / comp_90 - 1) * 100, 1)
        extras["roll_method"] = "eps_trend_90d"
        extras["composite_90d_b"] = round(comp_90, 1)
    else:
        # FALLBACK: our own snapshot log (63 weekday bars back)
        rows = store.history("silicon_e", limit=200)
        weekday_vals = [v for d, v in rows
                        if v is not None
                        and datetime.date.fromisoformat(d).weekday() < 5]
        extras["bars_collected"] = len(weekday_vals)
        if len(weekday_vals) > ROLL_BARS and weekday_vals[ROLL_BARS]:
            roll_pct = round((composite_b / weekday_vals[ROLL_BARS] - 1) * 100, 1)
            extras["roll_method"] = "snapshot_log"
        else:
            extras["warming_up"] = True

    if roll_pct is not None:
        light = "green" if roll_pct >= 0 else "red"
        extras["arrow"] = "up" if roll_pct >= 0 else "down"
        extras["roll_63bar_pct"] = roll_pct

    return {
        "id": "silicon_e",
        "light": light,
        "value": composite_b,
        "metric": f"${display_b}B",
        "state": None if roll_pct is None else ("rising" if roll_pct >= 0 else "falling"),
        "asof": datetime.date.today().isoformat(),
        "extras": extras,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
