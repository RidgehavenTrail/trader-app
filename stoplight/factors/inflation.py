"""
Factor #15 — INFLATION (keeps the Fed trapped). Rank 15.

Measure: core PCE YoY — the Fed's targeted gauge, NOT headline CPI (core PCE
runs ~0.3-0.5pp BELOW CPI; never read a CPI print against these lines).

STATES (LEVEL-ONLY by design — no direction/lookback; inverted board):
  RED    <= 2%     : at/below target -> Fed can ease -> rescue available
  YELLOW 2 - 3.5%  : elevated but manageable
  GREEN  > 3.5%    : hot -> Fed trapped hard, no rescue

BLIND SPOT (accepted): a demand-collapse disinflation to <=2% would mis-color
red standalone — the board's demand factors (copper, heavy haul) green
simultaneously in that scenario and catch it. Never read <=2% as "all clear."
MONETARY CLUSTER: co-moves with rate path (#3) + net liquidity (#16) — one
signal, not three.

SOURCE: FRED PCEPILFE — the INDEX, not the rate: YoY = idx / idx[-12mo] - 1.
Data lags ~4-6wk. Reference (2026-07-18 spec): 3.41% (May-2026), barely yellow,
one tick from the >3.5% green line, trail climbing 6 months straight.
"""
from .. import store
from ..sources.fred import fred_series

GREEN_ABOVE = 3.5
RED_AT_OR_BELOW = 2.0


def compute():
    idx = fred_series("PCEPILFE")
    yoy = (idx.pct_change(12) * 100).dropna()
    latest = round(float(yoy.iloc[-1]), 2)
    asof = yoy.index[-1].date().isoformat()   # reference month of the print

    if latest > GREEN_ABOVE:
        light, state = "green", "hot_trapped"
    elif latest <= RED_AT_OR_BELOW:
        light, state = "red", "target_can_ease"
    else:
        light, state = "yellow", "elevated"

    trail = [round(float(v), 2) for v in yoy.tail(6)]
    return {
        "id": "inflation",
        "light": light,
        "value": latest,
        "metric": f"{latest:.2f}%",
        "state": state,
        "asof": asof,
        "extras": {"trail_6mo": trail, "source": "FRED PCEPILFE (core PCE YoY)"},
    }



def ledger(days=10, top=10):
    """The last six core-PCE prints against the two lines that cut them.

    SNAPSHOT-DERIVED — `trail_6mo` rides in the day's own extras. ONE view: this factor
    is a level with no direction by design, and the six prints ARE the evidence. They
    are also a different series from the rail beside them: the rail is one row per day
    this board looked, the trail is one point per MONTH the BEA published."""
    out = []
    for day in store.history_payloads("inflation", days):
        ex = day.get("extras") or {}
        trail = ex.get("trail_6mo") or []
        if not trail:
            continue
        # THE TRAIL'S MONTHS, derived rather than stored. `trail_6mo` is a bare list of
        # numbers, but `asof` IS the reference month of its last print and the series is
        # monthly, so the whole axis follows by walking back one month per point. Doing
        # it here rather than changing what compute() stores dates the HISTORICAL
        # snapshots too, which a shape change could never reach back and do.
        ref = day.get("asof") or day.get("date") or ""
        months = []
        try:
            y, m = int(ref[:4]), int(ref[5:7])
            for k in range(len(trail) - 1, -1, -1):
                mm = m - k
                months.append("%04d-%02d" % (y + (mm - 1) // 12, (mm - 1) % 12 + 1))
        except (TypeError, ValueError):
            months = []

        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "yoy": day.get("value"),
            "trail": list(trail),
            "trail_months": months,
            "green_above": GREEN_ABOVE, "red_at_or_below": RED_AT_OR_BELOW,
            # Distance to the line the factor is one tick from, stated rather than left
            # to be eyeballed off six numbers.
            "to_green": round(GREEN_ABOVE - (day.get("value") or 0), 2),
            "climbing": all(b >= a for a, b in zip(trail, trail[1:])),
            "source": ex.get("source"),
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
