"""
Stoplight event calendar — the self-maintaining catalyst registry.

Two files, one role each (mirrors store.py's split-by-access-pattern):
  AI Stoplight/stoplight_events.json   SEED / template — human-authored non-earnings
                                       rows + wiring. Read once to bootstrap.
  stoplight_events.json (repo root)    LIVE — auto-maintained weekly. The engine
                                       reads and writes THIS one, atomically, next
                                       to stoplight_state.json.

`refresh_calendar()` is the weekly maintenance job the scheduler fires (see
scheduler.py). It keeps the LIVE registry's dates current from FREE sources only:

  - earnings rows  -> re-pull next date via yfinance get_earnings_dates()
  - date_status    -> firm 'estimate' to 'confirmed' as a date comes within 30d
  - monthly/weekly -> roll a passed release/sweep date forward to its next slot

HARD RULE — the billed-call firewall: this module NEVER triggers a billed
extraction. Refreshing a *date* is free (yfinance/FRED); *acting* on the event
(the regulatory / silicon web sweeps) is what costs, and that lives in the
extractor path, not here. Keeping the two apart is what makes the dashboard safe
to leave self-sustaining.

Contract: refresh_calendar() NEVER raises — a bad ticker keeps its old date and
is noted in the returned summary. The scheduler loop must survive anything.
"""
import json
import os
from datetime import date, datetime, timedelta

from engine.common import atomic_write_json
from . import store

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_FILE = os.path.join(_BASE_DIR, "stoplight_events.json")
SEED_FILE = os.path.join(_BASE_DIR, "AI Stoplight", "stoplight_events.json")

CONFIRM_WINDOW_DAYS = 30   # a date within this many days reads as 'confirmed'


# --- load / save -------------------------------------------------------------

def load_registry():
    """The LIVE registry, bootstrapping from the seed on first run. Returns a
    dict with an 'events' list; an empty skeleton if neither file is readable."""
    path = LIVE_FILE if os.path.exists(LIVE_FILE) else SEED_FILE
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"events": []}
    # First-run bootstrap: seed was read, materialize the live copy.
    if path == SEED_FILE:
        reg["_bootstrapped_from_seed"] = store.now_iso()
        atomic_write_json(LIVE_FILE, reg)
    return reg


def save_registry(reg):
    atomic_write_json(LIVE_FILE, reg)


def upcoming(days=90, reg=None, today=None):
    """Displayable catalysts (display != false) in the next `days`, soonest
    first — the shape the Catalysts sidebar renders. Recurring rows (monthly
    releases, the FOMC schedule) are PROJECTED forward to fill the window, so a
    single stored row yields all its occurrences without ever duplicating."""
    reg = reg or load_registry()
    today = today or store.now_et().date()
    horizon = today + timedelta(days=days)
    out = []
    for ev in reg.get("events", []):
        if ev.get("display") is False:
            continue
        for d, status in _occurrences(ev, today, horizon):
            out.append({
                "event_id": ev["event_id"],
                "date": d.isoformat(),
                "days_out": (d - today).days,
                "feeds": ev.get("feeds", []),
                "type": ev.get("type"),
                "date_status": status,
                "note": ev.get("note"),
            })
    return sorted(out, key=lambda e: e["date"])


def factor_markers(reg=None, today=None):
    """Per-factor compact-view 'next update' marker, keyed by factor id:
        'D'      a genuine daily/hourly poller (refreshes every day)
        'M/D'    soonest dated catalyst feeding the factor (e.g. '7/22')
        'M/D'    a weekly poller with no discrete catalyst -> its next release day

    Precedence is deliberate: a daily poller is 'D' even when it ALSO has a dated
    catalyst (memory_canary/heavy_haul/copper) — it moves every day regardless, so
    a single future date would understate it. 'Truly daily' is read from the seed's
    _pollers block, NOT registry cadence (regulatory's cadence reads 'daily' but it
    is a weekly sweep — the _pollers list has it right)."""
    reg = reg or load_registry()
    today = today or store.now_et().date()
    pollers = reg.get("_pollers", {})
    daily = set(pollers.get("hourly", [])) | set(pollers.get("daily", []))
    weekly = set(pollers.get("weekly_thursday", []))

    soonest = {}
    for ev in reg.get("events", []):
        d = _parse(ev.get("next_date"))
        if not d or d < today:
            continue
        for fid in ev.get("feeds", []):
            if fid not in soonest or d < soonest[fid]:
                soonest[fid] = d

    out = {}
    for fid in daily | weekly | set(soonest):
        if fid in daily:
            out[fid] = "D"
        elif fid in soonest:
            out[fid] = _fmt_md(soonest[fid])
        elif fid in weekly:
            out[fid] = _fmt_md(_next_thursday(today))
    return out


