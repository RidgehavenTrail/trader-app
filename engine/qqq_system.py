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

ADDING A STRATEGY
-----------------
`_adapt_full_system()` is the ONLY function that knows what a halo or a breakout is.
To run a second strategy, write a sibling adapter returning the same dict and add an
entry to STRATEGIES (near the bottom — the registry documents its own fields). The
endpoint, the renderer and the CSS do not move, and `get_state(name)` serves them all.

This module is named for QQQ because QQQ was the only strategy when it was written;
it now dispatches by name and is not QQQ-specific. The filename is referenced from
engine/strategy.py, engine/live_config.py, watchtower.html and static/js/strategy.js,
so renaming it is a four-file change and has been deliberately deferred.

Two pieces of state are PER STRATEGY and were global before: the TTL cache (a shared
slot would have two panels evicting each other every request, re-walking 26 years of
data to do it) and the SYS_* environment (see `_env()`).

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
UNCOMMITTED code AND uncommitted configuration (the strategy channel), and
`_assert_canonical()` verifies the LOADED MODULE against what its registry entry
declared. The SYS_* configuration channel is no longer merely checked — `_env()`
controls it, applying each strategy's declared overrides around its own import and
restoring afterwards. Changing the strategy is expected — verify the run, then commit it.

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


def _sys(spec):
    return getattr(cfg(), spec["cfg_key"])


def _spec_env(spec):
    """The SYS_* a strategy declares — resolved from strategy_config FIRST.

    A registry entry may declare `env` inline, and QQQ does (as `{}`). A strategy whose
    overrides are RULE PARAMETERS must not: THIS REPO HAS A PUBLIC REMOTE, and the numbers
    that make one fork behave differently from another are precisely what moved out of it
    on 2026-08-12. XLE's overrides are its two structural changes expressed as numbers, so
    they live in the config block and the registry entry stays parameter-free.

    The config block WINS and the registry entry is the fallback, so a strategy declaring
    neither behaves exactly as before.
    """
    return dict(_sys(spec).get("env") or spec.get("env") or {})


TTL_SECONDS = 6 * 3600
FAIL_TTL_SECONDS = 180            # cold-cache failure answers instantly this long (see get_state)
_lock = threading.Lock()
_cache = {}                       # strategy key -> {"payload", "at", "fail", "fail_at"}

# Containment is by PREFIX, not by list (2026-08-20). `_SYS_KEYS` used to enumerate
# "every SYS_* the backtest modules read" and drifted the day a third strategy
# arrived: seven of MO's declared keys (SYS_PURE_DIP, SYS_SIGNALS, ...) were absent
# from it, so `_env()` applied them for MO's import and its restore never removed
# them -- and the next strategy imported in the same process inherited
# SYS_PURE_DIP=1. QQQ rendered as a pure-dip strategy the same evening MO was
# registered; the user caught it on the panel. The modules also read a DYNAMIC
# family (SYS_PHASE_<phase>_<param>, the retired MO baseline's per-phase overrides --
# see live/archive/) that no
# static list can enumerate even in principle. So the working set is now "anything
# starting with SYS_": save it all, clear it all, apply exactly what the strategy
# declares, and on exit sweep the prefix again -- which also catches a module-level
# os.environ write made DURING a strategy's own import -- then restore what was
# saved. There is no list left to forget to update.
_SYS_PREFIX = "SYS_"


@contextlib.contextmanager
def _env(spec):
    """Apply a strategy's declared SYS_* for the duration of its import, then restore.

    The overrides are PROCESS-GLOBAL and read at import time, which makes them the one
    piece of shared state two strategies genuinely contend over: a research wrapper that
    sets `SYS_TICKER=XLE` at module level would otherwise leave it set for every later
    import in the process. Clearing first and restoring after makes each import see
    exactly its own declared configuration and nothing else.

    This REPLACES the environment half of the old `_assert_canonical` check. Detecting a
    stray override and refusing was the right call when the panel could not control the
    environment; now that it can, the hazard is removed by construction rather than
    caught after the fact. A stripped value is logged, never silently swallowed, and
    `_assert_canonical` still verifies the LOADED MODULE against the spec — which is the
    failure the guard actually exists to catch.
    """
    declared = _spec_env(spec)
    saved = {k: v for k, v in os.environ.items() if k.startswith(_SYS_PREFIX)}
    stray = {k: v for k, v in saved.items() if declared.get(k) != v}
    if stray:
        print(f"[{spec['tag']}] note: ignoring SYS_* from the environment for this "
              f"import -- {', '.join(f'{k}={v!r}' for k, v in stray.items())}")
    try:
        for k in list(saved):
            os.environ.pop(k, None)
        os.environ.update(declared)
        yield
    finally:
        # Sweep the PREFIX, not a remembered list: this removes the declared keys AND
        # anything the module's own import wrote, then puts back exactly what existed
        # before. The set of keys present cannot drift from the set restored.
        for k in [k for k in os.environ if k.startswith(_SYS_PREFIX)]:
            os.environ.pop(k, None)
        os.environ.update(saved)


