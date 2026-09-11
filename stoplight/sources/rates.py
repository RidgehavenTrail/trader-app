"""The dial's short-rate series, from whichever source its `series_id` names.

WHY THIS EXISTS (2026-09-10). The dial ran on FRED's DTB3, which is T+1 and in
practice landed two days behind — the board said "1 day behind" and the user could not
see the rate environment as it moved. `^IRX` is the SAME 13-week discount-basis series
quoted live by Yahoo, and it is same-day.

Measured over the 16,485 overlapping days before switching:
  * level        : median  -0.010, sd 0.009  (IRX minus DTB3)
  * 6-month CHANGE: mean   -0.0005, sd 0.0198 -- an offset in the level largely cancels
                    in a difference, which is what the dial actually reads
  * regime call  : differs on 78 days, 0.47%, EVERY one of them at a band edge
  * latched state: identical today; the latch date moves 2026-04-01 -> 2026-04-06

THE STUB IS THE ONE RISK, and it was already solved once. yfinance's ^IRX intermittently
returns a stub covering only the last few weeks (~1 pull in 5; once for a whole evening).
`irx_local.load_irx` -- in the strategy repo, beside the backtests that hit the same wall
-- keeps a local cache, merges whatever a stub does return (its rows are the recent tail,
exactly what an aging cache lacks), and falls back to DTB3 when cache and network together
cannot cover the window. It never writes a FRED result into the ^IRX cache: sources do not
mix silently. This module reuses that rather than writing a second answer to one problem.

The dial's `latch_days` is the second guard: a regime flip needs that many consecutive
prints in the same state, so a single bad print cannot move the board.
"""
import os
import sys

from engine.live_config import BACKTEST_DIR

from .fred import fred_series

# irx_local.py sits one level ABOVE BACKTEST_DIR (which points at .../backtests/live),
# alongside the backtests that share the cache file.
_BACKTESTS = os.path.dirname(BACKTEST_DIR)


def _today_et():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


def _recent_irx():
    """The last month of ^IRX closes, fresh from Yahoo, or None. Never raises."""
    import pandas as pd
    try:
        import yfinance as yf
        h = yf.Ticker("^IRX").history(period="1mo")["Close"].dropna()
    except Exception as e:
        print(f"[RATES] ^IRX tail refresh failed, using the cached series: "
              f"{type(e).__name__}: {e}")
        return None
    if not len(h):
        return None
    h.index = pd.to_datetime([t.date() for t in h.index])
    return h


def _load_irx():
    """^IRX: the strategy repo's cached history plus a FRESH tail. Raises if unreachable.

    THE CACHE IS HISTORY, NOT THE LATEST CLOSE (2026-09-11). irx_local counts its pickle
    as current whenever its last day is within four days of the ask -- the right trade
    for backtests, which re-read decades and do not care about last Tuesday -- so the
    dial's daily series froze at whatever day the pickle was last written. On 2026-09-11
    it still ended 2026-09-10, and that row was a MID-SESSION value (pickle written at
    13:40: 3.843 against a 3.845 close). The regime latch walks this series, so for up to
    four days it could not see a new close while the live delta crossed the tightening
    line.

    So irx_local supplies the long, stub-safe history and one small fresh pull supplies
    the recent month, which WINS where the two overlap: a newer read of a day is the
    close, the cached one may be an intraday snapshot. The pickle is never written from
    here -- the backtests own it.

    COMPLETED SESSIONS ONLY. A bar dated today (ET) is dropped: the latch arbitrates on
    consecutive daily CLOSES, and today's row is a live quote until the session ends.
    Today's reading reaches the panel through the separate live tip in engine.strategy.

    A labelled DTB3 fallback (irx_local serves FRED when cache and Yahoo together cannot
    cover the window) is returned as it is -- an ^IRX tail is never grafted onto a FRED
    history, which is the "sources don't mix silently" rule that module is built on.
    """
    if _BACKTESTS not in sys.path:
        sys.path.insert(0, _BACKTESTS)
    from irx_local import load_irx          # noqa: E402  (path set above)
    import pandas as pd

    # A wide window: the dial plots ten years and the 6-month lookback needs a run-up
    # before that. The cache makes a wide ask free after the first fill.
    start, end = "1990-01-01", (pd.Timestamp.today() + pd.Timedelta(days=1)).date()
    s = load_irx(start, str(end)).dropna()
    # irx_local's FRED fallback returns the CSV's own column, which FRED names after the
    # series id; its ^IRX path never produces that name.
    from_fred = str(getattr(s, "name", "") or "").upper() == "DTB3"
    # Normalise to date-only, matching what fred_series returns, so every downstream
    # date comparison (the 6-month reindex, the monthly resample) behaves identically.
    s.index = pd.to_datetime([t.date() for t in s.index])
    s = s.sort_index()
    if not from_fred:
        tail = _recent_irx()
        if tail is not None:
            s = tail.combine_first(s).sort_index()
    return s[s.index < pd.Timestamp(_today_et())]


def rate_series(series_id):
    """The dial series for `series_id`, dispatched on the symbol.

    A leading `^` is a Yahoo quote symbol (^IRX) -> the cached loader above.
    Anything else is a FRED series id (DTB3) -> the keyless CSV helper.

    One switch point, so the config alone decides the source and both the Rocket
    Strategy dial and the Charts-tab dial follow it together.
    """
    if str(series_id).startswith("^"):
        return _load_irx()
    return fred_series(series_id)