def _fire_date_of(ev):
    """The scheduler fire date for an event: pull_date (earnings report-session
    guard) when present, else the plain event date."""
    return _parse(ev.get("pull_date") or ev.get("next_date"))


def due_billed_pulls(policies, state=None, today=None, reg=None):
    """Which BILLED extractors are due to fire, from the calendar. Pure detection —
    makes NO billed call; the scheduler decides whether to fire or just notify.

    policies: {factor_id: {settle_days, min_interval_days}}. An extractor is due when
    a feeding event's fire_date has passed since the extractor's stored inputs (its
    `asof`), with two coalescing guards so an armed run never over-fires:
      - settle_days: hold off while a DISCRETE catalyst (earnings/self-gate) is still
        imminent, so an earnings CLUSTER yields ONE pull after the last reporter, not
        one per reporter.
      - min_interval_days: a floor since the last actual fire (for weekly-sweep-fed
        extractors, so a sweep + an earnings in the same week don't double-fire).
    The `asof` baseline means a manual CLI run clears the due flag too (both advance asof)."""
    from .extractors import read_input
    reg = reg or load_registry()
    today = today or store.now_et().date()
    billed = (state or {}).get("billed", {})
    due = []
    for fid, pol in policies.items():
        dated = [(ev, _fire_date_of(ev)) for ev in reg.get("events", [])
                 if fid in ev.get("feeds", [])]
        dated = [(ev, d) for ev, d in dated if d]
        passed = [d for _, d in dated if d <= today]
        if not passed:
            continue
        latest = max(passed)
        # settle: a discrete-catalyst cluster still in progress -> wait for the last one
        settle = pol.get("settle_days", 0)
        if settle and any(ev.get("type") in ("earnings", "self_gate")
                          and today < d <= today + timedelta(days=settle)
                          for ev, d in dated):
            continue
        try:
            baseline = _parse(read_input(fid).get("asof"))
        except Exception:
            baseline = None
        if baseline is not None and latest <= baseline:
            continue   # inputs already refreshed since this event
        # min-interval floor since the last ACTUAL fire (armed-mode coalescing)
        mi = pol.get("min_interval_days", 0)
        lf = (billed.get(fid) or {}).get("last_fired")
        last = _parse(lf[:10]) if lf else None
        if mi and last and (today - last).days < mi:
            continue
        due.append({
            "factor": fid,
            "fire_date": latest.isoformat(),
            "since_asof": baseline.isoformat() if baseline else None,
            "triggers": sorted(ev["event_id"] for ev, d in dated if d == latest),
        })
    return due


# --- Persistent billed-pull QUEUE (roll-proof) -------------------------------
# due_billed_pulls() answers "what does the calendar say is owed RIGHT NOW" — but
# refresh_calendar() rolls a passed earnings date forward to next quarter, so a pull
# that was owed on Fri and never fired silently vanishes from that view on Mon (the
# "gone Friday, Monday rolled it away" gap). The queue below persists an owed pull as
# a discrete (factor, event, fire_date) row and drains it ONLY when its own leg is
# actually refreshed on/after fire_date — per-source, so refreshing VRT's book-to-bill
# does not falsely clear GEV's still-missing available-GW leg. It is the source of
# truth for state['pending_billed'].

