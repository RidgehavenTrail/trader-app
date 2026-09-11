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
from datetime import date, datetime, timedelta

import pandas as pd
from flask import Blueprint, jsonify

from engine.common import ET
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
# THE DIAL CACHE KEYS OFF THE OBSERVATION DATE, NOT A CLOCK (2026-08-27).
#
# It was a rolling 6h, on the reasoning that "the series prints once a business day".
# True, but a rolling window is not aligned to the print: a cache built shortly before
# FRED posts serves the PREVIOUS day's figure for six more hours, and the frontend poll
# just re-reads the same cached answer. That is exactly what happened -- a panel showing
# 3.71 / +0.12 against a live 3.70 / +0.100, with no way to tell from the screen.
#
# The series is T+1: DTB3 for date D publishes on D+1. So the question is not "how old
# is this payload" but "has the latest observation that COULD exist arrived yet":
#   caught up  -> asof is the most recent business day. Nothing newer can print today;
#                 hold it until the ET date rolls (with a 24h ceiling as a backstop).
#   behind     -> today's print has not landed, or a holiday moved it. Re-check, but
#                 no more often than the floor, so waiting never becomes hammering.
# A holiday leaves it "behind" all day and re-checking on the floor, which is bounded
# and self-heals the moment a print appears -- deliberately preferred to a holiday
# calendar this file would then have to maintain.
DIAL_RECHECK_SECONDS = 900        # 15 min — floor while a print has not landed
DIAL_MAX_AGE_SECONDS = 24 * 3600  # backstop, so nothing can live forever on any path
QUOTE_TTL_SECONDS = 60            # intraday % change
# THE DIAL'S LIVE TIP (user, 2026-09-10: "the chart can be built daily — I just want the
# intraday updates for situational awareness"). Same split `_with_day_moves` already
# makes and for the same stated reason: compute_dial()'s result is cached long because
# everything in it moves at most daily (the history, the regime, the latch), so a live
# number must NOT ride that cache or it renders a stale reading as "now".
#
# Switching the source to ^IRX removed the two-day lag but did not make the panel move:
# `_dial_caught_up` returns True the moment `asof` reaches today, which pins the payload
# for DIAL_MAX_AGE_SECONDS — its docstring's "nothing newer can print today" was true of
# a T+1 FRED series and is false of a live quote. And irx_local's cache counts a tail
# within four days as current, so re-polling it would return the same pickle all day.
# Hence a separate, deliberately tiny fetch for the tip alone.
DIAL_LIVE_TTL_SECONDS = 60
_dial_live_lock = threading.Lock()
_dial_live = {"symbol": None, "rate": None, "at": 0.0}
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
    from stoplight.sources.fred import lookback_base, lookback_change
    from stoplight.sources.rates import rate_series

    d = _dial()
    # Dispatched on the configured symbol — `^IRX` (live, cached, DTB3-backed) or a
    # plain FRED id. The config alone decides; this file learns no source vocabulary.
    s = rate_series(d["series_id"])
    # The anchor now lives in fred.lookback_change, shared with the Charts-tab dial so
    # the two surfaces cannot state different 6-month changes for the same print.
    # Behaviour here is unchanged — this IS the convention that moved.
    chg = lookback_change(s, d["lookback_months"])     # rounded to the quote's 3 decimals
    base = lookback_base(s, d["lookback_months"])      # exact -- the live change reads it
    df = pd.DataFrame({"rate": s.to_numpy(), "chg": chg.to_numpy(), "base": base.to_numpy()},
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
           dark    50 SMA <= 200 SMA. The ERA is dark; the CROSS that starts it is a
                   death cross (user, 2026-08-27). This path feeds holdings with NO
                   registered strategy, and it must agree with qqq_system._era(): the
                   sidebar picks `st.era` for a wired name and `h.era` for an unwired
                   one, so two spellings here would colour MO and GLD differently for
                   the same regime.
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
    era = "golden" if bool(gold.iloc[-1]) else "dark"

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


def _dial_live_rate(symbol):
    """Latest quote for an intraday dial symbol, or None when it has no live tip.

    Only a `^` symbol has one — a FRED id publishes once a day and its cached payload
    is already the whole truth. Never raises: the dial must render on the daily figure
    if the quote is unreachable, which is the same rule the rest of this file follows.
    """
    if not str(symbol or "").startswith("^"):
        return None
    now = time.time()
    with _dial_live_lock:
        if (_dial_live["symbol"] == symbol and _dial_live["rate"] is not None
                and now - _dial_live["at"] < DIAL_LIVE_TTL_SECONDS):
            return _dial_live["rate"]
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="5d")["Close"].dropna()
        v = float(h.iloc[-1]) if len(h) else None
    except Exception as e:
        print(f"[STRATEGY] dial live quote failed: {type(e).__name__}: {e}")
        v = None
    if v is None:
        with _dial_live_lock:
            return _dial_live["rate"]          # last good; never a blank on one bad pull
    with _dial_live_lock:
        _dial_live.update(symbol=symbol, rate=v, at=now)
    return v


