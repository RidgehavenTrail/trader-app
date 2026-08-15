"""
Rocket Strategy — live status for the left-panel #strategy-section.

Engine-split pattern (engine/newsletter.py, engine/macro.py, engine/market.py):
a self-contained Flask Blueprint importing NOTHING from watchtower_engine, so
there is no circular import. Registered by the engine with:

    from engine.strategy import bp as strategy_bp
    app.register_blueprint(strategy_bp)

Serves GET /get_strategy_dial.

WHICH DIAL THIS IS
------------------
"Dial B" — the signal the regime-rotation backtest ran on, and the same one the
Charts-tab dial renders. Its series, lookback and thresholds are NOT in this
repository: they live in the strategy repo and arrive via engine/live_config.py.
See that module for why. It is NOT the three-pillar real-rates x net-liquidity x
pivot override switch — that is a different instrument and never drove the
rotation. Do not merge the two.

DAILY + LATCHED, NOT MONTHLY
----------------------------
The backtest resampled to month-end, which snaps the state on an arbitrary
calendar date and can leave the board up to five weeks stale (observed: the most
recent flip latches 2026-04-01 daily vs 2026-03-01 monthly). For a real-time
board we compute the change on EVERY trading day and LATCH a flip only once the
new state has held the configured run of consecutive prints (user, 2026-08-09: "not going to
just snap the chalk line once a month on a random date").

The latch REDUCES lag, it does not eliminate whipsaw, and that is deliberate —
the user works the edges by judgment (2026-08-10). Two consequences that are
features, not bugs:
  * When the change hugs a threshold the state can flip more than once in a few
    weeks (observed July 2019: easing -> hold -> easing in three weeks, where the
    monthly convention showed one flip). Suppressing that would hide exactly the
    signal he wants to see.
  * `near` marks a judgment period, but is NOT a guaranteed precursor: the change
    can jump a threshold in one print (a large value rolling OUT of the 6-month
    window moves it discontinuously), flipping with no day spent inside the near band.

CAVEATS THAT MUST TRAVEL WITH THIS
----------------------------------
n=4 tightening episodes since 1994. The deadband and the lookback window are
UNOPTIMIZED display choices. `allocation` is the rule's mechanical output, never
a recommendation. The underlying series posts about one business day late, so
`asof` is normally behind today — surface it rather than implying the read is
same-day.
"""
import threading
import time

import pandas as pd
from flask import Blueprint, jsonify

from engine.live_config import cfg

bp = Blueprint('strategy', __name__)

# The dial's series, lookback, thresholds and latch are NOT in this repository — they
# live in the strategy repo and arrive through engine/live_config.py. Read at CALL
# time rather than bound at import, so a committed change is picked up without an
# engine restart. Both this panel and stoplight/charts.py read the same source, so the
# box and the chart can no longer disagree about the regime — the duplication that
# used to need a "if one moves the other must" warning is gone.


def _dial():
    return cfg().DIAL


REGIME_COLOR = {"tightening": "#f87171", "easing": "#34d399", "hold": "#94a3b8"}
REGIME_LABEL = {"tightening": "Tightening", "easing": "Easing", "hold": "Hold"}

# The rotation's mechanical allocation per regime is NOT in this repository — it
# names the holdings, which is most of what would let a reader reconstruct the
# strategy, so it lives in the strategy repo (see engine/live_config.py). The notes
# that used to sit here — the 2026-07-23 final config, the unconfirmed gold vehicle,
# and why `symbol` is explicit rather than derived — travel with it.
#
# `strategy` on a holding is the per-holding rule governing entries/exits INSIDE the
# regime. The dial is the timing layer deciding WHICH column is live; _holding_state()
# below asks each holding what it is doing once it is.


def _portfolios():
    return cfg().PORTFOLIOS

# Display order for the alternate columns — rate direction, easing -> tightening.
REGIME_ORDER = ["easing", "hold", "tightening"]

