r"""
Board charts — the data behind the AI-bubble detail panel's CHARTS tab (3rd tab).

Spec-driven on purpose: every chart is one entry in BOARD_CHARTS below, so adding
the 4th/5th/6th graph is a spec entry, not new plumbing. Each entry declares its
FRED series, window, resampling and decorations; build_charts() turns the whole
list into the render-ready payload the frontend draws with lightweight-charts.

FREE SOURCES ONLY — FRED (sources/fred.py, no key) and yfinance (sources/yfin.py,
for the heavy-haul basket). This module can never trigger a billed call, same
firewall as events.py. Refreshed DAILY by the scheduler (_maybe_refresh_charts)
into board_charts.json next to stoplight_state.json; /get_board_charts serves that
cache so opening the tab is instant and never blocks on a fetch.

ERROR ISOLATION (house rule): one failing series degrades ONE chart — it carries
an `error` and the rest still render. build_charts() never raises.

TIME FORMAT: 'YYYY-MM-DD' strings, which lightweight-charts takes directly.

THE DIAL (chart 2) is the session-27 definition, unchanged: the policy-rate line
COLORED BY ITS CHANGE OVER THE LOOKBACK — above the upper threshold tightening
(red) / below the lower easing (green) / else hold (gray). That is the regime
filter behind [[fed-dial-regime-thesis]] and the rotation backtest. NOTE this is
the DIAL's own convention (red = tightening), NOT the stoplight board's inverted
palette — a rate chart is not a light.

  THE DIAL'S SERIES, LOOKBACK AND THRESHOLDS ARE NOT IN THIS REPOSITORY. They are
  strategy, not display, so they live in the strategy repo and arrive through
  engine/live_config.py — including this chart's title, subtitle and source line,
  which name the instrument and state the thresholds outright. The reasoning for
  the series choice (a 2026-07-28 regression against the authored dial CSV, and
  why NOT the funds rate) travels with them. See engine/live_config.py.
"""
import os
from datetime import date

import pandas as pd

from engine.common import atomic_write_json
from engine.live_config import cfg

from . import store
from .sources.fred import change_from, fred_series, lookback_base, lookback_change
from .sources.rates import rate_series

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(_BASE_DIR, "board_charts.json")

# The dial's thresholds are strategy, not display — they live in the strategy repo and
# arrive through engine/live_config.py. Read at CALL time, never bound at import, so a
# missing config fails the ONE chart that needs it rather than the whole module. This
# is the same source engine/strategy.py reads, so the chart and the panel can no longer
# disagree about the regime.


def _dial():
    return cfg().DIAL


REGIME_COLOR = {"tightening": "#f87171", "easing": "#34d399", "hold": "#94a3b8"}
REGIME_LABEL = {"tightening": "Tightening", "easing": "Easing", "hold": "Hold"}

LINE = "#22d3ee"        # house cyan, matches the SMA-50 line in charts.js
# Yield-curve palette — the user's reference chart translated to dark mode: a
# brighter blue that carries on #0f172a (the print original's navy would sink into
# it), and a red inverted-region fill light enough to read through.
CURVE_BLUE = "#60a5fa"
INVERT_RED = "rgba(248,113,113,0.38)"


# --- READ THIS BEFORE ADDING A CHART -------------------------------------------
# ROLLING WINDOW vs FULL HISTORY — the trap that broke heavy_haul (2026-08-11).
#
#   FRED (sources/fred.py)      returns the WHOLE series every call. T10Y3M from 1982,
#                               USRECD from 1854, the dial's series from the 1950s. Any
#                               window you apply is a client-side slice of complete data.
#   yfinance (sources/yfin.py)  `period="5y"` is a ROLLING window measured from TODAY.
#                               It advances every day.
#
# So a FIXED reference date (a rebase anchor, a pinned start) is safe against FRED and
# fragile against yfinance. heavy_haul pinned its base to 2021-08-02 — the first bar of
# a 5y fetch — and roughly ten days later the window had slid past it and the factor
# refused to build.
#
# RULE: NEVER pair a fixed date with a rolling fetch. Widening the period only resets a
# countdown (5y -> 10y just moved the next break from 2026 to ~2031, because the window
# start advances a year every year while the base does not). Fetch from an ABSOLUTE
# date instead — `batched_closes(..., start=BASE_DATE)` — so the two cannot diverge.
# When a chart only needs "the last N years" and has no fixed anchor, a rolling cutoff
# against rolling data is fine. The two FRED charts below are safe by construction (full
# history, decades of margin); heavy_haul is safe because its fetch IS its base.

