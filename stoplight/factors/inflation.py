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


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