def _tier(state, spec):
    s = _sys(spec)
    if state == s["cash_state"]:
        return "flat"
    if state == s["hunt_state"] or state == s.get("warn_state"):
        return "exiting"
    return "holding"


def _load(spec, refresh=False):
    """Import a strategy's backtest modules with their reports suppressed.

    They print a full performance table at import — system_plus_flush.py already
    establishes redirect_stdout as the way to import the core quietly; this does the
    same one level up.

    REFRESH MATTERS. The modules download their price data and build their arrays at
    IMPORT time, so Python's module cache would pin the board to whatever the engine
    saw at startup: the TTL would expire, we would re-walk the same frozen arrays,
    and the panel would sit on stale prices indefinitely without ever looking wrong.
    An expired cache therefore RELOADS rather than re-reading. ORDER IS LOAD-BEARING —
    `spec["modules"]` lists the core FIRST, since an overlay binds the core's arrays at
    its own import; the same order is used on reload.
    """
    _assert_blessed()
    if BACKTEST_DIR not in sys.path:
        sys.path.insert(0, BACKTEST_DIR)
    buf = io.StringIO()
    mods = []
    # ORDER MATTERS: _env() first, so its stray-override note reaches real stdout. Entered
    # the other way round, redirect_stdout swallows the one log that says the environment
    # was not what the strategy declared.
    with _env(spec), contextlib.redirect_stdout(buf):
        import importlib
        for name in spec["modules"]:
            m = importlib.import_module(name)
            if refresh:
                m = importlib.reload(m)
            mods.append(m)
    _assert_canonical(mods[0], spec)
    return mods


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


def _assert_canonical(fs, spec):
    """Refuse to render a module that is not the configuration the strategy DECLARED.

    The backtest modules gained SYS_TICKER / SYS_START / SYS_END / SYS_RETEST environment
    overrides on 2026-08-11 so the one canonical implementation could be pointed at other
    instruments without forking it. Those overrides are process-global and invisible at this
    import site: the wrong one would make a panel render XLE's state under a QQQ label, with
    no error anywhere. That is precisely the silent-break class the handoff warns about.

    `_env()` now removes the hazard at the source, so this no longer inspects the
    environment. What it checks instead is stronger and survives that change: the module
    that actually loaded must match the spec. A stale entry in `sys.modules`, a wrong module
    name in a registry entry, or an override this code does not know about all show up here
    as a ticker that is not the declared one — which the environment check could never see.
    """
    bad = []
    want_ticker = spec["ticker"]
    want_retest = _spec_env(spec).get("SYS_RETEST", "1")
    if getattr(fs, "TICKER", want_ticker) != want_ticker:
        bad.append(f"TICKER={fs.TICKER!r}, declared {want_ticker!r}")
    if getattr(fs, "RETEST_MODE", want_retest) != want_retest:
        bad.append(f"RETEST_MODE={fs.RETEST_MODE!r}, declared {want_retest!r}")
    if bad:
        raise RuntimeError(
            f"{spec['tag']}: the loaded backtest is not the declared configuration -- "
            + "; ".join(bad)
            + f". Module {fs.__name__!r} for strategy {spec['key']!r}.")


def _era(fs):
    """(era, era_start) — golden / WARNING / death, off the system's own arrays.

    SHARED BY EVERY ADAPTER ON PURPOSE. XLE's core is a FORK of QQQ's and exposes the same
    `golden` / `brk` / `warn_day` arrays, so the era question has one answer for both.
    Copying this walk into each sibling adapter would mean a later correction to one
    silently missing the other — which is the exact failure the registry comment below is
    trying to design out.
    """
    n = fs.n
    last_i = n - 1
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
    return era, era_start


def _phase(fs, era, era_start, T):
    """(phase, phase_days) — where the system is in its OWN cycle.

    Distinct from `era`, which is the trend regime. Era says golden; phase says whether the
    gate is still holding the slot, whether breakout 1 has been taken, or whether we are in
    the post-B1 regime where only the dip and failwarn sleeves can open. That distinction is
    invisible in `state` alone: a flat system reads "Cash" in all three, which is what
    prompted this (user, 2026-08-15).

    Everything is READ, not re-derived: the zone length is the module's own HALO_WAIT_CAP,
    and B1-done is simply whether the trade list the script returned holds a `breakout1`
    opened since the cross. `_era` already establishes the era and its start.
    """
    last_i = fs.n - 1
    if era == "death":
        return "dark", int(last_i - era_start + 1)

    zone = int(getattr(fs, "HALO_WAIT_CAP", 0) or 0)
    since = int(last_i - era_start)
    if zone and since < zone:
        return "gate", since + 1

    b1 = [t for t in T if t["kind"] == "breakout1" and t["e"] >= era_start]
    if not b1:
        return "b1_hunt", since - zone + 1
    return "post_b1", int(last_i - b1[-1]["e"] + 1)