def _leg_sources_for_event(factor, ev):
    """The per-source leg id(s) of `factor` that event `ev` refreshes: an earnings
    row -> its ticker's source(s); a weekly_sweep -> the factor's 'sweep'-trigger
    legs (e.g. silicon's OpenAI/Anthropic journalism legs, NOT its earnings legs);
    a self-gate / anything with no mapped leg -> [] (meaning 'the whole-factor asof
    is the fulfillment signal')."""
    from .extractors.run import sources_triggered_by, FACTOR_SOURCE_TRIGGERS
    tkr = ev.get("ticker")
    if tkr:
        return sorted(sources_triggered_by(factor, [tkr]))
    if ev.get("type") == "weekly_sweep":
        return sorted(sid for sid, trig in FACTOR_SOURCE_TRIGGERS.get(factor, {}).items()
                      if trig == "sweep")
    return []


def _leg_fulfilled(factor, sources, fire_date):
    """True iff the owed leg has actually been refreshed on/after fire_date. Per
    source when the event maps to source legs (EVERY mapped source must be fresh);
    else the factor's whole-record `asof` must have advanced to/past fire_date."""
    from .extractors import read_input
    from .extractors.run import leg_refreshed_at
    fd = fire_date if hasattr(fire_date, "year") else _parse(fire_date)
    if not fd:
        return False
    if sources:
        return all((leg_refreshed_at(factor, sid) or date.min) >= fd for sid in sources)
    asof = _parse((read_input(factor) or {}).get("asof"))
    return asof is not None and asof >= fd


def _owed_billed_legs(policies, state=None, today=None, reg=None):
    """Per-(factor, event) billed pulls the LIVE calendar currently shows as owed:
    a feeding event has fired (fire_date <= today) and the leg is not yet fulfilled.
    Unlike due_billed_pulls (one collapsed row per factor), this keeps one row per
    owed event so per-source legs drain independently."""
    from .extractors import read_input
    from .extractors.run import leg_failure
    reg = reg or load_registry()
    today = today or store.now_et().date()
    billed = (state or {}).get("billed", {})
    out = []
    for fid, pol in policies.items():
        lf = (billed.get(fid) or {}).get("last_fired")
        last = _parse(lf[:10]) if lf else None
        mi = pol.get("min_interval_days", 0)
        for ev in reg.get("events", []):
            if fid not in ev.get("feeds", []):
                continue
            fd = _fire_date_of(ev)
            if not fd or fd > today:
                continue
            srcs = _leg_sources_for_event(fid, ev)
            if _leg_fulfilled(fid, srcs, fd):
                continue
            # min-interval floor only guards recurring sweeps (avoid a sweep + an
            # earnings double-firing the same week); discrete catalysts always queue.
            if mi and last and ev.get("type") == "weekly_sweep" and (today - last).days < mi:
                continue
            asof = _parse((read_input(fid) or {}).get("asof"))
            row = {
                "factor": fid, "event_id": ev.get("event_id"),
                "ticker": ev.get("ticker"), "fire_date": fd.isoformat(),
                "sources": srcs, "triggers": [ev.get("event_id")],
                "since_asof": asof.isoformat() if asof else None,
            }
            # The fiscal period this earnings event reports on, pinned as a DATE so a
            # backward-looking leg asks for ONE quarter instead of "the most recent"
            # (which is how a stale Q1 print got written on 07-29). A non-calendar
            # filer can override by carrying `period_end` on its event row.
            if ev.get("type") == "earnings":
                from .extractors.run import quarter_end_before
                row["period_end"] = (ev.get("period_end")
                                     or quarter_end_before(ev.get("next_date") or fd).isoformat())
            # Carry any FAILED last attempt onto the row so the dashboard can alert:
            # this pull ran, cost money, and came back empty — it is still owed, and
            # the human decides whether re-clicking is worth it.
            fails = [dict(source=sid, **f) for sid, f in
                     ((s, leg_failure(fid, s)) for s in srcs) if f]
            if fails:
                row["failures"] = fails
            out.append(row)
    return out


def _dismiss_key(factor, event_id, fire_date):
    return f"{factor}|{event_id}|{fire_date}"


def dismissed_keys(state):
    return {d.get("key") for d in (state or {}).get("dismissed_billed", []) or []}


