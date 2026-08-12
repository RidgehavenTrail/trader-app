"""Turtle Trade Indicator (System 2) — see .claude/rules/turtle-volume-indicators.md.

Pure trigger + analytics math, split from any engine/IO so it is fully unit-testable
offline (the spec's "Layer 1"). Nothing here fetches data or touches the dashboard.

System 2: enter on a 55-day breakout of the daily HIGH/LOW (not close); exit on the
20-day opposite-channel breach; N = 20-day ATR; suggested stop = entry ± 2N; pyramid
adds every 0.5N in the trade's direction up to 4 units.

Conventions:
- highs/lows/closes are ascending-by-date lists of daily values (most recent LAST).
- A "channel" level is computed from the PRIOR n completed days (today excluded) — the
  caller passes a series ending at yesterday for a live breakout test, so `price`
  crossing it is a genuine break of the prior range.
"""

TURTLE_ENTRY_N = 55        # breakout lookback (System 2 entry)
TURTLE_EXIT_N = 20         # opposite-channel exit lookback
TURTLE_ATR_N = 20          # N = 20-day ATR
TURTLE_STOP_ATR_MULT = 2   # suggested stop = entry ± 2N
TURTLE_MAX_UNITS = 4       # pyramid to a 4-unit max
TURTLE_PYRAMID_STEP = 0.5  # add every 0.5N


def true_ranges(highs, lows, closes):
    """Per-day true range TR = max(H-L, |H-prevC|, |L-prevC|). Length = len-1."""
    trs = []
    for i in range(1, len(highs)):
        pc = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return trs


def atr(highs, lows, closes, period=TURTLE_ATR_N):
    """Wilder-smoothed ATR (the Turtle 'N'), seeded with the SMA of the first
    `period` true ranges. Returns the latest value, or None if too little data."""
    if len(highs) < period + 1:
        return None
    trs = true_ranges(highs, lows, closes)
    if len(trs) < period:
        return None
    n = sum(trs[:period]) / period
    for tr in trs[period:]:
        n = (n * (period - 1) + tr) / period
    return n


def donchian_high(highs, n):
    return max(highs[-n:]) if len(highs) >= n else None


def donchian_low(lows, n):
    return min(lows[-n:]) if len(lows) >= n else None


def detect_breakout(price, channel_high, channel_low):
    """'long' if price breaks above the channel high, 'short' if below the low, else None."""
    if channel_high is not None and price > channel_high:
        return "long"
    if channel_low is not None and price < channel_low:
        return "short"
    return None


def suggested_stop(entry, n_atr, direction, mult=TURTLE_STOP_ATR_MULT):
    """Classic Turtle stop: entry ∓ 2N (below entry for long, above for short)."""
    if n_atr is None:
        return None
    return entry - mult * n_atr if direction == "long" else entry + mult * n_atr


def pyramid_levels(entry, n_atr, direction, max_units=TURTLE_MAX_UNITS, step=TURTLE_PYRAMID_STEP):
    """All remaining add levels (units 2..max_units) at `step`·N increments in the
    trade's direction, shown at once. Returns [] if N is unknown."""
    if n_atr is None:
        return []
    levels = []
    for unit in range(1, max_units):
        delta = unit * step * n_atr
        levels.append(entry + delta if direction == "long" else entry - delta)
    return levels


def opposite_channel(highs, lows, direction, n=TURTLE_EXIT_N):
    """System 2 exit reference: the 20-day low for a long, the 20-day high for a short."""
    return donchian_low(lows, n) if direction == "long" else donchian_high(highs, n)


def breakout_episodes(highs, lows, entry_n=TURTLE_ENTRY_N, exit_n=TURTLE_EXIT_N):
    """Walk the daily series and simulate System 2 episodes for the historical stats.

    An episode starts at the FIRST 55-day crossing in a direction (entry at the
    breakout level) and ends at the 20-day opposite-channel breach (exit at that
    level). While in a position, further same-direction crossings do NOT start new
    episodes; a new one can only begin after the prior one exits. Returns a list of
    {direction, entry_price, entry_index, exit_price, exit_index, pct, win}.
    pct is percent PRICE MOVE (signed by direction), for cross-ticker comparability.
    """
    n = len(highs)
    episodes = []
    pos = None
    for i in range(entry_n, n):
        if pos is None:
            ch_high = max(highs[i - entry_n:i])
            ch_low = min(lows[i - entry_n:i])
            if highs[i] > ch_high:
                pos = {"direction": "long", "entry_price": ch_high, "entry_index": i}
            elif lows[i] < ch_low:
                pos = {"direction": "short", "entry_price": ch_low, "entry_index": i}
            continue
        # In a position — check the opposite-channel exit (needs exit_n prior days).
        if i < exit_n:
            continue
        if pos["direction"] == "long":
            exit_ref = min(lows[i - exit_n:i])
            if lows[i] < exit_ref:
                pct = (exit_ref - pos["entry_price"]) / pos["entry_price"] * 100
                episodes.append({**pos, "exit_price": exit_ref, "exit_index": i,
                                 "pct": pct, "win": pct > 0})
                pos = None
        else:
            exit_ref = max(highs[i - exit_n:i])
            if highs[i] > exit_ref:
                pct = (pos["entry_price"] - exit_ref) / pos["entry_price"] * 100
                episodes.append({**pos, "exit_price": exit_ref, "exit_index": i,
                                 "pct": pct, "win": pct > 0})
                pos = None
    return episodes