def _with_live_rate(payload):
    """Attach the live rate and the change it implies, WITHOUT moving the regime.

    THE LATCH DOES NOT MOVE INTRADAY, and that is a deliberate choice rather than a
    limitation: a flip needs `latch_days` consecutive PRINTS, which is a daily concept,
    and letting an intraday wiggle repaint the board would be exactly the whipsaw the
    latch exists to prevent. So `label`, `state` and `days_in_state` stay on the settled
    daily figures; `rate_live` / `chg_live` are situational awareness beside them.

    The six-month baseline is fixed for the day, so the live change needs no second
    pull: the live quote is measured against the exact baseline the daily frame carries
    (`chg_base`) and rounded once, exactly as the daily change is.
    """
    if not payload.get("ok"):
        return payload
    d = _dial()
    v = _dial_live_rate(d.get("series_id"))
    if v is None:
        return payload
    # THE BASELINE IS EXACT, NOT RECONSTRUCTED (2026-09-11). This was `rate - chg` off the
    # payload -- but the payload's rate is rounded to 2 decimals for display, which put up
    # to +/-0.005 of error into the live change: coarser than the three decimals the
    # regime is decided on, and enough to show a reading on the wrong side of the line.
    # A payload cached before the exact baseline existed gets no live figures rather than
    # approximate ones.
    base = payload.get("chg_base")
    if base is None:
        return payload
    from stoplight.sources.fred import change_from
    out = dict(payload)
    out["rate_live"] = round(v, 3)
    out["chg_live"] = change_from(v, base)
    out["live_at"] = datetime.now(ET).isoformat(timespec="seconds")
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
    # NO state=... here (moved to serve time, 2026-08-21). It used to be baked into
    # this payload, which the dial caches for SIX HOURS — so the one time a strategy
    # build failed at dial-build time (^IRX stubbed at engine start), the failure
    # froze inside an otherwise-successful payload and the sidebar showed QQQ as
    # "unavailable" for the rest of the night while the strategy cache had long since
    # healed. "Never cache a failure" could not fire: the DIAL build succeeded; the
    # failure rode in as data. Same trap _with_day_moves documents for quotes —
    # anything time-sensitive baked into a six-hour payload goes wrong in a way that
    # looks right. Holding state now resolves on every serve (see _with_day_moves),
    # riding get_state's own per-strategy TTL cache — a dict lookup when warm.
    holdings = [_tint(h) for h in portfolios[state]]
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
        # The exact six-month baseline behind `chg`. The live tip measures the live quote
        # against THIS, never against `rate - chg`: `rate` above is rounded for display.
        "chg_base": float(last["base"]),
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

    # Holding STATE resolves here, at serve time, for the LIVE column only — the same
    # rule as quotes and for the same reason (see compute_dial's note, 2026-08-21: a
    # strategy failure baked into the six-hour dial cache outlived its own recovery
    # by six hours). get_state is TTL-cached per strategy, so a warm serve is a dict
    # lookup and a recovered strategy is picked up on the next poll. Alternates stay
    # state-free on purpose — their state is fetched ON SELECTION (2026-08-15);
    # resolving it eagerly here would walk 26 years per alternate per cold poll.
    # The observation LAG rides here for the same reason the quotes do: computed inside
    # compute_dial() it would be frozen for six hours and could report "caught up" after
    # the day had rolled underneath it — wrong in the way that looks right.
    return dict(payload,
                asof_lag_bdays=_asof_lag_bdays(payload),
                holdings=[dict(_fill(h), state=_holding_state(h))
                          for h in payload["holdings"]],
                alternates=[dict(a, holdings=[_fill(h) for h in (a.get("holdings") or [])])
                            for a in alts])


