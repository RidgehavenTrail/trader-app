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

THE CACHE IS PER START DATE. "Strategy begins" is a full recalculation (~11s on the
171-name panel; a later start is proportionally faster), so each start gets its own slot
on the same 6h TTL the other strategies use. A second request for a start that is still
computing WAITS on the lock rather than launching a duplicate walk. A failure never
evicts a good payload: the last good one is served flagged `stale`, same as get_state().

WHAT IS AND IS NOT HERE. No rule, threshold or parameter -- this repository has a public
remote. The engine and the config block live in `Macro Newsletters\\backtests\\live\\`;
this file only asks that module for its payload and caches the answer.
"""
import sys
import threading
import time

from flask import Blueprint, jsonify, request

from engine.live_config import BACKTEST_DIR, assert_blessed

bp = Blueprint("moonshot", __name__)

TTL_SECONDS = 6 * 3600
FAIL_TTL_SECONDS = 180
_lock = threading.Lock()
_cache = {}          # start (str or "") -> {"payload", "at", "fail", "fail_at"}
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


def get_book(start=""):
    with _lock:
        slot = _cache.setdefault(start, {"payload": None, "at": 0.0,
                                         "fail": None, "fail_at": 0.0})
        if slot["payload"] and time.time() - slot["at"] < TTL_SECONDS:
            return slot["payload"]
        if (slot["payload"] is None and slot.get("fail")
                and time.time() - slot["fail_at"] < FAIL_TTL_SECONDS):
            return slot["fail"]
        try:
            m = _module(refresh=bool(slot["payload"]))
            t0 = time.time()
            p = dict(m.book(start or None), ok=True, stale=False,
                     built_in=round(time.time() - t0, 1))
            slot["payload"], slot["at"], slot["fail"] = p, time.time(), None
            return p
        except Exception as e:
            print(f"[MOON] book build failed (start={start or 'full'}): "
                  f"{type(e).__name__}: {e}")
            if slot["payload"]:
                return dict(slot["payload"], stale=True)
            slot["fail"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            slot["fail_at"] = time.time()
            return slot["fail"]


@bp.route("/get_moonshot", methods=["GET"])
def get_moonshot():
    """The Moonshot book for one start date. `?start=YYYY-MM-DD`; omit for full history."""
    try:
        start = _norm_start(request.args.get("start"))
    except ValueError:
        return jsonify({"ok": False, "error": "start must be YYYY-MM-DD"}), 400
    return jsonify(get_book(start))