def _aggregate_R(direction, filled_levels, exit_price, n_atr, stop_mult=TURTLE_STOP_ATR_MULT):
    """Sum the per-unit result of a pyramided position in R (1R = stop_mult·N, one
    unit's initial risk). A 4-unit winner reads ~4× a 1-unit result."""
    risk = stop_mult * n_atr
    total = 0.0
    for lvl in filled_levels:
        move = (exit_price - lvl) if direction == "long" else (lvl - exit_price)
        total += move / risk
    return total


def pyramided_episodes(highs, lows, closes, entry_n=TURTLE_ENTRY_N, exit_n=TURTLE_EXIT_N,
                       atr_n=TURTLE_ATR_N, max_units=TURTLE_MAX_UNITS,
                       step=TURTLE_PYRAMID_STEP, stop_mult=TURTLE_STOP_ATR_MULT):
    """Pyramided System-2 backtest — the realistic historical stats.

    Each episode enters at the 55-day breakout (unit 1), adds units at step·N
    intervals up to max_units as price runs in favor, and raises the WHOLE-position
    stop to stop_mult·N below (long) / above (short) the most recently added unit.
    All units exit together at whichever binds first: the raised stop or the 20-day
    opposite channel. Result is aggregate R (1R = one unit's initial stop_mult·N
    risk), so a runner that fills 4 units reads far larger than a failed breakout
    stopped at 1 — which is how the system is actually traded. Returns per episode
    {direction, entry, exit, units, R, win}. Uses today's-excluded (completed) bars.
    """
    n = len(highs)
    episodes = []
    pos = None
    for i in range(entry_n, n):
        if pos is None:
            ch_high = max(highs[i - entry_n:i])
            ch_low = min(lows[i - entry_n:i])
            direction = entry = None
            if highs[i] > ch_high:
                direction, entry = "long", ch_high
            elif lows[i] < ch_low:
                direction, entry = "short", ch_low
            if direction:
                n_atr = atr(highs[:i + 1], lows[:i + 1], closes[:i + 1], atr_n)
                if not n_atr or n_atr <= 0:
                    continue  # can't risk-size a unit without N
                if direction == "long":
                    unit_levels = [entry + u * step * n_atr for u in range(max_units)]
                    stop = entry - stop_mult * n_atr
                else:
                    unit_levels = [entry - u * step * n_atr for u in range(max_units)]
                    stop = entry + stop_mult * n_atr
                pos = {"direction": direction, "entry": entry, "n_atr": n_atr,
                       "entry_index": i, "unit_levels": unit_levels, "filled": 1, "stop": stop}
            continue

        d, n_atr = pos["direction"], pos["n_atr"]
        # 1. Fill any adds reached by today's extreme; each raises the stop.
        while pos["filled"] < max_units:
            lvl = pos["unit_levels"][pos["filled"]]
            reached = highs[i] >= lvl if d == "long" else lows[i] <= lvl
            if not reached:
                break
            pos["filled"] += 1
            pos["stop"] = (lvl - stop_mult * n_atr) if d == "long" else (lvl + stop_mult * n_atr)
        # 2. Exit all units at whichever binds first: raised stop or 20-day channel.
        if d == "long":
            chan = min(lows[i - exit_n:i]) if i >= exit_n else pos["stop"]
            trig = max(pos["stop"], chan)
            if lows[i] <= trig:
                R = _aggregate_R(d, pos["unit_levels"][:pos["filled"]], trig, n_atr, stop_mult)
                episodes.append({"direction": d, "entry": pos["entry"], "exit": trig,
                                 "units": pos["filled"], "entry_index": pos["entry_index"],
                                 "R": R, "win": R > 0})
                pos = None
        else:
            chan = max(highs[i - exit_n:i]) if i >= exit_n else pos["stop"]
            trig = min(pos["stop"], chan)
            if highs[i] >= trig:
                R = _aggregate_R(d, pos["unit_levels"][:pos["filled"]], trig, n_atr, stop_mult)
                episodes.append({"direction": d, "entry": pos["entry"], "exit": trig,
                                 "units": pos["filled"], "entry_index": pos["entry_index"],
                                 "R": R, "win": R > 0})
                pos = None
    return episodes


