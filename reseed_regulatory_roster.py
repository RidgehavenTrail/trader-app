"""Re-seed the regulatory roster on the 2026-08-29 criteria.

Usage: python reseed_regulatory_roster.py [--apply]

WHY. The roster was a PINNED BASELINE of three states — California, Ohio, Utah —
carrying no citation, no instrument and no date for any of them, seeded from a
MultiState read on 2026-07-18 and never held to the proof gate every later addition
faced. Audited against the four tests the factor now states, it was right about one:

  * Utah      KEPT     SB 132, state-wide, >=100MW large-load regime.
  * Ohio      DROPPED  the AEP Ohio tariff is one utility's territory (PUCO, Jul 2025).
  * California DROPPED SB 57 orders a CPUC study due 2027; it shifts no costs and
                       requires nothing of anyone.

And five qualifying actions were missing, three of them in force BEFORE the baseline —
which the old sweep could not have found, because it only ever asked for enactments
"beyond those already tracked".

EVERY ENTRY HERE CARRIES ITS PROOF: instrument type, citation, effective date, and a
source URL. That is the whole point — the seed is now held to the same gate as an
addition, so nothing in the roster is there because someone once said so.

NOT A BILLED RUN. These were assembled from public sources (session 49, 2026-08-29);
no extractor call is made and nothing is charged. The next billed sweep will verify
them against its own search and reconcile.

`excluded` records what was looked at and rejected, with the reason. An exclusion that
leaves no trace is indistinguishable from an oversight — and two of these (AEP Ohio,
Dominion GS-5) are the most economically consequential measures in the country.

Dry run by default; --apply writes.
"""
import json
import sys

from stoplight.extractors import SEED, read_input, write_input

# The roster lives in the package SEED (stoplight/extractors/__init__.py), not here:
# one source of truth, so the in-code fallback and the thing this script writes cannot
# drift apart. This script is the applier, not the data.
_SEED = SEED["regulatory"]
ACTIONS, EXCLUDED = _SEED["actions"], _SEED["excluded"]


def main(argv):
    apply = "--apply" in argv
    prev = read_input("regulatory")
    # Reads BOTH shapes, so this prints something true whether it is run against the
    # old pinned baseline or re-run against an already-migrated store.
    old = prev.get("actions") or prev.get("states") or []
    print(f"roster now : {len(old)} entries, basis "
          f"{prev.get('basis') or 'enacted_statutes_only (implied)'}")
    for s in old:
        print(f"   - {s.get('state') or s.get('name')}: "
              f"{s.get('instrument_type') or 'no instrument'} / "
              f"{s.get('citation') or s.get('statute') or 'NO CITATION'} / "
              f"{s.get('effective_date') or s.get('enacted_date') or 'NO DATE'}")
    print(f"\nroster after: {len(ACTIONS)} actions across "
          f"{len({a['state'] for a in ACTIONS})} states")
    for a in ACTIONS:
        print(f"   + {a['state']:<14} {a['instrument_type']:<16} {a['citation']:<38} "
              f"{a['effective_date']}")
    print(f"\nexcluded, recorded: {len(EXCLUDED)}")
    for e in EXCLUDED:
        print(f"   x {e['state']:<14} {e['citation'][:44]:<46} {e['reason'][:44]}")

    if not apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    rec = dict(prev)
    rec.pop("states", None)              # the old shape goes; it meant something else
    rec.pop("enacted_states", None)      # the count is derived in the factor now
    rec.update(actions=ACTIONS, excluded=EXCLUDED,
               basis="any_branch_in_force_statewide",
               roster_changed=True,
               provenance="re-seeded from public sources (session 49, 2026-08-29); "
                          "every entry carries instrument type, citation, effective "
                          "date and URL")
    write_input("regulatory", rec)
    print(f"\nwrote {len(ACTIONS)} actions + {len(EXCLUDED)} recorded exclusions.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