# Per-ticker pill colors also live in the strategy repo: the map is keyed BY TICKER,
# so shipping it here would list the holdings just as plainly as the allocation does.
# The reasoning behind the choices travels with it.

# TWO caches on deliberately different clocks. The dial is a slow macro series that
# prints once a business day; the day-moves are quotes that must not be six hours
# stale. Merged at request time so one endpoint serves both without either dragging
# the other's cadence.
CACHE_TTL_SECONDS = 6 * 3600      # the dial's series prints once a business day
QUOTE_TTL_SECONDS = 60            # intraday % change
_cache_lock = threading.Lock()
_cache = {"payload": None, "at": 0.0}
_quote_lock = threading.Lock()
_quotes = {"data": {}, "at": 0.0}


def _regime(chg, d=None):
    """Classify a change against the deadband. `d` is passed in by callers that
    already hold the dial config, so a per-row map does not re-read it each time."""
    d = d or _dial()
    if chg > d["tighten"]:
        return "tightening"
    if chg < d["ease"]:
        return "easing"
    return "hold"


def _dial_frame():
    """The dial's series with its daily change over the lookback, and the raw regime,
    oldest -> newest.

    The lookback is vectorised: reindexing the series onto its own index shifted back
    by the configured months with method='ffill' takes the last print ON OR BEFORE
    each target date, so holidays and gaps resolve BACKWARDS. Never forwards — that
    would read a rate that had not printed yet.
    """
    # Imported lazily so this blueprint does not pull in the stoplight package at
    # engine import time. fred.py is a plain requests+pandas helper with retries.
    from stoplight.sources.fred import fred_series

    d = _dial()
    s = fred_series(d["series_id"])
    back = s.reindex(s.index - pd.DateOffset(months=d["lookback_months"]),
                     method="ffill")
    df = pd.DataFrame({"rate": s.to_numpy(), "chg": s.to_numpy() - back.to_numpy()},
                      index=s.index).dropna()
    if df.empty:
        raise ValueError(f"{d['series_id']}: no overlapping "
                         f"{d['lookback_months']}-month window")
    df["raw"] = df["chg"].map(lambda c: _regime(c, d))
    return df


def _latch(raw_states):
    """Walk the raw daily states and return the latched series.

    A flip takes only after the configured number of consecutive prints in the SAME
    new state. If the candidate changes mid-run the count restarts — three days of
    easing followed by two of tightening latches neither.
    """
    need = _dial()["latch_days"]
    latched = raw_states[0]
    cand, run, out = None, 0, []
    for r in raw_states:
        if r == latched:
            cand, run = None, 0
        else:
            if r != cand:
                cand, run = r, 1
            else:
                run += 1
            if run >= need:
                latched, cand, run = r, None, 0
        out.append(latched)
    return out