def pyramid_stats(episodes):
    """Aggregate pyramided_episodes() into the displayed stats — everything in R
    (risk-normalized), plus average units filled. avg_loss_R is negative."""
    wins = [e["R"] for e in episodes if e["win"]]
    losses = [e["R"] for e in episodes if not e["win"]]
    Rs = [e["R"] for e in episodes]
    return {
        "total_episodes": len(episodes),
        "n_success": len(wins),
        "n_fail": len(losses),
        "avg_win_R": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_R": (sum(losses) / len(losses)) if losses else None,
        "expectancy_R": (sum(Rs) / len(Rs)) if Rs else None,
        "avg_units": (sum(e["units"] for e in episodes) / len(episodes)) if episodes else None,
    }


def turtle_signal_metrics(snapshot, direction):
    """Assemble the card/detail metrics for a fired breakout from a day's snapshot.
    Pure (given a snapshot) so it's unit-testable. entry = the breakout level itself
    (the 55-day extreme that was crossed)."""
    entry = snapshot["channel_high"] if direction == "long" else snapshot["channel_low"]
    n_atr = snapshot["atr"]
    return {
        "direction": direction,
        "breakout_level": entry,
        "atr": n_atr,
        "suggested_stop": suggested_stop(entry, n_atr, direction),
        "opposite_channel": snapshot["exit_long"] if direction == "long" else snapshot["exit_short"],
        "pyramid": pyramid_levels(entry, n_atr, direction),
        "stats": snapshot["stats"].get(direction),  # the fired direction's record only
    }


def snapshot_from_series(highs, lows, closes):
    """Assemble a Turtle snapshot from explicit daily H/L/C arrays (ascending by
    date, most recent last). Shared by the live fetch wrapper and the --as-of-date
    test injection. Uses COMPLETED bars only (drops the last bar) so a live/as-of
    price can genuinely cross the channel. Stats are split by direction — a fired
    signal shows the record of ITS OWN side, never diluted by the other. Returns a
    dict, or None if too little data."""
    if len(highs) < TURTLE_ENTRY_N + 2:
        return None
    c_highs, c_lows, c_closes = highs[:-1], lows[:-1], closes[:-1]
    eps = pyramided_episodes(c_highs, c_lows, c_closes)
    return {
        "channel_high": donchian_high(c_highs, TURTLE_ENTRY_N),
        "channel_low": donchian_low(c_lows, TURTLE_ENTRY_N),
        "atr": atr(c_highs, c_lows, c_closes, TURTLE_ATR_N),
        "exit_long": donchian_low(c_lows, TURTLE_EXIT_N),
        "exit_short": donchian_high(c_highs, TURTLE_EXIT_N),
        "stats": {
            "long": pyramid_stats([e for e in eps if e["direction"] == "long"]),
            "short": pyramid_stats([e for e in eps if e["direction"] == "short"]),
        },
    }


def compute_turtle_snapshot(stock, period="5y"):
    """Pull ~5y daily H/L/C for a yfinance Ticker and assemble the day's Turtle
    snapshot. Heavy — the caller caches this once/day per ticker. Returns a dict,
    or None on any data gap. Never raises."""
    try:
        hist = stock.history(period=period)
        if hist.empty:
            return None
        highs = [float(x) for x in hist['High'].tolist()]
        lows = [float(x) for x in hist['Low'].tolist()]
        closes = [float(x) for x in hist['Close'].tolist()]
        return snapshot_from_series(highs, lows, closes)
    except Exception:
        return None


def episode_stats(episodes):
    """Aggregate breakout_episodes() into the displayed win/loss stats (percent price
    move). avg_loss_pct is negative. Returns None averages when a bucket is empty."""
    wins = [e["pct"] for e in episodes if e["win"]]
    losses = [e["pct"] for e in episodes if not e["win"]]
    return {
        "total_episodes": len(episodes),
        "n_success": len(wins),
        "n_fail": len(losses),
        "avg_win_pct": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_pct": (sum(losses) / len(losses)) if losses else None,
    }