def dismiss_billed_row(state, factor, event_id, fire_date, note=None, today=None):
    """Manually drop one owed row from the queue — the human's 'this data does not
    exist, stop showing it' switch. Keyed to the SPECIFIC (factor, event, fire_date),
    so next quarter's event is a new key and queues normally; a dismissal cannot
    permanently blind a factor. Returns the updated dismissal list."""
    today = today or store.now_et().date()
    key = _dismiss_key(factor, event_id, fire_date)
    rows = [d for d in (state.get("dismissed_billed") or []) if d.get("key") != key]
    rows.append({"key": key, "factor": factor, "event_id": event_id,
                 "fire_date": fire_date, "at": today.isoformat(), "note": note})
    # Prune old dismissals — a stale key can never match a future event anyway.
    cutoff = (today - timedelta(days=400)).isoformat()
    state["dismissed_billed"] = [d for d in rows if (d.get("fire_date") or "") >= cutoff]
    return state["dismissed_billed"]


def snoozed_map(state):
    return {s.get("key"): s.get("until")
            for s in (state or {}).get("snoozed_billed", []) or []}


def snooze_billed_row(state, factor, event_id, fire_date, days=1, until=None, today=None):
    """Defer a row's next check without giving up on it — "the transcript isn't out,
    ask me again tomorrow". Distinct from a dismissal: the pull is STILL OWED and the
    row stays in the queue; it is simply not actionable until `until`, so the Update
    button will not fire (and not bill) it in the meantime. Returns the until-date."""
    today = today or store.now_et().date()
    until = until or (today + timedelta(days=max(1, int(days)))).isoformat()
    key = _dismiss_key(factor, event_id, fire_date)
    rows = [s for s in (state.get("snoozed_billed") or []) if s.get("key") != key]
    rows.append({"key": key, "factor": factor, "event_id": event_id,
                 "fire_date": fire_date, "until": until, "at": today.isoformat()})
    # An elapsed snooze has done its job — drop it so the row goes live again.
    state["snoozed_billed"] = [s for s in rows
                               if (s.get("until") or "") > today.isoformat()]
    return until


def reconcile_billed_queue(policies, state=None, today=None, reg=None):
    """The PERSISTENT billed-pull queue = still-unfulfilled prior rows UNION the
    freshly-owed rows. A weekly calendar roll can no longer erase an owed-but-unfired
    pull, because a queued row is dropped ONLY when its own leg is actually refreshed
    (per-source), never because its event date rolled past. Returns the new queue,
    sorted by (fire_date, factor). Replaces due_billed_pulls as the pending_billed
    source of truth."""
    from .extractors import read_input  # noqa: F401 (ensures store import path is live)
    today = today or store.now_et().date()
    reg = reg or load_registry()
    dismissed = dismissed_keys(state)
    by_key = {}
    # 1. carry forward prior rows that are STILL unfulfilled — the roll-proof part.
    for it in (state or {}).get("pending_billed", []) or []:
        fid, fd = it.get("factor"), it.get("fire_date")
        if not fid or not fd or _leg_fulfilled(fid, it.get("sources") or [], fd):
            continue
        by_key[(fid, it.get("event_id"), fd)] = it
    # 2. overlay live-owed rows (refreshes since_asof; adds brand-new owes). Preserve
    #    the original queued_at when a row was already present.
    for it in _owed_billed_legs(policies, state, today=today, reg=reg):
        k = (it["factor"], it.get("event_id"), it["fire_date"])
        prior = by_key.get(k, {})
        by_key[k] = {**it, "queued_at": prior.get("queued_at", today.isoformat())}
    # 3. drop anything the human explicitly cleared. Applied LAST so a dismissal wins
    #    over both the carried row and a fresh re-detection of the same event.
    for k in [k for k in by_key if _dismiss_key(k[0], k[1], k[2]) in dismissed]:
        del by_key[k]
    # 4. mark (do NOT remove) rows the human snoozed. They stay owed and visible —
    #    just not actionable until the date passes, at which point the tag simply
    #    stops being attached and the row is live again.
    snoozed, today_iso = snoozed_map(state), today.isoformat()
    for k, row in by_key.items():
        until = snoozed.get(_dismiss_key(k[0], k[1], k[2]))
        if until and until > today_iso:
            row["snoozed_until"] = until
    return sorted(by_key.values(),
                  key=lambda x: (x.get("fire_date") or "", x.get("factor") or ""))


def _fmt_md(d):
    return f"{d.month}/{d.day}"


def _next_thursday(today):
    return today + timedelta(days=(3 - today.weekday()) % 7)  # Thu=3; today if today is Thu


