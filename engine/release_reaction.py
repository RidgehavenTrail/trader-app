"""Measure the market's reaction to a scheduled data release, from price alone.

WHY THIS EXISTS (2026-08-13, session 44). The 08:30 PPI print was released, indexed
nowhere search could reach it for the better part of an hour, and the macro briefing
consequently spent that hour saying "Markets Await PPI Data" -- with `data_releases`
simultaneously recording "RELEASED figure not found". The tape, meanwhile, had already
answered: ZN bid, ^TNX -0.235%, equities firm. The reaction is an INDEPENDENT path to
the fact the briefing was missing, and it needs no search index to be legible.

WHAT THIS IS NOT. It does not tell you the figure. It tells you what the market did
with the figure, which on a shock print is the part you needed first anyway.

MEASURED FEED LAG (2026-08-13 09:03 ET, live probe -- do not assume, this drives the
whole schedule):

    SPY / QQQ            ~0 min   real time, pre-market bars from 04:00, max gap 2m
    ES=F NQ=F ZN=F GC=F  ~11 min  continuous overnight, but ELEVEN MINUTES STALE
    ^TNX / ^VIX          ~16 min  and ^TNX has ~29 pre-market bars, starting 08:20

Two consequences, both load-bearing:
  1. At release+5 only the ETFs can be read at all. The futures legs are not "flat",
     they are NOT YET PUBLISHED -- and those are different answers. See PENDING below.
  2. ^TNX is the wrong pre-market rates instrument despite being the one the macro
     briefing already pulls. ZN=F is the real one.

PENDING IS NOT ZERO. The session-43 `AV_UNAVAILABLE` lesson, applied here: a leg whose
bars have not arrived yet must never be reported as no reaction. A quota failure that
read as "No news surfaced today." poisoned a whole card; a feed lag that reads as
"muted" would poison a whole print. Every leg carries an explicit status.

SELECT BARS BY TIMESTAMP, NEVER BY POSITION. `period="2d", interval="1m"` returns TWO
sessions -- verified live for all eight instruments probed. Summing or `.iloc[-N:]`-ing
that frame is exactly what produced the phantom NVDA 3.2x volume spike in session 43.
Every lookup here filters on the index.
"""

import argparse
from datetime import datetime, timedelta

import yfinance as yf

try:
    from engine.common import ET
except Exception:                                    # standalone / CLI use
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except Exception:
        import pytz
        ET = pytz.timezone("America/New_York")


# --- What we watch ------------------------------------------------------------
# `kind` selects the magnitude floors below. `lag_min` is the MEASURED publication
# lag and is what makes a leg legitimately PENDING rather than flat at +5.
INSTRUMENTS = [
    {"symbol": "SPY",  "label": "S&P 500 (SPY)",     "kind": "equity", "lag_min": 1},
    {"symbol": "QQQ",  "label": "Nasdaq 100 (QQQ)",  "kind": "equity", "lag_min": 1},
    {"symbol": "ZN=F", "label": "10y note (ZN)",     "kind": "rates",  "lag_min": 12},
    {"symbol": "GC=F", "label": "Gold (GC)",         "kind": "metals", "lag_min": 12},
]

# Offsets after the release, in minutes. +5 is the ALERT read -- the user's call
# (2026-08-13): "it's ok if the answer 5 minutes in is muted; sometimes the reaction
# is violent and that can be caught immediately." The later offsets refine it; today's
# PPI moved almost nothing by +5 and accumulated over the following half hour, so a
# single early sample is an alert, not a verdict.
OFFSETS_MIN = (5, 15, 30)

# A mark is only honoured if a bar exists within this many minutes of it. Prevents a
# stale carry-forward price from silently standing in for a bar that does not exist.
BAR_TOLERANCE_MIN = 3

# Minimum pre-release bars before that morning's volatility is trusted as a yardstick.
MIN_BASELINE_BARS = 30

