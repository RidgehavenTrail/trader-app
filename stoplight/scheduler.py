"""
Stoplight scheduler — ONE daemon thread that runs factor builders when due.

Model (Tier-0 decisions, 2026-07-19):
- Cadence = CHECK rate, per the sources-doc taxonomy. No release-calendar math:
  we poll on a clock and detect a data-release by the reading's `asof` moving
  (that diff IS the "new-tag" firing for weekly+ factors).
- Restart-tolerant: due-ness is computed from the persisted `updated_at`, so an
  engine that was off for a week runs everything overdue at startup instead of
  waiting for the next wall-clock slot. (The engine is not running 24/7.)
- Error isolation: a failing builder keeps its last good reading + an `error`
  field and retries on a short leash. It can never take down the loop or the
  other factors.
- Every successful run appends to the daily snapshot log (store.record_snapshot)
  — the history the 63-bar / last-5 factors need.

Factor contract — stoplight/factors/<builder>.py exports:
    compute() -> {"id", "light", "value", "metric", "state"?, "asof", "extras"?}
Builders are pure: no Flask, no persistence, no scheduling knowledge.
"""
import importlib
import os
import threading
import time
import traceback
from datetime import date, datetime, timedelta

from . import charts, events, store
from .registry import FACTORS

# --- Event-driven BILLED extractors (STOPLIGHT_SCHEDULING §6 step 4) ----------
# The four extraction factors' primitives are refreshed by billed OpenRouter calls
# (extractors/run.py run_*_multi). They are NEVER polled on a clock — they fire on
# their feeding events' fire_date (pull_date: earnings report-session guarded).
BILLED_EXTRACTORS = {
    "silicon_payback": "run_silicon_multi",
    "infra_backlog":   "run_infra_backlog_multi",
    "capex_spigot":    "run_capex_spigot_multi",
    "regulatory":      "run_regulatory_multi",
}
# Per-extractor coalescing (see events.due_billed_pulls). settle_days = 0 across the
# board since the per-source refactor: each leg refreshes the DAY its own company
# reports (GOOGL's capex leg on GOOGL day, GEV's GW leg on GEV day), so there is no
# reason to wait for the whole cluster — the old settle:9 hold was for the retired
# whole-basket re-pull. weekly-sweep factors keep a min-interval floor so a sweep +
# an earnings in the same week don't double-fire; earnings-only factors don't need it
# (distinct report dates + the asof baseline already prevent re-firing an event).
BILLED_POLICIES = {
    "regulatory":      {"settle_days": 0, "min_interval_days": 6},
    "silicon_payback": {"settle_days": 0, "min_interval_days": 6},
    "capex_spigot":    {"settle_days": 0, "min_interval_days": 0},
    "infra_backlog":   {"settle_days": 0, "min_interval_days": 0},
}
# SAFETY GATE (prompt-before-billed-runs): billed pulls NEVER auto-fire unless this
# is explicitly set. Disarmed (default) = detect + notify only; the human runs the
# extractor (or arms this) after seeing what is due. Arming is standing approval for
# autonomous, recurring, billed calls — set only with eyes open on the cost.
BILLED_AUTOFIRE = os.environ.get("STOPLIGHT_BILLED_AUTOFIRE") == "1"

