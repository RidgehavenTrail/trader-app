"""
Live state for the QQQ trading system — the strategy INSIDE the Fed dial's regime.

THE CONTRACT
------------
Everything above this module sees ONE dict and nothing else:

    { state, state_tier, entry_price, entry_date, days_held,
      target, target_mult, pnl_pct, era, era_days, era_pnl_pct, asof }

`state` is the strategy's own label; `state_tier` is holding | exiting | flat, and
is what the DISPLAY colors off. That split is the whole point: the renderer never
learns a single strategy-specific state name, so a different strategy shows its own
vocabulary and still colors correctly with no frontend change.

SWAPPING THE STRATEGY
---------------------
`_adapt_full_system()` is the ONLY function that knows what a halo or a breakout is.
To point the dashboard at a different script, write a sibling adapter returning the
same dict and change ADAPTER. The endpoint, the renderer and the CSS do not move.

The adapter deliberately REIMPLEMENTS NOTHING. It imports the canonical backtest and
reads state off what that script itself computed, so the board and the backtest can
never disagree about what the system is doing. `warned` and `b1_done` are locals
inside system2() and are not exposed — both are derived here from the returned trades
and the module's own arrays rather than by copying the walk.

WHAT THIS PANEL IS ALLOWED TO RUN (the live/experimental boundary, 2026-08-12)
------------------------------------------------------------------------------
The strategy lives in `Macro Newsletters\\backtests\\live\\` — a git repository
holding ONLY the two modules below plus `strategy_config.py`, which carries the
parameters that used to sit in this repo (2026-08-12; see engine/live_config.py).
The ~60 research scripts one level up in `backtests\\` are unversioned working
material and are not on this module's import path, so a what-if there cannot change
what the board renders. Two guards enforce what remains: `_assert_blessed()` refuses
UNCOMMITTED code AND uncommitted configuration (the strategy channel),
`_assert_canonical()` refuses SYS_* environment overrides (the configuration
channel). Changing the strategy is expected — verify the run, then commit it.

COST
----
Importing the backtest downloads ~26 years of QQQ/^IRX/^VIX and walks it. That is a
compute-once-daily job, not a per-request one — hence the long TTL below.
"""
import contextlib
import io
import os
import subprocess
import sys
import threading
import time
from datetime import date

from engine.live_config import BACKTEST_DIR, cfg

# The two scripts this panel runs live outside this repo, in their OWN
# version-controlled directory: `Macro Newsletters\backtests\live\`. The ~60
# research scripts one level up in `backtests\` are unversioned and are edited
# freely — and none of them are on this path, so a what-if cannot reach the
# board. That separation IS the isolation; `_assert_blessed()` enforces it.
#
# BACKTEST_DIR is defined ONCE, in engine/live_config.py, which reads the strategy
# configuration out of that same directory. Two copies of the path could drift.

# The `kind` -> display vocabulary, the profit target, and the two states that are not
# sleeves all describe the STRATEGY's structure — naming its sleeves gives away as much
# as its parameters do — so they live in the strategy repo alongside everything else
# that would let a reader reconstruct it. See engine/live_config.py.


def _sys():
    return cfg().QQQ_SYSTEM


TTL_SECONDS = 6 * 3600
_lock = threading.Lock()
_cache = {"payload": None, "at": 0.0}


def _tier(state):
    s = _sys()
    if state == s["cash_state"]:
        return "flat"
    if state == s["hunt_state"]:
        return "exiting"
    return "holding"


def _load(refresh=False):
    """Import the canonical backtest modules with their reports suppressed.

    Both print a full performance table at import — system_plus_flush.py already
    establishes redirect_stdout as the way to import the core quietly; this does the
    same one level up.

    REFRESH MATTERS. Both modules download their price data and build their arrays at
    IMPORT time, so Python's module cache would pin the board to whatever the engine
    saw at startup: the TTL would expire, we would re-walk the same frozen arrays,
    and the panel would sit on stale prices indefinitely without ever looking wrong.
    An expired cache therefore RELOADS rather than re-reading. Order is load-bearing:
    the core first, since system_plus_flush binds the core's arrays at its own import.
    """
    _assert_blessed()
    if BACKTEST_DIR not in sys.path:
        sys.path.insert(0, BACKTEST_DIR)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import qqq_full_system as fs
        import system_plus_flush as pf
        if refresh:
            import importlib
            fs = importlib.reload(fs)
            pf = importlib.reload(pf)
    _assert_canonical(fs)
    return fs, pf


