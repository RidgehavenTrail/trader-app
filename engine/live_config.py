"""Loads the live strategy configuration from the out-of-repo strategy repository.

WHY THIS INDIRECTION EXISTS (2026-08-12)
----------------------------------------
This repository has a PUBLIC remote. The dial's series and thresholds, the regime ->
allocation map, the warning rule and the profit target are the STRATEGY — signal plus
deadband plus portfolios makes the rotation reproducible from one file — so they were
moved out to `Macro Newsletters\\backtests\\live\\strategy_config.py` and are read
through here at runtime.

What stayed behind is the generic mechanism: fetch a series, compute an N-month
change, classify it against thresholds, latch a flip, render the result. That code is
worth keeping in the repo and gives nothing away on its own. What left is every value
that would let a reader reconstruct WHICH series, WHICH thresholds, and WHICH
holdings — including any label that names an instrument.

This is the same split `qqq_system.py` already applies to the backtest's CODE, applied
one layer up to its NUMBERS.

BLESSING
--------
`assert_blessed()` lives here because the configuration now sits in the blessed repo
alongside the strategy modules, so a values change is gated exactly as a code change
is: an uncommitted edit refuses to render.

`qqq_system.py` keeps its OWN copy of this check rather than calling this one. That is
deliberate, not an oversight — it guards the heavy backtest import and raises a
strategy-specific message telling you where to commit and that what-if work belongs one
directory up. Both run the same `git status` against the same repo, so neither can pass
while the other would fail; only the wording differs.

FAILURE MODE
------------
A missing or unreadable config raises. It does NOT fall back to defaults: a dial
silently running on a placeholder threshold would render a confident, wrong regime,
which is worse than an empty panel. Callers already serve a stale cache or an error
payload rather than blanking the board.
"""
import os
import subprocess
import sys
import threading

# The strategy repo. Same directory `qqq_system.py` imports its backtests from — the
# config is a third module in it, so it inherits the same version control and the same
# blessing guard.
BACKTEST_DIR = os.path.join(os.path.expanduser("~"), "Documents",
                            "Macro Newsletters", "backtests", "live")

CONFIG_MODULE = "strategy_config"

_lock = threading.Lock()
_cached = None


def assert_blessed(tag="LIVE"):
    """Refuse to run a strategy change that has not been COMMITTED.

    `BACKTEST_DIR` is a git repository holding the modules and the configuration this
    board runs on. COMMITTING IS WHAT BLESSES A CHANGE: an experiment you are still
    editing is by definition uncommitted, so it cannot reach the board.

    The scope is deliberate on both ends. Modifications to TRACKED files refuse;
    untracked files only log, so a stray editor backup cannot take a working panel
    down. And if git itself cannot run, this logs and PASSES rather than refusing — the
    gate exists to catch an accidental edit, and blanking a correct panel over a
    missing binary would be a worse failure than the one being prevented.
    """
    try:
        r = subprocess.run(
            ["git", "-C", BACKTEST_DIR, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            print(f"[{tag}] bless check SKIPPED (git exit {r.returncode}): "
                  f"{r.stderr.strip()[:200]}")
            return
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[{tag}] bless check SKIPPED ({type(e).__name__}: {e})")
        return

    dirty, untracked = [], []
    for line in r.stdout.splitlines():
        (untracked if line.startswith("??") else dirty).append(line[3:].strip())

    if untracked:
        print(f"[{tag}] note: untracked file(s) in the strategy repo, ignored: "
              f"{', '.join(untracked[:5])}")
    if dirty:
        raise RuntimeError(
            f"strategy repo has UNCOMMITTED changes to tracked file(s): "
            f"{', '.join(dirty[:5])}. Commit them in {BACKTEST_DIR} to bless the "
            f"change, or revert them.")


def cfg(refresh=False):
    """The live strategy configuration module, imported once and cached.

    `refresh=True` re-imports, so an edit committed while the engine is running is
    picked up without a restart — matching how `qqq_system._load()` reloads the
    backtests rather than sitting on Python's module cache.
    """
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return _cached

        assert_blessed()

        if not os.path.isdir(BACKTEST_DIR):
            raise RuntimeError(
                f"strategy repo not found at {BACKTEST_DIR}. The dial's values live "
                f"there, outside this repository, and there is no fallback by design.")

        if BACKTEST_DIR not in sys.path:
            sys.path.insert(0, BACKTEST_DIR)
        try:
            mod = __import__(CONFIG_MODULE)
            if refresh:
                import importlib
                mod = importlib.reload(mod)
        except ImportError as e:
            raise RuntimeError(
                f"could not import {CONFIG_MODULE}.py from {BACKTEST_DIR}: {e}") from e

        _cached = mod
        return _cached
