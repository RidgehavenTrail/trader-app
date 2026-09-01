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
from .. import store
from ..sources.yfin import daily_closes, bars_since_52wk_high, project_gate_date

GATE_BARS = 63

# THE PICTURE'S WINDOW (user, 2026-08-31): back to 2020, which is before the AI
# melt-up began -- the point of the chart is to show copper's trend across the era
# the rest of this board is about. The FETCH starts a year earlier so the 200-bar MA
# is fully seeded at the left edge instead of ramping up inside the visible window;
# same trick heavy_haul's chart uses (compute on the full history, trim after).
CHART_START = "2020-01-01"
CHART_FETCH_START = "2019-01-01"


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


def ledger(days=10, top=10):
    """Copper against its own 200-bar trend since 2020, plus the day's own reading.

    Per-day rows are SNAPSHOT-DERIVED -- they re-shape what the day already recorded,
    so they cannot disagree with the light. The SERIES is re-pulled (yfinance serves
    the full history on demand, so unlike market_credit there is no vendor window to
    archive against) and rides only when `days > 1`: the scheduler captures with
    days=1 and stores what it gets permanently, so a 1,700-bar series behind a
    one-line reading would be written to disk every hour.

    THE CHART IS THE POINT. This factor's rule is "any close below the 200" with no
    persistence clause, chosen because copper has not closed below its 200 once in
    2026 -- a claim that is either visible in one glance or taken on faith. The
    green-shaded runs are every stretch that WOULD have fired it."""
    out = []
    for day in store.history_payloads("copper", days):
        ex = day.get("extras") or {}
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "vs200": day.get("value"),
            "price": ex.get("price"), "ma200": ex.get("ma200"),
            "high_52wk": ex.get("high_52wk"), "high_date": ex.get("high_date"),
            "bars_since_high": ex.get("bars_since_high"),
            "gate_bars": ex.get("gate_bars") or GATE_BARS,
            "gate_bars_remaining": ex.get("gate_bars_remaining"),
            "gate_date": ex.get("gate_date"),
            "source": ex.get("source"),
        })

    if out and days > 1:
        px = daily_closes("HG=F", start=CHART_FETCH_START)
        ma = px.rolling(200).mean()
        series, below, last_below = [], 0, None
        for ts, close in px.items():
            d = ts.date().isoformat()
            if d < CHART_START:
                continue
            m = ma.loc[ts]
            if m != m:                      # NaN -- MA not seeded yet
                continue
            series.append([d, round(float(close), 4), round(float(m), 4)])
            if close < m:
                below += 1
                last_below = d
        if series:
            out[0]["series"] = series
            out[0]["chart_from"] = series[0][0]
            out[0]["n_bars"] = len(series)
            # Every close under the 200 in the window -- the green light's own
            # trigger, counted rather than asserted. `last_below` dates the streak
            # the docstring's "not once in 2026" claim rests on.
            out[0]["below_200_days"] = below
            out[0]["last_below"] = last_below
            hi = max(range(len(series)), key=lambda i: series[i][1])
            out[0]["window_high"] = {"price": series[hi][1], "date": series[hi][0]}
            # The chart's last MA and the factor's own ma200 are the same mean over
            # the same 200 bars, computed two ways (rolling vs tail). If they ever
            # part company the picture is not the light's, and the pane says so
            # rather than drawing a line that quietly disagrees with the reading.
            stored = out[0].get("ma200")
            out[0]["ma_matches"] = (
                stored is not None and abs(series[-1][2] - stored) < 0.005)

    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