def _entry_trigger(fs, phase):
    """(level, basis) — the price that would OPEN a position in the current phase.

    THE LEVELS ARE THE MODULE'S OWN, not a second implementation. The dip level is
    `s50p[i]*(1-ENTRY_DEPTH/100)` exactly as system2() computes it, evaluated one bar
    forward — today's 50 SMA is tomorrow's prior-day value, which is what `s50p` holds.
    The breakout level is the 252-bar high over the module's own `h`, matching `hi252`'s
    window (that array is pre-shifted, so it excludes today and cannot be used directly
    for tomorrow's threshold).

    RAW PRICES, deliberately. `o/h/l/c` come from the UNADJUSTED download, so the SMAs and
    highs are already in quoted terms and need no `ratio` conversion — unlike `entry_price`,
    which is converted back out of the adjusted fill. Getting that backwards would put a
    silently wrong number where a reader would act on it.

    Returns (None, None) when the phase has no price trigger at all.
    """
    last_i = fs.n - 1

    def _dip():
        depth = float(getattr(fs, "ENTRY_DEPTH", 0) or 0)
        if not depth:
            return None, None
        return (round(float(fs.s50[last_i]) * (1.0 - depth / 100.0), 2),
                f"50 SMA −{depth:g}%")

    if phase == "post_b1":
        return _dip()
    if phase == "gate":
        # The gate is dead time UNLESS this strategy lets the dip sleeve trade inside the
        # exclusion zone (XLE does, QQQ does not) — so the honest answer differs per
        # strategy and is read from the module rather than assumed.
        return _dip() if getattr(fs, "HALO_ZONE_DIP", False) else (None, None)
    if phase == "b1_hunt":
        lo = max(0, last_i - 251)
        return round(float(max(fs.h[lo:last_i + 1])), 2), "252-day high"
    return None, None   # dark era: the overlay is a day filter, not a price level


def _cycle(fs, spec, era, era_start, T):
    """The phase fields, shared by every adapter. Display names come from the strategy's
    own config block, same as `kind_state` — naming the phases gives away as much as
    naming the sleeves does, so they live on the private side."""
    phase, phase_days = _phase(fs, era, era_start, T)
    level, basis = _entry_trigger(fs, phase)
    return {
        "phase": _sys(spec).get("phase_state", {}).get(phase, phase),
        "phase_days": phase_days,
        "trigger": level,
        "trigger_basis": basis,
    }


def _core_position(fs, spec, T):
    """The CORE system's current position — the position half of the contract.

    Shared for the same reason as `_era`, and safe to share because the vocabulary already
    comes from `_sys(spec)`: nothing here names a state, it looks one up. What genuinely
    differs between strategies is the OVERLAY that sits on top of a FLAT core, and that
    stays in each adapter.
    """
    last_i = fs.n - 1
    cash = _sys(spec)["cash_state"]
    out = {"state": cash, "entry_price": None, "entry_date": None,
           "days_held": None, "target": None, "pnl_pct": None}

    t = T[-1] if T else None
    if not t:
        return out

    if t["why"] == "OPEN":
        out["state"] = _sys(spec)["kind_state"].get(t["kind"], t["kind"])
    elif t["why"].endswith("->capped") and t["x"] >= last_i:
        # wait_for_200() returns min(n-1, frm+RETEST_CAP). Landing on the LAST
        # bar means the scan ran out of data, not that the 252-day cap was
        # genuinely reached — the position is still held, hunting the 200.
        # Without this the board would show the flat state while you are
        # actually long.
        out["state"] = _sys(spec)["hunt_state"]

    if out["state"] != cash:
        e = t["e"]
        ratio_e = fs.ratio[e]
        out["entry_price"] = round(float(t["fill"] / ratio_e), 2)   # back to raw price
        out["entry_date"] = fs.dates[e].date().isoformat()
        out["days_held"] = int(last_i - e)
        out["pnl_pct"] = round(float(fs.ac[last_i] / t["fill"] - 1) * 100, 2)
        if t["kind"] in ("dip", "failwarn"):
            out["target"] = round(out["entry_price"] * _sys(spec)["target_mult"], 2)
    return out


