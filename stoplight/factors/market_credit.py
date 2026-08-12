"""
Factor #7 — MARKET CREDIT (the spark). Rank 7.

Measure: ICE BofA US High-Yield Option-Adjusted Spread, in bps (up = stress).

STATES (inverted board: GREEN = pro-burst):
  RED    < ~400bps       : tight, firewall holding, complacency
  YELLOW ~400-500bps     : widening off lows / brief scare
  GREEN  > ~500bps AND STAYS WIDE (doesn't heal within weeks)

The "AND STAYS WIDE" clause is LOAD-BEARING (two historical false alarms healed;
Apr-2025's 461bps spike correctly never fired). Implemented as: every one of the
last 10 trading prints > 500bps — a two-week hold, so a one-day spike reads
YELLOW (widening, unconfirmed), not green.

CAVEATS (from spec): RED = "no stress NOW", NOT "safe" — 2007 echo: record
tights right before the blowout. And the asymmetry: tights -> 600+ took WEEKS in
2008/2020; it gaps, it doesn't drift.

SOURCE: FRED BAMLH0A0HYM2 (daily, PERCENT — x100 for bps). Reference
(2026-07-18 spec): 272bps, deeply red, at/near record tights.
"""
from ..sources.fred import fred_series

GREEN_BPS = 500
YELLOW_BPS = 400
SUSTAIN_DAYS = 10


def compute():
    oas_bps = (fred_series("BAMLH0A0HYM2") * 100).dropna()
    latest = round(float(oas_bps.iloc[-1]))
    asof = oas_bps.index[-1].date().isoformat()
    sustained_wide = bool((oas_bps.tail(SUSTAIN_DAYS) > GREEN_BPS).all())

    if latest > GREEN_BPS and sustained_wide:
        light, state = "green", "stress_firing"
    elif latest > YELLOW_BPS:
        light, state = "yellow", "widening"
    else:
        light, state = "red", "complacent"

    return {
        "id": "market_credit",
        "light": light,
        "value": latest,
        "metric": f"{latest}bps",
        "state": state,
        "asof": asof,
        "extras": {
            "sustained_wide": sustained_wide,
            "min_1y_bps": round(float(oas_bps.tail(252).min())),
            "source": "FRED BAMLH0A0HYM2",
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