def _occurrences(ev, today, horizon):
    """Every (date, date_status) this event contributes to [today, horizon].
    One-offs yield 0-or-1; recurring rows project forward by their cadence."""
    schedule = ev.get("schedule")
    if schedule:  # FOMC and any explicit date list
        return [(d, _status_for(d, today))
                for d in (_parse(s) for s in schedule) if d and today <= d <= horizon]
    if ev.get("cadence") == "monthly":
        occ, d = [], _parse(ev.get("next_date"))
        while d and d <= horizon:
            if d >= today:
                occ.append((d, _status_for(d, today)))
            d = _add_month(d)
        return occ
    d = _parse(ev.get("next_date"))  # one-off / quarterly earnings / self-gate
    return [(d, ev.get("date_status"))] if d and today <= d <= horizon else []


def _status_for(d, today):
    return "confirmed" if (d - today).days <= CONFIRM_WINDOW_DAYS else "estimate"


# --- the weekly maintenance job ----------------------------------------------

def refresh_calendar(today=None):
    """Re-pull/roll the LIVE registry's dates from free sources. Never raises;
    returns a summary dict for the scheduler log."""
    today = today or store.now_et().date()
    summary = {"refreshed_at": store.now_iso(), "changed": [], "errors": []}
    try:
        reg = load_registry()
    except Exception as e:  # defensive; load_registry already swallows the usual
        return {**summary, "errors": [f"load: {type(e).__name__}: {e}"]}

    for ev in reg.get("events", []):
        try:
            etype = ev.get("type")
            if etype == "earnings" and ev.get("ticker"):
                _refresh_earnings(ev, today, summary)
            elif etype == "data_release" and ev.get("schedule"):
                _roll_scheduled(ev, today, summary)
            elif etype == "data_release":
                _roll_release(ev, today, summary)
            elif etype == "weekly_sweep":
                _roll_weekly(ev, today, summary)
            elif etype == "self_gate":
                _refresh_self_gate(ev, today, summary)
        except Exception as e:
            summary["errors"].append(f"{ev.get('event_id')}: {type(e).__name__}: {e}")

    reg["_last_refresh"] = summary["refreshed_at"]
    try:
        save_registry(reg)
    except Exception as e:
        summary["errors"].append(f"save: {type(e).__name__}: {e}")
    return summary


def _refresh_self_gate(ev, today, summary):
    """Point a self-gate row at the date its feeding factor currently projects.

    A self-gate fires on ELAPSED TIME -- "no new 52-week high for 63 trading bars" --
    so its date is a function of the last 52-week high and RESETS every time a new one
    prints. It cannot be computed once.

    This used to be a comment saying self-gate rows were "computed elsewhere (the
    factor projects them)". Nothing was: no code anywhere wrote a self_gate date.
    Measured 2026-08-13 -- copper's row still read 2026-09-01, computed on 2026-07-18
    off a 2026-06-02 high, while copper had made a new high on 2026-08-05 that pushed
    the real gate out by about two months. The LIGHT was correct throughout (it
    recomputes from data every poll); only the stored date drifted, so the calendar
    advertised a transition that was never going to happen on that day.

    Reads the factor's own projection rather than recomputing here -- the factor owns
    its gate rule (copper 63 bars on HG=F, heavy_haul 63 bars on its custom index) and
    a second implementation would be free to disagree with it.
    """
    factors = (store.load_state() or {}).get("factors") or {}
    for fid in ev.get("feeds") or []:
        gate = ((factors.get(fid) or {}).get("extras") or {}).get("gate_date")
        if not gate:
            continue
        old = ev.get("next_date")
        if gate != old:
            ev["next_date"] = gate
            ev["date_status"] = "computed"
            summary["changed"].append(
                {"event_id": ev["event_id"], "from": old, "to": gate})
        return
    # No projection available yet -- the factor has not run since this shipped. Leave
    # the stored date alone rather than blanking a row the UI is rendering.
    summary["errors"].append(f"{ev.get('event_id')}: no gate_date from {ev.get('feeds')}")