def _tech_one(d):
    """Per-symbol technicals from one OHLC frame. Generic — nothing here is
    QQQ-specific, so it means the same thing for MO or GC as it does for QQQ.

    era:   golden  50 SMA > 200 SMA, no live warning
           WARNING still golden, but a warning has fired since the last 52-week
                   high (a new high CANCELS a live warning — that is the rule, so
                   "since the last new high" IS the live-warning test and needs no
                   state machine)
           death   50 SMA <= 200 SMA
    depth: today's price against the 50 SMA — negative means below it.
    """
    c, h, l = d["Close"], d["High"], d["Low"]
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    if pd.isna(s50.iloc[-1]) or pd.isna(s200.iloc[-1]):
        return None

    price = float(c.iloc[-1])
    gap = (float(s50.iloc[-1]) - float(s200.iloc[-1])) / float(s200.iloc[-1]) * 100
    depth = (price - float(s50.iloc[-1])) / float(s50.iloc[-1]) * 100

    # Only bars where BOTH SMAs exist count. Without this mask the leading NaN
    # stretch compares as not-golden and manufactures a crossover at bar 200.
    valid = s50.notna() & s200.notna()
    gold = (s50 > s200)[valid]
    era = "golden" if bool(gold.iloc[-1]) else "death"

    # Days in the era, in TRADING days, matching the dial's own unit.
    flips = gold.index[gold != gold.shift(1)][1:]
    era_start = flips[-1] if len(flips) else gold.index[0]
    capped = not len(flips)          # era began before the window — a floor, not a count

    if era == "golden":
        hi252 = h.rolling(252).max().shift(1)
        new_high = h > hi252 * (1 + 1e-9)
        gap_s = (s50 - s200) / s200 * 100
        # Both conditions, same day. The two thresholds are strategy, not display,
        # so they arrive from the strategy repo rather than living here.
        w = cfg().WARN
        warn_day = ((l <= s50.shift(1) * (1 - w["depth"] / 100.0))
                    & (gap_s < w["gap"]))[valid]
        since = new_high[new_high].index[-1] if new_high.any() else gold.index[0]
        live = warn_day.loc[warn_day.index > since]
        if bool(live.any()):
            era = "WARNING"
            # A WARNING's clock runs from the warning itself, not the golden cross —
            # "how long have I been warned" is the question that state raises.
            era_start, capped = live[live].index[0], False

    day = None
    if len(c) >= 2 and float(c.iloc[-2]):
        day = round((price / float(c.iloc[-2]) - 1) * 100, 2)
    return {"price": round(price, 2), "day_pct": day,
            "s50": round(float(s50.iloc[-1]), 2), "s200": round(float(s200.iloc[-1]), 2),
            "gap_pct": round(gap, 2), "depth_pct": round(depth, 2), "era": era,
            "era_days": int((c.index >= era_start).sum()), "era_days_capped": capped}


def _tech(symbols):
    """{symbol: technicals} for the live holdings. Fails SOFT — a quote outage must
    not blank the allocation, so a missing symbol returns nothing and its pill just
    renders without a move or a directional border.

    5y of history: the 200 SMA needs 200 bars before the first valid reading, and
    era_days must be able to count back through a long golden run. 2y left only ~250
    usable bars, which silently floored any era older than a year.
    """
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    with _quote_lock:
        if _quotes["data"] and time.time() - _quotes["at"] < QUOTE_TTL_SECONDS:
            if all(s in _quotes["data"] for s in symbols):
                return _quotes["data"]
    out = {}
    try:
        import yfinance as yf
        raw = yf.download(" ".join(symbols), period="5y", auto_adjust=False,
                          progress=False, group_by="ticker")
        for s in symbols:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close"]].dropna()
                if len(d) >= 200:
                    t = _tech_one(d)
                    if t:
                        out[s] = t
            except Exception:
                continue                       # one bad symbol must not sink the rest
    except Exception as e:
        print(f"[STRATEGY] technicals pull failed: {type(e).__name__}: {e}")
        return dict(_quotes["data"])           # last good, or {} on a cold start
    if not out:
        return dict(_quotes["data"])
    with _quote_lock:
        _quotes["data"], _quotes["at"] = out, time.time()
    return out


def _holding_state(h):
    """The per-holding strategy state — the strategy INSIDE the regime.

    The dial decides which column is live; this says what each name in that column
    is actually doing once it is. Only QQQ has a real rule today; the other sleeves
    are simply held and rebalanced monthly, which is the rotation's own mechanic
    rather than a per-name strategy.

    Anything with a `strategy` key returns engine/qqq_system.py's CONTRACT dict
    verbatim — this function does not reshape it, so a future strategy needs no
    change here. A failed build degrades to the unwired marker rather than blanking
    the holding.
    """
    name = h.get("strategy")
    if name:
        try:
            from engine.qqq_system import STRATEGIES, get_state
            if name in STRATEGIES:
                s = get_state(name)
                if s.get("ok"):
                    return s
            else:
                print(f"[STRATEGY] holding declares unknown strategy {name!r}")
        except Exception as e:
            print(f"[STRATEGY] {name} state failed: {type(e).__name__}: {e}")
        return {"ok": False, "state": "unavailable", "state_tier": "flat"}
    return {"ok": True, "state": "hold", "state_tier": "flat",
            "detail": "monthly rebal", "no_strategy": True}