# --- chart specs -------------------------------------------------------------
# kind: 'line'  -> one series, optional recession bands + zero line
#       'dial'  -> policy rate colored by its change over the lookback (regime segments)
BOARD_CHARTS = [
    {
        "id": "yield_curve",
        "kind": "line",
        "title": "Yield curve — 10yr minus 3mo",
        "subtitle": "Inversion below zero; un-inversion is the trigger. Recessions shaded.",
        "series_id": "T10Y3M",
        "start": "2000-01-01",
        "resample": "W-FRI",       # daily -> weekly, visually identical at this zoom
        "unit": "%",
        "color": CURVE_BLUE,
        "recessions": True,
        "zero_line": True,
        # Baseline render (user's reference chart, 2026-07-28, dark-mode palette):
        # blue line throughout, and the INVERTED region — the stretch below zero —
        # filled red. Nothing fills above zero, so the inversion is the only thing
        # that draws the eye. lightweight-charts' baseline series does exactly this
        # split natively at baseValue.
        "baseline": {"price": 0,
                     "top_line": CURVE_BLUE, "top_fill": "rgba(96,165,250,0)",
                     "bottom_line": CURVE_BLUE, "bottom_fill": INVERT_RED},
        "marker_last": True,          # the "today" dot + value label
        # FIXED y-axis (user, 2026-07-28): -2..5, not autoscaled. The window's real
        # extremes are ~-1.9 (2023 inversion) and ~+3.4 (2003), so autoscale kept
        # re-framing the plot around whatever happened to be in view; pinning it
        # makes the zero line sit in the same place every render and keeps the
        # inverted region visually comparable across time.
        "y_range": {"min": -2, "max": 5},
        "legend": [{"label": "Inverted (10yr < 3mo)", "color": "rgba(248,113,113,0.65)"}],
        "source": "FRED T10Y3M (= DGS10 - DGS3MO, the yield_curve factor's own measure)",
    },
    {
        "id": "fed_dial",
        "kind": "dial",
        # title / subtitle / series_id / source are NOT in this repository — each one
        # either names the instrument or states the thresholds. `from_config` marks
        # this spec for _resolve() to fill from the strategy repo at BUILD time, so a
        # missing config fails this chart alone and the rest of the board still renders.
        "from_config": "dial",
        "years": 10,
        "unit": "%",
    },
    # Slots 3-6 — reserved, content TBD (user, 2026-07-28). They render as labeled
    # placeholder boxes so the tab's full layout is visible now. To make one real:
    # replace its entry in place with a 'line' (or 'dial') spec — nothing else has
    # to change, the endpoint/scheduler/renderer are already generic.
    {
        "id": "heavy_haul",
        "kind": "heavy_haul",
        "title": "Heavy haul — freight index",
        "subtitle": "16 equal-weight freight names, quarterly rebalance, with the "
                    "50 and 200-bar MAs that drive the factor's 4-state ladder.",
        "display_years": 3,
        "unit": "",
        "source": "yfinance 16-name equal-weight index (factors/heavy_haul.py)",
    },
    {"id": "tbd4", "kind": "placeholder", "title": "Chart 4 — TBD"},
    {"id": "tbd5", "kind": "placeholder", "title": "Chart 5 — TBD"},
    {"id": "tbd6", "kind": "placeholder", "title": "Chart 6 — TBD"},
]


# --- helpers -----------------------------------------------------------------

def _points(s):
    """A pandas Series -> [{time, value}] with lightweight-charts date strings."""
    return [{"time": ts.date().isoformat(), "value": round(float(v), 3)}
            for ts, v in s.items()]