# Check intervals per cadence (seconds). Checking is free (public endpoints), so
# weekly/monthly factors are CHECKED much more often than they change — the asof
# diff decides whether anything is "new". Billed extractors (Phase D) will carry
# explicit per-factor overrides via spec["check_interval_s"].
CHECK_INTERVAL_S = {
    "hourly": 3600,
    "daily": 6 * 3600,
    "weekly": 6 * 3600,
    "monthly": 24 * 3600,
    "quarterly": 24 * 3600,
}
FAIL_RETRY_S = 15 * 60   # failed factor retries on this leash (FRED is intermittent)
CALENDAR_REFRESH_S = 7 * 24 * 3600   # weekly event-calendar maintenance (free pulls)
CHARTS_REFRESH_S = 24 * 3600          # daily rebuild for the Charts tab (FRED, free)
# While a chart is BEHIND its source, re-check on this floor instead of waiting out the
# daily timer (2026-08-27). A wall-clock daily rebuild cannot tell a complete build from
# a partial one: the 08:31 pass caught T10Y3M's new print but not DTB3's, which lands
# later in the morning, so the Fed dial served a one-print-old 3.71 / +0.12 for the rest
# of the day while the yield curve beside it was current. FREE pulls, so the only cost
# of re-checking is a request FRED is happy to serve.
CHARTS_CATCHUP_S = 30 * 60
TICK_S = 60


def _age_seconds(iso_ts):
    if not iso_ts:
        return float("inf")
    try:
        return (store.now_et() - datetime.fromisoformat(iso_ts)).total_seconds()
    except ValueError:
        return float("inf")


def _is_due(spec, entry):
    interval = spec.get("check_interval_s") or CHECK_INTERVAL_S[spec["cadence"]]
    if entry.get("error"):
        return _age_seconds(entry.get("last_attempt")) >= FAIL_RETRY_S
    return _age_seconds(entry.get("updated_at")) >= interval


def run_factor(spec, state):
    """Run one builder and fold its reading into state. Mutates state; never raises."""
    fid = spec["id"]
    now = store.now_iso()
    try:
        mod = importlib.import_module(f"stoplight.factors.{spec['builder']}")
        reading = mod.compute()
    except Exception as e:
        entry = state["factors"].setdefault(fid, {"id": fid})
        entry["last_attempt"] = now
        entry["error"] = f"{type(e).__name__}: {e}"
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        print(f"[STOPLIGHT] {fid} FAILED ({entry['consecutive_failures']}x): {entry['error']}")
        if entry["consecutive_failures"] == 1:
            traceback.print_exc()
        return

    prev = state["factors"].get(fid) or {}
    entry = dict(reading)
    entry.update(
        updated_at=now,
        last_attempt=now,
        error=None,
        consecutive_failures=0,
        prev_light=prev.get("light"),
        prev_metric=prev.get("metric"),
    )
    # STATE-CHANGE: any color flip, cadence-independent.
    if prev.get("light") and entry.get("light") != prev.get("light"):
        entry["flipped_at"] = now
        print(f"[STOPLIGHT] {fid} FLIPPED {prev['light']} -> {entry['light']} ({entry.get('metric')})")
    else:
        entry["flipped_at"] = prev.get("flipped_at")
    # NEW-DATA: a fresh asof on a new-tag factor is news. First-ever reading is
    # baseline, not news.
    if (spec["highlight"] == "new-tag" and prev.get("asof")
            and entry.get("asof") and entry["asof"] != prev["asof"]):
        entry["new_at"] = now
        print(f"[STOPLIGHT] {fid} new print: asof {prev['asof']} -> {entry['asof']}")
    else:
        entry["new_at"] = prev.get("new_at")

    state["factors"][fid] = entry
    # An asof-keyed factor files its row under the day the DATA is for, and the FIRST
    # capture of that day wins (registry.asof_keyed / store.record_snapshot). Every
    # other factor keeps the write-date key and last-run-wins.
    asof = reading.get("asof") if spec.get("asof_keyed") else None
    store.record_snapshot(fid, entry.get("value"), payload=reading,
                          day=asof, keep_first=bool(asof))
    _record_ledger_day(mod, fid, reading)