# --- The bands (user, 2026-08-13) ---------------------------------------------
# Absolute magnitude decides the band. Sigma was tried first and rejected: it inverted
# on the first live run (SPY at 3.3 sigma grading below QQQ at 1.9 sigma, because a
# dead-quiet pre-market makes 9bp look enormous). Statistical rarity is not what the
# question "did this move the market" is asking.
#
#     band 1   |move| < 0.25%        tepid
#     band 2   0.25% - 0.50%         moved the market
#     band 3   |move| >= 0.50%       significant mover
#
# NAMING IS DELIBERATELY NOT DONE HERE. Python emits the band NUMBER and its numeric
# boundaries; the model supplies the words. Same rule as every other card in the
# dashboard -- display copy is the model's distilled read, never the engine's narration.
BAND_EDGES_PCT = (0.25, 0.50)

# The edges above are stated in EQUITY terms -- "the market" means SPY/QQQ. A note
# future whose median full day is 0.180% can never reach 0.50% in a 30-minute window,
# so the same numbers on that leg would grade every rates reaction tepid forever.
#
# Non-equity legs therefore scale by their MEASURED typical daily range relative to SPY
# (yfinance 1y daily, median |close-to-close|, probed 2026-08-13):
#
#     SPY 0.481%   QQQ 0.708% (1.47x)   ZN=F 0.180% (0.37x)   GC=F 0.981% (2.04x)
#
# so the bands mean the same THING on each leg rather than carrying the same number.
# Set SCALE_BANDS_BY_INSTRUMENT = False for one uniform band set on every leg.
SCALE_BANDS_BY_INSTRUMENT = True
INSTRUMENT_SCALE = {"SPY": 1.00, "QQQ": 1.47, "ZN=F": 0.37, "GC=F": 2.04}


