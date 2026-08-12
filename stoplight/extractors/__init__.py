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
        # enacted_states is now Python-DERIVED = len(states) (2026-07-19 hardening),
        # so the baseline states list must be present or a no-new-candidates run would
        # derive 0. The 3 baseline states are PINNED (statute/enacted_date null = a
        # trusted insider baseline, like PINNED_CAPEX_PRIORS); newly-found states must
        # bring a citation + enacted date. enacted_states kept in sync for the deriver.
        "enacted_states": 3,
        "states": [
            {"name": "California", "statute": None, "enacted_date": None,
             "note": "pinned baseline (MultiState insider)"},
            {"name": "Ohio", "statute": None, "enacted_date": None,
             "note": "pinned baseline (MultiState insider)"},
            {"name": "Utah", "statute": None, "enacted_date": None,
             "note": "pinned baseline (MultiState insider)"},
        ],
        "dcw_blocked_projects": 75, "dcw_prev_blocked": 20,
        "asof": "2026-07-18",
        "provenance": "seed:MultiState insider (3=CA/OH/UT) + Data Center Watch Q1'26"},
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
