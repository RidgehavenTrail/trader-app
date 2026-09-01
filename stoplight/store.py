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
        # A VENDOR WINDOW THAT ROLLS (2026-09-01). Some sources serve only a trailing
        # slice and trim the far end as time passes, so the history gets SHORTER the
        # longer you wait. Measured on the ICE BofA family: every one of five series
        # (BAMLH0A0HYM2, BAMLC0A0CM, BAMLH0A3HYC, BAMLHE00EHYIOAS, BAMLEMCBPIOAS)
        # starts on exactly the same day, 1095 days back -- a rolling three-year licence
        # window, not a discontinued series with a successor. DGS2 comes back from 1976
        # through the identical helper, so it is the vendor, not us.
        #
        # Keyed by SERIES so a second truncating source needs no migration. First write
        # wins: a closed day's print is an observation, and a later pull of the same day
        # is the same observation, not a new one.
        """CREATE TABLE IF NOT EXISTS series_archive (
               series_id   TEXT NOT NULL,
               date        TEXT NOT NULL,   -- the observation's own date
               value       REAL NOT NULL,   -- native units; the caller owns the scale
               first_seen  TEXT NOT NULL,   -- when WE first stored it
               PRIMARY KEY (series_id, date)
           )"""
    )
    con.execute(
        # AS-REPORTED QUARTERLY FINANCIALS, from SEC XBRL (2026-08-30). A closed
        # quarter's operating cash flow and capex are IMMUTABLE facts; capex_pressure
        # used to re-ask yfinance for them on every poll and take whatever rolling
        # window it served, which was 5-7 quarters, one name a quarter behind the
        # rest, and one with a hole in the middle. This table is the same answer the
        # snapshots table above is: keep what a vendor only shows transiently.
        """CREATE TABLE IF NOT EXISTS financials (
               symbol       TEXT NOT NULL,
               period_end   TEXT NOT NULL,   -- fiscal quarter end; the key, with symbol
               period_start TEXT NOT NULL,
               ocf          REAL NOT NULL,
               capex        REAL NOT NULL,   -- stored POSITIVE (an outflow's magnitude)
               fin_lease    REAL NOT NULL DEFAULT 0,  -- finance-lease PRINCIPAL PAYMENTS,
                                             -- the cash leg of "capex including finance
                                             -- leases". 0 when the company files no such
                                             -- tag; fin_lease_filed says which it is.
               fin_lease_filed INTEGER NOT NULL DEFAULT 0,
               ocf_basis    TEXT NOT NULL,   -- 'filed' (a 3-month fact as reported) |
               capex_basis  TEXT NOT NULL,   -- 'derived' (differenced out of the YTD
                                             -- facts; the only way to get Q4, which no
                                             -- 10-Q reports)
               ocf_tag      TEXT,
               capex_tag    TEXT,            -- which us-gaap tag it came from: AMZN
                                             -- switched tags in 2017 and both are kept
               form         TEXT,
               accn         TEXT,
               filed        TEXT,
               fy           INTEGER,
               fp           TEXT,
               restated     INTEGER NOT NULL DEFAULT 0,
               first_seen   TEXT NOT NULL,   -- when WE first stored it, not when filed
               updated_at   TEXT NOT NULL,
               PRIMARY KEY (symbol, period_end)
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
    fcols = [r[1] for r in con.execute("PRAGMA table_info(financials)").fetchall()]
    if fcols and "fin_lease" not in fcols:
        # Added 2026-08-31 when the spigot's priors moved off pinned constants and onto
        # a derived lease-inclusive basis. CREATE TABLE IF NOT EXISTS will not add a
        # column to a table that already exists, so the migration is explicit.
        con.execute("ALTER TABLE financials ADD COLUMN fin_lease REAL NOT NULL DEFAULT 0")
        con.execute("ALTER TABLE financials ADD COLUMN fin_lease_filed INTEGER NOT NULL DEFAULT 0")
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


def archive_series(series_id, points):
    """Accumulate a rolling-window series -> {'added', 'kept'}.

    `points` is an iterable of (date_iso, value). Existing days are LEFT ALONE: the
    vendor re-serving a day we already hold is the same observation, and the whole
    point of the table is to outlive what the vendor will still show us. Nothing is
    ever deleted here -- the archive only grows, which is the one property the source
    does not have."""
    con = _connect()
    now = now_iso()
    added = 0
    try:
        with con:
            for d, v in points:
                cur = con.execute(
                    "INSERT INTO series_archive (series_id, date, value, first_seen) "
                    "VALUES (?,?,?,?) ON CONFLICT(series_id, date) DO NOTHING",
                    (series_id, d, float(v), now))
                added += cur.rowcount or 0
    finally:
        con.close()
    return {"added": added, "kept": added}


def series_archive(series_id):
    """The archived series, OLDEST FIRST -> [(date_iso, value)]."""
    con = _connect()
    try:
        return [(d, v) for d, v in con.execute(
            "SELECT date, value FROM series_archive WHERE series_id=? ORDER BY date",
            (series_id,))]
    finally:
        con.close()


def record_financials(rows):
    """Upsert as-reported quarter rows -> {'added', 'changed', 'unchanged'}.

    A closed quarter does not move, so re-importing the same numbers is a NO-OP and
    the common case. When a value DOES move, SEC itself has accepted a restatement
    (sec._dedupe already resolved which filing wins); the row updates and `first_seen`
    is preserved, so the store still says when we first knew about the period even
    though the figure has since been corrected. This is the opposite tie-break from
    the snapshot log's `keep_first`, and deliberately: a snapshot's duplicates are the
    same observation re-recorded, while these are a company correcting its own filing."""
    con = _connect()
    now = now_iso()
    counts = {"added": 0, "changed": 0, "unchanged": 0}
    try:
        for r in rows:
            key = (r["symbol"], r["period_end"])
            cur = con.execute(
                "SELECT ocf, capex, fin_lease FROM financials WHERE symbol=? "
                "AND period_end=?", key).fetchone()
            if (cur is not None and abs(cur[0] - r["ocf"]) < 1
                    and abs(cur[1] - r["capex"]) < 1
                    and abs((cur[2] or 0) - (r.get("fin_lease") or 0)) < 1):
                counts["unchanged"] += 1
                continue
            counts["changed" if cur is not None else "added"] += 1
            con.execute(
                "INSERT INTO financials (symbol, period_end, period_start, ocf, capex,"
                " fin_lease, fin_lease_filed,"
                " ocf_basis, capex_basis, ocf_tag, capex_tag, form, accn, filed, fy, fp,"
                " restated, first_seen, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(symbol, period_end) DO UPDATE SET"
                "   period_start=excluded.period_start, ocf=excluded.ocf,"
                "   capex=excluded.capex, fin_lease=excluded.fin_lease,"
                "   fin_lease_filed=excluded.fin_lease_filed,"
                "   ocf_basis=excluded.ocf_basis,"
                "   capex_basis=excluded.capex_basis, ocf_tag=excluded.ocf_tag,"
                "   capex_tag=excluded.capex_tag, form=excluded.form, accn=excluded.accn,"
                "   filed=excluded.filed, fy=excluded.fy, fp=excluded.fp,"
                "   restated=excluded.restated, updated_at=excluded.updated_at",
                (r["symbol"], r["period_end"], r["period_start"], r["ocf"], r["capex"],
                 r.get("fin_lease") or 0.0, int(bool(r.get("fin_lease_filed"))),
                 r["ocf_basis"], r["capex_basis"], r.get("ocf_tag"), r.get("capex_tag"),
                 r.get("form"), r.get("accn"), r.get("filed"), r.get("fy"), r.get("fp"),
                 int(bool(r.get("restated"))), now, now))
        con.commit()
    finally:
        con.close()
    return counts


def financials(symbol, limit=None):
    """Stored quarters for one symbol, OLDEST FIRST — the order a TTM is summed in."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT symbol, period_end, period_start, ocf, capex, fin_lease,"
            " fin_lease_filed, ocf_basis, capex_basis, ocf_tag, capex_tag, form, accn,"
            " filed, fy, fp, restated, first_seen FROM financials WHERE symbol=? "
            "ORDER BY period_end", (symbol,)
        ).fetchall()
    finally:
        con.close()
    cols = ("symbol", "period_end", "period_start", "ocf", "capex", "fin_lease",
            "fin_lease_filed", "ocf_basis", "capex_basis", "ocf_tag", "capex_tag",
            "form", "accn", "filed", "fy", "fp", "restated", "first_seen")
    out = [dict(zip(cols, r)) for r in rows]
    return out[-limit:] if limit else out


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