def _adapt_full_system(spec, refresh=False):
    """QQQ: the core system + the VIX-flush idle-cash overlay.

    One of two sibling adapters. Everything strategy-specific about QQQ is in here; the
    era walk and the core-position read are shared (see `_era` / `_core_position`), and
    the endpoint, the renderer and the CSS learn nothing about either strategy.
    """
    fs, pf = _load(spec, refresh)
    last_i = fs.n - 1

    era, era_start = _era(fs)
    T = fs.system2()
    cycle = _cycle(fs, spec, era, era_start, T)

    pos = _core_position(fs, spec, T)
    state = pos["state"]
    entry_price, entry_date = pos["entry_price"], pos["entry_date"]
    days_held, target, pnl_pct = pos["days_held"], pos["target"], pos["pnl_pct"]

    # --- the VIX flush overlay sits on top and only trades while the system is flat
    if state == _sys(spec)["cash_state"] and pf.trades:
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
        **cycle,
        "state": state,
        "state_tier": _tier(state, spec),
        "entry_price": entry_price,
        "entry_date": entry_date,
        "days_held": days_held,
        "target": target,
        # The multiplier travels with the target so the renderer can caption it
        # ("fill x N") without the number living in a committed file.
        "target_mult": _sys(spec)["target_mult"],
        "pnl_pct": pnl_pct,
        "era": era,
        "era_days": int(last_i - era_start + 1),
        "era_pnl_pct": round((era_pnl - 1.0) * 100, 2),
        "asof": fs.dates[last_i].date().isoformat(),
    }


def _adapt_xle_avoidlow(spec, refresh=False):
    """XLE: the core system + the avoid-post-52wk-low dark-era overlay (the XLE BASELINE).

    Sibling of `_adapt_full_system`. The two differ in exactly one place — what sits on top
    of a FLAT core — because XLE's core is a fork of QQQ's and shares its arrays.

    THE OVERLAY IS A DAY FILTER, NOT A TRADE, and that is the whole difference. QQQ's flush
    produces discrete trade records carrying an entry and a hold; this one produces a
    boolean array (`add`) marking the days it is long, so there is no trade record to read
    an entry off. The live position is therefore the RUN of consecutive `add` days ending
    today, and its P&L is that run compounded on the overlay's own combined series. Both
    are READ off what the script computed — the rule that decides `add` (dark, flat, and
    the prior session did not make a new 252-day low) is never re-implemented here.

    No `entry_price` on an overlay run, matching the flush branch above: the overlay earns
    a day's return on the day it is on, so the price you would have bought at is the PRIOR
    close, and publishing this run's first close as an entry would be off by one bar in a
    field a reader would reasonably compare against `pnl_pct`.
    """
    core, ov = _load(spec, refresh)
    last_i = core.n - 1

    era, era_start = _era(core)
    T = core.system2()
    cycle = _cycle(core, spec, era, era_start, T)

    pos = _core_position(core, spec, T)
    state = pos["state"]
    entry_price, entry_date = pos["entry_price"], pos["entry_date"]
    days_held, target, pnl_pct = pos["days_held"], pos["target"], pos["pnl_pct"]

    if state == _sys(spec)["cash_state"] and bool(ov.add[last_i]):
        run_start = last_i
        while run_start > 0 and bool(ov.add[run_start - 1]):
            run_start -= 1
        state = _sys(spec)["overlay_state"]
        entry_date = core.dates[run_start].date().isoformat()
        days_held = int(last_i - run_start + 1)
        run = 1.0
        for r in ov.comb[run_start:last_i + 1]:
            run *= (1.0 + float(r))
        pnl_pct = round((run - 1.0) * 100, 2)

    # --- era P&L on the BASELINE curve (core + overlay), idle cash earning the T-bill
    # rate between trades. `ov.comb` is exactly that daily series — the same role `pf.comb`
    # plays for QQQ — so this needs no reconstruction.
    era_pnl = 1.0
    for r in ov.comb[era_start:]:
        era_pnl *= (1.0 + float(r))

    return {
        **cycle,
        "state": state,
        "state_tier": _tier(state, spec),
        "entry_price": entry_price,
        "entry_date": entry_date,
        "days_held": days_held,
        "target": target,
        "target_mult": _sys(spec)["target_mult"],
        "pnl_pct": pnl_pct,
        "era": era,
        "era_days": int(last_i - era_start + 1),
        "era_pnl_pct": round((era_pnl - 1.0) * 100, 2),
        "asof": core.dates[last_i].date().isoformat(),
    }


