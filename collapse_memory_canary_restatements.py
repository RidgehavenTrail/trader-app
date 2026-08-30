"""Collapse memory_canary's snapshot log from one row per POLL to one per OBSERVATION.

Usage: python collapse_memory_canary_restatements.py [--apply]

WHY (2026-08-29). yfinance's "last 7 days" is not a rolling window; it is a field the
vendor refreshes in steps. Over this factor's own log, 42 daily rows hold TEN distinct
observations — the longest unchanged for 13 days — so three quarters of the rows are one
observation restated with a fresh date on it. `16751dd` carries `asof` forward and keys
the factor on the observation date, which fixes it GOING FORWARD; this brings the
existing rows onto the same footing so the panel's rail reads honestly all the way back.

WHAT IT DOES
  1. Groups CONSECUTIVE rows by the factor's own `_observation_key` — imported, not
     re-implemented, so the collapse cannot use a different definition of "same
     observation" from the one the light uses. The key is counts + window + basis, and a
     basis change always starts a new observation.
  2. Keeps the FIRST row of each run and deletes the restatements. First-capture wins,
     the same rule `store.record_snapshot(keep_first=)` applies going forward: the first
     sighting is the observation and every later one is a restatement of it.
  3. Stamps each surviving row `observation_age_days: 0` — true by construction, since
     what survives is a first sighting.
  4. Deletes ledger rows whose snapshot day no longer exists, so the two stay joinable.

WHAT IT DOES NOT DO
  It never merges or edits a reading. No light, metric, value or count is altered — the
  surviving rows are byte-identical to what was recorded on the day, minus the added age
  stamp. Nothing is recomputed. A row that is the only one of its run is untouched.

THIS DELETES HISTORY. Every deleted row is a restatement whose surviving twin holds the
same numbers, and the DB is backed up first — but it is still a deletion, and it was an
explicit call (user, 2026-08-29), not a tidy-up.

Dry run by default; --apply writes, after backing the DB up beside itself.
"""
import json
import os
import shutil
import sys

from stoplight import store
from stoplight.factors.memory_canary import _observation_key

FID = "memory_canary"


def runs():
    """[(key, [(date, payload_dict), ...]), ...] — consecutive rows sharing an
    observation. Ordered oldest-first, which is the order they were observed in."""
    con = store._connect()
    try:
        rows = con.execute(
            "SELECT date, payload FROM snapshots WHERE factor_id=? ORDER BY date",
            (FID,)).fetchall()
    finally:
        con.close()
    out = []
    for date, payload in rows:
        try:
            rec = json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            rec = {}
        ex = rec.get("extras") or {}
        # A row we cannot key is its OWN observation — never fold an unreadable row into
        # a neighbour, which would silently delete something we did not understand.
        key = (_observation_key(ex.get("per_ticker"), ex.get("window"),
                                ex.get("basis") or "all_periods")
               if ex.get("per_ticker") else f"__unkeyable__{date}")
        if out and out[-1][0] == key:
            out[-1][1].append((date, rec))
        else:
            out.append((key, [(date, rec)]))
    return out


def main(argv):
    apply = "--apply" in argv
    groups = runs()
    total = sum(len(g) for _, g in groups)
    keep = [g[0] for _, g in groups]
    drop = [d for _, g in groups for d, _ in g[1:]]

    print(f"{FID}: {total} snapshot rows -> {len(groups)} observations "
          f"({len(drop)} restatements to delete)\n")
    for (_, g) in groups:
        first, rec = g[0]
        ex = rec.get("extras") or {}
        pt = ex.get("per_ticker") or {}
        counts = " ".join(f"{k.split('.')[0]} {int(v.get('up7', 0))}/{int(v.get('down7', 0))}"
                          for k, v in sorted(pt.items()))
        span = f"stood {len(g):>2}d" if len(g) > 1 else "  one day"
        print(f"  {first}  {str(rec.get('metric','?')):<8} {span}  {counts}")

    if not drop:
        print("\nnothing to collapse.")
        return 0
    if not apply:
        print(f"\nDRY RUN — would delete {len(drop)} rows. Re-run with --apply.")
        return 0

    backup = store.SNAPSHOT_DB + ".pre-observation-collapse"
    if os.path.exists(backup):
        print("backup already exists, left alone ->", backup)
    else:
        shutil.copy2(store.SNAPSHOT_DB, backup)
        print("backed up ->", backup)

    con = store._connect()
    try:
        con.executemany("DELETE FROM snapshots WHERE factor_id=? AND date=?",
                        [(FID, d) for d in drop])
        # The surviving rows ARE first sightings, so an age of 0 is a fact about them,
        # not a guess. Written into the payload the panel reads.
        for date, rec in keep:
            ex = rec.setdefault("extras", {})
            ex.setdefault("observation_age_days", 0)
            ex.setdefault("restated", False)
            con.execute("UPDATE snapshots SET payload=? WHERE factor_id=? AND date=?",
                        (json.dumps(rec), FID, date))
        # Ledger rows are keyed on the same date; one whose snapshot is gone is
        # unreachable from the rail, so it goes with it.
        orphans = con.execute(
            "DELETE FROM ledgers WHERE factor_id=? AND date NOT IN "
            "(SELECT date FROM snapshots WHERE factor_id=?)", (FID, FID)).rowcount
        con.commit()
    finally:
        con.close()
    print(f"deleted {len(drop)} restatement rows, stamped {len(keep)} survivors, "
          f"removed {orphans} orphaned ledger rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