def _recession_bands(start):
    """Contiguous NBER recession spans (USRECD daily, 1 = in recession) clipped to
    [start, now] -> [{from, to}]. A recession straddling `start` is clipped, not
    dropped, so 2001 still shades correctly on a 2000-start chart."""
    s = fred_series("USRECD")
    start_ts = pd.Timestamp(start)
    bands, in_rec, b0, prev = [], False, None, None
    for ts, v in s.items():
        if v == 1 and not in_rec:
            in_rec, b0 = True, ts
        elif v != 1 and in_rec:
            in_rec = False
            bands.append((b0, prev))
        prev = ts
    if in_rec:
        bands.append((b0, prev))
    out = []
    for a, b in bands:
        if b < start_ts:
            continue
        out.append({"from": max(a, start_ts).date().isoformat(),
                    "to": b.date().isoformat()})
    return out


def _regime(chg, d=None):
    """Classify a change against the deadband. `d` is passed in by callers that
    already hold the dial config, so a per-point walk does not re-read it each time."""
    d = d or _dial()
    if chg > d["tighten"]:
        return "tightening"
    if chg < d["ease"]:
        return "easing"
    return "hold"


def _dial_segments(rate, chg, d=None):
    """Split the rate line into contiguous same-regime runs. Each segment REPEATS
    its predecessor's last point so the colored pieces join seamlessly instead of
    showing a gap at every regime flip."""
    d = d or _dial()
    segs, cur, cur_regime, prev_pt = [], [], None, None
    for ts, v in rate.items():
        c = chg.get(ts)
        if c is None or pd.isna(c):
            continue
        r = _regime(float(c), d)
        pt = {"time": ts.date().isoformat(), "value": round(float(v), 3)}
        if r != cur_regime:
            if cur:
                segs.append({"regime": cur_regime, "color": REGIME_COLOR[cur_regime],
                             "data": cur})
            cur = [prev_pt] if prev_pt else []      # bridge the seam
            cur_regime = r
        cur.append(pt)
        prev_pt = pt
    if cur:
        segs.append({"regime": cur_regime, "color": REGIME_COLOR[cur_regime], "data": cur})
    return segs


# --- builders ----------------------------------------------------------------

def _clamp_last(s, true_last):
    """Re-label a resampled series' final bin to the REAL last observation date.
    resample('W-FRI') stamps the bin with its week-ending Friday, so a partial
    current week lands a point in the FUTURE (observed: last point dated 2026-07-31
    on 07-28). The value is right; only the label is ahead."""
    if len(s) and s.index[-1] > true_last:
        s.index = s.index[:-1].append(pd.DatetimeIndex([true_last]))
    return s


def _build_line(spec):
    raw = fred_series(spec["series_id"])
    true_last = raw.index[-1]
    s = raw[raw.index >= pd.Timestamp(spec["start"])]
    if spec.get("resample"):
        s = _clamp_last(s.resample(spec["resample"]).last().dropna(), true_last)
    if s.empty:
        raise ValueError(f"{spec['series_id']}: no data in window")
    latest = float(s.iloc[-1])
    out = {
        "series": [{"name": spec["title"], "color": spec["color"], "data": _points(s)}],
        "latest": {"value": round(latest, 2),
                   "label": f"{latest:+.2f}{spec['unit']}"},
        "asof": s.index[-1].date().isoformat(),
    }
    if spec.get("recessions"):
        out["bands"] = _recession_bands(spec["start"])
    if spec.get("zero_line"):
        out["zero_line"] = True
    for k in ("baseline", "legend", "marker_last", "y_range"):   # render hints, passed through
        if spec.get(k):
            out[k] = spec[k]
    return out


