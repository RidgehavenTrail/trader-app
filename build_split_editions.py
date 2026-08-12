#!/usr/bin/env python3
"""build_split_editions.py — one-off, OFFLINE ($0) regeneration of the per-issue
edition files with the POST-SPLIT trade shape (fixes the missing split-record gap,
2026-07-10). Rebuilds the store cascade from the saved pristine raw_extracts and
rewrites ONLY the two edition files; `_store.json` is left untouched.

Run:  python build_split_editions.py
No API calls — merge_into_store/normalize_derived/split_tranches/compute_pnl are
pure Python, so this is free and deterministic.
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

# Cascade order matters: 260615 merges onto 260608's store.
ISSUES = [
    ("260608", "260608 _Trillion club_ unwind _ The Crown Macro Letter.json"),
    ("260615", "260615 The Space Trade _ The Crown Macro Letter.json"),
]


def latest_raw(frag):
    files = sorted(glob.glob(os.path.join(EXTRACTED, "run_archive", f"*{frag}*__raw_extract.json")))
    if not files:
        sys.exit(f"no raw_extract for {frag}")
    return files[-1]


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    store = ni.new_store()
    for frag, edition_name in ISSUES:
        raw = json.load(open(latest_raw(frag), encoding="utf-8"))
        updates = copy.deepcopy(raw.get("trade_updates", []))
        store, counts, processed = ni.merge_into_store(
            store, updates, issue_date=raw.get("issue_date"))
        edition = {k: v for k, v in raw.items() if k != "trade_updates"}
        edition["trade_updates"] = processed
        atomic_write(os.path.join(EXTRACTED, edition_name), edition)
        coppers = [t.get("id") for t in processed if "hg-copper" in (t.get("id") or "")]
        print(f"{frag}: {len(processed)} trades  ->  {edition_name}")
        print(f"   copper records: {coppers}")
        print(f"   counts: live={counts['live']} archived_now={counts['archived_now']} flags={counts['flags']}")


if __name__ == "__main__":
    main()