def compute_dial():
    """The live dial payload. Raises on a failed pull — the caller decides whether
    to serve a stale cache."""
    c = cfg()
    d = c.DIAL

    df = _dial_frame()
    df["latched"] = _latch(df["raw"].tolist())

    last = df.iloc[-1]
    state = last["latched"]
    chg = float(last["chg"])

    # When the latched state last changed. iloc[1:] drops the synthetic "flip" at
    # the seed row, which is just the series starting, not a real transition.
    flips = df[df["latched"] != df["latched"].shift(1)].iloc[1:]
    latched_at = flips.index[-1] if len(flips) else df.index[0]
    latched_on = latched_at.date().isoformat()

    # How long this state has run. TRADING days, counted as prints in the series
    # since the latch — consistent with the latch run, also counted in trading days.
    # Calendar days travel alongside for anything that wants a human duration.
    days_in_state = int((df.index >= latched_at).sum())
    cal_days_in_state = int((df.index[-1] - latched_at).days)

    # A pending flip: raw has diverged from latched but has not yet run its course.
    pending = None
    if last["raw"] != state:
        run = 0
        for r in reversed(df["raw"].tolist()):
            if r == last["raw"]:
                run += 1
            else:
                break
        pending = {"state": last["raw"], "label": REGIME_LABEL[last["raw"]],
                   "days": min(run, d["latch_days"]), "need": d["latch_days"]}

    nearest = min(abs(d["tighten"] - chg), abs(d["ease"] - chg))

    # The live column plus the two dimmed alternates, in rate-direction order.
    def _tint(h):
        return dict(h, color=c.TICKER_COLOR.get(h["ticker"], c.TICKER_COLOR_DEFAULT))

    portfolios = c.PORTFOLIOS
    holdings = [dict(_tint(h), state=_holding_state(h)) for h in portfolios[state]]
    alternates = [{"state": r, "label": REGIME_LABEL[r], "color": REGIME_COLOR[r],
                   "holdings": [_tint(h) for h in portfolios[r]]}
                  for r in REGIME_ORDER if r != state]

    return {
        "ok": True,
        "state": state,
        "label": REGIME_LABEL[state],
        "color": REGIME_COLOR[state],
        "rate": round(float(last["rate"]), 2),
        "chg": round(chg, 3),
        "to_tighten": round(d["tighten"] - chg, 3),   # how far chg must RISE
        "to_ease": round(d["ease"] - chg, 3),         # how far chg must FALL (negative)
        "nearest_pp": round(nearest, 3),
        "near": bool(nearest <= d["near_pp"]),
        "latched_on": latched_on,
        "days_in_state": days_in_state,
        "cal_days_in_state": cal_days_in_state,
        "pending": pending,
        "holdings": holdings,
        "alternates": alternates,
        "asof": df.index[-1].date().isoformat(),
        "latch_days": d["latch_days"],
        "near_pp": d["near_pp"],
        # The series' short name and the lookback travel in the payload so the
        # frontend can caption the rate without naming the instrument, or stating the
        # window, in a committed file.
        "rate_label": d["rate_label"],
        "lookback_months": d["lookback_months"],
        "stale": False,
    }