def _refresh_earnings(ev, today, summary):
    nxt, session = _next_earnings(ev["ticker"], today)
    old = ev.get("next_date")
    if nxt and nxt.isoformat() != old:
        ev["next_date"] = nxt.isoformat()
        summary["changed"].append(
            {"event_id": ev["event_id"], "from": old, "to": ev["next_date"]})
    if session:
        ev["session"] = session
    # Firm the status + recompute the billed-PULL date. A pull must never fire
    # before the report lands: BMO (morning) reporters are out before a same-day
    # afternoon pull, so pull_date = the event date; AMC/unknown reporters go +1
    # day so the print has landed and propagated (the same 'let the noise settle'
    # rule as FOMC, skipped only for morning reporters). Display still shows the
    # EVENT date (next_date); pull_date is the scheduler's concern.
    d = _parse(ev.get("next_date"))
    if d:
        ev["date_status"] = _status_for(d, today)
        ev["pull_date"] = (d if ev.get("session") == "bmo"
                           else d + timedelta(days=1)).isoformat()


def _roll_scheduled(ev, today, summary):
    """Point next_date at the next entry in an explicit schedule list (FOMC).
    Does not fabricate dates — once the list is exhausted the date goes stale,
    the honest cue to extend the schedule when the Fed posts the next year."""
    future = sorted(d for d in (_parse(s) for s in ev.get("schedule", []))
                    if d and d >= today)
    if not future:
        return
    old = ev.get("next_date")
    if future[0].isoformat() != old:
        ev["next_date"] = future[0].isoformat()
        summary["changed"].append(
            {"event_id": ev["event_id"], "from": old, "to": ev["next_date"]})
    ev["date_status"] = _status_for(future[0], today)


def _roll_release(ev, today, summary):
    """Roll a passed monthly release forward ~1 month until it is in the future.
    Approximate (PCE/FINRA land ~month-end, not on a fixed day) and already
    estimate-flagged; the FRED/BEA release-calendar pull can firm these later.
    FOMC (~6wk cadence) is left alone — it has a maintained 8/yr schedule."""
    d = _parse(ev.get("next_date"))
    if not d or d >= today:
        return
    if ev.get("cadence") != "monthly":
        return  # only monthly releases self-roll; FOMC stays on its list
    old = ev.get("next_date")
    while d < today:
        d = _add_month(d)
    ev["next_date"] = d.isoformat()
    ev["date_status"] = "estimate"
    summary["changed"].append(
        {"event_id": ev["event_id"], "from": old, "to": ev["next_date"]})


def _roll_weekly(ev, today, summary):
    """Advance a weekly-sweep trigger to its next occurrence (same weekday)."""
    d = _parse(ev.get("next_date"))
    if not d or d >= today:
        return
    old = ev.get("next_date")
    while d < today:
        d += timedelta(days=7)
    ev["next_date"] = d.isoformat()
    summary["changed"].append(
        {"event_id": ev["event_id"], "from": old, "to": ev["next_date"]})


# --- free-source helpers -----------------------------------------------------

def _next_earnings(ticker, today):
    """(date, session) for the next earnings on/after `today`, or (None, None) on
    any failure (import error, empty frame, network) — caller keeps the old values.
    session in {bmo, amc, unknown}, read from the report time yfinance encodes in
    the timestamp: ~08:00 ET = before the open, 16:00 ET = after the close."""
    import yfinance as yf
    ed = yf.Ticker(ticker).get_earnings_dates(limit=16)
    if ed is None or ed.empty:
        return None, None
    future = sorted(ts for ts in ed.index if ts.date() >= today)
    if not future:
        return None, None
    ts = future[0]
    return ts.date(), _session_from_hour(ts.hour)


def _session_from_hour(h):
    if h < 12:
        return "bmo"       # morning / overnight-foreign — out before a same-day pull
    if h >= 15:
        return "amc"       # after ~market close — pull the next day
    return "unknown"       # midday/ambiguous — treated as amc (safe: +1 day)


def _parse(iso):
    try:
        return date.fromisoformat(iso) if iso else None
    except (ValueError, TypeError):
        return None


def _add_month(d):
    """d shifted forward one calendar month, clamped to the month's last day."""
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 28, 29, 30, 31):
        try:
            return date(y, m, min(day, 31))
        except ValueError:
            continue
    return date(y, m, 28)