def _record_ledger_day(mod, fid, reading):
    """Capture the day's per-item ledger, for the factors that keep one.

    Runs right after a successful compute() so the ledger is written at the same prices
    the light was decided on — which is the entire point (see store.record_ledger).
    Guarded three ways so it can never become a cost or a failure:
      - a factor with no ledger() is skipped (15 of 16);
      - a day already captured is skipped WITHOUT pulling, so a scheduler running
        several times a day makes one round-trip, not several;
      - any exception is swallowed with a log line. The ledger is evidence for the
        panel; it must never be able to fail a factor whose reading already succeeded."""
    fn = getattr(mod, "ledger", None)
    if fn is None:
        return
    asof = reading.get("asof")
    try:
        if asof and store.has_ledger_day(fid, asof) == "recorded":
            return
        for day in fn(days=1):
            store.record_ledger(fid, day["date"], day, basis="recorded")
    except Exception as e:
        print(f"[STOPLIGHT] {fid} ledger capture failed (reading kept): "
              f"{type(e).__name__}: {e}")


def _maybe_refresh_calendar(state):
    """Weekly, re-pull the event calendar's dates from free sources. Keyed off a
    persisted timestamp (like factor due-ness), so an engine that was dark for
    >7d refreshes on the next boot instead of waiting for a wall-clock slot.
    Free pulls only — this never triggers a billed extraction (see events.py)."""
    if _age_seconds(state.get("calendar_refreshed_at")) < CALENDAR_REFRESH_S:
        return False
    summary = events.refresh_calendar()
    state["calendar_refreshed_at"] = summary["refreshed_at"]
    state["calendar_last_summary"] = summary
    if summary["changed"]:
        print(f"[STOPLIGHT] calendar refreshed — {len(summary['changed'])} date(s) moved: "
              + ", ".join(f"{c['event_id']} {c['from']}->{c['to']}" for c in summary["changed"]))
    else:
        print("[STOPLIGHT] calendar refreshed — no date changes.")
    if summary["errors"]:
        print(f"[STOPLIGHT] calendar refresh errors: {summary['errors']}")
    return True


def _charts_behind():
    """True when the cached Charts payload is older than what its sources could give.

    Keyed off each chart's OWN `asof` — the real print date every builder already
    publishes — against the latest weekday that could plausibly have printed. FRED is
    T+1, so being one weekday back is CURRENT and must not trigger a re-check; two or
    more is behind.

    This is what the daily timer cannot see. Both charts rebuild in one pass, but their
    series publish at different times of the morning, so a pass can be complete for one
    and stale for another — and a timestamp on the PASS says nothing about either.
    """
    payload = charts.load_cached()
    if not payload:
        return True
    # store.today_et() returns a STRING (it is used as a cache key elsewhere); the date
    # arithmetic below needs a real date, so take it from now_et().
    today = store.now_et().date()
    # the most recent weekday strictly before today: FRED's newest possible observation
    latest = today - timedelta(days=1)
    while latest.weekday() >= 5:
        latest -= timedelta(days=1)
    for c in payload.get("charts") or []:
        a = c.get("asof")
        if not a:
            continue
        try:
            if date.fromisoformat(a) < latest:
                return True
        except ValueError:
            continue
    return False


def _maybe_refresh_charts(state):
    """Rebuild the Charts-tab cache from FRED. Daily by the clock, but ALSO whenever a
    chart is behind its source — see `_charts_behind`. Keyed off a persisted timestamp
    (same pattern as the calendar), so an engine that was dark for a day rebuilds on the
    next boot instead of waiting for a wall-clock slot. FREE pulls only — FRED, no key,
    no billed path. Returns True if state changed."""
    age = _age_seconds(state.get("charts_refreshed_at"))
    # The catch-up floor bounds the re-checking: a source that is genuinely late (or a
    # holiday, where `latest` names a day that will never print) costs two pulls an hour,
    # not one per scheduler tick.
    if age >= CHARTS_REFRESH_S:
        pass                                   # the ordinary daily rebuild
    elif age >= CHARTS_CATCHUP_S and _charts_behind():
        print("[STOPLIGHT] board charts are behind their source — re-checking.")
    else:
        return False
    try:
        payload = charts.refresh()
    except Exception as e:   # build_charts is already error-isolated; this is the write
        print(f"[STOPLIGHT] board charts refresh FAILED: {type(e).__name__}: {e}")
        return False
    state["charts_refreshed_at"] = payload["generated_at"]
    errs = payload.get("errors") or []
    ok = sum(1 for c in payload["charts"] if not c.get("error"))
    print(f"[STOPLIGHT] board charts refreshed — {ok}/{len(payload['charts'])} built"
          + (f"; errors: {errs}" if errs else "."))
    return True


