"""
Stoplight persistence — split by access pattern (Tier-0 decision, 2026-07-19):

  stoplight_state.json     current board: one record per factor (light, metric,
                           prev_*, updated_at, error state). Small, read by the
                           Flask endpoint on every dashboard poll, human-readable.
                           Atomic-write JSON like every other store in this repo.

  stoplight_snapshots.db   append-only observation log, SQLite (stdlib). One row
                           per factor per ET day. This is the history yfinance
                           can't provide: Silicon E's 63-bar roll, the memory
                           canary's last-5 reconstruction, and (Phase D) the
                           per-call LLM cost/route/validity log all read from here.

Both files live in the repo root next to the other engine stores (paths anchored
to this package's parent so cwd never matters). Single writer (the scheduler
thread); Flask readers are safe because state writes are atomic and SQLite
handles its own locking.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.common import atomic_write_json

ET = ZoneInfo("America/New_York")

# Shared lock for read-modify-write on stoplight_state.json. Until now the
# scheduler thread was the sole writer; the /run_stoplight_updates endpoint is a
# second one (it recomputes the fired factors' lights + pending after a billed
# pull). Both hold this around their load->modify->save so neither clobbers the
# other's update. RLock so a caller can nest (e.g. save inside a locked block).
_STATE_LOCK = threading.RLock()


def state_lock():
    return _STATE_LOCK

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(_BASE_DIR, "stoplight_state.json")
SNAPSHOT_DB = os.path.join(_BASE_DIR, "stoplight_snapshots.db")


def now_et():
    return datetime.now(ET)


def now_iso():
    return now_et().isoformat(timespec="seconds")


def today_et():
    return now_et().date().isoformat()


# --- current board state -----------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"factors": {}}


def save_state(state):
    atomic_write_json(STATE_FILE, state)


# --- snapshot log ------------------------------------------------------------

def _connect():
    con = sqlite3.connect(SNAPSHOT_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS ledgers (
               factor_id  TEXT NOT NULL,
               date       TEXT NOT NULL,   -- the DATA date (the reading's asof), not
                                           -- the date the row was written: premium_share
                                           -- publishes yesterday's day, so keying by
                                           -- write-date would file every ledger under
                                           -- the wrong day.
               basis      TEXT NOT NULL,   -- 'recorded' (captured that day, at that
                                           -- day's prices) | 'reconstructed' (re-derived
                                           -- later, from a price list that has moved)
               payload    TEXT NOT NULL,   -- the day's ledger JSON
               created_at TEXT NOT NULL,
               PRIMARY KEY (factor_id, date)
           )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
               factor_id  TEXT NOT NULL,
               date       TEXT NOT NULL,   -- ET observation date (YYYY-MM-DD)
               value      REAL,            -- the factor's primary numeric value
               payload    TEXT,            -- full reading JSON at capture time
               created_at TEXT NOT NULL,
               PRIMARY KEY (factor_id, date)
           )"""
    )
    # LLM-call ledger — the AutoRouter cost/quality scoreboard (Phase D). Every
    # billed extractor call lands one row: what model we asked for, what
    # OpenRouter actually routed to, tokens, cost, and whether the output passed
    # its schema. The quality metric is schema_valid rate per model_routed.
    con.execute(
        """CREATE TABLE IF NOT EXISTS llm_calls (
               ts              TEXT NOT NULL,
               extractor       TEXT NOT NULL,
               stage           TEXT,            -- sweep | classify | extract
               model_requested TEXT,
               model_routed    TEXT,            -- what auto-beta actually chose
               prompt_tokens   INTEGER,
               completion_tokens INTEGER,
               cost_usd        REAL,
               schema_valid    INTEGER,         -- 1/0
               note            TEXT,
               raw_response    TEXT             -- verbatim model output (added D-fix)
           )"""
    )
    # Migration: add raw_response to a pre-existing table (older runs get NULL).
    cols = [r[1] for r in con.execute("PRAGMA table_info(llm_calls)").fetchall()]
    if "raw_response" not in cols:
        con.execute("ALTER TABLE llm_calls ADD COLUMN raw_response TEXT")
    return con


def record_llm_call(extractor, stage, model_requested, model_routed,
                    prompt_tokens, completion_tokens, cost_usd, schema_valid,
                    note=None, raw_response=None):
    con = _connect()
    try:
        with con:
            con.execute(
                "INSERT INTO llm_calls (ts, extractor, stage, model_requested, "
                "model_routed, prompt_tokens, completion_tokens, cost_usd, "
                "schema_valid, note, raw_response) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), extractor, stage, model_requested, model_routed,
                 prompt_tokens, completion_tokens, cost_usd,
                 1 if schema_valid else 0, note, raw_response),
            )
    finally:
        con.close()