def _assert_blessed():
    """Refuse to run a strategy change that has not been COMMITTED.

    `BACKTEST_DIR` is a git repository holding the modules this panel runs and the
    configuration it reads, so this one check covers both.
    COMMITTING IS WHAT BLESSES A CHANGE: an experiment you are still editing is by
    definition uncommitted, so it cannot reach the board. This closes the channel
    `_assert_canonical` cannot see — a change to the CODE rather than to the
    configuration, which no environment check can detect. Checked BEFORE the import so
    unblessed code is never executed at all (importing it downloads and walks 26 years).

    The scope is deliberate on both ends. Modifications to TRACKED files refuse;
    untracked files only log, so a stray editor backup cannot take a working panel down.
    And if git itself cannot run, this logs and PASSES rather than refusing — the gate
    exists to catch an accidental edit, and blanking a correct panel over a missing
    binary would be a worse failure than the one being prevented.
    """
    try:
        r = subprocess.run(
            ["git", "-C", BACKTEST_DIR, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            print(f"[QQQ] bless check SKIPPED (git exit {r.returncode}): "
                  f"{r.stderr.strip()[:200]}")
            return
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[QQQ] bless check SKIPPED ({type(e).__name__}: {e})")
        return

    dirty, untracked = [], []
    for line in r.stdout.splitlines():
        (untracked if line.startswith("??") else dirty).append(line[3:].strip())
    if untracked:
        print("[QQQ] note: untracked file(s) in the live strategy dir -- "
              f"{', '.join(untracked)}")
    if dirty:
        raise RuntimeError(
            "qqq_system: refusing to render an UNCOMMITTED strategy change -- "
            + ", ".join(dirty)
            + f". Verify the run, then commit it in {BACKTEST_DIR} to bless it; or "
              "revert it with `git checkout -- .` there. What-if work belongs one "
              "level up in backtests\\, which is not on this path.")


def _assert_canonical(fs):
    """Refuse to render anything that is not the canonical QQQ configuration.

    The backtest modules gained SYS_TICKER / SYS_START / SYS_END / SYS_RETEST environment
    overrides on 2026-08-11 so the one canonical implementation could be pointed at other
    instruments without forking it. Those overrides are PROCESS-GLOBAL and invisible at this
    import site: a stray SYS_TICKER in the engine's environment would make this panel render
    XLE's state under a QQQ label, with no error anywhere. That is precisely the silent-break
    class the handoff warns about, so it is checked rather than trusted.
    """
    bad = []
    if getattr(fs, "TICKER", "QQQ") != "QQQ":
        bad.append(f"SYS_TICKER={fs.TICKER!r} (panel is QQQ-only)")
    if getattr(fs, "RETEST_MODE", "1") != "1":
        bad.append(f"SYS_RETEST={fs.RETEST_MODE!r} (must be the full never-sell-below-200 rule)")
    if os.environ.get("SYS_END"):
        bad.append(f"SYS_END={os.environ['SYS_END']!r} (would pin the panel to a stale date)")
    if os.environ.get("SYS_START"):
        bad.append(f"SYS_START={os.environ['SYS_START']!r}")
    if bad:
        raise RuntimeError(
            "qqq_system: refusing to render a non-canonical backtest configuration -- "
            + "; ".join(bad)
            + ". Unset these in the engine's environment; they exist for backtest work only.")


def _adapt_full_system(refresh=False):
    """THE ONLY STRATEGY-AWARE FUNCTION. Maps the backtest's internals -> the contract."""
    fs, pf = _load(refresh)
    n = fs.n
    last_i = n - 1
    T = fs.system2()

    # --- era: golden / WARNING / death, from the system's own arrays
    golden = fs.golden
    era = "golden" if bool(golden[last_i]) else "death"

    # Era start = the most recent flip of the golden flag.
    era_start = 0
    for i in range(last_i, 0, -1):
        if bool(golden[i]) != bool(golden[i - 1]):
            era_start = i
            break

    # A warning is live if warn_day fired since the last new 52-week high — a new
    # high CANCELS a warning, so "since the last new high" IS the live test and
    # needs no state machine. Scoped to this era.
    if era == "golden":
        last_high = era_start
        for i in range(last_i, era_start - 1, -1):
            if bool(fs.brk[i]):
                last_high = i
                break
        if any(bool(fs.warn_day[i]) for i in range(last_high + 1, n)):
            era = "WARNING"

    # --- current position
    state = _sys()["cash_state"]
    entry_price = entry_date = target = pnl_pct = None
    days_held = None

    t = T[-1] if T else None
    if t:
        if t["why"] == "OPEN":
            state = _sys()["kind_state"].get(t["kind"], t["kind"])
        elif t["why"].endswith("->capped") and t["x"] >= last_i:
            # wait_for_200() returns min(n-1, frm+RETEST_CAP). Landing on the LAST
            # bar means the scan ran out of data, not that the 252-day cap was
            # genuinely reached — the position is still held, hunting the 200.
            # Without this the board would show the flat state while you are
            # actually long.
            state = _sys()["hunt_state"]

        if state != _sys()["cash_state"]:
            e = t["e"]
            ratio_e = fs.ratio[e]
            entry_price = round(float(t["fill"] / ratio_e), 2)   # back to raw price
            entry_date = fs.dates[e].date().isoformat()
            days_held = int(last_i - e)
            pnl_pct = round(float(fs.ac[last_i] / t["fill"] - 1) * 100, 2)
            if t["kind"] in ("dip", "failwarn"):
                target = round(entry_price * _sys()["target_mult"], 2)

    # --- the VIX flush overlay sits on top and only trades while the system is flat
    if state == _sys()["cash_state"] and pf.trades:
        ft = pf.trades[-1]
        if ft["x"] == fs.dates[last_i].date():
            state = "VIX Bounce"
            entry_date = ft["e"].isoformat()
            days_held = int(ft["hold"])
            pnl_pct = round(float(ft["ret"]), 2)

    # --- era P&L: compounded across the era on the BASELINE curve (core + flush),
    # including idle cash earning the T-bill rate between trades. pf.comb is exactly
    # that daily series, so this needs no reconstruction.
    era_pnl = 1.0
    for r in pf.comb[era_start:]:
        era_pnl *= (1.0 + float(r))

    return {
        "state": state,
        "state_tier": _tier(state),
        "entry_price": entry_price,
        "entry_date": entry_date,
        "days_held": days_held,
        "target": target,
        # The multiplier travels with the target so the renderer can caption it
        # ("fill x N") without the number living in a committed file.
        "target_mult": _sys()["target_mult"],
        "pnl_pct": pnl_pct,
        "era": era,
        "era_days": int(last_i - era_start + 1),
        "era_pnl_pct": round((era_pnl - 1.0) * 100, 2),
        "asof": fs.dates[last_i].date().isoformat(),
    }


ADAPTER = _adapt_full_system      # <- the single line to change when the strategy does


def get_state():
    """TTL-cached contract dict. Never caches a failure; serves the last good payload
    flagged stale rather than blanking the block."""
    with _lock:
        if _cache["payload"] and time.time() - _cache["at"] < TTL_SECONDS:
            return _cache["payload"]
        try:
            # refresh on every REBUILD (not the first build — that import is already
            # fresh), so an expired TTL re-downloads instead of re-walking stale arrays.
            p = dict(ADAPTER(refresh=bool(_cache["payload"])), ok=True, stale=False)
            _cache["payload"], _cache["at"] = p, time.time()
            return p
        except Exception as e:
            print(f"[QQQ] state build failed: {type(e).__name__}: {e}")
            if _cache["payload"]:
                return dict(_cache["payload"], stale=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
