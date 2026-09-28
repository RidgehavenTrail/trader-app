"""
Moonshot on the board -- the endpoint the header button opens.

WHY ITS OWN MODULE AND NOT A qqq_system STRATEGIES ENTRY. The registry serves ONE
contract dict per strategy, keyed by TICKER, through `get_state()` -- a position, not a
book. Moonshot is a ten-slot rotating book with a bank; it has no ticker, and the thing
the panel shows is a book. Forcing it through `_load()` would also break today: `_env()`
reads `_sys(spec)` = `getattr(strategy_config, cfg_key)`, and the MOONSHOT block is not
in strategy_config.py yet (see the strategy module's header for why, and how to bless).
So this module does the three things `_load()` does that matter -- refuse an uncommitted
strategy repo, put BACKTEST_DIR on the path, import by name -- and nothing it does not
need.

THE CACHE IS PER START DATE. "Strategy begins" is a full recalculation (~11s standalone,
~40s inside the busy engine), so each start gets its own slot on the same 6h TTL the other
strategies use. A failure never evicts a good payload.

SERVE, THEN REFRESH (2026-09-14). An out-of-date book is served immediately, flagged
`refreshing`, while a background thread walks the new one; the page swaps it in when it
lands. The last good book per start is also kept on disk, outside both repositories, so a
restart opens on it. See get_book().

THE CACHE IS ALSO KEYED ON THE PRICE PANEL (2026-09-10). The strategy module reads a
price panel from disk once and keeps it; a daily feed (the strategy repo's
`pit_panel_extend.py`, scheduled after the close) rewrites that file. Each slot records
the panel file's mtime at build time; a request that finds a different mtime starts a
rebuild, and the rebuild goes through the module reload path so the module re-reads the
file. No restart, no TTL wait, and since 2026-09-14 no viewer waits either: the request
that notices the change is served the previous book and triggers the walk. The feed writes the file atomically, so a mtime that
changed is a whole new panel, never half of one.

WHAT IS AND IS NOT HERE. No rule, threshold or parameter -- this repository has a public
remote. The engine and the config block live in `Macro Newsletters\\backtests\\live\\`;
this file only asks that module for its payload and caches the answer.
"""
import json
import os
import sys
import threading
import time

from flask import Blueprint, jsonify, request

from engine.live_config import BACKTEST_DIR, assert_blessed

bp = Blueprint("moonshot", __name__)

TTL_SECONDS = 6 * 3600
FAIL_TTL_SECONDS = 180
_lock = threading.Lock()
_cache = {}          # start (str or "") -> {"payload", "at", "fail", "fail_at", "stamp", "building", "from_disk"}
_mod = None


def _module(refresh=False):
    """The blessed strategy module, imported from the strategy repo by name."""
    global _mod
    assert_blessed(tag="MOON")
    if BACKTEST_DIR not in sys.path:
        sys.path.insert(0, BACKTEST_DIR)
    import importlib
    if _mod is None:
        _mod = importlib.import_module("moonshot")
    elif refresh:
        importlib.reload(sys.modules["moonshot_engine"])
        _mod = importlib.reload(_mod)
    return _mod


def _norm_start(s):
    """'' for the full history; otherwise an ISO date. Anything else is a 400."""
    s = (s or "").strip()
    if not s:
        return ""
    import datetime as _dt
    _dt.date.fromisoformat(s)          # raises ValueError on junk
    return s


def _panel_stamp():
    """The price panel file's mtime, or None before the module has loaded (nothing to
    compare against yet) or if the file is unreadable (the build will say so itself)."""
    if _mod is None:
        return None
    try:
        return os.path.getmtime(_mod.PANEL)
    except (OSError, AttributeError):
        return None


# THE LAST GOOD BOOK ON DISK, per start date, so an engine restart opens the panel on it
# instantly instead of making the first viewer wait for a walk. Outside BOTH repositories:
# the payload carries the rules text, which must never sit under the public tree, and the
# strategy repo's blessing guard would log it as an untracked file. The backtests folder
# the strategy repo lives in is neither.
DISK_CACHE = os.path.join(os.path.dirname(BACKTEST_DIR), "moonshot_book_cache")
_build_lock = threading.Lock()     # one walk at a time; requests never wait on it once a book exists