def _build_dial(spec):
    d = _dial()
    months = d["lookback_months"]
    # Same dispatcher the Rocket Strategy dial uses, so the two cannot end up on
    # different sources any more than they can on different anchors.
    raw = rate_series(spec["series_id"])
    true_last = raw.index[-1]
    # month-start label carrying the month's LAST print — the authored dial's own
    # convention. The current month is partial and firms up as it completes; that is
    # what makes the dial update daily.
    monthly = raw.resample("MS").last().dropna()
    # THE CHANGE IS ANCHORED ON THE CALENDAR DATE, not on the monthly grid (user,
    # 2026-09-10). `monthly.shift(months)` measured month-END to month-END, which read
    # +0.19 against the Rocket Strategy sidebar's +0.22 for the same 2026-09-08 print —
    # the two baselines were 2026-03-31 (3.61) and 2026-03-06 (3.58), and DTB3's +0.03
    # drift across late March was the entire gap. The daily anchor is the literal
    # six-month change and is what the dial LATCHES on, so the picture follows it.
    #
    # The plotted VALUES stay on the monthly grid — the line and its segments are
    # monthly by design. Only the change is re-derived: computed daily, then read off
    # at each month's LAST print, which is the observation that month-start label
    # actually carries.
    daily_chg = lookback_change(raw, months)
    last_dates = pd.Series(raw.index, index=raw.index).resample("MS").last().dropna()
    chg = pd.Series(daily_chg.reindex(pd.DatetimeIndex(last_dates)).to_numpy(),
                    index=last_dates.index)
    # keep `years` of DISPLAY, but only after the change exists
    cutoff = pd.Timestamp(date.today()) - pd.DateOffset(years=spec["years"])
    rate = monthly[monthly.index >= cutoff]
    chg = chg[chg.index >= cutoff]
    rate = rate[rate.index.isin(chg.dropna().index)]
    if rate.empty:
        raise ValueError(f"{spec['series_id']}: no dial data in window")
    segs = _dial_segments(rate, chg, d)
    last_chg = float(chg.dropna().iloc[-1])
    regime = _regime(last_chg, d)
    # The exact baseline behind that change, so the live header measures against it
    # instead of against a value and a change that were each rounded for display.
    last_base = float(lookback_base(raw, months).iloc[-1])
    return {
        "series": [{"name": REGIME_LABEL[s["regime"]], "color": s["color"], "data": s["data"]}
                   for s in segs],
        "legend": [{"label": REGIME_LABEL[k], "color": v} for k, v in REGIME_COLOR.items()],
        "latest": {"value": round(float(rate.iloc[-1]), 2),
                   # THREE DECIMALS ON THE CHANGE (user, 2026-09-10). Two rounded
                   # +0.248 to "+0.25" — the tightening threshold exactly — beside the
                   # word "Hold", which reads as a misclassification and is not one.
                   # Invisible while the dial ran on DTB3 at +0.22; on the live ^IRX it
                   # sits near the edge, which is the whole point of watching it live.
                   "label": f"{float(rate.iloc[-1]):.2f}% · {REGIME_LABEL[regime]} "
                            f"({last_chg:+.3f} {months}mo)",
                   # The numeric change travels beside the rendered label so the live
                   # tip (with_live_tip, below) can measure the live quote without
                   # re-pulling, against `base` -- the exact six-month baseline.
                   "chg": round(last_chg, 3),
                   "base": last_base,
                   "months": months,
                   "regime": regime},
        "asof": true_last.date().isoformat(),   # the real print date, not the month label
    }


