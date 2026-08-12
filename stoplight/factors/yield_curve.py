"""
Factor #1 — YIELD CURVE. Rank 1 (PERMANENT — definitional anchor: is the window open?).

Measure: DGS10 - DGS3MO spread, SEQUENCE-AWARE (the un-inversion is the trigger,
not the inversion — inversion preceded 6/7 recessions since 1970; recession hits
~6-18mo AFTER the crossover back to normal).

STATES (inverted board: GREEN = pro-burst):
  RED    normal    : positive spread with NO inversion in the lookback window
                     (nothing armed)
  YELLOW inverted  : spread < 0 now (the clock is loading)
  GREEN  window    : positive spread AFTER an inversion -> crossover
                     (danger window open; "clock-running" green)

The green carries months-since-crossover in extras — the 6-18mo post-crossover
band is where the historical recessions landed. Lookback for "was there an
inversion" = 3 years (an inversion older than that is a previous cycle, not an
armed window).

SOURCE: FRED DGS10, DGS3MO. Current reference (2026-07-18 spec): +0.86, green,
crossed back ~1yr ago.
"""
from ..sources.fred import fred_series

LOOKBACK_YEARS = 3


def compute():
    d10 = fred_series("DGS10")
    d3m = fred_series("DGS3MO")
    spread = (d10 - d3m).dropna()
    latest = round(float(spread.iloc[-1]), 2)
    asof = spread.index[-1].date().isoformat()

    window = spread.tail(252 * LOOKBACK_YEARS)
    inverted_days = window[window < 0]

    extras = {"source": "FRED DGS10/DGS3MO"}
    if latest < 0:
        light, state = "yellow", "inverted"
    elif inverted_days.empty:
        light, state = "red", "normal"
    else:
        light, state = "green", "window_open"
        last_inv = inverted_days.index[-1]
        extras["crossover_date"] = last_inv.date().isoformat()
        extras["months_since_crossover"] = round(
            (spread.index[-1] - last_inv).days / 30.44, 1)

    sign = "+" if latest >= 0 else ""
    return {
        "id": "yield_curve",
        "light": light,
        "value": latest,
        "metric": f"{sign}{latest:.2f}",
        "state": state,
        "asof": asof,
        "extras": extras,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
