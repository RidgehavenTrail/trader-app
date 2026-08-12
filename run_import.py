#!/usr/bin/env python3
"""
Reusable newsletter-import CLI — timed, with a token/cost readout.

Why this exists: the Flask /import_newsletter endpoint discards the model `usage`
(it only returns `counts`), so measuring cost through HTTP forces log-scraping. This
calls `newsletter_ingest.ingest_issue()` DIRECTLY, which already returns usage, and
commits to disk exactly like the endpoint (atomic store write, then marker LAST as the
completion signal). Same code path the app uses — just with telemetry.

Usage:
    python run_import.py 260615            # incremental: merge onto the existing store
    python run_import.py 260615 --cold     # cold start: delete _store.json + marker, rebuild
    python run_import.py 260615 --force    # re-run even if already imported (deletes marker)
    python run_import.py 260615 --effort=medium   # override effort (default: omitted -> API's "high")

The filename arg is a substring matched against PDFs in NEWSLETTER_PDF_DIR (so a bare
date like "260615" is enough); it must match exactly one PDF.

--effort is for the Layer-0 cost experiment (see newsletter-ingestion.md "Token/
reasoning-cost investigation" section) — one of low/medium/high/xhigh/max. Every run
also now captures the actual thinking trace (previously 100% discarded) to
NEWSLETTER_EXTRACTED_DIR/thinking_logs/, splits output tokens into thinking vs. final,
and appends a row to NEWSLETTER_EXTRACTED_DIR/cost_experiment_log.jsonl so runs at
different effort levels are directly comparable without hand-copying numbers.
"""
import os
import sys
import copy
import json
import time

# Load the .env next to this script, not one relative to the launch cwd (same
# __file__-anchoring the engine uses) so config survives whatever dir you run from.
from dotenv import load_dotenv
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
sys.path.insert(0, _HERE)
import newsletter_ingest

# Standard Claude Sonnet rates, USD per million tokens. Swap if you're on a
# different tier — the token counts printed below are exact regardless.
RATE_IN, RATE_CACHE_WRITE, RATE_CACHE_READ, RATE_OUT = 3.00, 3.75, 0.30, 15.00

PDF_DIR = os.getenv("NEWSLETTER_PDF_DIR")
EXTRACTED_DIR = os.getenv("NEWSLETTER_EXTRACTED_DIR") or (
    os.path.join(PDF_DIR, "extracted") if PDF_DIR else None)

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _parse_effort(args):
    """--effort=VALUE, validated against the real API-accepted set (verified via
    the live Models API, 2026-07-08 — low/medium/high/xhigh/max, nothing else;
    e.g. no "extra"/"ultracode" — those aren't API effort values, see
    newsletter-ingestion.md). None (the default) omits output_config.effort
    entirely, which is claude-sonnet-5's own "high" default."""
    for a in args:
        if a.startswith("--effort="):
            value = a.split("=", 1)[1].strip().lower()
            if value not in VALID_EFFORTS:
                sys.exit(f"--effort={value!r} is not valid — must be one of {sorted(VALID_EFFORTS)}.")
            return value
    return None


def _atomic_write_json(path, obj):
    """Temp file + os.replace so the destination only ever appears complete."""
    tmp = os.path.join(os.path.dirname(path), ".tmp_" + os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _resolve_pdf(fragment):
    matches = [fn for fn in os.listdir(PDF_DIR)
               if fn.lower().endswith(".pdf") and fragment.lower() in fn.lower()]
    if len(matches) == 0:
        sys.exit(f"No PDF in {PDF_DIR} matching '{fragment}'.")
    if len(matches) > 1:
        sys.exit(f"'{fragment}' is ambiguous — matches {len(matches)}: {matches}")
    return matches[0]


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    fragment = args[0]
    cold = "--cold" in args
    force = "--force" in args
    effort = _parse_effort(args)
    if not PDF_DIR or not EXTRACTED_DIR:
        sys.exit("NEWSLETTER_PDF_DIR not set — check .env.")

    filename = _resolve_pdf(fragment)
    stem = os.path.splitext(filename)[0]
    pdf_path = os.path.join(PDF_DIR, filename)
    store_path = os.path.join(EXTRACTED_DIR, "_store.json")
    marker = os.path.join(EXTRACTED_DIR, stem + ".json")
    os.makedirs(EXTRACTED_DIR, exist_ok=True)

    if cold:
        for p in (store_path, marker):
            if os.path.isfile(p):
                os.remove(p)
                print(f"[cold] deleted {os.path.basename(p)}")
    elif os.path.isfile(marker):
        if not force:
            sys.exit(f"Already imported ({os.path.basename(marker)} exists). "
                     f"Re-run with --force (re-merges onto current store) or --cold (rebuild).")
        os.remove(marker)
        print(f"[force] deleted marker {os.path.basename(marker)} (store kept)")

    # Load existing store for an incremental merge, else start fresh.
    if os.path.isfile(store_path):
        with open(store_path, encoding="utf-8") as f:
            store = json.load(f)
        mode = "incremental (merging onto existing store)"
    else:
        store = newsletter_ingest.new_store()
        mode = "cold start (fresh store)"

    effort_label = effort or "default(high)"
    print(f"Importing: {filename}\nMode: {mode}\nEffort: {effort_label}\n")
    text = newsletter_ingest.extract_pdf_text(pdf_path)

    # Delegate to the SHARED instrumented path (also used by the /import_newsletter
    # endpoint) so the two can't drift — it splits the pipeline for the pristine
    # re-derive receipt, writes store+marker atomically, and records the thinking
    # log, run_archive receipts, and cost_experiment_log row.
    r = newsletter_ingest.ingest_issue_recorded(
        text, store, EXTRACTED_DIR, stem, filename, mode, effort=effort)
    data, counts, usage = r["data"], r["counts"], r["usage"]
    store = r["store"]

    print("=== DONE ===")
    print(f"issue_date : {data.get('issue_date')}")
    print(f"elapsed    : {r['elapsed_s']:.1f}s")
    print(f"counts     : {counts}")
    print(f"store now  : live {len(store.get('live', []))} / archive {len(store.get('archive', []))}")
    print(f"tokens     : in {usage.get('input_tokens')} | cache_write {usage.get('cache_creation_input_tokens')} "
          f"| cache_read {usage.get('cache_read_input_tokens')} | out {usage.get('output_tokens')} "
          f"(thinking {usage.get('thinking_tokens')} / final {usage.get('final_tokens')})")
    print(f"est. cost  : ${r['cost_usd']:.4f}  (Sonnet rates ${RATE_IN}/${RATE_CACHE_WRITE}/${RATE_CACHE_READ}/${RATE_OUT} per M)")
    print(f"thinking log : {r['thinking_log']}")
    print(f"experiment log (appended) : {r['experiment_log']}")


if __name__ == "__main__":
    main()