def _prev_business_day(d):
    """The latest weekday strictly before `d`. Weekends only — see the cache note on
    why holidays are handled by re-checking rather than by a calendar."""
    x = d - timedelta(days=1)
    while x.weekday() >= 5:
        x -= timedelta(days=1)
    return x


def _dial_caught_up(payload, today=None):
    """Is this payload holding the newest observation that could exist?

    True once `asof` reaches the most recent business day: the series is T+1, so on a
    Thursday the newest possible observation is Wednesday's. Returns False on a missing
    or unparseable `asof` — an unknown date must re-check, never pin the cache open.
    """
    asof = (payload or {}).get("asof")
    if not asof:
        return False
    try:
        seen = date.fromisoformat(str(asof)[:10])
    except ValueError:
        return False
    return seen >= _prev_business_day(today or datetime.now(ET).date())


def _asof_lag_bdays(payload, today=None):
    """How many BUSINESS days behind the newest observation that could exist.

    0 = caught up (the T+1 series has printed everything it can); 1 = today's expected
    print has not landed; 2+ = the release itself is late or a holiday moved it. Returns
    None when `asof` is missing or unparseable — an unknown lag must not render as zero,
    which would assert freshness we cannot prove.

    A NUMBER, never a phrase: the frontend words it. Baking "1 day behind" into the
    payload would freeze an English string into the dial cache and put display copy in a
    module whose job is the regime.

    WHY THIS EXISTS (2026-09-03). FRED went a full business day late on the whole H.15
    set — DTB3, DGS3MO and DFF all stopped at the same date — while Monday and Tuesday
    happened to print the SAME 3.78. The panel showed a correct, current reading that had
    not visibly moved since Monday, and nothing on screen could tell "caught up" from
    "the source is behind". `stale` does not answer it either: that flag means the PULL
    failed, not that the observation is old. The module docstring has said "surface it
    rather than implying the read is same-day" since the dial was built; this is that.
    """
    asof = (payload or {}).get("asof")
    if not asof:
        return None
    try:
        seen = date.fromisoformat(str(asof)[:10])
    except ValueError:
        return None
    newest = _prev_business_day(today or datetime.now(ET).date())
    lag = 0
    while seen < newest:
        newest = _prev_business_day(newest)
        lag += 1
    return lag


def get_dial():
    """Observation-date-keyed dial cache. Follows the price_history cache rules: never
    cache a failure, and if a fresh pull throws while a stale payload exists, serve the
    stale one flagged rather than blanking the panel."""
    with _cache_lock:
        age = time.time() - _cache["at"]
        p = _cache["payload"]
        # Caught up -> hold it; the answer cannot change until the date rolls. Behind ->
        # hold only to the re-check floor, then pull again.
        fresh = bool(p) and age < (DIAL_MAX_AGE_SECONDS if _dial_caught_up(p)
                                   else DIAL_RECHECK_SECONDS)
        if fresh:
            return _with_live_rate(_with_day_moves(_cache["payload"]))
        try:
            payload = compute_dial()
            _cache["payload"], _cache["at"] = payload, time.time()
            return _with_live_rate(_with_day_moves(payload))
        except Exception as e:
            print(f"[STRATEGY] dial pull failed: {type(e).__name__}: {e}")
            if _cache["payload"]:
                return _with_live_rate(_with_day_moves(dict(_cache["payload"], stale=True)))
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
