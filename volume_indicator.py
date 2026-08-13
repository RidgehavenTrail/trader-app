"""2x Volume Indicator — see .claude/rules/turtle-volume-indicators.md.

Fires when a ticker's cumulative REGULAR-SESSION volume so far today exceeds a
multiple (default 2x) of its 50-day average daily regular-session volume.

Deliberately NOT pro-rated for time-of-day — realistically a mid-afternoon-or-
later trigger most days, and that is intentional, not a bug. Regular-hours
volume only for BOTH the numerator (today's cumulative) and the baseline
average — pre-market and after-hours volume are excluded entirely, consistent
with yfinance's regular-session `Volume` field (not `fast_info`/pre-post).

The math (`volume_ratio_from_data`) is split from the fetch (`compute_volume_ratio`)
so the trigger logic can be unit-tested offline with injected arrays.
"""
from datetime import datetime

try:
    from engine.common import ET
except Exception:                                    # standalone / unit-test use
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except Exception:
        import pytz
        ET = pytz.timezone("America/New_York")

VOLUME_TRIGGER_MULTIPLE = 2.0
VOLUME_BASELINE_DAYS = 50


def volume_ratio_from_data(baseline_daily_volumes, cumulative_today):
    """Pure math: today's cumulative regular-session volume ÷ trailing average
    daily regular-session volume.

    baseline_daily_volumes: iterable of PRIOR full-day regular-session volumes
      (most recent last); today's partial bar must NOT be included. The last
      VOLUME_BASELINE_DAYS positive values are averaged.
    cumulative_today: regular-session volume accumulated so far today.

    Returns the ratio as a float, or None if no usable baseline can be formed.
    """
    vols = [float(v) for v in baseline_daily_volumes if v is not None and v > 0]
    if not vols:
        return None
    window = vols[-VOLUME_BASELINE_DAYS:]
    baseline = sum(window) / len(window)
    if baseline <= 0:
        return None
    return cumulative_today / baseline


def volume_check_slot(now):
    """Identify the current :15/:45 volume-check window as a once-per-window key,
    or None when outside a window.

    Windows are [:15,:30) and [:45,:60) each hour, producing checks at :15 and :45
    (9:45, 10:15, 10:45, 11:15, ...) — the spec cadence. Each window is wide enough
    that a 60s poll never misses it; the caller fires the sweep once per distinct
    key. Pre-9:45 windows never fire because volume is only swept in the `open`
    state (09:30+), so the first key of the day is the :45 of hour 9.
    """
    m = now.minute
    if 15 <= m < 30:
        return (now.date(), now.hour, 15)
    if 45 <= m < 60:
        return (now.date(), now.hour, 45)
    return None


def compute_volume_ratio(stock, today=None):
    """Fetch + compute the live 2x-volume ratio for a yfinance Ticker object.

    Reuses the caller's `stock` (same yfinance session). Returns the ratio as a
    float, or None on any data gap. Never raises — a data problem must not abort
    the caller's per-ticker pipeline.

    ONE FETCH, ONE SOURCE. The last row of the daily frame IS today's cumulative
    regular-session volume, so it serves as both the numerator and (once dropped)
    the thing excluded from the baseline. This function used to fetch 1-minute bars
    separately and sum them to reconstruct that same number — a second network call
    per ticker per sweep, computing a value it already had in hand.

    WHY THE 1m PATH IS GONE (2026-08-13, measured, not inferred). 33 paired samples
    of both sources 45s apart, 3 of them corrupt (~9%):

        12:44:16  NVDA  195 bars  daily  52,781,066   1m 447,657,208   8.48x
        12:44:16  TSLA  195 bars  daily  15,516,464   1m  62,006,573   4.00x
        12:45:01  NVDA  195 bars  daily  52,850,045   1m  52,848,190   1.00x

    On every corrupt sample the BAR COUNT was correct and identical to the clean
    samples either side, one session, no duplicates — the per-bar Volume VALUES were
    simply inflated, transiently, clearing within one sample. It hit two tickers in
    the same instant while a third stayed clean.

    That matters because the previous guard trimmed multi-SESSION responses, and this
    failure has one session and the right number of bars: the guard could never have
    seen it. The session-43 note attributing NVDA's 3.2x to "about five sessions" was
    inferred from the implied cumulative, never observed; a corrupt 1m read on NVDA
    works out to 3.18x, which fits the same evidence without any extra sessions.

    THE DAILY BAR WAS CORRECT AND MONOTONIC IN ALL 33 SAMPLES, including during both
    corruption events, on the very tickers that were corrupt. It cannot express this
    fault at all: one row, one session, nothing summed.

    NOT GATED, deliberately (user, 2026-08-13). A confirmation gate — reject a 2x
    read until a later sample confirms it at or above the same level, since cumulative
    session volume cannot fall — was designed and left unbuilt: this had not surfaced
    in a month, and the source switch removes the observed fault rather than defending
    against it. If inflation ever appears in the DAILY bar, that gate is the fix, and
    the invariant it rests on needs no threshold tuning.
    """
    try:
        daily = stock.history(period="3mo", prepost=False)
        if daily.empty or 'Volume' not in daily:
            return None
        daily_vols = [float(v) for v in daily['Volume'].tolist()]
        if len(daily_vols) < 2:
            return None

        # FAIL CLOSED on a stale frame. Outside market hours, on a holiday, or against
        # a lagging feed the last bar is a PRIOR session — whose full-day volume would
        # read ~1x and, on a genuinely heavy prior session, could re-fire yesterday's
        # trigger. No bar for today means no reading, which is not the same as a zero.
        today = today or datetime.now(ET).date()
        if daily.index[-1].date() != today:
            return None

        # The last bar is today's PARTIAL bar: the numerator. Everything before it is
        # the baseline — today must not contaminate its own average.
        return volume_ratio_from_data(daily_vols[:-1], daily_vols[-1])
    except Exception:
        return None
