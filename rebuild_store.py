#!/usr/bin/env python3
"""rebuild_store.py — OFFLINE ($0) full rebuild of _store.json by replaying the
saved pristine raw_extracts through the CURRENT merge_into_store pipeline, in
issue order. Use to re-derive the store for free after a derivation-layer change
(classify_legs, compute_pnl, etc.) — no API calls. Deterministic: replaying the
same raw_extracts must reproduce the store exactly except for the intended change.
Verified 2026-07-12: the 5-issue cascade reproduces the live store byte-for-byte
except the intended C.18 MU-iron-condor pricing fields.

CAVEAT — rewrites _store.json ONLY, not the per-issue MARKER/edition files
(`<stem>.json`) that Past Editions reads. After a derivation change that affects a
CLOSED trade, refresh the affected issue's marker separately (re-import it, or run
compute_pnl over that marker's trade_updates) — see the session-21 handoff gotcha.

Run:  python rebuild_store.py
"""
import os
import sys
import json
import copy
import glob

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
sys.stdout.reconfigure(encoding="utf-8")

import newsletter_ingest as ni

EXTRACTED = os.getenv("NEWSLETTER_EXTRACTED_DIR") or (
    os.path.join(os.getenv("NEWSLETTER_PDF_DIR", ""), "extracted"))

# Cascade order matters: each issue merges onto the prior store. Full in-window
# set as of 2026-07-13 (260608 -> 260713); extend as new issues are ingested.
ISSUES = ["260608", "260615", "260622", "260629", "260706", "260713"]


def latest_raw(frag):
    files = sorted(glob.glob(os.path.join(EXTRACTED, "run_archive", f"*{frag}*__raw_extract.json")))
    if not files:
        sys.exit(f"no raw_extract for {frag}")
    return files[-1]


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    store = ni.new_store()
    all_flags = []
    for frag in ISSUES:
        raw = json.load(open(latest_raw(frag), encoding="utf-8"))
        updates = copy.deepcopy(raw.get("trade_updates", []))
        store, counts, processed = ni.merge_into_store(
            store, updates, issue_date=raw.get("issue_date"))
        all_flags += [f"[{frag}] {x}" for x in counts["flags"]]
        print(f"{frag}: live={counts['live']} archived_now={counts['archived_now']} "
              f"discarded_now={counts['discarded_now']} flags={counts['flags']}")
    store_path = os.path.join(EXTRACTED, "_store.json")
    atomic_write(store_path, store)
    print(f"\n_store.json written: live {len(store.get('live', []))} / "
          f"archive {len(store.get('archive', []))} / discarded {len(store.get('discarded', []))}")
    if all_flags:
        print("\nALL FLAGS across cascade:")
        for f in all_flags:
            print("  -", f)


if __name__ == "__main__":
    main()
