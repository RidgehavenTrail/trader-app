"""Re-key ONE factor's snapshot rows on the DATA date they report.

Usage: python migrate_snapshots_to_asof.py <factor_id> [--apply]

WHY (2026-08-28). The detail panel's rail is the snapshot log, one row per ET write
date; the Ledger is one row per data date; the panel joins them on `asof`
(stoplight.js: `led.find(x => x.date === (d.asof || d.date))`). OpenRouter publishes
the completed day with a lag, so whether a run sees today's day or yesterday's depends
on the hour it fires — and the join drifted with it:

  * two rail days showed ONE ledger day (08-25 on rail 08-25 + 08-26;
    08-27 on rail 08-27 + 08-28);
  * two RECORDED ledger days were unreachable — no rail day carried their asof
    (08-26, 08-23);
  * the weekday label ran a day ahead of its own data, which matters for this factor
    specifically: it reads red on Saturdays as a calendar artifact, and rail row
    08-23 "Sun" was holding Saturday 08-22's reading.

Going forward `registry.asof_keyed` + `store.record_snapshot(keep_first=)` file the row
under its data day and keep the first capture. This script brings the existing rows
onto that key.

WHAT IT DOES
  1. Re-keys every premium_share snapshot on its payload's `asof` (rows with no asof
     keep their date — pre-2026-08-14 rows already agree).
  2. On collision (two write dates, one data day) keeps the EARLIEST capture: the later
     one re-priced the same day against a floor that had moved. 08-25 keeps 71.5% red,
     not the 49.2% yellow the next morning's run wrote over it.
  3. Restores a data day whose snapshot was clobbered out of existence but whose
     `recorded` ledger row survives. This is RECOVERY, not reconstruction: the ledger
     row was written by the same compute() call whose snapshot was lost, so its share
     and light ARE that reading's value and light. Restored payloads carry a
     `restored_from` marker; it stays in the store and never reaches the frontend
     (history_payloads copies light/metric/state/asof/extras only).

It does not touch the `ledgers` table, any other factor, or any value it did not find
already recorded somewhere.

Dry run by default; --apply writes, after backing the DB up beside itself.
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import date as _date

from stoplight import store

FID = next((a for a in sys.argv[1:] if not a.startswith("-")), "premium_share")


def load(con):
    snaps = [dict(date=d, value=v, payload=p, created_at=c) for d, v, p, c in con.execute(
        "SELECT date, value, payload, created_at FROM snapshots WHERE factor_id=? "
        "ORDER BY date DESC", (FID,))]
    for s in snaps:
        try:
            s["reading"] = json.loads(s["payload"]) if s["payload"] else {}
        except (ValueError, TypeError):
            s["reading"] = {}
        s["asof"] = s["reading"].get("asof") or s["date"]
    ledgers = {d: (b, json.loads(p), c) for d, b, p, c in con.execute(
        "SELECT date, basis, payload, created_at FROM ledgers WHERE factor_id=?", (FID,))}
    return snaps, ledgers


def restored_row(date, led, created_at):
    """A snapshot row rebuilt from a RECORDED ledger day — only fields the ledger
    itself carries. `state` and the arrow are not among them and are left absent
    rather than guessed; the rail reads light/metric/value, all of which are real."""
    return dict(
        date=date, value=led["share"], created_at=created_at,
        reading={
            "id": FID,
            "light": led["light"],
            "value": led["share"],
            "metric": f"{led['share']:.1f}%",
            "asof": date,
            "extras": {
                "commodity_token_share_pct": led["comm_tok"],
                "floor_out_per_m": led["floor"],
                "premium_line_out_per_m": led["line"],
                "source": "OpenRouter rankings-daily + /models",
            },
            "restored_from": f"recorded ledger row, migrate_premium_share_asof "
                             f"{_date.today().isoformat()}",
        })


def plan(snaps, ledgers):
    keep, dropped = {}, []
    for s in sorted(snaps, key=lambda s: s["created_at"]):     # earliest first
        cur = keep.get(s["asof"])
        if cur is None:
            keep[s["asof"]] = s
        else:
            dropped.append((s, cur))
    restored = []
    for date, (basis, led, created_at) in sorted(ledgers.items()):
        if basis == "recorded" and date not in keep:
            # created_at is the LEDGER's — the moment the lost reading was captured.
            row = restored_row(date, led, created_at)
            keep[date] = row
            restored.append(row)
    return keep, dropped, restored


def main():
    apply = "--apply" in sys.argv
    print("factor:", FID)
    con = sqlite3.connect(store.SNAPSHOT_DB)
    try:
        snaps, ledgers = load(con)
        keep, dropped, restored = plan(snaps, ledgers)

        print(f"{len(snaps)} snapshot rows -> {len(keep)} data days "
              f"({len(dropped)} re-priced duplicates dropped, {len(restored)} restored)\n")
        moved = [s for s in snaps if s["asof"] != s["date"]]
        print(f"re-keyed (write date -> data date): {len(moved)}")
        for s in sorted(dropped, key=lambda t: t[0]["date"], reverse=True):
            lost, won = s
            print(f"  DROP  write {lost['date']} (asof {lost['asof']}, {lost['value']}, "
                  f"{lost['created_at']}) - later re-price of a day held by "
                  f"{won['date']} ({won['value']})")
        for r in restored:
            print(f"  RESTORE {r['date']} = {r['value']} {r['reading']['light']} "
                  f"(from recorded ledger)")

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return

        backup = store.SNAPSHOT_DB + f".pre-asof-rekey-{FID}"
        # NEVER overwrite an existing backup. A second --apply is idempotent on the
        # rows but destructive on the safety net: it would copy the ALREADY migrated
        # DB over the only pre-migration copy of it.
        if os.path.exists(backup):
            print("backup already exists, left alone ->", backup)
        else:
            shutil.copy2(store.SNAPSHOT_DB, backup)
            print("backed up ->", backup)
        rows = [(FID, d, r["value"], json.dumps(r["reading"]), r["created_at"])
                for d, r in sorted(keep.items())]
        with con:
            con.execute("DELETE FROM snapshots WHERE factor_id=?", (FID,))
            con.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?)", rows)
        print(f"wrote {len(rows)} rows keyed on the data date.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
