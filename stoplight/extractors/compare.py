"""
extractors/compare.py — head-to-head model comparison (Phase D experiment).

Runs each extractor under two model configs on the SAME live inputs and reports
outputs side by side: extracted value, accuracy vs the spec-verified ground
truth, cost, the actually-routed model, latency, schema validity. Holds stage-1
constant (auto-beta) so the only variable is the stage-2 model (auto-beta vs
Sonnet) — which the 3 single-call earnings extractors exercise directly.

NON-DESTRUCTIVE: writes go to a temp input store, never the real board. BILLED:
each config makes real OpenRouter calls (all logged to the llm_calls ledger, so
the scoreboard persists beyond this printout).

CLI:  python -m stoplight.extractors.compare [factor ...]   (default: all 4)
"""
import json
import os
import sys
import tempfile
import time

from .. import llm, store
from . import SEED
import stoplight.extractors as ex
from stoplight.extractors import run as runner

# Ground truth = the spec session's verified values (2026-07-18); GEV/VRT have
# not reported since, so live web data should still match. (key, expected).
GROUND_TRUTH = {
    "infra_backlog":   ("vrt_book_to_bill", 2.9),
    "silicon_payback": ("services_rev_b",   86.5),
    "capex_spigot":    ("guidance_yoy_pct", 73),
    # RE-BASELINED 2026-08-29: the key changed (`actions`, a roster of proven state
    # actions) and so did the value. The old ("enacted_states", 3) was ground truth
    # for a rule that counted statutes only and for a seed that was right about one
    # state of three — comparing models against it graded them on reproducing a
    # known-wrong number. 7 states / 8 actions is the audited roster.
    "regulatory":      ("actions",          8),
}
TOL = {"infra_backlog": 0.5, "silicon_payback": 20, "capex_spigot": 15, "regulatory": 1}

CONFIGS = [
    ("auto",   "openrouter/auto-beta", "openrouter/auto-beta"),
    ("sonnet", "openrouter/auto-beta", "anthropic/claude-sonnet-5"),
]


def _ledger_since(rowid):
    con = store._connect()
    try:
        rows = con.execute(
            "SELECT model_routed, cost_usd, schema_valid, note, raw_response "
            "FROM llm_calls WHERE rowid > ? ORDER BY rowid", (rowid,)).fetchall()
    finally:
        con.close()
    return rows


def _run_one(factor, s1, s2):
    con = store._connect()
    start_rowid = con.execute("SELECT COALESCE(MAX(rowid),0) FROM llm_calls").fetchone()[0]
    con.close()

    orig = (ex._INPUTS, llm.STAGE1_MODEL, llm.STAGE2_MODEL)
    ex._INPUTS = tempfile.mktemp(suffix=".json")   # isolated; falls back to SEED for prev
    llm.STAGE1_MODEL, llm.STAGE2_MODEL = s1, s2
    t0 = time.time()
    try:
        summary = runner.run(factor)
        vals = ex.read_input(factor) if summary.get("changed") else dict(SEED[factor])
        out = {"ok": True, "values": vals, "changed": summary.get("changed", True)}
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {e}", "values": None}
    finally:
        secs = round(time.time() - t0, 1)
        if os.path.exists(ex._INPUTS):
            os.remove(ex._INPUTS)
        ex._INPUTS, llm.STAGE1_MODEL, llm.STAGE2_MODEL = orig

    rows = _ledger_since(start_rowid)
    out["secs"] = secs
    out["cost"] = round(sum((r[1] or 0) for r in rows), 5)
    out["routes"] = ",".join(sorted({(r[0] or "?").split("/")[-1] for r in rows}))
    out["valid"] = all(r[2] == 1 for r in rows) if rows else out["ok"]
    out["raw"] = [{"routed": r[0], "valid": r[2], "note": r[3],
                   "response": r[4]} for r in rows]
    return out


def compare(factors):
    results = {}
    print(f"{'factor':16s} {'config':7s} {'routed':22s} {'value':>10s} {'GT?':8s} "
          f"{'cost':>9s} {'s':>6s} valid")
    print("-" * 92)
    totals = {c[0]: 0.0 for c in CONFIGS}
    for factor in factors:
        key, expected = GROUND_TRUTH[factor]
        tol = TOL[factor]
        results[factor] = {}
        for label, s1, s2 in CONFIGS:
            r = _run_one(factor, s1, s2)
            results[factor][label] = r
            totals[label] += r["cost"]
            if not r["ok"]:
                print(f"{factor:16s} {label:7s} {r['routes'][:22]:22s} {'--':>10s} "
                      f"{'FAILED':8s} {'$'+format(r['cost'],'.4f'):>9s} {r['secs']:>6} no")
                continue
            val = r["values"].get(key)
            gt = "MATCH" if (isinstance(val, (int, float)) and abs(val - expected) <= tol) else "DIVERGE"
            vstr = f"{val}" if val is not None else "--"
            print(f"{factor:16s} {label:7s} {r['routes'][:22]:22s} {vstr:>10s} {gt:8s} "
                  f"{'$'+format(r['cost'],'.4f'):>9s} {r['secs']:>6} {'yes' if r['valid'] else 'no'}")
    print("-" * 92)
    for label in totals:
        print(f"  total {label:7s}: ${totals[label]:.4f}")
    print(f"  TOTAL RUN: ${sum(totals.values()):.4f}")

    # --- granular: full extracted values + verbatim raw output per run ---
    print("\n" + "=" * 92 + "\nGRANULAR — full extracted fields + verbatim model output\n" + "=" * 92)
    for factor in factors:
        print(f"\n### {factor}  (ground truth {GROUND_TRUTH[factor][0]}={GROUND_TRUTH[factor][1]})")
        for label in results[factor]:
            r = results[factor][label]
            print(f"\n  [{label}] routed={r['routes']} cost=${r['cost']:.4f} valid={r['valid']}")
            if r["ok"] and r["values"]:
                fields = {k: v for k, v in r["values"].items()
                          if k not in ("asof", "provenance")}
                print(f"    fields: {json.dumps(fields)}")
            elif not r["ok"]:
                print(f"    error: {r['error']}")
            for c in r.get("raw", []):
                body = (c["response"] or "").strip().replace("\n", " ")
                print(f"    raw({(c['routed'] or '?').split('/')[-1]}, valid={c['valid']}): "
                      f"{body[:400]}{'...' if len(body) > 400 else ''}")

    print(f"\nPer-call cost/route/validity/raw persisted in the llm_calls ledger.")


if __name__ == "__main__":
    targets = sys.argv[1:] or list(GROUND_TRUTH.keys())
    compare(targets)
