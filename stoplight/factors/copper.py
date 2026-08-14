"""
Factor #14 — COPPER (Dr. Copper; leading, hourly). Rank 14.

Measure (user rule — deliberately AGGRESSIVE, explicitly NOT backtested):
  GREEN  : below the 200-bar MA (green dominates — any breach)
  YELLOW : above 200MA BUT no new 52-week CLOSE high for 63 TRADING BARS
  RED    : above 200MA WITH a 52wk high inside 63 bars (humming)

Gate = 63 TRADING BARS (a quarter of trading), not calendar days. No absolute
price line (level has no fixed meaning across decades — anti-rot). No green
persistence clause BY CHOICE: copper hasn't closed below its 200MA once in 2026,
so a green here breaks a 10-month streak = a real event.

Direction (inverted board): GREEN = below trend = real economy rolling =
pro-burst; RED = humming = bubble-supportive.

SOURCE: yfinance HG=F (COMEX front month; tariff premium distorts LEVEL not
TREND — LME not worth a pipeline). 200MA = 200 TRADING bars (2y pull; naive
period="200d" is calendar days = too short). Reference (2026-07-18 spec):
red, +8.7-8.9% vs 200MA, 52wk high 6.6495 on 2026-06-02 -> self-executing
yellow gate ~Sep 1 absent a new high.
"""
from ..sources.yfin import daily_closes, bars_since_52wk_high, project_gate_date

GATE_BARS = 63


def compute():
    px = daily_closes("HG=F", period="2y")
    last = float(px.iloc[-1])
    ma200 = float(px.tail(200).mean())
    vs200 = round((last / ma200 - 1) * 100, 1)
    high, high_date, bars_since = bars_since_52wk_high(px)
    gate_date, gate_remaining = project_gate_date(px, GATE_BARS)

    if last < ma200:
        light, state = "green", "below_trend"
    elif bars_since >= GATE_BARS:
        light, state = "yellow", "stalling"
    else:
        light, state = "red", "humming"

    return {
        "id": "copper",
        "light": light,
        "value": vs200,
        "metric": f"{vs200:+.1f}%",   # vs 200-bar MA (mockup rail is 72px; detail in extras)
        "state": state,
        "asof": px.index[-1].date().isoformat(),
        "extras": {
            "price": round(last, 4),
            "ma200": round(ma200, 4),
            "high_52wk": round(high, 4),
            "high_date": high_date,
            "bars_since_high": bars_since,
            "gate_bars": GATE_BARS,
            # Projected on every compute so the calendar row can be REFRESHED from it
            # rather than pinned once -- see project_gate_date's note.
            "gate_date": gate_date,
            "gate_bars_remaining": gate_remaining,
            "source": "yfinance HG=F",
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
