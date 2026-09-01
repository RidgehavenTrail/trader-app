"""
AI Bubble Stoplight — self-contained Flask Blueprint + scheduler (session 31 build).

Registers like engine/newsletter.py: imports NOTHING from watchtower_engine.
    from stoplight import bp as stoplight_bp, start_scheduler
    app.register_blueprint(stoplight_bp)      # module level
    start_scheduler()                         # __main__, next to the other loops

GET /get_stoplight serves the whole board from the persisted state — it never
computes factors inline, so it is instant and works even when the scheduler is
not running (e.g. --as-of-date test mode serves the last known board).

Display flags are computed HERE, server-side, once — the frontend renderer
(Phase E) stays dumb:
  is_new         new-tag factor whose fresh print landed this ET day
  flipped_today  light changed color this ET day (any cadence)
  stale_days     days since last update, surfaced once past the cadence's
                 expected gap (else 0) — the inverse cue to "new data"
  header_id      the header-pin rule: a monthly-or-longer print pins for the
                 trading day (longer cadence wins a same-day tie); otherwise
                 the freshest update holds the slot.
"""
import threading
from datetime import datetime

import importlib

from flask import Blueprint, jsonify, request

from . import charts, events, store
from .registry import FACTORS, BY_ID
from .scheduler import start_scheduler  # re-export for watchtower_engine

bp = Blueprint("stoplight", __name__)

# Serialize an inline rate-chart build (cold cache) so two tab-opens don't both
# hit FRED. The scheduler normally keeps the cache warm; this is the cold path.
_charts_lock = threading.Lock()

# One inline ledger rebuild at a time, and a one-entry day cache in front of it.
# The pull is FREE (rankings-daily + /models, no inference), but it is still an
# external round-trip and the answer only changes once a day — without this, every
# panel open and every rail click would hit OpenRouter again.
_ledger_lock = threading.Lock()
_ledger_cache = {}          # (factor, days) -> (et_date, payload)

# One billed-update run at a time (the "Update" button). The endpoint acquires this
# non-blocking and the background thread releases it when done — a second click while
# a run is in flight gets 409 rather than double-spending.
_update_lock = threading.Lock()
_update_status = {"running": False, "last": None}

# Days since update at which a factor starts reading as stale, per cadence.
EXPECTED_MAX_DAYS = {"hourly": 2, "daily": 3, "weekly": 9, "monthly": 35, "quarterly": 100}
CADENCE_RANK = {"hourly": 0, "daily": 1, "weekly": 2, "monthly": 3, "quarterly": 4}

_READING_KEYS = ("light", "value", "metric", "state", "asof", "extras",
                 "updated_at", "prev_light", "prev_metric", "error",
                 "consecutive_failures")


def _row(spec, entry, now, today):
    row = {
        "id": spec["id"], "name": spec["name"], "rank": spec["rank"],
        "cadence": spec["cadence"], "catalyst": spec["catalyst"],
        "highlight": spec["highlight"], "module": bool(spec.get("module")),
        "built": bool(spec.get("builder")),
        "refine": bool(spec.get("refine")),   # live but flagged for refinement (badge)
    }
    for k in _READING_KEYS:
        row[k] = entry.get(k)
    row["is_new"] = bool((entry.get("new_at") or "").startswith(today))
    row["flipped_today"] = bool((entry.get("flipped_at") or "").startswith(today))
    row["stale_days"] = 0
    if entry.get("updated_at"):
        try:
            days = (now - datetime.fromisoformat(entry["updated_at"])).days
            if days > EXPECTED_MAX_DAYS[spec["cadence"]]:
                row["stale_days"] = days
        except ValueError:
            pass
    return row


def _header_id(rows):
    live = [r for r in rows if r["updated_at"]]
    if not live:
        return None
    # A monthly-or-longer arrival pins for the trading day; longer cadence wins.
    pinned = [r for r in live if r["is_new"] and CADENCE_RANK[r["cadence"]] >= 3]
    pool = pinned or live
    return max(pool, key=lambda r: (CADENCE_RANK[r["cadence"]] if pinned else 0,
                                    r["updated_at"]))["id"]