# A BARE NaN IS NOT JSON, AND IT BLANKS THE WHOLE PANEL (2026-09-23). Python writes NaN
# and Infinity by default and reads them back happily; a browser's JSON.parse rejects the
# document outright. So one unusable number does not degrade the panel -- it destroys it:
# the request returns 200, the page throws the payload away, and the panel reads "Book
# unavailable" with no error anywhere. Measured: 2026-09-22 went missing from the price
# source, the walk's equity and bank for that one day came back NaN, three headline facts
# (cagr, calmar, mult) computed across the series came back NaN with it, and the panel went
# dark even though 3158 of 3159 curve points were fine.
#
# Every number that cannot be represented becomes null here, at the edge: a gap in a chart
# and a dash in a figure, which is what an absent value should look like. The book's own
# arithmetic is untouched -- this is the serializer's business, not the strategy's.
def _json_safe(o):
    if isinstance(o, float):
        return o if -1e308 < o < 1e308 and o == o else None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


def _disk_path(start):
    return os.path.join(DISK_CACHE, f"book_{start or 'full'}.json")


def _read_disk(start):
    try:
        with open(_disk_path(start), encoding="utf-8") as fh:
            return _json_safe(json.load(fh))   # a book cached before _json_safe existed
    except (OSError, ValueError):
        return None


def _write_disk(start, payload):
    try:
        os.makedirs(DISK_CACHE, exist_ok=True)
        tmp = _disk_path(start) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, _disk_path(start))
    except OSError as e:
        print(f"[MOON] could not write the book cache: {e}")


def _slot(start):
    return _cache.setdefault(start, {"payload": None, "at": 0.0, "fail": None, "fail_at": 0.0,
                                     "stamp": None, "building": False, "from_disk": False})


def _is_fresh(slot):
    stamp = _panel_stamp()
    return (slot["payload"] is not None and not slot["from_disk"] and stamp is not None
            and slot["stamp"] == stamp and time.time() - slot["at"] < TTL_SECONDS)