def _robust_sigma(values):
    """1.4826 * MAD -- a stdev that one overnight spike cannot inflate.

    The plain stdev of pre-release returns is dominated by whatever single jump the
    overnight session happened to contain, which would flatten every subsequent
    reaction into "less than one sigma".
    """
    vals = sorted(values)
    if not vals:
        return None
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    devs = sorted(abs(v - med) for v in vals)
    mad = devs[n // 2] if n % 2 else (devs[n // 2 - 1] + devs[n // 2]) / 2.0
    return 1.4826 * mad if mad > 0 else None


def _fetch_session(symbol, day):
    """1m bars for `day` only, in ET, selected BY TIMESTAMP.

    Returns (bars, newest_overall) where bars is a list of (datetime, close) for that
    calendar day and newest_overall is the newest bar in the whole response -- the
    latter is what tells us the feed's true position, and it is reported even when the
    day filter comes back empty.
    """
    df = yf.Ticker(symbol).history(period="2d", interval="1m", prepost=True)
    if df is None or df.empty:
        return [], None
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx = idx.tz_convert(ET)
    closes = [float(c) for c in df["Close"].tolist()]
    pairs = list(zip(idx.to_pydatetime(), closes))
    newest = pairs[-1][0] if pairs else None
    return [(t, c) for t, c in pairs if t.date() == day], newest


def _close_at(bars, mark):
    """Last close at or before `mark`, or None if no bar is within tolerance.

    The tolerance is the difference between "the price then" and "the last price we
    happen to have", which on a thin pre-market instrument can be an hour apart.
    """
    prior = [(t, c) for t, c in bars if t <= mark]
    if not prior:
        return None
    t, c = prior[-1]
    return c if (mark - t) <= timedelta(minutes=BAR_TOLERANCE_MIN) else None


def _edges_for(symbol):
    """This leg's band edges, in percent."""
    lo, hi = BAND_EDGES_PCT
    if not SCALE_BANDS_BY_INSTRUMENT:
        return lo, hi
    k = INSTRUMENT_SCALE.get(symbol, 1.0)
    return lo * k, hi * k


def _band(pct, symbol):
    """-> (band_number, 'lo-hi%' description). Magnitude only; sigma is context."""
    lo, hi = _edges_for(symbol)
    mag = abs(pct)
    if mag >= hi:
        return 3, f">={hi:.2f}%"
    if mag >= lo:
        return 2, f"{lo:.2f}-{hi:.2f}%"
    return 1, f"<{lo:.2f}%"


def measure_release_reaction(release_dt, now=None, offsets_min=OFFSETS_MIN,
                             instruments=None):
    """What did the tape do to the release at `release_dt` (an ET datetime)?

    Returns a JSON-serialisable dict. Every leg carries a `status`:

        ok       measured -- a real bar on each side of the window
        pending  the feed has not published far enough yet (see lag_min). NOT flat.
        stale    bars exist but none within tolerance of a mark; thin instrument
        error    the fetch itself failed

    The overall `band` is the highest band among `ok` legs at the newest offset that
    has any, and is None when nothing is readable yet -- deliberately, so a caller
    cannot mistake an unread release for an unmoved one.
    """
    now = now or datetime.now(ET)
    instruments = instruments or INSTRUMENTS
    day = release_dt.date()

    out = {
        "release_at": release_dt.isoformat(),
        "measured_at": now.isoformat(),
        "minutes_since_release": round((now - release_dt).total_seconds() / 60.0, 1),
        "offsets_min": list(offsets_min),
        "legs": [],
        "band": None,
        "readable_legs": 0,
        "pending_legs": 0,
    }

    for inst in instruments:
        sym, kind = inst["symbol"], inst["kind"]
        leg = {"symbol": sym, "label": inst["label"], "kind": kind,
               "status": "ok", "baseline": None, "sigma_pct": None,
               "feed_newest": None, "feed_lag_min": None, "moves": {}}
        try:
            bars, newest = _fetch_session(sym, day)
        except Exception as e:
            leg["status"] = "error"
            leg["note"] = f"{type(e).__name__}: {e}"
            out["legs"].append(leg)
            continue

        if newest is not None:
            leg["feed_newest"] = newest.isoformat()
            leg["feed_lag_min"] = round((now - newest).total_seconds() / 60.0, 1)
        if not bars:
            leg["status"] = "pending" if newest else "error"
            leg["note"] = "no bars dated the release session yet"
            out["legs"].append(leg)
            continue

        base = _close_at(bars, release_dt)
        if base is None:
            leg["status"] = "stale"
            leg["note"] = "no bar within tolerance of the release minute"
            out["legs"].append(leg)
            continue
        leg["baseline"] = round(base, 4)

        # That morning's own volatility, over each measured horizon, from bars BEFORE
        # the release only -- the yardstick must not contain the event it is judging.
        pre = [(t, c) for t, c in bars if t <= release_dt]

        newest_bar_t = bars[-1][0]
        any_ok = False
        for off in offsets_min:
            mark = release_dt + timedelta(minutes=off)
            entry = {"status": "pending", "pct": None, "z": None, "band": None}

            if newest_bar_t < mark - timedelta(minutes=BAR_TOLERANCE_MIN):
                entry["note"] = (f"feed reaches {newest_bar_t:%H:%M}; "
                                 f"needs {mark:%H:%M}")
                leg["moves"][f"+{off}m"] = entry
                continue

            post = _close_at(bars, mark)
            if post is None:
                entry["status"] = "stale"
                leg["moves"][f"+{off}m"] = entry
                continue

            pct = (post - base) / base * 100.0
            horizon = [
                (c2 - c1) / c1 * 100.0
                for (_, c1), (_, c2) in zip(pre, pre[off:])
                if c1
            ] if len(pre) >= MIN_BASELINE_BARS + off else []
            sigma = _robust_sigma(horizon) if horizon else None
            band, band_range = _band(pct, sym)
            # Sigma is retained as CONTEXT, not as the classifier -- it is the only
            # thing that distinguishes "small because nothing happened" from "small
            # because this instrument barely moves", and that is worth carrying even
            # though it no longer decides the band.
            z = (abs(pct) / sigma) if sigma else None

            entry.update({
                "status": "ok",
                "price": round(post, 4),
                "pct": round(pct, 4),
                "band": band,
                "band_range_pct": band_range,
                "sigma_pct": round(sigma, 4) if sigma else None,
                "z": round(z, 2) if z else None,
                "direction": "up" if pct > 0 else ("down" if pct < 0 else "flat"),
            })
            leg["moves"][f"+{off}m"] = entry
            leg["sigma_pct"] = entry["sigma_pct"]
            any_ok = True

        # The LATEST tick, which is what a reader actually wants quoted. A windowed
        # percentage change is something they can read off a chart; the current level
        # is the thing a briefing can tell them (user, 2026-08-13).
        leg["latest"] = {"price": round(bars[-1][1], 4),
                         "at": bars[-1][0].strftime("%H:%M")}

        if not any_ok:
            leg["status"] = "pending"
        out["legs"].append(leg)

    ok_legs = [l for l in out["legs"] if any(
        m.get("status") == "ok" for m in l["moves"].values())]
    out["readable_legs"] = len(ok_legs)
    out["pending_legs"] = sum(1 for l in out["legs"] if l["status"] == "pending")

    # Highest band reached, at the newest offset anything can be read at. Reported as a
    # NUMBER; the caller (and ultimately the model) supplies the language.
    best, best_off, driver = None, None, None
    for off in offsets_min:
        key = f"+{off}m"
        hits = [(l["moves"][key]["band"], l["label"]) for l in ok_legs
                if l["moves"].get(key, {}).get("status") == "ok"]
        if hits:
            best, driver = max(hits, key=lambda h: h[0])
            best_off = off
    out["band"] = best
    out["band_at_offset_min"] = best_off
    out["band_driver"] = driver
    return out


def format_for_prompt(reaction):
    """Compact text block for the briefing prompt.

    The model narrates numbers PYTHON computed; it never supplies one. Same split as
    the newsletter path -- model owns prose, Python owns anything computable.
    """
    if not reaction or not reaction.get("legs"):
        return None

    # DELIBERATELY TERSE. An earlier version handed over every offset, percentage and
    # sigma multiple, and the model dutifully wrote "rising 0.101% over 30 minutes in a
    # market-shifting move" into a briefing. A windowed percentage is something the
    # reader can get off a chart; what a briefing can tell them is the CURRENT level,
    # and only when the move was big enough to be worth the sentence at all (user,
    # 2026-08-13). So the measurement's job here is a GATE, not copy.
    band = reaction.get("band")
    latest = "; ".join(
        f"{leg['label']} {leg['latest']['price']:,.2f} @{leg['latest']['at']}"
        for leg in reaction["legs"] if leg.get("latest"))

    if band is None:
        return (
            "PRICE ACTION around the 08:30 ET window: NOT YET READABLE - no instrument "
            "has published bars past the window yet. This is a data-timing state, NOT "
            "an absence of reaction; do not describe the market as unmoved, and do not "
            "mention a reaction at all."
        )

    movers = sorted({
        leg["label"] for leg in reaction["legs"]
        for m in leg["moves"].values()
        if m.get("status") == "ok" and (m.get("band") or 0) >= 2
    })

    if band == 1:
        verdict = ("ROUTINE - everything stayed inside its normal early-session range. "
                   "DO NOT mention a market reaction to the release; there was nothing "
                   "worth reporting.")
    else:
        size = "LARGE" if band >= 3 else "NOTABLE"
        verdict = (
            f"{size} - a real move, in: {', '.join(movers)}. Mention it in ONE short "
            "clause, and report the CURRENT LEVEL (from the latest ticks below or the "
            "market-data block) - never a percentage change, never a time span, never "
            "a sigma multiple. The SHAPE to follow is 'the 10-year rallied, yield down "
            "to <the current level>'; the shape to avoid is 'rising <x>% over 30 "
            "minutes'. Use the real numbers given to you, never a number from this "
            "instruction."
        )

    return (
        "PRICE ACTION around the 08:30 ET window, measured (for your judgement, not "
        "for quoting):\n"
        f"  Verdict: {verdict}\n"
        f"  Latest ticks: {latest}\n"
        "If no release printed at 08:30 today, this is ordinary early trading and must "
        "not be called a reaction. Never infer the released FIGURE from the price move."
    )


def _parse_when(date_s, time_s):
    d = datetime.strptime(date_s, "%y%m%d").date() if date_s else datetime.now(ET).date()
    hh, mm = (int(x) for x in time_s.split(":"))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Measure a release reaction from the tape.")
    ap.add_argument("--date", help="release date YYMMDD (default today ET)")
    ap.add_argument("--time", default="08:30", help="release time ET HH:MM (default 08:30)")
    ap.add_argument("--json", action="store_true", help="dump the raw dict")
    args = ap.parse_args()

    rel = _parse_when(args.date, args.time)
    res = measure_release_reaction(rel)
    if args.json:
        import json
        print(json.dumps(res, indent=2))
    else:
        band = f"band {res['band']} of 3" if res["band"] else "NOT YET READABLE"
        print(f"release {rel:%Y-%m-%d %H:%M %Z} | measured "
              f"{res['minutes_since_release']:.0f}m later | {band}\n")
        print(format_for_prompt(res))
