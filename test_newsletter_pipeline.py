"""
Standalone pipeline test (NOT wired into Flask).

Runs the real end-to-end path for one or more newsletter PDFs under the live-set
model:
    PDF -> pdfplumber text -> extraction prompt (Claude, cached system) -> JSON
         -> Python merge into the persistent store (live / archive / discarded)

Issues are chained in the order given: each issue's model call is fed the store's
current live set, and its output is merged back in. Per-issue extracts and the
rolling store are written to the output dir.

This makes BILLED Anthropic API calls (one per PDF). It needs ANTHROPIC_API_KEY —
copy the main Trader App `.env` into this worktree, or export the key.

Usage:
    python test_newsletter_pipeline.py <pdf1> [pdf2 ...]
    python test_newsletter_pipeline.py --outdir extracted_test <pdf1> [pdf2 ...]
    python test_newsletter_pipeline.py --fresh <pdf1> ...   # ignore any existing store
"""
import os
import sys
import json

from dotenv import load_dotenv
# explicit path: find_dotenv()'s stack-walk fails under some run contexts
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))  # ANTHROPIC_API_KEY

import newsletter_ingest as ni

STORE_NAME = "_store.json"


def run(pdf_paths, outdir, fresh):
    os.makedirs(outdir, exist_ok=True)
    store_path = os.path.join(outdir, STORE_NAME)
    if fresh or not os.path.isfile(store_path):
        store = ni.new_store()
    else:
        store = json.load(open(store_path, encoding="utf-8"))

    for path in pdf_paths:
        if not os.path.isfile(path):
            print(f"  [skip] not found: {path}")
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        print(f"\n=== {stem} ===")
        text = ni.extract_pdf_text(path)
        print(f"  extracted {len(text):,} chars | live set in: {len(store['live'])}")
        try:
            data, store, usage, counts = ni.ingest_issue(text, store)
        except Exception as e:
            print(f"  INGEST FAILED: {type(e).__name__}: {e}")
            print("  (per the atomic-write rule, nothing is written on failure)")
            return 1
        print(f"  issue_date={data.get('issue_date')}  trade_updates={len(data.get('trade_updates', []))}")
        print(f"  store now: live={counts['live']} archive={len(store['archive'])} "
              f"discarded={len(store['discarded'])}  (this issue: +{counts['archived_now']} archived, "
              f"+{counts['discarded_now']} discarded)")
        print(f"  tokens in/out={usage['input_tokens']}/{usage['output_tokens']}  "
              f"cache write/read={usage['cache_creation_input_tokens']}/{usage['cache_read_input_tokens']}")
        # per-issue extract (envelope + this issue's activity) = the completion marker
        with open(os.path.join(outdir, stem + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # rolling store
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, ensure_ascii=False)
    print(f"\ndone. store: {store_path}")
    return 0


def main(argv):
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted_test")
    fresh = False
    args = list(argv)
    out = []
    i = 0
    while i < len(args):
        if args[i] == "--outdir":
            outdir = args[i + 1]; i += 2
        elif args[i] == "--fresh":
            fresh = True; i += 1
        else:
            out.append(args[i]); i += 1
    if not out:
        print(__doc__)
        return 1
    return run(out, outdir, fresh)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