def _build_heavy_haul(spec):
    """The heavy-haul freight index with its 50 and 200-bar MAs.

    Calls the FACTOR's own build_index() rather than re-deriving the composite, so
    the chart and the light can never disagree about what the index is — the whole
    methodology (equal weight, quarterly rebalance, fixed base) lives in one place.

    MAs are computed on the FULL history and only then trimmed to the display window,
    so both lines are fully seeded across everything visible — no ramp-up gap at the
    left edge. Same trick the ticker charts use (fetch 2y, show 6mo)."""
    from .factors.heavy_haul import TICKERS, FETCH_START, build_index
    from .sources.yfin import batched_closes

    idx = build_index(batched_closes(TICKERS, start=FETCH_START))
    ma50, ma200 = idx.rolling(50).mean(), idx.rolling(200).mean()

    cutoff = idx.index[-1] - pd.DateOffset(years=spec.get("display_years", 3))
    win = idx.index >= cutoff
    idx_v, ma50_v, ma200_v = idx[win], ma50[win].dropna(), ma200[win].dropna()

    last, m200 = float(idx_v.iloc[-1]), float(ma200.iloc[-1])
    return {
        # House colours: SMA-50 cyan / SMA-200 white, matching the ticker charts;
        # the composite itself gets the violet the pair-ratio series already uses
        # for "a computed series rather than a quoted price".
        "series": [
            {"name": "Index", "color": "#a78bfa", "data": _points(idx_v)},
            {"name": "50-bar MA", "color": "#22d3ee", "data": _points(ma50_v)},
            {"name": "200-bar MA", "color": "#f8fafc", "data": _points(ma200_v)},
        ],
        "legend": [{"label": "Index", "color": "#a78bfa"},
                   {"label": "50-bar MA", "color": "#22d3ee"},
                   {"label": "200-bar MA", "color": "#f8fafc"}],
        "latest": {"value": round(last, 1),
                   "label": f"{last:.0f} · {((last / m200 - 1) * 100):+.1f}% vs 200"},
        "asof": idx_v.index[-1].date().isoformat(),
    }


def _build_placeholder(spec):
    """A reserved slot — no data, no FRED call. The renderer draws a labeled box."""
    return {"series": [], "placeholder": True}


_BUILDERS = {"line": _build_line, "dial": _build_dial,
             "heavy_haul": _build_heavy_haul, "placeholder": _build_placeholder}


def _resolve(spec):
    """Fill a spec's strategy-owned fields from the out-of-repo config.

    Only the dial needs this today: its title, subtitle, series and source each either
    name the instrument or state the thresholds, so none of them can sit in a committed
    file. Called INSIDE build_charts' try, so a missing config downgrades the dial to an
    error card and leaves the rest of the board intact.
    """
    if spec.get("from_config") != "dial":
        return spec
    d = cfg().DIAL
    return {**spec,
            "title":     d["chart_title"],
            "subtitle":  d["chart_subtitle"],
            "series_id": d["series_id"],
            "source":    d["chart_source"]}


def build_charts():
    """Build every spec in BOARD_CHARTS. NEVER raises — a failing chart carries an
    `error` and the others still render."""
    charts, errors = [], []
    for raw_spec in BOARD_CHARTS:
        # A config-sourced spec has no title until it is resolved, so seed the error
        # card from the raw spec and upgrade once _resolve has run.
        base = {"id": raw_spec["id"], "title": raw_spec.get("title", raw_spec["id"]),
                "subtitle": raw_spec.get("subtitle"), "unit": raw_spec.get("unit", ""),
                "source": raw_spec.get("source")}
        try:
            spec = _resolve(raw_spec)
            base = {"id": spec["id"], "title": spec["title"],
                    "subtitle": spec.get("subtitle"), "unit": spec.get("unit", ""),
                    "source": spec.get("source")}
            charts.append({**base, **_BUILDERS[spec["kind"]](spec)})
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            charts.append({**base, "error": msg, "series": []})
            errors.append({"chart": raw_spec["id"], "error": msg})
    return {"generated_at": store.now_iso(), "charts": charts, "errors": errors}