@bp.route("/get_stoplight", methods=["GET"])
def get_stoplight():
    state = store.load_state()
    now = store.now_et()
    today = store.today_et()

    markers = events.factor_markers(today=now.date())
    rows = []
    for spec in FACTORS:
        row = _row(spec, state["factors"].get(spec["id"], {}), now, today)
        row["cat"] = markers.get(spec["id"], "")   # 'D' or 'M/D' next-update marker
        rows.append(row)
    ranked = sorted((r for r in rows if not r["module"]), key=lambda r: r["rank"])
    module = next((r for r in rows if r["module"]), None)

    return jsonify({
        "factors": ranked,
        "module": module,
        "header_id": _header_id(rows),
        "catalysts": events.upcoming(90),   # upcoming dated events for the detail panel
        "pending_billed": state.get("pending_billed", []),   # factors with new data ready
        "update_status": _update_status,    # is an Update run in flight / last result
        "generated_at": now.isoformat(timespec="seconds"),
    })


# --- Event-driven billed update ("Update" button in the detail panel) ------------
# The disarmed scheduler only DETECTS due billed pulls (records pending_billed) — it
# never spends. This endpoint is the human authorization: a click fires exactly the
# sources the due triggers point at (part 1's per-source refresh), so a GOOGL-earnings
# update pulls only the gemini/GOOGL legs, not the whole basket.

def _group_by_factor(queue):
    """Collapse the per-(factor, event) queue into one run per factor, unioning the
    owed source legs. {factor: sorted([source_ids]) or None}; None = whole-factor run
    (regulatory / any sweep with no per-source mapping)."""
    groups = {}
    for it in queue:
        groups.setdefault(it["factor"], set()).update(it.get("sources") or [])
    return {fid: (sorted(srcs) or None) for fid, srcs in groups.items()}


def _actionable(queue):
    """Queue rows the Update button may actually fire — i.e. not snoozed. A snoozed
    row is still OWED and still displayed; it just must not spend until its date."""
    today = store.today_et()
    return [it for it in (queue or [])
            if not (it.get("snoozed_until") and it["snoozed_until"] > today)]


def _period_by_factor(queue):
    """The fiscal period each factor's run should be pinned to — the LATEST owed
    event's period_end, since that is the print we are actually waiting on."""
    out = {}
    for it in queue:
        pe = it.get("period_end")
        if pe and pe > out.get(it["factor"], ""):
            out[it["factor"]] = pe
    return out


def _run_updates_bg(queue):
    """Fire the QUEUED billed pulls (per-source), then recompute the affected lights +
    re-reconcile the queue under the state lock — so freshly-refreshed legs drain and
    any still-unfulfilled leg stays queued. Records each fire in state['billed'].
    Never raises; always releases the run lock + clears the running flag."""
    from .extractors import run as run_mod   # lazy: pulls in the OpenRouter client
    from . import scheduler
    fired = []
    groups = _group_by_factor(queue)
    periods = _period_by_factor(queue)
    try:
        for factor, only in groups.items():
            try:
                _rec, cost = run_mod.run_factor_only(   # None -> whole (regulatory)
                    factor, only, period_end=periods.get(factor))
                entry = {"factor": factor, "cost": round(cost or 0, 4),
                         "sources": only or "all"}
                # A per-source extractor does NOT raise when one leg is rejected — it
                # carries the prior and reports the leg in failed_sources. Surface that
                # here, or a run that pulled nothing usable reads as a clean success.
                bad = (_rec.get("failed_sources") or _rec.get("failed_companies") or []
                       ) if isinstance(_rec, dict) else []
                na = (_rec.get("unavailable_sources") or []) if isinstance(_rec, dict) else []
                if na:
                    entry["unavailable_sources"] = na
                if bad:
                    entry["failed_sources"] = bad
                fired.append(entry)
                print(f"[STOPLIGHT] update fired: {factor} sources={only or 'all'} "
                      f"cost=${cost}" + (f" FAILED LEGS: {bad}" if bad else ""))
            except Exception as e:
                fired.append({"factor": factor, "error": f"{type(e).__name__}: {e}"})
                print(f"[STOPLIGHT] update FAILED: {factor}: {e}")

        # Recompute the fired factors' lights + re-reconcile the queue, serialized
        # with the scheduler. reconcile drains only the legs that actually refreshed.
        with store.state_lock():
            state = store.load_state()
            for factor in groups:
                spec = BY_ID.get(factor)
                if spec and spec.get("builder"):
                    scheduler.run_factor(spec, state)   # reads the freshly-written input
            billed = state.setdefault("billed", {})
            for f in fired:
                if "error" not in f:
                    billed[f["factor"]] = {"last_fired": store.now_iso(),
                                           "last_cost": f["cost"], "sources": f["sources"]}
            state["pending_billed"] = events.reconcile_billed_queue(
                scheduler.BILLED_POLICIES, state)
            store.save_state(state)
    except Exception as e:
        print(f"[STOPLIGHT] update run error: {type(e).__name__}: {e}")
    finally:
        _update_status.update(running=False,
                              last={"fired": fired, "at": store.now_iso()})
        _update_lock.release()


