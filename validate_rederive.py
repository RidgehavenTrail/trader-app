#!/usr/bin/env python3
"""Offline ($0) validation: re-derive the saved raw_extracts through the NEW derivation
(fill-mechanics backstops) and print resulting statuses. No API, writes nothing."""
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


def latest_raw(frag):
    files = sorted(glob.glob(os.path.join(EXTRACTED, "run_archive", f"*{frag}*__raw_extract.json")))
    return files[-1]


def dump(store, title):
    print(f"\n=== {title} ===")
    for t in store["live"] + store["archive"]:
        sid = t.get("strategy_id", "")
        src = t.get("source_section")
        trig = (t.get("entry") or {}).get("trigger_type")
        print(f"  {str(t.get('status')):8} {sid:24} src={str(src):8} trig={trig}")


store = ni.new_store()
raw608 = json.load(open(latest_raw("260608"), encoding="utf-8"))
store, _, _ = ni.merge_into_store(store, copy.deepcopy(raw608.get("trade_updates", [])))
dump(store, "260608 cold (re-derived)")

raw615 = json.load(open(latest_raw("260615"), encoding="utf-8"))
store, _, _ = ni.merge_into_store(store, copy.deepcopy(raw615.get("trade_updates", [])))
dump(store, "after 260615 merge (re-derived)")