class _FrameView:
    """Attribute view over a strategy that publishes its price frame as a DICT.

    Every other strategy hands the helpers a MODULE and they read `fs.n`, `fs.ratio`,
    `fs.ac`. gld_system exec's xle_system.py into a private namespace — not a copy and
    not an import, so its logic stays byte-identical and cannot collide with a live XLE
    panel — and exposes that namespace as `NS`, a dict. This adapts the one shape to the
    other in a single place rather than teaching six shared helpers about two.
    Because NS *is* the core's namespace, everything they reach for is there: the frame
    arrays, `system2`, and the ENTRY_DEPTH / HALO_ZONE_DIP flags `_entry_trigger` reads.
    """

    def __init__(self, ns):
        self.__dict__.update(ns)


def _adapt_gld(spec, refresh=False):
    """GLD: the blessed core ruleset PLUS the user's dark-era sleeve, sharing one book.

    FIFTH ADAPTER. The novelty is not the ruleset — the core is the blessed XLE one, pointed
    at GLD through its env — but that TWO SLEEVES ARBITRATE FOR ONE SLOT. gld_system runs
    them first-come-first-served and iterates to a fixed point, asserting zero overlaps
    before any number leaves it, so by the time this adapter sees `TRADES` the arbitration
    is already settled and the list is a single book's history.
    That is why there is no overlay branch here, unlike the XLE adapter: the dark sleeve
    produces real TRADE RECORDS rather than a day-filter mask, so `_core_position` reads it
    the same way it reads a dip, and the config already names it ("Dark-era dip").

    WHAT THE NUMBERS ARE AND ARE NOT — the module's docstring says to repeat this wherever
    they are quoted, so: the CORE clears both nulls on both axes and survives stripped
    fills; the DARK sleeve does NOT clear its own null (p=0.159 / 0.215) and is there for
    the regime and the stop, not for entry skill. Nothing in this file re-derives either.
    """
    (m,) = _load(spec, refresh)
    fs = _FrameView(m.NS)
    last_i = fs.n - 1

    era, era_start = _era(fs)
    # The UNION's trades, both sleeves, in one list — which is the whole point of the slot
    # arbitration upstream. `_core_position` reads the last one, so the panel shows
    # whichever sleeve actually holds the book.
    T = list(m.TRADES)
    cycle = _cycle(fs, spec, era, era_start, T)
    pos = _core_position(fs, spec, T)

    # Era P&L off the module's OWN published series — the union curve with idle cash
    # earning the T-bill rate between trades, exactly as `series()` documents it.
    ret, _inv = m.series()
    era_pnl = 1.0
    for r in ret[era_start:last_i + 1]:
        era_pnl *= (1.0 + float(r))

    return {
        **cycle,
        "state": pos["state"],
        "state_tier": _tier(pos["state"], spec),
        "entry_price": pos["entry_price"],
        "entry_date": pos["entry_date"],
        "days_held": pos["days_held"],
        "target": pos["target"],
        "target_mult": _sys(spec)["target_mult"],
        "pnl_pct": pos["pnl_pct"],
        "era": era,
        "era_days": int(last_i - era_start + 1),
        "era_pnl_pct": round((era_pnl - 1.0) * 100, 2),
        "asof": fs.dates[last_i].date().isoformat(),
    }


