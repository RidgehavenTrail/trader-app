"""Seed ONE factor's `ledgers` rows from the snapshot log it derives them from.

Usage: python backfill_ledger_from_snapshots.py <factor_id> [--apply]

WHY (2026-08-29). A factor whose ledger() re-shapes its own SNAPSHOT payload — today
that is `memory_canary`, whose per-ticker revision counts ride in `extras` — can serve
evidence for every day it has ever recorded. But the panel only renders an evidence
view for a day the `ledgers` table holds: `/get_factor_ledger` merges stored days with
a live tail and marks anything not stored `reconstructed`, which paints the pane with a
"re-priced today" banner. For a snapshot-derived ledger that banner would be FALSE —
nothing is re-derived and nothing can move, because the numbers are the ones the light
was decided on, read back out of the row that recorded them.

So these days are `recorded`, and the claim is exact: the payload was written by the
compute() call whose light the row carries. That is the same standard
migrate_snapshots_to_asof.py uses when it restores a snapshot from a recorded ledger,
pointed the other way.

WHAT IT DOES
  Calls the factor's own ledger() (which reads the snapshot log) and writes each day it
  returns into `ledgers` with basis='recorded'. store.record_ledger's direction rule
  still holds — an existing `recorded` day is never overwritten — so re-running is a
  no-op and this can never rewrite a day the scheduler captured live.

  It does NOT touch snapshots, any other factor, or any day the factor's own ledger()
  declines to shape (a row from before the per-ticker extras existed is skipped there,
  and stays skipped here).

DO NOT point this at a factor whose ledger() re-derives from a live source
(premium_share re-prices old token volumes against today's list — those days are
reconstructions and must say so). It is only correct where the ledger reads the record.

Dry run by default; --apply writes.
"""
import sys

from stoplight import store
from stoplight.registry import BY_ID

# The factors whose ledger() reads the SNAPSHOT LOG rather than a live source. A list,
# not a guess: being wrong here writes a reconstruction into the store wearing the word
# `recorded`, which is the one thing the ledgers table exists to prevent.
SNAPSHOT_DERIVED = {"memory_canary"}


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    fid, apply = argv[0], "--apply" in argv[1:]
    if fid not in BY_ID:
        print(f"unknown factor: {fid}")
        return 2
    if fid not in SNAPSHOT_DERIVED:
        print(f"{fid}'s ledger is not snapshot-derived — see the module docstring.")
        return 2

    import importlib
    mod = importlib.import_module(f"stoplight.factors.{BY_ID[fid]['builder']}")
    days = mod.ledger(days=3650)
    if not days:
        print(f"{fid}: ledger() returned no days — nothing to seed.")
        return 0

    have = {d["date"]: d.get("basis") for d in store.ledger_days(fid, limit=3650)}
    fresh = [d for d in days if d["date"] not in have]
    print(f"{fid}: ledger() shaped {len(days)} days "
          f"({days[-1]['date']} .. {days[0]['date']}); "
          f"{len(have)} already stored, {len(fresh)} to write.")
    for d in fresh[:5]:
        print(f"  + {d['date']}  {d.get('metric')}  {d.get('light')}  "
              f"window {d.get('window')}  pool {d.get('pool_down')}/{d.get('pool_total')} down")
    if len(fresh) > 5:
        print(f"  ... and {len(fresh) - 5} more")
    if not apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    for d in fresh:
        store.record_ledger(fid, d["date"], d, basis="recorded")
    print(f"\nwrote {len(fresh)} ledger days for {fid}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