def _maybe_fire_billed(state):
    """Event-driven billed extraction. Maintains state['pending_billed'] as a
    PERSISTENT per-(factor, event) queue (events.reconcile_billed_queue) — so a pull
    owed while the engine was dark / the human was away is NOT erased when the weekly
    calendar roll advances the earnings date; it stays queued until its own leg is
    actually refreshed. Fires ONLY when armed (STOPLIGHT_BILLED_AUTOFIRE=1); otherwise
    it logs the queue and leaves the run to the human (the Update button). Returns
    True if state changed."""
    queue = events.reconcile_billed_queue(BILLED_POLICIES, state)
    changed = queue != state.get("pending_billed")
    state["pending_billed"] = queue
    if not queue:
        return changed

    # Group owed legs by factor (union their source legs -> one run per factor).
    groups = {}
    for it in queue:
        g = groups.setdefault(it["factor"], {"sources": set(), "triggers": set()})
        g["sources"].update(it.get("sources") or [])
        g["triggers"].update(it.get("triggers") or [])

    for fid, g in groups.items():
        trg = ",".join(sorted(g["triggers"]))
        if not BILLED_AUTOFIRE:
            print(f"[STOPLIGHT] billed pull QUEUED: {fid} (trigger {trg}) — NOT firing "
                  f"(autofire off). Click Update in the detail panel or run "
                  f"`python -m stoplight.extractors.run {fid}` to fire.")
            continue
        try:
            run_mod = importlib.import_module("stoplight.extractors.run")
            only = sorted(g["sources"]) or None   # None -> whole factor (regulatory)
            _rec, cost = run_mod.run_factor_only(fid, only)
            state.setdefault("billed", {})[fid] = {
                "last_fired": store.now_iso(), "last_cost": cost,
                "sources": only or "all", "triggers": sorted(g["triggers"])}
            changed = True
            print(f"[STOPLIGHT] billed pull FIRED: {fid} sources={only or 'all'} — cost ${cost}")
        except Exception as e:
            print(f"[STOPLIGHT] billed pull {fid} FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    if BILLED_AUTOFIRE:
        # Re-reconcile after firing so freshly-refreshed legs drain out of the queue.
        state["pending_billed"] = events.reconcile_billed_queue(BILLED_POLICIES, state)
    return changed


def scheduler_loop():
    print("[STOPLIGHT] scheduler up — "
          f"{sum(1 for s in FACTORS if s.get('builder'))}/{len(FACTORS)} factors built."
          f" Billed autofire: {'ARMED' if BILLED_AUTOFIRE else 'off (detect+notify)'}.")
    while True:
        try:
            with store.state_lock():   # serialize with the /run_stoplight_updates endpoint
                state = store.load_state()
                ran = False
                for spec in FACTORS:
                    if not spec.get("builder"):
                        continue
                    entry = state["factors"].get(spec["id"], {})
                    if _is_due(spec, entry):
                        run_factor(spec, state)
                        ran = True
                ran = _maybe_refresh_calendar(state) or ran
                ran = _maybe_refresh_charts(state) or ran
                ran = _maybe_fire_billed(state) or ran
                if ran:
                    store.save_state(state)
        except Exception as e:
            # belt-and-braces: the loop itself must survive anything
            print(f"[STOPLIGHT] loop error: {type(e).__name__}: {e}")
        time.sleep(TICK_S)


def start_scheduler():
    t = threading.Thread(target=scheduler_loop, daemon=True, name="stoplight_loop")
    t.start()
    return t