def record_snapshot(factor_id, value, payload=None, day=None, keep_first=False):
    """Upsert one observation row. Re-runs within the same ET day overwrite (the log
    is one row per factor per day, holding the latest reading).

    `keep_first` INVERTS that, for a factor keyed on its data date rather than the
    write date (see scheduler.run_factor). Two runs that see the same data day are not
    two observations of it: the first ran at the prices the day's light was decided on,
    and every later one is RE-PRICING it. premium_share's premium line is a multiple of
    a floor that deflates fast, so a re-price sweeps whole models across the line — the
    2026-08-25 data day recorded 71.5% red at 23:01 and re-priced to 49.2% YELLOW the
    next morning, which is a different band, not a rounding difference. Without this
    the later run silently overwrites the record, exactly as it did there.

    Same direction rule as record_ledger, for the same reason and on the same key: once
    a data day is captured it is history, not a cell to refresh."""
    con = _connect()
    try:
        with con:
            if keep_first:
                con.execute(
                    "INSERT INTO snapshots VALUES (?,?,?,?,?) "
                    "ON CONFLICT(factor_id, date) DO NOTHING",
                    (factor_id, day or today_et(), value,
                     json.dumps(payload) if payload is not None else None, now_iso()),
                )
            else:
                con.execute(
                    "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
                    (factor_id, day or today_et(), value,
                     json.dumps(payload) if payload is not None else None, now_iso()),
                )
    finally:
        con.close()


def history(factor_id, limit=90):
    """Newest-first list of (date, value) observations."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT date, value FROM snapshots WHERE factor_id=? ORDER BY date DESC LIMIT ?",
            (factor_id, limit),
        ).fetchall()
    finally:
        con.close()
    return rows


def record_ledger(factor_id, date, payload, basis="recorded"):
    """Persist ONE day's per-item ledger. First recording wins.

    This exists because a re-derived ledger is not the same thing as the one that was
    live. premium_share prices models against a floor that deflates fast, so re-running
    an old day with today's price list can move whole models across the premium line —
    2026-08-13 recomputes at 45.9% against a recorded 27.1%, which is a different BAND,
    not a rounding difference. Once a day is captured it must never be silently
    replaced by a later reconstruction.

    The upsert therefore has a direction: a `recorded` row may replace a
    `reconstructed` one (an upgrade — the real thing arriving late), and nothing may
    replace a `recorded` one. A second `recorded` write for the same day is a no-op, so
    the scheduler running twice in a day cannot rewrite history with fresher prices."""
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ledgers (factor_id, date, basis, payload, created_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(factor_id, date) DO UPDATE SET "
            "  basis=excluded.basis, payload=excluded.payload, created_at=excluded.created_at "
            "WHERE ledgers.basis='reconstructed' AND excluded.basis='recorded'",
            (factor_id, date, basis, json.dumps(payload), now_iso()),
        )
        con.commit()
    finally:
        con.close()


def ledger_days(factor_id, limit=30):
    """Newest-first stored ledger days, each with the `basis` it was captured on."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT date, basis, payload FROM ledgers WHERE factor_id=? "
            "ORDER BY date DESC LIMIT ?",
            (factor_id, limit),
        ).fetchall()
    finally:
        con.close()
    out = []
    for date, basis, payload in rows:
        try:
            day = json.loads(payload)
        except (ValueError, TypeError):
            continue
        day["basis"] = basis
        day["date"] = date          # the key is authoritative over the body
        out.append(day)
    return out


def has_ledger_day(factor_id, date):
    """Is this day already captured? Lets the scheduler skip a redundant pull."""
    con = _connect()
    try:
        row = con.execute(
            "SELECT basis FROM ledgers WHERE factor_id=? AND date=?", (factor_id, date)
        ).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def history_payloads(factor_id, limit=30):
    """Newest-first [{date, value, ...reading}] — the FULL reading as captured that
    day, not just its value. `history()` above returns (date, value) pairs because its
    callers do arithmetic on them (the Silicon E 63-bar roll, the memory canary); this
    one exists for DISPLAY, where the day's own light, metric, state and extras are the
    whole point — the detail panel's day rail lets you click back to a past reading and
    see what it said, which a bare value cannot reconstruct.
    A row whose payload never got written (or no longer parses) still returns its date
    and value rather than being dropped: a gap in the rail is information, a missing
    day is a lie about the history's shape."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT date, value, payload FROM snapshots WHERE factor_id=? "
            "ORDER BY date DESC LIMIT ?",
            (factor_id, limit),
        ).fetchall()
    finally:
        con.close()
    out = []
    for date, value, payload in rows:
        day = {"date": date, "value": value}
        if payload:
            try:
                rec = json.loads(payload)
            except (ValueError, TypeError):
                rec = None
            if isinstance(rec, dict):
                for k in ("light", "metric", "state", "asof", "extras"):
                    if k in rec:
                        day[k] = rec[k]
        out.append(day)
    return out


def value_n_back(factor_id, n):
    """The value n observation-days back (0 = latest). None if history is short —
    callers (Silicon E 63-bar roll, memory canary) must handle the warm-up gap."""
    rows = history(factor_id, n + 1)
    return rows[n][1] if len(rows) > n else None