@bp.route("/run_stoplight_updates", methods=["POST"])
def run_stoplight_updates():
    """Authorize + fire all currently-DUE billed pulls (per-source). Returns
    immediately; the pulls run on a background thread. Poll /get_stoplight for
    update_status + the refreshed lights."""
    from . import scheduler
    if not _update_lock.acquire(blocking=False):
        return jsonify({"status": "already_running"}), 409
    queue = _actionable(events.reconcile_billed_queue(
        scheduler.BILLED_POLICIES, store.load_state()))   # snoozed rows never bill
    if not queue:
        _update_lock.release()
        return jsonify({"status": "nothing_due", "firing": []})
    _update_status.update(running=True, last=None)
    threading.Thread(target=_run_updates_bg, args=(queue,), daemon=True,
                     name="stoplight_update").start()
    firing = [{"factor": fid, "sources": only or "all"}
              for fid, only in _group_by_factor(queue).items()]
    return jsonify({"status": "started", "firing": firing})


@bp.route("/dismiss_billed_pull", methods=["POST"])
def dismiss_billed_pull():
    """Clear ONE owed row from the billed queue by hand — the 'this data does not
    exist, stop showing it' switch for a pull that already ran and came back empty
    (VRT declining to disclose orders is the motivating case). Spends nothing.

    Scoped to the exact (factor, event_id, fire_date), so the SAME event next
    quarter is a new key and queues normally — a dismissal can never permanently
    blind a factor."""
    from . import scheduler
    body = request.get_json(silent=True) or {}
    factor, event_id = body.get("factor"), body.get("event_id")
    fire_date = body.get("fire_date")
    if not factor or not fire_date:
        return jsonify({"status": "bad_request",
                        "error": "factor and fire_date are required"}), 400
    with store.state_lock():
        state = store.load_state()
        events.dismiss_billed_row(state, factor, event_id, fire_date,
                                  note=body.get("note"))
        state["pending_billed"] = events.reconcile_billed_queue(
            scheduler.BILLED_POLICIES, state)
        store.save_state(state)
        pending = state["pending_billed"]
    print(f"[STOPLIGHT] billed row DISMISSED by hand: {factor}/{event_id}@{fire_date}")
    return jsonify({"status": "dismissed", "pending_billed": pending})


@bp.route("/snooze_billed_pull", methods=["POST"])
def snooze_billed_pull():
    """Kick a row's next check down the road without giving it up — "the transcript
    isn't published yet, ask me again tomorrow". Spends nothing, and the row stays
    OWED and visible; it just cannot be fired (or billed) until the date passes, when
    it becomes actionable again on its own. `days` defaults to 1."""
    from . import scheduler
    body = request.get_json(silent=True) or {}
    factor, fire_date = body.get("factor"), body.get("fire_date")
    if not factor or not fire_date:
        return jsonify({"status": "bad_request",
                        "error": "factor and fire_date are required"}), 400
    with store.state_lock():
        state = store.load_state()
        until = events.snooze_billed_row(state, factor, body.get("event_id"), fire_date,
                                         days=body.get("days") or 1)
        state["pending_billed"] = events.reconcile_billed_queue(
            scheduler.BILLED_POLICIES, state)
        store.save_state(state)
        pending = state["pending_billed"]
    print(f"[STOPLIGHT] billed row SNOOZED: {factor}/{body.get('event_id')}"
          f"@{fire_date} until {until}")
    return jsonify({"status": "snoozed", "until": until, "pending_billed": pending})


# --- Per-factor history (the detail panel's day rail + sparkline) ---------------
# Served on PANEL OPEN rather than folded into /get_stoplight: the board payload is
# polled on a cadence by every open tab, and thirty days x 16 factors of full readings
# would ride along on every one of those polls to be thrown away. One factor, on
# demand, is the cheaper shape.
# FREE — a pure read of the snapshot log the scheduler already writes. Nothing here
# pulls a source or bills anything.
@bp.route("/get_factor_history")
def get_factor_history():
    fid = (request.args.get("factor") or "").strip()
    if fid not in BY_ID:
        return jsonify({"error": "unknown factor", "factor": fid}), 404
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))
    spec = BY_ID[fid]
    return jsonify({
        "factor": fid,
        "name": spec["name"],
        "cadence": spec["cadence"],
        # NEWEST-FIRST, matching store.history() — the rail reads down from today.
        # A sparkline wants the other order and reverses it itself.
        "days": store.history_payloads(fid, days),
    })


