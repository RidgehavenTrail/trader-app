"""
Extraction stage — the BILLED half of the board (silicon payback #5, infra
backlog #8, regulatory #10, capex spigot #13). Two cleanly-split layers:

- PRIMITIVE STORE (this module): inputs/extracted_inputs.json holds the typed
  numbers each deriver factor reads. Seeded with verified spec values so the 4
  lights are correct with ZERO billed calls; the extractors refresh it.
- EXTRACTORS (llm.py + this package's modules): automated OpenRouter inference
  that reads earnings docs / trackers and WRITES fresh primitives here. Billed;
  gated on explicit go per the prompt-before-billed-runs rule.

Factors NEVER call inference — they read_input() and derive deterministically,
exactly the newsletter model->primitives->Python-derives doctrine (schema §7).
Every stored record carries `asof` (drives the new-tag) and `provenance`.
"""
import json
import os

from engine.common import atomic_write_json

_INPUTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "inputs", "extracted_inputs.json")

# SEED — the spec-session verified primitives, in code so a fresh clone derives
# correct lights with no runtime file and no billed call (mirrors concentration's
# SEED_SEMIS pattern). The runtime inputs/extracted_inputs.json is gitignored;
# an extractor's write_input() overrides the seed per factor. asof drives the
# new-tag; provenance records where each number came from.
SEED = {
    "silicon_payback": {
        "services_rev_b": 86.5, "nvda_dc_qtr_b": 75.2, "nvda_accel_share": 0.73,
        "components": {"openai": 24.5, "anthropic": 47, "copilot": 9, "gemini": 6},
        "asof": "2026-07-18",
        "provenance": "seed:SESSION_DELTA_2026-07-18 (spec-session verified)"},
    "infra_backlog": {
        "vrt_book_to_bill": 2.9, "prev_book_to_bill": 1.4,
        # GEV hardened to STATED primitives (2026-07-19): the glyph is code-resolved
        # from a two-print GW-stock diff OR a management-stated direction — neither
        # can be seeded from an asserted trend, so all null until a billed read lands.
        # VRT still drives the light, so the seed is a correct RED with no GEV glyph.
        "gev_available_gw": None, "gev_total_available_gw": None,
        "gev_prev_total_available_gw": None, "gev_stated_direction": None,
        "asof": "2026-07-18",
        "provenance": "seed:VRT Q4'25 book-to-bill (web-verified); GEV pends billed stock-diff or stated direction"},
    "regulatory": {
        # REBUILT 2026-08-29. What stood here was the origin of the fault: three states
        # (CA/OH/UT) with `statute`/`enacted_date` null, described in this very comment
        # as "PINNED ... a trusted insider baseline" while every LATER addition had to
        # bring a citation and a date. A seed exempt from the gate its own successors
        # face is an assertion, and this one was wrong about two of its three entries —
        # Ohio was a single-utility tariff (AEP Ohio, PUCO Jul 2025) and California a
        # study mandate (SB 57, a CPUC report due 2027 that shifts no costs).
        #
        # Every entry below carries instrument type, citation, effective date and URL,
        # and is held to the same four tests an addition faces: IN FORCE, ANY BRANCH,
        # STATE-WIDE, ABOUT LARGE-LOAD POWER (see factors/regulatory.py). Two of the
        # eight are executive orders, which the previous "only ENACTED statutes count"
        # rule could not see at all.
        #
        # This is also what reseed_regulatory_roster.py writes — imported, not copied,
        # so the seed and the re-seed cannot drift apart.
        "actions": [
            {"state": "Utah", "instrument_type": "statute", "citation": "SB 132",
             "effective_date": "2025-03-25", "statewide": True, "threshold_mw": 100,
             "expires": None,
             "url": "https://www.latitudemedia.com/news/utah-is-taking-a-different-approach-to-new-data-center-load/",
             "note": "Large-load regime: utility has 90 days to assess; if it cannot "
                     "serve without significant investment the load must source its "
                     "own supply."},
            {"state": "Texas", "instrument_type": "statute", "citation": "SB 6",
             "effective_date": "2025-06-21", "statewide": True, "threshold_mw": 75,
             "expires": None,
             "url": "https://www.mcguirewoods.com/client-resources/alerts/2025/7/texas-senate-bill-6-significantly-expands-regulatory-oversight-over-large-loads-in-ercot/",
             "note": "ERCOT large-load interconnection + cost allocation. PUCT rule "
                     "16 TAC 25.194 implements it."},
            {"state": "Minnesota", "instrument_type": "statute", "citation": "HF 16",
             "effective_date": "2025-06-14", "statewide": True, "threshold_mw": None,
             "expires": None,
             "url": "https://www.sierraclub.org/sites/default/files/2026-01/policies-for-data-centers-2026.pdf",
             "note": "Directs the PUC to create a 'very large customer' rate class and "
                     "allocate all attributable costs of service to it."},
            {"state": "Oregon", "instrument_type": "statute",
             "citation": "HB 3546 (POWER Act)", "effective_date": "2025-08-01",
             "statewide": True, "threshold_mw": 20, "expires": None,
             "url": "https://www.afslaw.com/perspectives/alerts/state-regulation-data-centers-2026-shifting-landscape",
             "note": "Separate rate class for large energy use facilities; 10-year PPAs "
                     "and payment for projected use plus new transmission."},
            # FOUND BY THE EXTRACTOR 2026-08-29 (first run under the rebuilt sweep) and
            # verified by hand before being promoted here. The extractor's own entries
            # cited a third-party tracker for both; these carry the official record.
            {"state": "Oklahoma", "instrument_type": "statute",
             "citation": "HB 2992 (Data Center Customer Ratepayer Protection Act of 2026)",
             "effective_date": "2026-07-01", "statewide": True, "threshold_mw": 75,
             "expires": None,
             "binds": "all_utilities",
             "scope_quote": "All Oklahoma electric suppliers subject to Corporation "
                            "Commission jurisdiction, including cooperatives",
             "url": "https://www.okhouse.gov/posts/News-20260513_1",
             "note": "Binds ALL Oklahoma electric suppliers under Corporation Commission "
                     "jurisdiction, including cooperatives. Utilities must create data "
                     "center tariffs with 10-year minimum contracts and credit "
                     "requirements. Approved 2026-05-11, effective 2026-07-01. The "
                     "extractor's scope, date and 75MW threshold all verified."},
            {"state": "New Jersey", "instrument_type": "statute",
             "citation": "S731 / A796 (Data Center Fair Share Act), 3rd reprint",
             "effective_date": "2026-07-07", "statewide": True,
             "binds": "all_utilities",
             "scope_quote": "the Board of Public Utilities shall establish, by order "
                            "for every electric public utility, standards for the "
                            "provision of electricity to large data center customers",
             # NO THRESHOLD IS IN FORCE. The introduced version fixed one at >=100MW
             # maximum monthly demand; the THIRD REPRINT (2026-06-18, the version
             # signed) replaced it with a threshold the BOARD sets, capping the minimum
             # designation at "not greater than 50 megawatts". So 50 is a CEILING on a
             # number that does not exist yet, not the number. Recorded as null rather
             # than picking one -- the coverage figure (50) and the extractor's (50)
             # were both the cap, and the earlier 100 was a superseded draft.
             "threshold_mw": None, "expires": None,
             "url": "https://pub.njleg.gov/Bills/2026/S1000/731_R3.HTM",
             "note": "Signed by Gov. Sherrill 2026-07-07. Every electric public utility "
                     "gets BPU-set standards for large data center customers; large "
                     "loads commit to 85% of requested service for 10 years. Threshold "
                     "pending: the BPU sets it, statutorily capped at <=50MW. Scope "
                     "verified against the enacted 3rd reprint, not coverage."},
            {"state": "New York", "instrument_type": "executive_order",
             "citation": "Executive Order No. 62", "effective_date": "2026-07-14",
             "statewide": True, "threshold_mw": 50, "expires": None,
             "url": "https://www.governor.ny.gov/executive-order/no-62-establishing-temporary-moratorium-data-centers-new-york-while-state-develops",
             "note": "TEMPORARY. Pauses discretionary DEC permits for data centers "
                     ">=50MW until the DPS completes a Generic EIS. No fixed end date "
                     "in the order, so `expires` is null and the sweep re-verifies."},
            {"state": "Texas", "instrument_type": "executive_order",
             "citation": "Governor's data center audit directive",
             "effective_date": "2026-08-03", "statewide": True, "threshold_mw": None,
             "expires": None,
             "url": "https://www.texastribune.org/2026/08/03/texas-data-center-project-audit-greg-abbott/",
             "note": "TEMPORARY. New grid-connection approvals paused pending a "
                     "PUCT/ERCOT audit. Texas holds two live instruments with SB 6."},
        ],
        # Looked at and rejected, with the reason. An exclusion that leaves no trace is
        # indistinguishable from an oversight -- and the first and third of these are
        # among the most economically consequential measures in the country.
        "excluded": [
            # VERIFIED AND DROPPED 2026-08-29. It was carried for a few hours flagged
            # "verify", and the verification killed it: the PUC's final order (voted
            # 04-30, released 05-13) is a MODEL tariff -- guidance to the EDCs, explicitly
            # non-binding, reported as "voluntary". It binds nobody, and any utility that
            # does adopt it files a single-utility tariff, which is the AEP Ohio case.
            # The suspicion in the note was right, which is the argument for writing such
            # notes down rather than rounding an uncertain entry up to a state.
            {"state": "Pennsylvania",
             "citation": "PUC model large-load tariff framework (final order 2026-05-13)",
             "reason": "voluntary - a model tariff giving guidance to utilities, not a "
                       "binding regulation; each utility would file its own",
             "was_counted": True},
            # VERIFIED AND DROPPED 2026-08-29, off the bill text rather than the coverage.
            # SB 253 / HB 1393 (Chapter 1124, approved 05-14, effective 07-01) reads:
            # "directs DOMINION ENERGY VIRGINIA to propose to the Commission ... that
            # certain costs ... are allocated to the utility's customer class ... 25
            # megawatts or greater". One named utility, and a direction to PROPOSE -- the
            # SCC still decides. Appalachian Power appears only in the weatherization
            # pilot. It is the legislative sibling of the Dominion GS-5 class below.
            {"state": "Virginia",
             "citation": "SB 253 / HB 1393 (Chapter 1124, eff. 2026-07-01)",
             "reason": "single utility - directs Dominion Energy Virginia to PROPOSE a "
                       ">=25MW cost allocation to the SCC; binds no other utility",
             "was_counted": True},
            {"state": "Ohio", "citation": "AEP Ohio data center tariff (PUCO, Jul 2025)",
             "reason": "single utility - binds AEP Ohio's territory, not the state",
             "was_counted": True},
            {"state": "California", "citation": "SB 57 (Oct 2025)",
             "reason": "study mandate - directs a CPUC report due 2027, shifts no costs",
             "was_counted": True},
            {"state": "Virginia", "citation": "Dominion GS-5 rate class (SCC, Nov 2025)",
             "reason": "single utility - Dominion only, though that is ~2/3 of Virginia "
                       "and effectively all of Data Center Alley",
             "was_counted": False},
            {"state": "Indiana", "citation": "HB 1210 (Mar 2026)",
             "reason": "not about power - shares 1% of sales-tax savings with localities",
             "was_counted": False},
            {"state": "New York",
             "citation": "Responsible Data Center Development Act",
             "reason": "passed both chambers 2026-06-04 but UNSIGNED - not in force",
             "was_counted": False},
            {"state": "California", "citation": "SB 886",
             "reason": "pending - introduced Jan 2026, not enacted", "was_counted": False},
        ],
        "basis": "any_branch_in_force_statewide",
        # The blocked-project arrow. 75 was itself a SEEDED figure (blocked/quarter) and
        # the only number the leg has ever extracted was a differently-defined 20
        # (Q1 cancellations), so both are held with the quote that produced them.
        "dcw_blocked_projects": 20, "dcw_prev_blocked": 20,
        "dcw_source_quote": None, "dcw_url": None,
        "asof": "2026-08-29",
        "provenance": "audited roster (session 49, 2026-08-29): every entry carries "
                      "instrument type, citation, effective date and URL"},
    "capex_spigot": {
        "guidance_yoy_pct": 73, "asof": "2026-07-18",
        "provenance": "seed:reported-capex basket +73% YoY (check_spigot2.py); guidance runs ahead"},
}


def _load():
    try:
        with open(_INPUTS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def read_input(factor_id):
    """Runtime file first (fresh extractor output), else the in-code SEED."""
    d = _load().get(factor_id) or SEED.get(factor_id)
    if d is None:
        raise ValueError(f"no extracted input or seed for {factor_id}")
    return d


def write_input(factor_id, data):
    """Merge one factor's fresh primitives into the store (extractors call this)."""
    os.makedirs(os.path.dirname(_INPUTS), exist_ok=True)
    all_ = _load()
    all_[factor_id] = data
    atomic_write_json(_INPUTS, all_)