def _adapt_tobacco(spec, refresh=False):
    """THE TOBACCO COMMON RULESET -- one ruleset, one adapter, every name in the universe.

    Replaced MO's all-dip + carry baseline on 2026-08-25 at the user's instruction, and
    brought PM onto the board as its first blessed strategy. The retired baseline is kept at
    live/archive/mo_alldip_carry.py -- off the import path, so nothing here can reach it.

    FOURTH ADAPTER, AND THE FIRST SERVING MORE THAN ONE INSTRUMENT. Every other adapter is
    one strategy on one name; this one is one strategy on several, which is the entire claim
    the ruleset makes -- nothing in it is fitted to an instrument. The per-name difference is
    a window, and a window is configuration, so it lives in the strategy repo's env block and
    the module name is the only thing that varies here.

    IT READS, IT DOES NOT DERIVE. The module computes its own state at import and publishes
    it as STATE; everything below is looked up off that or off the shared helpers. No rule,
    threshold, level or sleeve name is written in this file -- they would be strategy, and
    this repository has a public remote. The display vocabulary comes from `_sys(spec)` and
    the numbers come from STATE.

    TWO TIERS, ONE SLOT. The trend tier and the bid tier share a single position: the book is
    long if either says long, and a handover between them is NOT a transaction. That is why
    the position fields come from the module's own view of the open run rather than from any
    per-sleeve bookkeeping this adapter might try to reconstruct.
    """
    (m,) = _load(spec, refresh)
    last_i = m.n - 1
    st = m.STATE
    s = _sys(spec)

    era, era_start = _era(m)

    # PHASE. This ruleset has no breakout hunt and no timed gate, so the shared `_phase`
    # walk -- which decides a phase by finding a breakout trade -- has nothing to find. The
    # phase here IS the regime, which the module already published.
    phase = "dark" if st["regime"] == "dark" else "golden"
    # THE WHOLE RESTING LADDER, not just its first rung (user, 2026-08-26: show both, in
    # case I want to choose). More than one bid genuinely rests at a time — `deep_bid` is
    # published on EVERY flat bar, while `dark` and `dip` are mutually exclusive with each
    # other but never with it — so publishing a single trigger hid a live order every day
    # the regime bid was up. A held book has no bids and the list is simply empty.
    # NEAREST FIRST: sorted by level descending, which is the order a decline would fill
    # them. Each rung carries its own name from the display vocabulary, because the old
    # constant "resting bid" read identically for every sleeve — the level moved but the
    # label never said which order it belonged to. The names come from `kind_state`; none
    # is written here, and neither is any depth that would say where a bid sits.
    ladder = [(st["dark_bid"], "dark"), (st["dip_bid"], "dip"), (st["deep_bid"], "deep")]
    triggers = sorted(
        ({"level": lv, "kind": k, "label": s["kind_state"].get(k, k)}
         for lv, k in ladder if lv is not None),
        key=lambda t: -t["level"])
    # `trigger` / `trigger_basis` keep their EXACT previous meaning — the module's own
    # priority pick, not the ladder's first rung. They are the shared contract QQQ and XLE
    # also fill, and a consumer reading only them must not silently change what it gets.
    primary_kind = ("dark" if st["dark_bid"] is not None
                    else "dip" if st["dip_bid"] is not None else "deep")
    cycle = {
        "phase": s.get("phase_state", {}).get(phase, phase),
        "phase_days": int(last_i - era_start + 1),
        "trigger": (st["deep_bid"] if st["deep_bid"] is not None and st["dark_bid"] is None
                    and st["dip_bid"] is None else
                    st["dark_bid"] if st["dark_bid"] is not None else st["dip_bid"]),
        "trigger_basis": (s["kind_state"].get(primary_kind, "resting bid")
                          if not st["in_position"] else None),
        "triggers": triggers,
    }

    # STATE NAMES THE SLEEVE THAT HOLDS THE BOOK. The config defines a display name for
    # every sleeve the module can report, and this now uses all of them (user,
    # 2026-08-26). It previously collapsed the bid sleeves into the hunt, so a filled
    # Dark bid and a filled Deep bid both rendered "200MA hunt" and their own names were
    # defined but never reachable — the state described where the position would LEAVE
    # rather than what it was.
    # Nothing is lost by naming the sleeve instead: the 200 those sleeves exit at is now
    # published as its own `exit_level` row, so the exit is stated where it belongs.
    # THE ONE GENUINE HUNT is a stopped dip — its target is gone and it is being held to
    # the 200 retest rather than sold below the 200. That is not the dip sleeve any more,
    # it is the hunt, and `exit_target is None` is the module's own way of saying so.
    # A RETEST HOLD NAMES ITS REASON (user, 2026-08-26). Below the 200 a warning does not
    # sell — never-sell-below turns the exit into a hold — and that is a different animal
    # from hunting an ordinary stopped dip. The module publishes the reason as a TYPED
    # field (`exit_why`); nothing here parses the note's sentence to find it.
    # Other retest reasons (a target printed below the 200, a death cross) keep the hunt
    # name: they are the same waiting, without the warning's meaning.
    if not st["in_position"]:
        state = s["cash_state"]
    elif st.get("exit_mode") == "retest":
        state = (s.get("warn_state", s["hunt_state"]) if st.get("exit_why") == "warning"
                 else s["hunt_state"])
    elif st["sleeve"] == "dip" and st["exit_target"] is None:
        state = s["hunt_state"]
    else:
        state = s["kind_state"].get(st["sleeve"], s["hunt_state"])

    # THE 200 IS THE TARGET DURING A RETEST HOLD, not a floor under a position that is
    # going somewhere else (user). Everywhere else it is the floor and `target` is the
    # dip's own objective, so the two levels stay distinct and neither row duplicates the
    # other. target_mult is suppressed with it: the 200 is a level being waited for, not
    # a fill struck at a multiple of the entry.
    retest = st.get("exit_mode") == "retest"
    target = st["exit_200"] if retest else st["exit_target"]
    target_mult = None if retest else s["target_mult"]

    # ERA P&L -- the strategy's OWN equity across the era, straight off the series it
    # published. Nothing is re-walked and no trade is re-priced.
    ret, inv = m.series()
    era_pnl = float((1.0 + ret[era_start:last_i + 1]).prod())

    return {
        **cycle,
        "state": state,
        "state_tier": _tier(state, spec),
        "entry_price": st["entry_price"],
        "entry_date": st["entry_date"],
        "days_held": st["days_held"],
        "target": target,
        "target_mult": target_mult,
        "pnl_pct": st["pnl_pct"],
        "era": era,
        "era_days": int(last_i - era_start + 1),
        "era_pnl_pct": round((era_pnl - 1.0) * 100, 2),
        "era_pnl_basis": ("since death cross" if era == "death" else "since golden cross"),
        # THE POSITION'S EXIT — the 200, and ONLY ever the 200. The bid sleeves have no
        # other, and a stopped dip is HELD to it rather than sold below it. Passed
        # through exactly as the module publishes it, including the null it publishes
        # while a trend position runs: there is no resting 200 order during histate, and
        # inventing one here would be this repo deriving a rule.
        # Suppressed during a retest hold — the 200 is the TARGET there and is already
        # rendered as one. Publishing it twice would put the same price on two rows and
        # two chart lines under two different names.
        "exit_level": (None if retest else st["exit_200"]),
        "exit_level_label": s["hunt_state"],
        "exit_note": st["exit_note"],
        "ma200": st["ma200"],
        # WHERE THE STATE ENDS — a different question from where the POSITION exits, and
        # the distinction is the whole of histate (user, 2026-08-26). The trend holds
        # while the most recent 252-bar extreme is a high, so it ENDS on a new 252-day
        # low — but that low is invariably below the 200, and a position is never sold
        # below the 200. So breaking this level ends the STATE and hands the book to a
        # 200 retest; it does not fill anything. Two levels, two meanings, two rows.
        # `low252` is the module's own published figure — read, not derived.
        "state_end_level": (st["low252"] if st["sleeve"] == "histate" else None),
        "state_end_label": (s.get("trend_state", "Trend") if st["sleeve"] == "histate"
                            else None),
        "state_end_note": ("state ends here — the position still holds for the 200"
                           if st["sleeve"] == "histate" else None),
        "asof": st["asof"],
    }


