#!/usr/bin/env python3
"""
stats.py — cumulative cross-run stats for EVERY billed extraction.

Reads the standing cost_experiment_log.jsonl ledger, which every run_import.py run
appends to — across ALL sessions, schemas, and effort levels. Run this FIRST each
session to see the whole billed-run history at a glance, so analysis is cumulative
(all runs) rather than scoped to the latest one.

Offline, $0. Runs as a script so `Bash(python *)` covers it (no `-c` prompt).

Usage:
    python stats.py            # every billed run
    python stats.py 260608     # only runs whose stem matches the fragment

Columns: in = input+cache tokens; out = billed output; reasoning = out - final
(billed thinking); final = the visible JSON tokens.
"""
import os
import sys
import json
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
sys.stdout.reconfigure(encoding="utf-8")

EXTRACTED = os.getenv("NEWSLETTER_EXTRACTED_DIR") or (
    os.path.join(os.getenv("NEWSLETTER_PDF_DIR", ""), "extracted"))


def main():
    frag = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    path = os.path.join(EXTRACTED, "cost_experiment_log.jsonl")
    if not os.path.isfile(path):
        sys.exit(f"No cost_experiment_log.jsonl in {EXTRACTED}")

    rows = []
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not frag or frag in (r.get("stem", "").lower()):
            rows.append(r)
    rows.sort(key=lambda r: r.get("timestamp", ""))
    if not rows:
        sys.exit(f"No billed runs matching '{frag}'.")

    fmt = "%-16s %-7s %-9s %8s %8s %9s %8s %8s %9s"
    print("=" * 96)
    print(f"CUMULATIVE BILLED-RUN STATS — {len(rows)} run(s)" + (f" matching '{frag}'" if frag else ""))
    print("=" * 96)
    print(fmt % ("when", "stem", "effort", "in", "out", "reasoning", "final", "elapsed", "cost$"))

    total_cost = 0.0
    for r in rows:
        tin = (r.get("input_tokens") or 0) + (r.get("cache_creation_input_tokens") or 0) + (r.get("cache_read_input_tokens") or 0)
        tout = r.get("output_tokens") or 0
        fin = r.get("final_tokens") or 0
        cost = r.get("cost_usd") or 0
        total_cost += cost
        print(fmt % (r.get("timestamp", "?"), (r.get("stem", "?")[:6]), r.get("effort", "?"),
                     tin, tout, tout - fin, fin, f"{r.get('elapsed_s', '?')}s", f"${cost:.4f}"))

    print("-" * 96)
    print(f"TOTAL SPEND: ${total_cost:.4f} across {len(rows)} billed run(s)")

    agg = defaultdict(lambda: [0, 0.0, 0, 0])   # effort -> [count, cost, out, reasoning]
    for r in rows:
        a = agg[r.get("effort", "?")]
        tout, fin = (r.get("output_tokens") or 0), (r.get("final_tokens") or 0)
        a[0] += 1; a[1] += (r.get("cost_usd") or 0); a[2] += tout; a[3] += (tout - fin)
    print("\nBy effort (avg per run):")
    for eff in sorted(agg, key=lambda e: {"low": 0, "medium": 1, "default(high)": 2, "high": 2, "xhigh": 3, "max": 4}.get(e, 9)):
        c, cost, out, reasoning = agg[eff]
        print(f"  {eff:14} {c} run(s)  ${cost / c:.4f}  out {out // c} tok  reasoning {reasoning // c} tok "
              f"({100 * reasoning / out if out else 0:.0f}% of out)")


if __name__ == "__main__":
    main()
