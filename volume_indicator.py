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


def compute_volume_ratio(stock):
    """Fetch + compute the live 2x-volume ratio for a yfinance Ticker object.

    Reuses the caller's `stock` (same yfinance session). Returns the ratio as a
    float, or None on any data gap. Never raises — a data problem must not abort
    the caller's per-ticker pipeline.
    """
    try:
        daily = stock.history(period="3mo", prepost=False)
        if daily.empty or 'Volume' not in daily:
            return None
        daily_vols = [float(v) for v in daily['Volume'].tolist()]
        if len(daily_vols) < 2:
            return None
        # The last daily bar is TODAY's partial bar during market hours; its
        # Volume duplicates the intraday sum below and must be dropped from the
        # baseline so today doesn't contaminate its own average.
        baseline_vols = daily_vols[:-1]

        intraday = stock.history(period="1d", interval="1m", prepost=False)
        if intraday.empty or 'Volume' not in intraday:
            return None

        # period="1d" is a REQUEST, not a guarantee. yfinance serves 1-minute data out
        # of a rolling ~7-day window and has been observed returning SEVERAL sessions
        # for this call. Summing them turns "volume so far today" into a multi-day
        # total and inflates the ratio by however many sessions came back.
        #
        # Observed live 2026-08-12: NVDA reported 3.2x and TSLA 3.5x in the same sweep,
        # on a day both traded BELOW average (true ratios 0.64x and 0.60x). The implied
        # cumulatives were ~4.4 and ~5.4 full days — i.e. about five sessions each.
        # Both fired 1-sigma-plus-volume cards and one burned a news pull.
        #
        # Keep only the LAST session present. Slicing on the last date rather than on
        # the wall clock also means stale data fails SAFE: an all-yesterday response
        # yields yesterday's full volume (~1x, no trigger) instead of a false spike.
        try:
            bar_dates = intraday.index.date
            last_session = bar_dates[-1]
            n_sessions = len(set(bar_dates))
            if n_sessions > 1:
                intraday = intraday[bar_dates == last_session]
                print(f"[VOLUME] 1m fetch returned {n_sessions} sessions for a period='1d' "
                      f"request — trimmed to {last_session} ({len(intraday)} bars)")
        except Exception:
            pass          # no usable index -> fall through and sum what we have

        cumulative_today = float(intraday['Volume'].sum())

        return volume_ratio_from_data(baseline_vols, cumulative_today)
    except Exception:
        return None