# --------------------------------------------------------------------------------------
# THE REGISTRY — the one place a strategy is wired in.
#
# Each entry declares everything this module needs to run one strategy and nothing about
# what the strategy IS; that knowledge stays in its adapter. Adding a second strategy is a
# sibling adapter plus an entry here — no change to the endpoint, the renderer, or the CSS,
# because `state` carries the strategy's own vocabulary and `state_tier` is what the
# display colors off.
#
#   key      the `strategy` value on a holding (see engine/strategy.py) and the cache key
#   tag      log prefix
#   modules  import order, CORE FIRST — an overlay binds the core's arrays at its own import
#   adapter  the strategy-aware function; takes (spec, refresh) and returns the contract
#   ticker   what the loaded core module's TICKER must be; `_assert_canonical` enforces it
#   env      the SYS_* this strategy declares. `_env()` applies exactly this and nothing
#            else, so a wrapper's module-level os.environ write cannot leak to another
#            strategy. Empty = the module's own defaults, which is the canonical QQQ run.
#   cfg_key  the display vocabulary in strategy_config.py (kind_state / hunt / cash / target)
#
# XLE WAS ADDED THIS WAY (2026-08-15) and this note now records what was done rather than
# what to do. ONE DEPARTURE from the recipe it used to give: it said to declare
# `env={"SYS_TICKER": "XLE", ...}` on the registry entry. That was written before the
# 2026-08-12 split and following it literally would have published the fork's rule
# parameters into a repo with a public remote — so the env lives in the XLE_SYSTEM config
# block instead and `_spec_env()` resolves it. A third strategy should do the same.
# --------------------------------------------------------------------------------------

