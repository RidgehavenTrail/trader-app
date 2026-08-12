#!/usr/bin/env python3
"""Offline ($0) unit test for the section-status taxonomy + fill-mechanics backstops —
derive_status_from_section, enforce_untriggered_conditional, enforce_scaled_planned. No API."""
import copy
import sys
import newsletter_ingest as ni


def status_after(trade):
    t = copy.deepcopy(trade)
    ni.derive_status_from_section(t)        # section forces status only where obvious
    ni.enforce_untriggered_conditional(t)   # backstop: untriggered conditional -> planned
    ni.enforce_scaled_planned(t)            # scaled guard, carried-fill release
    return t["status"]


CASES = [
    ("closed section is authoritative",
     {"source_section": "closed", "status": "open", "entry": {"trigger_type": "market"}}, "closed"),

    ("USDJPY: mis-bucketed 'open' but untriggered sell-stop -> backstop -> planned",
     {"source_section": "open", "status": "open", "entry": {"trigger_type": "stop"},
      "tranches": [], "status_history": [{"date": "2026-06-08", "status": "planned"}]}, "planned"),

    ("review + untriggered 'level' limit, no fill -> planned",
     {"source_section": "review", "status": "open", "entry": {"trigger_type": "level"}}, "planned"),

    ("filled 'level' entry (entry_price set) -> backstop stands down -> open",
     {"source_section": "review", "status": "open", "entry": {"trigger_type": "level"},
      "entry_price": 6.15}, "open"),

    ("defensive-breadth @260615: review, scaled, CARRIED, filled tranche -> open",
     {"source_section": "review", "status": "open", "entry": {"trigger_type": "scaled"},
      "first_seen": "2026-06-08", "last_mentioned": "2026-06-15",
      "tranches": [{"status": "open"}, {"status": "open"}]}, "open"),

    ("defensive-breadth @260608: new, scaled, FIRST appearance, fabricated fill -> planned",
     {"source_section": "new", "status": "open", "entry": {"trigger_type": "scaled"},
      "first_seen": "2026-06-08", "last_mentioned": "2026-06-08",
      "tranches": [{"status": "open", "entry_date": "2026-06-08"}]}, "planned"),

    ("SLV/RKLB: new + market entry (already entered) -> open",
     {"source_section": "new", "status": "open", "entry": {"trigger_type": "market"}}, "open"),

    ("new + planned setup (level, no fill) -> planned",
     {"source_section": "new", "status": "planned", "entry": {"trigger_type": "level"}}, "planned"),

    ("watching -> standing observation (planned)",
     {"source_section": "watching", "status": "open", "entry": {"trigger_type": "market"}}, "planned"),

    ("scaled, carried, only PLANNED tranches (no fill yet) -> still planned",
     {"source_section": "review", "status": "open", "entry": {"trigger_type": "scaled"},
      "first_seen": "2026-06-08", "last_mentioned": "2026-06-15",
      "tranches": [{"status": "planned"}]}, "planned"),

    ("abandoned is definitive — never overridden",
     {"source_section": "open", "status": "abandoned", "entry": {"trigger_type": "stop"}}, "abandoned"),

    ("null section, scaled, has CLOSED tranche -> released, model status kept",
     {"source_section": None, "status": "open", "entry": {"trigger_type": "scaled"},
      "tranches": [{"status": "closed"}, {"status": "open"}]}, "open"),
]


def main():
    fails = 0
    for desc, trade, exp in CASES:
        got = status_after(trade)
        ok = got == exp
        fails += (not ok)
        print(f"[{'ok ' if ok else 'FAIL'}] {desc}\n        got {got!r}, expected {exp!r}")
    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