def _with_day_moves(payload):
    """Attach live technicals to EVERY holding — the live column and the alternates.

    WAS LIVE-ONLY (changed 2026-08-15). A vehicle sitting in a column the dial has not
    selected still has a price, a day move and a 50/200 reading; withholding them made an
    alternate's detail block render as a column of dashes, which reads as broken rather
    than as unallocated. Which column is live is an ALLOCATION fact, and the column itself
    already carries it. Symbols are deduped (QQQ is in two columns) and `_tech` batches
    behind its own 60s quote cache, so covering the alternates costs a couple of extra
    symbols on one call, not a call per column.

    Done HERE and not in compute_dial() on purpose: compute_dial's result is cached
    for six hours, and a six-hour-old quote rendered as "today's move" would be
    wrong in a way that looks right. Quotes ride their own 60s cache instead.
    """
    if not payload.get("ok"):
        return payload

    alts = payload.get("alternates") or []
    symbols = {h["symbol"] for h in payload["holdings"]}
    for a in alts:
        symbols.update(h["symbol"] for h in (a.get("holdings") or []))
    tech = _tech(sorted(symbols))

    blank = {"price": None, "day_pct": None, "s50": None, "s200": None,
             "gap_pct": None, "depth_pct": None, "era": None,
             "era_days": None, "era_days_capped": False}

    def _fill(h):
        return dict(h, **(tech.get(h["symbol"]) or blank))

    return dict(payload,
                holdings=[_fill(h) for h in payload["holdings"]],
                alternates=[dict(a, holdings=[_fill(h) for h in (a.get("holdings") or [])])
                            for a in alts])


def get_dial():
    """TTL-cached dial. Follows the price_history cache rules: never cache a
    failure, and if a fresh pull throws while a stale payload exists, serve the
    stale one flagged rather than blanking the panel."""
    with _cache_lock:
        fresh = _cache["payload"] and (time.time() - _cache["at"] < CACHE_TTL_SECONDS)
        if fresh:
            return _with_day_moves(_cache["payload"])
        try:
            payload = compute_dial()
            _cache["payload"], _cache["at"] = payload, time.time()
            return _with_day_moves(payload)
        except Exception as e:
            print(f"[STRATEGY] dial pull failed: {type(e).__name__}: {e}")
            if _cache["payload"]:
                return _with_day_moves(dict(_cache["payload"], stale=True))
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@bp.route('/get_strategy_dial', methods=['GET'])
def get_strategy_dial():
    return jsonify(get_dial())


@bp.route('/get_ticker_strategy/<ticker>', methods=['GET'])
def get_ticker_strategy(ticker):
    """One ticker's strategy state, INDEPENDENT of what the dial has allocated.

    WHY THIS EXISTS. `_holding_state()` is the only other way strategy state reaches the
    UI, and it runs over the holdings the dial has made live — so a registered strategy on
    a name the current regime does not hold could not be asked about itself at all. XLE off
    a tightening dial is exactly that: the system has a live reading every day, and the
    board could only show it in one regime out of three. Allocation and state are different
    questions and this separates them.

    Serves the CONTRACT dict unchanged, plus the ticker's own color so the deep-dive can
    paint `state` the same way the sidebar does. A ticker with no registered strategy is a
    200 with `has_strategy: false`, not a 404 — "nothing to show here" is a normal answer
    for most of the watchlist, and a 404 would put an error in the console on every click.
    """
    t = (ticker or "").upper()
    try:
        from engine.qqq_system import BY_TICKER, get_state
        key = BY_TICKER.get(t)
        if not key:
            return jsonify({"ok": True, "has_strategy": False, "ticker": t})
        c = cfg()
        return jsonify(dict(
            get_state(key),
            has_strategy=True, ticker=t, strategy=key,
            color=c.TICKER_COLOR.get(t, c.TICKER_COLOR_DEFAULT),
        ))
    except Exception as e:
        print(f"[STRATEGY] {t} ticker-strategy failed: {type(e).__name__}: {e}")
        # Degrade to the unwired shape rather than a 500 — the deep-dive treats this
        # exactly like a ticker with no strategy and simply shows nothing.
        return jsonify({"ok": False, "has_strategy": False, "ticker": t,
                        "error": f"{type(e).__name__}: {e}"})
