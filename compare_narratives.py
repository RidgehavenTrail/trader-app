#!/usr/bin/env python3
"""
compare_narratives.py — side-by-side review of the AMBIGUOUS / NARRATIVE fields
across effort levels, to test whether a higher-reasoning engine writes BETTER
narratives. This is the ONE field-class where §7.4 says effort MIGHT earn its cost
(thesis prose, notable_flow_summary, analysis summaries, linked_theme) — unlike the
mechanical/derived fields, where the token test already proved effort does not.

Pure OFFLINE analysis — no API calls. Reads the pristine `raw_extract.json` snapshots
that run_import.py auto-saves to run_archive/ (one per run, tagged stem/effort/stamp)
plus the token/cost readout from cost_experiment_log.jsonl. So it runs for $0 against
whatever billed extracts already exist, and re-runs freely as more efforts are added.

Usage:
    python compare_narratives.py 260608           # compare every effort run of that stem
"""
import os
import re
import sys
import json
import glob

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

EXTRACTED = os.getenv("NEWSLETTER_EXTRACTED_DIR") or (
    os.path.join(os.getenv("NEWSLETTER_PDF_DIR", ""), "extracted"))

# low -> max, for stable left-to-right ordering
_EFFORT_ORDER = {"low": 0, "medium": 1, "default(high)": 2, "high": 2, "xhigh": 3, "max": 4}


def _load_cost_log():
    p = os.path.join(EXTRACTED, "cost_experiment_log.jsonl")
    rows = {}
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[r.get("timestamp")] = r
    return rows


def _trade_key(t):
    """Stable key to match the SAME trade across runs (ids drift; underlying/basket
    don't)."""
    u = t.get("underlying")
    if u:
        return u.upper()
    b = t.get("basket")
    if b:
        return "basket:" + "+".join(sorted((x.get("ticker") or "").upper() for x in b))
    return t.get("id") or "?"


def _narratives(data):
    env = {
        "notable_flow_summary": data.get("notable_flow_summary"),
        "analysis": [f"{a.get('title')}: {a.get('summary')}" for a in (data.get("analysis_features") or [])],
    }
    trades = {}
    for t in (data.get("trade_updates") or []):
        th = t.get("thesis") or {}
        if not isinstance(th, dict):
            th = {"rationale": th}   # tolerate a legacy flat-string thesis
        trades[_trade_key(t)] = {
            "rationale": th.get("rationale"),
            "positioning": th.get("positioning"),
            "linked_theme": t.get("linked_theme"),
            "campaign_title": t.get("campaign_title"),
        }
    return env, trades


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    frag = args[0]

    files = glob.glob(os.path.join(EXTRACTED, "run_archive", f"*{frag}*__raw_extract.json"))
    runs = []   # (effort, timestamp, path)
    for f in files:
        m = re.search(r"__effort-(.+?)__(\d{8}-\d{6})__raw_extract\.json$", os.path.basename(f))
        if m:
            runs.append((m.group(1), m.group(2), f))
    if not runs:
        sys.exit(f"No raw_extract snapshots matching '{frag}' in {EXTRACTED}/run_archive/.")
    runs.sort(key=lambda r: (_EFFORT_ORDER.get(r[0], 9), r[1]))

    # Label each run by effort; disambiguate repeats of the SAME effort with #N so the
    # run-to-run noise floor (e.g. low#1 vs low#2) sits side by side too.
    from collections import Counter
    total = Counter(r[0] for r in runs)
    seen = Counter()
    efforts, label_ts, loaded = [], {}, {}
    for eff, ts, f in runs:
        seen[eff] += 1
        lab = f"{eff}#{seen[eff]}" if total[eff] > 1 else eff
        efforts.append(lab)
        label_ts[lab] = ts
        loaded[lab] = json.load(open(f, encoding="utf-8"))
    cost = _load_cost_log()

    line = "=" * 92
    print(line)
    print(f"NARRATIVE COMPARISON — '{frag}' — efforts: {', '.join(efforts)}")
    print(line)

    print("\nTOKENS & COST per effort  (in = input+cache, reasoning = out-final billed thinking):")
    print("  %-14s %9s %9s %10s %10s %9s %8s" %
          ("effort", "in", "out", "reasoning", "consumed", "elapsed", "cost$"))
    for e in efforts:
        r = cost.get(label_ts[e], {})
        tin = (r.get("input_tokens") or 0) + (r.get("cache_creation_input_tokens") or 0) + (r.get("cache_read_input_tokens") or 0)
        tout = r.get("output_tokens") or 0
        reasoning = tout - (r.get("final_tokens") or 0)
        print("  %-14s %9s %9s %10s %10s %8ss %8s" %
              (e, tin, tout, reasoning, tin + tout, r.get("elapsed_s", "?"), r.get("cost_usd", "?")))

    def _block(title, getter):
        print("\n" + "-" * 92 + f"\n{title}\n" + "-" * 92)
        return getter

    _block("ENVELOPE NARRATIVES", None)
    for field in ("notable_flow_summary", "analysis"):
        print(f"\n### {field} ###")
        for e in efforts:
            env, _ = _narratives(loaded[e])
            v = env.get(field)
            if isinstance(v, list):
                v = ("\n        ".join(v)) if v else None
            print(f"  [{e}]\n     {v}\n")

    _block("PER-TRADE NARRATIVES  (thesis.rationale / positioning / linked_theme / campaign_title)", None)
    merged = {}
    for e in efforts:
        _, tr = _narratives(loaded[e])
        for k, fields in tr.items():
            merged.setdefault(k, {})[e] = fields
    for k in sorted(merged):
        print(f"\n### {k} ###")
        for field in ("rationale", "positioning", "linked_theme", "campaign_title"):
            vals = {e: (merged[k].get(e) or {}).get(field) for e in efforts}
            if not any(vals.values()):
                continue
            print(f"  -- {field} --")
            for e in efforts:
                print(f"     [{e}] {vals[e]}")


if __name__ == "__main__":
    main()