STRATEGIES = {
    "qqq_system": {
        "key":     "qqq_system",
        "tag":     "QQQ",
        "modules": ("qqq_full_system", "system_plus_flush"),
        "adapter": _adapt_full_system,
        "ticker":  "QQQ",
        "env":     {},
        "cfg_key": "QQQ_SYSTEM",
    },
    "xle_system": {
        "key":     "xle_system",
        "tag":     "XLE",
        "modules": ("xle_system", "xle_system_plus_avoidlow"),
        "adapter": _adapt_xle_avoidlow,
        "ticker":  "XLE",
        # Deliberately empty — see the note above. The real declaration is
        # strategy_config.XLE_SYSTEM["env"], which `_spec_env()` reads first.
        "env":     {},
        "cfg_key": "XLE_SYSTEM",
    },
    # MO's ALL-DIP + CARRY baseline was REPLACED here on 2026-08-25 (user's instruction).
    # Its module is archived at live/archive/mo_alldip_carry.py and its display block is
    # kept as strategy_config.MO_SYSTEM_RETIRED. Both names below run the SAME ruleset from
    # the same engine module; only the window differs, and a window is configuration.
    # env stays empty here -- the real declaration is strategy_config.TOBACCO_*["env"],
    # because this repository has a public remote (see the note above).
    "tobacco_mo": {
        "key":     "tobacco_mo",
        "tag":     "MO",
        "modules": ("tobacco_mo",),
        "adapter": _adapt_tobacco,
        "ticker":  "MO",
        "env":     {},
        "cfg_key": "TOBACCO_MO",
    },
    # PM ADDED 2026-08-25 -- its first blessed strategy. Registering serves
    # /get_ticker_strategy/PM; whether an allocation sleeve RUNS it is a separate decision.
    # GLD ADDED 2026-08-27. The gold sleeve the easing regime holds, and the first
    # strategy on the board whose module arbitrates TWO sleeves into one slot.
    # env stays empty here for the usual reason -- the real declaration is
    # strategy_config.GLD_SYSTEM["env"], and this repository has a public remote.
    "gld_system": {
        "key":     "gld_system",
        "tag":     "GLD",
        "modules": ("gld_system",),
        "adapter": _adapt_gld,
        "ticker":  "GLD",
        "env":     {},
        "cfg_key": "GLD_SYSTEM",
    },
    "tobacco_pm": {
        "key":     "tobacco_pm",
        "tag":     "PM",
        "modules": ("tobacco_pm",),
        "adapter": _adapt_tobacco,
        "ticker":  "PM",
        "env":     {},
        "cfg_key": "TOBACCO_PM",
    },
}

# ticker -> strategy key. THIS IS WHAT DECOUPLES STRATEGY STATE FROM ALLOCATION: the panel
# reaches a strategy through the dial's holdings, so a name the dial is not currently
# allocated to had no way to be asked about itself. Clicking XLE in a non-tightening regime
# is exactly that case. Derived from the registry rather than written out, so it cannot
# fall out of step with it.
BY_TICKER = {s["ticker"]: k for k, s in STRATEGIES.items()}

DEFAULT_STRATEGY = "qqq_system"

# `ADAPTER` is GONE. It was the single-strategy dispatch point and nothing outside this
# module ever referenced it; keeping it would leave a name whose signature silently
# changed from (refresh) to (spec, refresh). The registry above replaces it.


def get_state(strategy=DEFAULT_STRATEGY):
    """TTL-cached contract dict for one strategy. Never caches a failure; serves the last
    good payload flagged stale rather than blanking the block.

    The cache is PER STRATEGY — a single shared slot would have the two panels evicting
    each other on every request and re-walking 26 years of data to do it.
    """
    spec = STRATEGIES.get(strategy)
    if spec is None:
        return {"ok": False, "error": f"unknown strategy {strategy!r}"}
    with _lock:
        slot = _cache.setdefault(strategy, {"payload": None, "at": 0.0,
                                            "fail": None, "fail_at": 0.0})
        if slot["payload"] and time.time() - slot["at"] < TTL_SECONDS:
            return slot["payload"]
        # SHORT failure-memory (2026-08-21). Holding state moved to the dial's SERVE
        # path, which polls — and with a cold cache during a feed outage, every poll
        # would otherwise queue a fresh ~90s failing import behind this lock (the old
        # bake-at-build accidentally rate-limited retries to once per 6h). A failed
        # build with NO last-good payload answers instantly for FAIL_TTL_SECONDS,
        # then retries. This is not "caching a failure" in the sense the docstring
        # forbids: a last-good payload still always wins, and recovery is picked up
        # at the first retry after the window (the ^IRX outage healed in minutes).
        if (slot["payload"] is None and slot.get("fail")
                and time.time() - slot["fail_at"] < FAIL_TTL_SECONDS):
            return slot["fail"]
        try:
            # refresh on every REBUILD (not the first build — that import is already
            # fresh), so an expired TTL re-downloads instead of re-walking stale arrays.
            p = dict(spec["adapter"](spec, refresh=bool(slot["payload"])),
                     ok=True, stale=False)
            slot["payload"], slot["at"] = p, time.time()
            slot["fail"] = None
            return p
        except Exception as e:
            print(f"[{spec['tag']}] state build failed: {type(e).__name__}: {e}")
            if slot["payload"]:
                return dict(slot["payload"], stale=True)
            slot["fail"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            slot["fail_at"] = time.time()
            return slot["fail"]