# --- Per-factor LEDGER (the evidence views: Ledger / Two lenses) ----------------
# A factor "has a ledger" iff its builder module exports ledger(). Today only
# premium_share does — the discovery is by capability, not by a list, so a factor that
# grows one becomes clickable in the panel with no change here.
# FREE: premium_share.ledger() re-slices the SAME rankings_daily() pull compute() makes
# (~30 days x 51 rows arrive on every call and the light keeps only the latest day).
# No new source, no inference, nothing billed.
def _ledger_fn(fid):
    spec = BY_ID.get(fid) or {}
    name = spec.get("builder")
    if not name:
        return None
    try:
        mod = importlib.import_module(f".factors.{name}", __package__)
    except ImportError:
        return None
    return getattr(mod, "ledger", None)


@bp.route("/get_factor_ledger")
def get_factor_ledger():
    fid = (request.args.get("factor") or "").strip()
    if fid not in BY_ID:
        return jsonify({"error": "unknown factor", "factor": fid}), 404
    fn = _ledger_fn(fid)
    if fn is None:
        # NOT an error — most factors have no per-item evidence to show. The frontend
        # reads has_ledger and renders its generic view instead of a broken switcher.
        return jsonify({"factor": fid, "has_ledger": False, "days": []})
    try:
        days = int(request.args.get("days", 10))
    except (TypeError, ValueError):
        days = 10
    days = max(1, min(days, 30))

    # STORED days first. Since 2026-08-21 the scheduler captures each day's ledger at
    # the prices the light was decided on, so a stored day is the RECORD. Days from
    # before that (or any the scheduler missed) are re-derived live and marked
    # `reconstructed` — re-pricing old volumes with today's list can move whole models
    # across the premium line, so the two are not interchangeable and the frontend is
    # told which it is holding.
    stored = {d["date"]: d for d in store.ledger_days(fid, days)}

    key, today = (fid, days), store.today_et()
    hit = _ledger_cache.get(key)
    if hit is None or hit[0] != today:
        with _ledger_lock:
            hit = _ledger_cache.get(key)    # re-check inside the lock
            if hit is None or hit[0] != today:
                try:
                    live = fn(days=days)
                except Exception as exc:    # a dead source must not 500 the panel
                    # Stored days still serve — a source outage costs the live tail,
                    # not the history.
                    out = sorted(stored.values(), key=lambda d: d["date"], reverse=True)
                    return jsonify({"factor": fid, "has_ledger": True,
                                    "days": out, "error": str(exc)}), 200
                hit = (today, live)
                _ledger_cache[key] = hit

    merged = dict(stored)
    for day in hit[1]:
        if day["date"] not in merged:       # never shadow a recorded day
            merged[day["date"]] = dict(day, basis="reconstructed")
        else:
            # A RECORDED DAY CAN STILL BE MISSING ITS BACKDROP (2026-09-01). The
            # scheduler captures with days=1, and a factor whose picture needs a long
            # series only emits one when days > 1 — net_liquidity's 348 weekly points,
            # rate_path's cloud, leverage's frame — precisely so a poll does not write
            # them to disk every time. So the stored row is the record of the READING
            # and carries no series, and shadowing wholesale left the pane with a
            # header and no chart the moment a factor was first captured.
            # Fill ONLY keys the record does not have: every recorded value still
            # wins, and the day keeps its `basis`. The backdrop is display bulk, not
            # evidence the light was decided on, so re-deriving it changes nothing
            # about what the day says.
            rec = merged[day["date"]]
            for k, v in day.items():
                if k not in rec:
                    rec[k] = v
    out = sorted(merged.values(), key=lambda d: d["date"], reverse=True)[:days]
    return jsonify({"factor": fid, "has_ledger": True, "days": out})


@bp.route("/get_board_charts")
def get_board_charts():
    """The CHARTS tab's data (AI-bubble detail panel, 3rd tab). Serves the
    daily cache the scheduler maintains — instant, and never blocks the request on
    FRED. On a COLD cache (first run after deploy) it builds inline once, under a
    lock so concurrent opens don't duplicate the pulls. FREE sources only."""
    payload = charts.load_cached()
    if payload is None:
        with _charts_lock:
            payload = charts.load_cached() or charts.refresh()   # re-check inside the lock
    return jsonify(payload)