def refresh(force=False):
    """Rebuild the cache file, KEEPING the last good build of any chart that failed.

    A FAILED PULL MUST NOT ERASE A DRAWN CHART (user, 2026-09-08). `build_charts()`
    replaces a chart it cannot build with an error card carrying `series: []`, and
    writing that straight over the cache threw away data that was already on disk and
    perfectly renderable: a transient FRED connect-timeout at 13:05 blanked the yield
    curve, the Fed dial and heavy haul at once, and the daily rebuild timer meant they
    stayed blank until 13:05 the NEXT day. The sources had recovered within minutes.

    Same rule the dial and price-history caches already follow — never cache a failure;
    if a fresh pull throws while a good payload exists, serve the good one FLAGGED
    rather than blanking the panel. The flag matters: a chart silently showing old data
    is worse than one that says it is old.

    Carrying the old chart also restores the RETRY. `_charts_behind()` reads each
    chart's `asof` and skips one that has none, so a wiped chart could never mark the
    payload behind and the 30-minute catch-up never fired. A carried chart keeps its
    real (now lagging) `asof`, so the catch-up sees it and re-tries within the half
    hour instead of waiting out the day.
    """
    prev = load_cached() or {}
    prev_ok = {c.get("id"): c for c in (prev.get("charts") or [])
               if c.get("id") and not c.get("error") and not c.get("placeholder")}

    payload = build_charts()
    carried = []
    for i, c in enumerate(payload.get("charts") or []):
        old_c = prev_ok.get(c.get("id"))
        if c.get("error") and old_c:
            payload["charts"][i] = {**old_c,
                                    "stale": True,
                                    "stale_error": c["error"],
                                    "stale_since": payload["generated_at"]}
            carried.append(c["id"])
    if carried:
        payload["carried"] = carried
    atomic_write_json(CACHE_FILE, payload)
    return payload


def with_live_tip(payload):
    """Overlay the dial chart's HEADING with a live quote. The PICTURE is untouched.

    The user's split, 2026-09-10: "the chart can just be rebuilt daily — I just want
    the latest data above the chart". So the plotted series, its regime segments and
    its colouring stay exactly as the daily build left them, and only the reading in
    the header — the rate, its six-month change and the as-of date — is refreshed.

    Costs no pull of its own: it reuses the dial's own 60-second live-quote cache in
    engine.strategy, so the sidebar and this header cannot show different numbers for
    the same instant. Returns the payload unchanged for a non-live source (a FRED id
    has no intraday tip), on any failure, and for every chart that is not the dial.
    """
    try:
        from engine.strategy import _dial, _dial_live_rate
        d = _dial()
        v = _dial_live_rate(d.get("series_id"))
        if v is None:
            return payload
    except Exception:
        return payload                      # a live extra must never break the tab

    out = dict(payload)
    charts_out = []
    for c in out.get("charts") or []:
        lat = c.get("latest") or {}
        if c.get("id") != "fed_dial" or lat.get("chg") is None or c.get("error"):
            charts_out.append(c)
            continue
        base = lat.get("base")               # exact -- `value - chg` is two rounded numbers
        if base is None:
            # A cache built before `base` existed (board_charts.json is rebuilt daily, not
            # on restart). Borrow the sidebar dial's exact baseline -- same series, same
            # anchor -- but only for the same observation date and lookback, so a header
            # never measures today's quote against a different day's baseline.
            try:
                from engine.strategy import get_dial
                dp = get_dial() or {}
                if (dp.get("asof") == c.get("asof")
                        and dp.get("lookback_months") == lat.get("months")):
                    base = dp.get("chg_base")
            except Exception:
                base = None
        if base is None:
            charts_out.append(c)             # no exact baseline: keep the daily header
            continue
        chg = change_from(v, base)
        months = lat.get("months") or d.get("lookback_months")
        # The REGIME is not recomputed here — see _with_live_rate in engine/strategy.py.
        # A flip needs consecutive daily prints; repainting the header's word off an
        # intraday wiggle would assert a state change the latch has not made.
        c = dict(c, latest=dict(lat,
                                value=round(v, 3),
                                chg=chg,
                                live=True,
                                label=f"{v:.2f}% · {REGIME_LABEL[lat['regime']]} "
                                      f"({chg:+.3f} {months}mo)"),
                 asof=store.now_et().date().isoformat())
        charts_out.append(c)
    out["charts"] = charts_out
    return out


def load_cached():
    """The cached payload, or None when it has never been built."""
    try:
        import json
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    import json
    p = refresh()
    for c in p["charts"]:
        n = sum(len(s.get("data", [])) for s in c.get("series", []))
        print(f"{c['id']:14} pts={n:>5} asof={c.get('asof')} "
              f"latest={(c.get('latest') or {}).get('label')} err={c.get('error')}")
    print("bands:", json.dumps([b for c in p["charts"] for b in c.get("bands", [])]))