def _build(start):
    """One walk, serialised on _build_lock. Stores the book in memory and on disk. A failure
    keeps whatever book the slot already had."""
    with _build_lock:
        with _lock:
            slot = _slot(start)
            if _is_fresh(slot):
                return slot["payload"]
            reload_mod = slot["payload"] is not None and not slot["from_disk"]
        try:
            m = _module(refresh=reload_mod)
            stamp = _panel_stamp()             # read BEFORE the walk: a panel replaced mid-walk is caught next time
            t0 = time.time()
            p = _json_safe(dict(m.book(start or None), ok=True, stale=False,
                                refreshing=False,
                                built_in=round(time.time() - t0, 1)))
            with _lock:
                slot.update(payload=p, at=time.time(), fail=None, stamp=stamp, from_disk=False)
            _write_disk(start, p)
            print(f"[MOON] book built (start={start or 'full'}) in {p['built_in']}s")
            return p
        except Exception as e:
            print(f"[MOON] book build failed (start={start or 'full'}): {type(e).__name__}: {e}")
            with _lock:
                if slot["payload"] is None:
                    slot["fail"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                    slot["fail_at"] = time.time()
                return slot["payload"] or slot["fail"]


def _refresh_in_background(start):
    slot = _slot(start)
    if slot["building"]:
        return
    slot["building"] = True

    def run():
        try:
            _build(start)
        finally:
            slot["building"] = False
    threading.Thread(target=run, name=f"moonshot-book-{start or 'full'}", daemon=True).start()


def get_book(start=""):
    """NEVER MAKE A VIEWER WAIT FOR A WALK THAT A BOOK ALREADY EXISTS FOR (user, 2026-09-14:
    "The strategy tab is rather static and rarely changes from day to day - I should never
    have to wait for the tab to appear").

    Serve-then-refresh. A fresh book is served as it is. A book that is out of date -- the
    price panel changed, the TTL ran out, or it came from disk after a restart -- is served
    AT ONCE, flagged `refreshing`, and a background walk replaces it; the page polls and
    swaps the new book in. Only a start date with no book anywhere, in memory or on disk,
    waits for its first walk.
    """
    with _lock:
        slot = _slot(start)
        if slot["payload"] is None:
            disk = _read_disk(start)
            if disk:
                slot.update(payload=disk, at=0.0, stamp=None, from_disk=True)
        if _is_fresh(slot):
            return dict(slot["payload"], refreshing=bool(slot["building"]))
        if slot["payload"] is not None:
            _refresh_in_background(start)
            return dict(slot["payload"], refreshing=True)
        if slot.get("fail") and time.time() - slot["fail_at"] < FAIL_TTL_SECONDS:
            return slot["fail"]
    return _build(start)


_notices = {"payload": None, "at": 0.0}
NOTICES_TTL = 300


# THE BOOK IS REBUILT BEFORE ANYONE ASKS (user, 2026-09-23: "Anytime I click on the
# moonshot panel, I should see the latest hour's result. Never should I make it to the end
# of the day and I'm staring at an update over 3 hours old.").
#
# Serve-then-refresh fixed the WAIT -- a viewer always gets a book at once -- but the walk
# it starts only ever ran because someone clicked, and it takes ~40s. So the first click
# after a quiet stretch showed whatever the last viewer's rebuild had produced: measured
# 2026-09-23 at 17:49, the hourly rank poll had written new panels at 13:30, 14:30 and
# 15:30 and the engine was still serving the 12:30 book, because nobody had opened the
# panel since 12:38.
#
# This watcher does the asking. Every minute it primes the default book (so a restart with
# nobody watching still ends up current) and rebuilds any cached start whose panel has
# changed or whose TTL has run out. Cost: one walk per panel write -- six a day from the
# intraday poll, one from the evening feed -- on a daemon thread, with no source call of
# its own beyond what the walk already does. A failing build is not retried before
# FAIL_TTL_SECONDS, so a dirty strategy repo or a bad panel cannot spin.
BOOK_WATCH_SECONDS = 60
BOOK_WATCH_START_DELAY = 25        # let the engine finish booting before the first walk


def _watch_books():
    tried = {}                     # start -> when this watcher last asked for a rebuild
    time.sleep(BOOK_WATCH_START_DELAY)
    while True:
        try:
            if "" not in _cache:
                get_book("")       # prime: reads the disk book and starts the first walk
            now = time.time()
            with _lock:
                due = [s for s, slot in _cache.items()
                       if slot["payload"] is not None and not slot["building"]
                       and not _is_fresh(slot)
                       and now - tried.get(s, 0.0) >= FAIL_TTL_SECONDS]
            for start in due:
                tried[start] = now
                print(f"[MOON] book is behind its panel -- rebuilding (start="
                      f"{start or 'full'}).")
                _refresh_in_background(start)
        except Exception as e:     # a watcher must never take the engine down
            # Throttled like the rebuilds: a condition that fails every tick -- an
            # uncommitted strategy repo, an unreadable panel -- is one console line every
            # few minutes, not one a minute for the rest of the day.
            msg = f"[MOON] book watcher error: {type(e).__name__}: {e}"
            if time.time() - tried.get(msg, 0.0) >= FAIL_TTL_SECONDS:
                tried[msg] = time.time()
                print(msg)
        time.sleep(BOOK_WATCH_SECONDS)


def start_book_watcher():
    t = threading.Thread(target=_watch_books, daemon=True, name="moonshot_book_watcher")
    t.start()
    return t


@bp.route("/get_moonshot_notices", methods=["GET"])
def get_moonshot_notices():
    """The light call the header makes on page load: announced index changes not yet in
    force, and when the watch last ran. Reads two small files in the strategy module --
    no walk, no panel -- so it is cheap enough to hit on every load. Five-minute cache."""
    with _lock:
        if _notices["payload"] and time.time() - _notices["at"] < NOTICES_TTL:
            return jsonify(_notices["payload"])
        try:
            p = dict(_module().notices(), ok=True)
        except Exception as e:
            p = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        _notices["payload"], _notices["at"] = p, time.time()
        return jsonify(p)


@bp.route("/get_moonshot", methods=["GET"])
def get_moonshot():
    """The Moonshot book for one start date. `?start=YYYY-MM-DD`; omit for full history."""
    try:
        start = _norm_start(request.args.get("start"))
    except ValueError:
        return jsonify({"ok": False, "error": "start must be YYYY-MM-DD"}), 400
    return jsonify(get_book(start))
