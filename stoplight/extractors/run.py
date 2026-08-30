"""
Extractor runners (Phase D) — automated inference that refreshes the 4
extraction factors' primitives via write_input(). BILLED: each function makes
OpenRouter calls (llm.extract_json logs cost/route/validity). Gated on explicit
go per the prompt-before-billed-runs rule.

CLI:  python -m stoplight.extractors.run <regulatory|infra_backlog|silicon_payback|capex_spigot|all>
Each returns a summary dict; primitives are only written when validation passes
(a validation failure keeps the prior seed/primitive and is logged).
"""
import json
import sys
from datetime import date

from .. import llm
from . import schemas, read_input, write_input

def _today():
    """Today, evaluated PER CALL — never cached at import.

    This was a module-level constant, which froze at whatever day the ENGINE
    BOOTED. The engine runs for days, so every extraction stamped the boot date:
    a pull that ran 07-29 08:46 wrote `asof/refreshed_at: 2026-07-28`. Cosmetic
    until the billed QUEUE started keying fulfillment off those stamps — then a
    same-day event could never be satisfied (stamp 07-28 < fire_date 07-29), so
    the row stayed queued and every Update click re-ran (and re-paid for) it.
    """
    return date.today().isoformat()


_QUARTER_ENDS = ((12, 31), (9, 30), (6, 30), (3, 31))


def quarter_end_before(d):
    """The calendar quarter-end strictly BEFORE `d` — i.e. the period a report filed
    on that date covers, for a calendar-year filer. Returns a date.

    Pinned as a DATE, not a fiscal LABEL, on purpose: labels are company-specific
    (MSFT's FY ends in June, ORCL's in May, NVDA's runs a full year ahead), but "the
    quarter that ended 2026-06-30" is unambiguous for everyone. A non-calendar filer
    can override this by carrying an explicit `period_end` on its calendar event."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    for m, day in _QUARTER_ENDS:
        qe = date(d.year, m, day)
        if qe < d:
            return qe
    return date(d.year - 1, 12, 31)

# --- Regulatory ------------------------------------------------------------
# The legacy single-stage run_regulatory() lived here and was DELETED 2026-08-29. It
# encoded the criteria this factor was rebuilt to remove ("Only ENACTED statutes count"
# — which silently excluded executive orders and commission rules), and it was still
# reachable from the CLI and the compare harness. A superseded rule left executable is
# a rule that will be executed; this repo has written that lesson down more than once.
# The live path is run_regulatory_multi(), below.

# --- Earnings extractors (single-call, STAGE2) -----------------------------

_INFRA_SYS = (
    "You extract two datacenter-infrastructure demand signals. Using the web "
    "search results as primary source: (1) Vertiv's (VRT) most recent quarterly "
    "BOOK-TO-BILL ratio = new orders booked / billings-shipments in the period "
    "(a flow ratio, typically 1-3x) — NOT total backlog (a stock, in $B) and NOT "
    "backlog growth; VRT usually reports the ratio directly on its earnings call. "
    "(2) GE Vernova's (GEV) available-GW trend — is uncommitted future gas/grid "
    "capacity shrinking, flat, or growing? Quote the source sentence. Respond "
    'ONLY with JSON: {"vrt_book_to_bill": float, "gev_available_gw_trend": '
    '"shrinking"|"flat"|"growing", "source_quote": str, "url": str}.'
)
_INFRA_QUERY = ("Vertiv VRT latest quarter book-to-bill ratio earnings; "
                "GE Vernova GEV available capacity backlog gigawatts sold out 2026")

_SILICON_SYS = (
    "You extract AI SERVICES revenue run-rates to compute a silicon-payback ratio.\n"
    "TODAY IS {today}. 'Latest' always means the most recent data available as of "
    "today — never an older period.\n"
    "RULE: SERVICES, not rails — count seat/subscription/model-sale revenue; EXCLUDE "
    "raw compute consumption. EXCLUDE Amazon entirely (sells rails; Bedrock/Nova not "
    "broken out).\n"
    "Extract each component as an ANNUALIZED run-rate in $B, using the web results as "
    "primary source (these are 2026 figures):\n"
    "- openai_rev_b: OpenAI (private; journalism only — The Information, Reuters, "
    "Bloomberg, FT, Epoch AI tracker). Recently ~mid-$20s B.\n"
    "- anthropic_rev_b: Anthropic — DISPUTED swing input, ranged $9B->$30B->$47B "
    "across 2026; take the most recent widely-reported run-rate in the results.\n"
    "- copilot_rev_b: MSFT discloses a large '~$37B AI run rate' but that is MOSTLY "
    "Azure consumption (RAILS) — do NOT use it. STRIP to Copilot only: M365 Copilot "
    "(~$7B at 20M+ seats) + GitHub Copilot (~$1.5-2B). So ~$9B.\n"
    "- gemini_rev_b: GOOGL Gemini — not disclosed directly; build up from Gemini "
    "Enterprise seat pricing ($30/$50 seat x ~8M seats) + consumer subs (~$1.2B). "
    "~mid-single-digit $B.\n"
    "For the DENOMINATOR (NVIDIA — its fiscal year runs ~1 year AHEAD of the calendar, "
    "so FY2027 quarters are reported during calendar 2026):\n"
    "- nvda_dc_qtr_b: NVIDIA data-center segment revenue for its MOST RECENTLY REPORTED "
    "fiscal quarter as of today — the single latest quarter NVIDIA has announced, NOT "
    "an older one. Single quarter only, in $B (it will be x4'd; do NOT annualize).\n"
    "- nvda_dc_quarter: the fiscal-quarter label AND its report/announcement date for "
    "the figure above, e.g. 'Q1 FY2027, reported 2026-05-28'. REQUIRED — this is how we "
    "verify you used the latest quarter, not a stale one.\n"
    "- nvda_accel_share: NVIDIA's share of the AI accelerator market (0-1, ~0.70-0.75; "
    "re-check, it drifts down as custom silicon grows).\n"
    "Where a component is not in the results, use the most recent reported figure from "
    "the guidance above. Respond ONLY with JSON: {\"openai_rev_b\": float, "
    "\"anthropic_rev_b\": float, \"copilot_rev_b\": float, \"gemini_rev_b\": float, "
    "\"nvda_dc_qtr_b\": float, \"nvda_dc_quarter\": str, \"nvda_accel_share\": float}."
)
_SILICON_QUERY = (
    "OpenAI annualized revenue run rate 2026; Anthropic annualized revenue run rate "
    "2026 latest; Microsoft M365 Copilot GitHub Copilot revenue seats; Google Gemini "
    "revenue estimate enterprise seats; NVIDIA MOST RECENT quarterly earnings 2026 "
    "newest quarter data center segment revenue; NVIDIA AI accelerator GPU market share 2026")

_SPIGOT_SYS = (
    "You extract hyperscaler forward capex GUIDANCE growth. Using the web results, "
    "determine the aggregate year-over-year growth (percent) of forward capital-"
    "expenditure GUIDANCE across MSFT, GOOGL, AMZN, META, ORCL (their stated planned "
    "capex for the coming year vs the prior year). Respond ONLY with JSON: "
    '{"guidance_yoy_pct": float, "per_name": {"MSFT": float, "GOOGL": float, '
    '"AMZN": float, "META": float, "ORCL": float}}.'
)
_SPIGOT_QUERY = ("Microsoft Google Amazon Meta Oracle 2026 capex guidance forecast "
                 "capital expenditure year over year growth datacenter AI spending")

_EARNINGS = {
    "infra_backlog":   {"system": _INFRA_SYS,   "query": _INFRA_QUERY,
                        "validate": schemas.validate_infra_backlog, "max_results": 5},
    "silicon_payback": {"system": _SILICON_SYS, "query": _SILICON_QUERY,
                        "validate": schemas.validate_silicon_payback, "max_results": 10},
    "capex_spigot":    {"system": _SPIGOT_SYS,  "query": _SPIGOT_QUERY,
                        "validate": schemas.validate_capex_spigot, "max_results": 8},
}


def run_earnings(factor):
    cfg = _EARNINGS[factor]
    system = cfg["system"].replace("{today}", _today())   # anchor "latest" to today
    data, meta = llm.extract_json(
        factor, "extract",
        [{"role": "system", "content": system},
         {"role": "user", "content": cfg["query"]}],
        model=llm.STAGE2_MODEL, validate=cfg["validate"], web_search=True,
        max_results=cfg["max_results"])
    prev = read_input(factor)
    rec = {**data, "asof": _today(), "provenance": f"extractor:{factor} {_today()}"}
    if factor == "infra_backlog":
        rec["prev_book_to_bill"] = prev.get("vrt_book_to_bill")
    write_input(factor, rec)
    return {"factor": factor, "changed": True, "cost": meta["cost_usd"],
            "route": meta["model_routed"]}


# --- Per-source refresh (STOPLIGHT_SCHEDULING §1-2 source-oriented model) --------
# When a company reports, ONLY its source(s) refresh; every other leg carries its
# prior value + asof. So a GOOGL earnings pull touches the gemini leg of silicon and
# the GOOGL leg of capex — NOT NVDA's datacenter number or MSFT's Copilot number,
# which don't change until those names report. 'sweep' = not earnings-driven (weekly
# journalism / statute sweep), refreshed on its own weekly trigger, never here.
FACTOR_SOURCE_TRIGGERS = {
    "silicon_payback": {"openai": "sweep", "anthropic": "sweep", "copilot": "MSFT",
                        "gemini": "GOOGL", "nvda_dc": "NVDA", "nvda_share": "NVDA"},
    "capex_spigot":    {"MSFT": "MSFT", "GOOGL": "GOOGL", "AMZN": "AMZN",
                        "META": "META", "ORCL": "ORCL"},
    "infra_backlog":   {"vrt_btb": "VRT", "gev_gw": "GEV"},
    "regulatory":      {},   # statute + DCW sweep, not earnings-fed
}
# The record key each silicon source contributes — used to confirm a carried leg
# actually holds a usable prior value before its pull is skipped.
_SILICON_KEYS = {"openai": "value_b", "anthropic": "value_b", "copilot": "value_b",
                 "gemini": "value_b", "nvda_dc": "dc_qtr_b", "nvda_share": "accel_share"}


def sources_triggered_by(factor, tickers):
    """Source ids of `factor` whose trigger ticker is in `tickers` (a set/iterable)."""
    tickers = set(tickers)
    return {sid for sid, t in FACTOR_SOURCE_TRIGGERS.get(factor, {}).items()
            if t in tickers}


# Where each factor stores its per-leg records (silicon/infra keep them under
# 'sources', capex under 'per_company'). Used by leg_refreshed_at() so the billed
# queue can confirm a specific leg was actually refreshed — the per-source drain.
_PER_LEG_CONTAINER = {"silicon_payback": "sources", "infra_backlog": "sources",
                      "capex_spigot": "per_company"}


def leg_refreshed_at(factor, source_id):
    """The date `factor`'s `source_id` leg last pulled data SUCCESSFULLY.

    ONLY `refreshed_at` counts — a rejected pull does NOT satisfy the billed queue
    (user, 2026-07-29: "it should only clear if it successfully pulls down data").
    Spend is gated by the human clicking Update, so a stuck row cannot run away on
    its own; leaving it queued and ALERTING is strictly better than clearing it and
    silently losing the miss. `attempted_at`/`reason` are recorded for that alert —
    see leg_failure() — never to drain the row.

    Legacy fallback: a leg with no stamps at all and no failure marker falls back to
    the record's `asof`, so a seed that predates per-leg stamping is not read as
    forever-unfulfilled. A leg that HAS been attempted never takes that fallback —
    the record's `asof` advances on every run, including failed ones, and would
    otherwise mark a failure as fulfilled."""
    rec = read_input(factor) or {}
    leg = (rec.get(_PER_LEG_CONTAINER.get(factor, "sources")) or {}).get(source_id)
    if not isinstance(leg, dict) or not leg:
        return None
    stamp = leg.get("refreshed_at")
    if not stamp and not leg.get("attempted_at") and not leg.get("failed"):
        stamp = rec.get("asof")
    try:
        return date.fromisoformat(str(stamp)[:10]) if stamp else None
    except (ValueError, TypeError):
        return None


def leg_failure(factor, source_id):
    """{'at', 'reason'} when this leg's last billed attempt FAILED, else None.
    Drives the dashboard alert; never affects whether the queue row drains."""
    rec = read_input(factor) or {}
    leg = (rec.get(_PER_LEG_CONTAINER.get(factor, "sources")) or {}).get(source_id)
    if not isinstance(leg, dict) or not leg.get("attempted_at"):
        return None
    if leg.get("refreshed_at", "") >= leg["attempted_at"]:
        return None                      # a later success supersedes the failure
    # kind matters to the human: 'unavailable' means WAIT (the world hasn't published
    # it yet), 'rejected' means the answer was bad. Different next action.
    return {"at": leg["attempted_at"], "reason": leg.get("reason") or "extraction failed",
            "cost": leg.get("cost") or 0,          # cumulative spend chasing this leg
            "attempts": leg.get("attempts") or 1,
            "kind": "unavailable" if leg.get("unavailable") else "rejected",
            "why": leg.get("unavailable_reason"),   # not_published | not_disclosed
            "period_end": leg.get("period_end")}


# --- Silicon payback: PER-SOURCE multi-search (spec STOPLIGHT_SCHEDULING §5) ----
# One focused search per source (no multiplexing = no dilution). Each leg returns
# its own number + citation; Python assembles numerator/denominator/ratio.
_SILICON_SOURCES = [
    {"id": "openai", "field": "value_b", "max_results": 5,
     "system": ("Today is {today}. Report OpenAI's most recent ANNUALIZED revenue "
                "run-rate in $B (services). Use the web results (The Information, "
                "Reuters, Bloomberg, Epoch AI). State published_at — the source's OWN "
                "publication date (YYYY-MM-DD), not today's; null if it carries none. "
                "Respond ONLY with JSON: "
                '{"value_b": float, "source": str, "url": str, "published_at": str}.'),
     "query": "OpenAI annualized revenue run rate latest 2026 The Information Reuters",
     "validate": schemas.make_value_validator(0, 500)},
    {"id": "anthropic", "field": "value_b", "max_results": 5,
     "system": ("Today is {today}. Report Anthropic's most recent ANNUALIZED revenue "
                "run-rate in $B. Disputed, fast-moving (ranged $9B->$47B in 2026) — "
                "use the most recent widely-reported figure in the results. State "
                "published_at — the source's OWN publication date (YYYY-MM-DD), not "
                "today's; null if it carries none. Respond ONLY with JSON: "
                '{"value_b": float, "source": str, "url": str, "published_at": str}.'),
     "query": "Anthropic annualized revenue run rate latest 2026 reported",
     "validate": schemas.make_value_validator(0, 500)},
    {"id": "copilot", "field": None, "max_results": 5,
     "system": ("Today is {today}. Report Microsoft Copilot SERVICES primitives — DO "
                "NOT compute the total; Python calculates it (M365 seats x price x 12 "
                "+ GitHub). Provide:\n"
                "1. m365_seats_m: paid M365 Copilot seats in MILLIONS (~20M+; Microsoft "
                "discloses this on earnings calls).\n"
                "2. m365_price_month: M365 Copilot per-seat list price $/month (~$30).\n"
                "3. github_b: GitHub Copilot ANNUAL revenue in $B (~$1.5-2B).\n"
                "4. seat_disclosed: true ONLY if the M365 seat count came from an "
                "official Microsoft disclosure; false if it is a third-party estimate.\n"
                "Do NOT use Microsoft's ~$37B total 'AI run rate' (mostly Azure rails "
                "= NOT Copilot services). Respond ONLY with JSON: {\"m365_seats_m\": "
                'float, "m365_price_month": float, "github_b": float, '
                '"seat_disclosed": bool, "seat_source": str, "url": str}.'),
     "query": ("Microsoft M365 Copilot paid seats count GitHub Copilot annual revenue "
               "2026 earnings call"),
     "validate": schemas.validate_copilot, "samples": 3},
    {"id": "gemini", "field": None, "max_results": 8,
     "system": ("Today is {today}. Google does NOT disclose Gemini revenue, so we "
                "estimate it. Your job is to PULL three numbers — DO NOT compute the "
                "total revenue yourself; Python calculates it (seats x price x 12 + "
                "consumer). Report:\n"
                "1. enterprise_seats_m: the TOTAL paid Gemini/Workspace-AI seat count "
                "across ALL customers (aggregate installed base, in MILLIONS). EXCLUDE "
                "any single-customer/single-contract deployment ('Company X rolled "
                "Gemini to N employees') — that is one customer, not the market total. "
                "Prefer an Alphabet earnings-call figure or an official Google "
                "AGGREGATE disclosure; third-party aggregate estimate only if none.\n"
                "2. avg_price_month: blended paid price per seat per month in $ "
                "(Gemini Business/Enterprise tiers, ~$20-30).\n"
                "3. consumer_b: Google One AI Premium / Gemini Advanced ANNUAL "
                "subscriber revenue in $B (~$1.2B). ALWAYS provide this — do not omit.\n"
                "4. seat_disclosed: true ONLY if the seat count came from an official "
                "Google/Alphabet disclosure; false if it is a third-party estimate.\n"
                "State where the seat count came from. Respond ONLY with JSON: "
                '{"enterprise_seats_m": float, "avg_price_month": float, '
                '"consumer_b": float, "seat_disclosed": bool, "seat_source": str, "url": str}.'),
     "query": ("Google Gemini Workspace AI total paid seats subscribers aggregate "
               "installed base 2026 Alphabet earnings; Gemini Advanced Google One "
               "AI Premium total subscribers price per seat"),
     "validate": schemas.validate_gemini, "samples": 3},
    {"id": "nvda_dc", "field": None, "max_results": 5,
     "system": ("Today is {today}. Report NVIDIA's data-center segment revenue for its "
                "MOST RECENTLY REPORTED fiscal quarter as of today (NVIDIA's fiscal "
                "year runs ~1yr AHEAD; FY2027 quarters report during calendar 2026 — "
                "NOT the older Q4 FY2026 annual results). Single quarter only, $B, from "
                "NVIDIA's earnings release. Respond ONLY with JSON: "
                '{"dc_qtr_b": float, "quarter": str, "url": str}.'),
     "query": ("NVIDIA most recent quarterly earnings latest quarter data center "
               "segment revenue billion"),
     "validate": schemas.validate_nvda_dc},
    {"id": "nvda_share", "field": None, "max_results": 6,
     # NO EXPECTED RANGE AND NO DIRECTION IN THIS PROMPT (2026-08-28). It used to say
     # the figure was "~70-75% and DRIFTING DOWN"; asked to confirm a stated range, the
     # model returned 0.73 on EVERY pull across seven prints while only NVDA's revenue
     # moved -- a pinned constant wearing the appearance of a refreshed input. The
     # DEFINITION is the thing that must be pinned (all-accelerator vs merchant-GPU are
     # different questions with ~20 points between them); the VALUE and its direction are
     # what we are paying to measure. The trend is observable from the recorded ledger
     # now, so it never needs asserting here again.
     "system": ("Today is {today}. Report NVIDIA's share of the TOTAL AI ACCELERATOR "
                "market as a fraction (0-1), as of the most recent measurement you can "
                "find. CRITICAL DEFINITION: this is NVIDIA's share of ALL AI accelerator "
                "compute/spend INCLUDING custom silicon — Google TPU, Amazon "
                "Trainium/Inferentia, AMD MI-series, etc. It is NOT the "
                "merchant/discrete GPU market: that GPU-only figure (~90%) is WRONG for "
                "this purpose because it excludes custom silicon. Report what the "
                "sources actually say, whether the share is rising or falling. Prefer a "
                "PRIMARY market-research house (Mercury Research, Jon Peddie Research, "
                "TrendForce, IDC, Gartner, Bloomberg Intelligence) over a site "
                "republishing them, and prefer the most recently published measurement "
                "over an older one. State the definition, the source, and "
                "published_at — the source's OWN publication date (YYYY-MM-DD), not "
                "today's date; null if the source carries none. Respond ONLY with JSON: "
                '{"accel_share": float, "definition": str, "source": str, "url": str, '
                '"published_at": str}.'),
     "query": ("NVIDIA share of total AI accelerator market including custom silicon "
               "TPU Trainium latest quarter Mercury Research JPR TrendForce IDC"),
     "validate": schemas.validate_nvda_share},
]


def run_silicon_multi(only=None):
    """Per-source silicon extraction. `only` = iterable of source ids to (re)pull;
    None = full run (the weekly backstop). A source NOT in `only` CARRIES its prior
    value from the stored record instead of re-pulling — so a GOOGL-earnings refresh
    touches only the gemini leg and leaves OpenAI/Anthropic/Copilot/NVDA untouched.
    A carried leg with no usable prior is pulled anyway (the composite can't be
    derived without every leg). Returns (record, cost)."""
    only = None if only is None else set(only)
    prev_sources = (read_input("silicon_payback").get("sources") or {})
    per_source, total_cost, refreshed = {}, 0.0, []
    for src in _SILICON_SOURCES:
        sid = src["id"]
        prior = prev_sources.get(sid)
        if (only is not None and sid not in only
                and isinstance(prior, dict) and _SILICON_KEYS[sid] in prior):
            per_source[sid] = prior            # carry — no new data for this leg
            continue
        data, meta = llm.extract_sampled(
            f"silicon:{sid}", "extract",
            [{"role": "system", "content": src["system"].replace("{today}", _today())},
             {"role": "user", "content": src["query"]}],
            model=llm.STAGE2_MODEL, validate=src["validate"], web_search=True,
            max_results=src["max_results"], samples=src.get("samples", 1))
        per_source[sid] = {**data, "_cost": round(meta["cost_usd"] or 0, 4),
                           "_routed": meta["model_routed"], "refreshed_at": _today()}
        total_cost += meta["cost_usd"] or 0
        refreshed.append(sid)

    p = per_source
    rec = {
        "openai_rev_b": p["openai"]["value_b"],
        "anthropic_rev_b": p["anthropic"]["value_b"],
        "copilot_rev_b": p["copilot"]["value_b"],
        "gemini_rev_b": p["gemini"]["value_b"],
        "services_rev_b": round(p["openai"]["value_b"] + p["anthropic"]["value_b"]
                                + p["copilot"]["value_b"] + p["gemini"]["value_b"], 1),
        "nvda_dc_qtr_b": p["nvda_dc"]["dc_qtr_b"],
        "nvda_dc_quarter": p["nvda_dc"]["quarter"],
        "nvda_accel_share": p["nvda_share"]["accel_share"],
        "asof": _today(),
        "provenance": ("multi-search per-source (STOPLIGHT_SCHEDULING §5)"
                       + ("" if only is None else f"; refreshed {refreshed}")),
        "sources": p,
        "refreshed_sources": (None if only is None else refreshed),
    }
    write_input("silicon_payback", rec)
    return rec, round(total_cost, 4)


# --- Infra backlog: PER-SOURCE multi-search (doctrine #1: one search per source) --
# The legacy run_earnings("infra_backlog") multiplexed VRT book-to-bill AND GEV
# available-GW into ONE query — exactly the dilution doctrine #1 warns against (Exa
# ranks by the blended query, so a recency-sensitive leg gets a stale doc). Split
# into two focused searches: VRT book-to-bill is the HARD light-driving number
# (disclosed on the call); GEV emits a verbatim STOCK of unsold available-GW (or
# null), and CODE derives the +/- direction from the period-over-period delta — the
# model never asserts a trend it could fabricate (user's hardened spec 2026-07-19).
# Python assembles; prev_book_to_bill carries the last print for the two-consecutive
# rule; the GEV stock + prior total carry so the deriver can diff them.
_INFRA_SOURCES = [
    {"id": "vrt_btb", "max_results": 5, "period_aware": True,
     "system": ("Today is {today}. Report Vertiv's (VRT) BOOK-TO-BILL ratio for the "
                "FISCAL QUARTER THAT ENDED {period} — THAT QUARTER ONLY. Do not "
                "substitute the most recent quarter you happen to find.\n"
                "IF THAT QUARTER'S FIGURE IS NOT AVAILABLE, say so — an honest 'not "
                "available' is a CORRECT and expected answer. Return "
                "{\"book_to_bill\": null, \"unavailable\": true, "
                "\"period_end\": \"{period}\", \"unavailable_reason\": <see below>, "
                "\"note\": \"<one line, quoting management if they declined>\"}.\n"
                "unavailable_reason MUST be one of — this drives whether a human waits "
                "or stops asking, so get it right:\n"
                "  'not_published' — the earnings release or call transcript for that "
                "quarter is not out/indexed yet. Asking again later will work.\n"
                "  'not_disclosed' — the release/transcript IS available, but the "
                "company did not give the figure (e.g. management said they do not "
                "disclose orders, or spoke only qualitatively about 'strong orders'). "
                "Asking again will NOT work.\n"
                "Do NOT fall back to an earlier quarter and do NOT reconstruct a "
                "number.\n"
                "It is a DIMENSIONLESS FLOW ratio, typically "
                "0.8-3x (e.g. 1.2, 2.9) — NOT a dollar amount. Do NOT report total "
                "backlog (a stock, ~$7-8B), backlog in $B, or backlog growth %.\n"
                "SOURCE IT IN THIS PRIORITY ORDER, and report which you used as "
                "`method`:\n"
                "1. STATED — if VRT management states the ratio directly on the call "
                "or in the deck (they do in the AI-boom quarters), use that number. "
                "method='stated'.\n"
                "2. ORDERS÷REVENUE — else compute it = orders (bookings) ÷ revenue, "
                "BOTH from the same release, same period, same basis. You may have to "
                "reconstruct the orders $ from an organic-orders-growth % they give. "
                "method='orders_over_revenue'.\n"
                "3. NEVER derive it from the CHANGE IN BACKLOG (ΔBacklog = orders − "
                "shipments). Scan-sourced backlog figures are routinely non-comparable "
                "(RPO vs backlog vs different report dates) and produce implausible "
                "ratios. If the ONLY path you have is a backlog delta, DO NOT ANSWER — "
                "return method='backlog_delta' (it will be rejected) rather than a "
                "guessed number.\n"
                "REPORT `period_end` = the END DATE (YYYY-MM-DD) of the quarter your "
                "figure actually covers, plus the fiscal `quarter` label as published "
                "(e.g. 'Q2 2026'). period_end MUST equal {period} or the answer is "
                "rejected — it is how we prove you did not return a different quarter. "
                "Use the web results (VRT earnings release / call transcript) as "
                "primary source. Respond ONLY with JSON: "
                '{"book_to_bill": float|null, "unavailable": bool, "method": "stated"|'
                '"orders_over_revenue"|"backlog_delta", "period_end": str, '
                '"quarter": str, "note": str, "source": str, "url": str}.'),
     "query": ("Vertiv VRT book-to-bill ratio orders bookings revenue quarter ended "
               "{period} earnings call transcript"),
     "validate": schemas.validate_book_to_bill},
    {"id": "gev_gw", "max_results": 6,
     "system": ("Today is {today}. Report GE Vernova's (GEV) REMAINING AVAILABLE "
                "(UNSOLD) capacity for gas + grid equipment. Two facets, BOTH "
                "optional — report whichever the source actually states, null "
                "otherwise. Do NOT infer or compute either.\n"
                "Emit EXACTLY this JSON:\n"
                '{"gev_available_gw": {"as_of": "<fiscal quarter, e.g. Q1-2026>", '
                '"by_year": [{"year": 2029, "available_gw": <num>}], "combined": '
                '<num or null>, "method": "stated_available_gw", "source_quote": '
                '"<verbatim sentence with the GW number>"} | null, '
                '"gev_stated_direction": {"direction": "shrinking"|"flat"|"growing", '
                '"as_of": "<fiscal quarter>", "method": "stated_direction", '
                '"source_quote": "<verbatim management sentence>"} | null}\n'
                "FACET 1 — gev_available_gw: the REMAINING UNSOLD capacity in "
                "GIGAWATTS by delivery year (a STOCK of unsold GW). Rules:\n"
                '  a. method MUST be the literal "stated_available_gw".\n'
                "  b. source_quote MUST be a verbatim sentence CONTAINING the GW "
                "figure. No verbatim quote => not stated => this facet is null.\n"
                "  c. NEVER fabricate/estimate/interpolate a GW number; a year with "
                "no stated figure is OMITTED, not filled.\n"
                "  d. ONE combined figure across years ('~10 GW across 2029-2030') "
                "goes in `combined` with by_year empty — do NOT split it yourself.\n"
                "FACET 2 — gev_stated_direction: use ONLY IF MANAGEMENT EXPLICITLY "
                "characterizes the trend in available/unsold capacity as shrinking "
                "(selling out further / tightening = demand strong), growing (slots "
                "reopening / de-bookings = demand cooling), or flat. method MUST be "
                'the literal "stated_direction" with a verbatim management quote. If '
                "management does not explicitly say it, LEAVE IT null — do NOT infer "
                "a direction from a sold-out date, backlog, or booking color.\n"
                "FORBIDDEN for BOTH facets (these are NOT the metric; => null): a "
                "sold-out DATE/horizon ('sold out through 2030' — a date is not a GW "
                "quantity), TOTAL backlog GW (contaminated by factory-capacity adds), "
                "orders/revenue/book-to-bill (that is VRT's metric), or anything you "
                "had to COMPUTE. Use the web results (GEV earnings release / call / "
                "deck). Respond ONLY with the JSON above."),
     "query": ("GE Vernova remaining available uncommitted capacity gigawatts by "
               "delivery year unsold GW management commentary tightening latest "
               "earnings call"),
     "validate": schemas.validate_gev},
]


def run_infra_backlog_multi(only=None, period_end=None):
    """Per-source infra-backlog: VRT book-to-bill (hard, drives the light) + GEV
    available-GW STOCK (verbatim-or-null; CODE derives the +/- direction from the
    period delta), each its own focused search; Python assembles. A source failing
    keeps the prior value rather than aborting. GEV null/failure carries the prior
    stock forward (no news != a changed stock); a fresh GEV stock advances the diff
    baseline so the deriver can compute the direction.

    `only` = source ids to (re)pull; None = both. A source NOT in `only` is skipped,
    and the assembly's own prev-fallback carries it forward — so a VRT-earnings refresh
    pulls vrt_btb only and GEV's stock/direction ride their prior values, and vice
    versa. (The two legs already map to distinct reporters, VRT and GEV.)"""
    only = None if only is None else set(only)
    prev = read_input("infra_backlog")
    per_source, total_cost, failed, unavailable = {}, 0.0, [], []
    for src in _INFRA_SOURCES:
        if only is not None and src["id"] not in only:
            continue   # carried: the assembly below falls back to prev for this leg
        # Period-pinned legs ask for ONE named quarter and may answer "not published
        # yet"; see schemas.make_book_to_bill_validator for why.
        sys_txt = src["system"].replace("{today}", _today())
        qry = src["query"]
        validate = src["validate"]
        if src.get("period_aware") and period_end:
            sys_txt = sys_txt.replace("{period}", period_end)
            qry = qry.replace("{period}", period_end)
            validate = schemas.make_book_to_bill_validator(period_end)
        try:
            data, meta = llm.extract_sampled(
                f"infra:{src['id']}", "extract",
                [{"role": "system", "content": sys_txt},
                 {"role": "user", "content": qry}],
                model=llm.STAGE2_MODEL, validate=validate, web_search=True,
                max_results=src["max_results"], samples=src.get("samples", 1))
        except ValueError as e:
            # The leg RAN and was rejected (e.g. VRT declining to disclose orders —
            # the method-guard working as designed). Stamp `attempted_at` so the
            # billed queue treats the event as CONSUMED: we looked, the number does
            # not exist this quarter, and re-asking costs money for the same answer.
            # The search already billed, so count it (llm attaches the amount).
            failed.append(src["id"])
            spent = getattr(e, "cost_usd", 0) or 0
            # ACCUMULATE across consecutive failures on this leg. The alert should
            # answer "how much has chasing this cost me", not "what did the last try
            # cost" — observed 07-29: two clicks, two rejections, $0.0299 sunk.
            prior_leg = (prev.get("sources") or {}).get(src["id"]) or {}
            carried = (prior_leg.get("cost") or 0) if (
                prior_leg.get("attempted_at") and not prior_leg.get("refreshed_at")) else 0
            per_source[src["id"]] = {
                "failed": True, "attempted_at": _today(), "reason": str(e)[:200],
                "cost": round(carried + spent, 6),
                "attempts": (prior_leg.get("attempts") or 0) + 1}
            total_cost += spent
            continue
        total_cost += meta["cost_usd"] or 0
        if data.get("unavailable"):
            # NOT a failure and NOT data: the quarter simply isn't published yet. No
            # refreshed_at, so the pull stays owed; no book_to_bill key, so the
            # assembly below carries the prior value instead of reading a None.
            prior_leg = (prev.get("sources") or {}).get(src["id"]) or {}
            carried = (prior_leg.get("cost") or 0) if (
                prior_leg.get("attempted_at") and not prior_leg.get("refreshed_at")) else 0
            per_source[src["id"]] = {
                "unavailable": True, "attempted_at": _today(),
                "unavailable_reason": data.get("unavailable_reason") or "not_published",
                "period_end": data.get("period_end") or period_end,
                "reason": data.get("note") or "no figure given",
                "cost": round(carried + (meta["cost_usd"] or 0), 6),
                "attempts": (prior_leg.get("attempts") or 0) + 1,
                "source": data.get("source"), "url": data.get("url")}
            unavailable.append(src["id"])
            continue
        per_source[src["id"]] = {**data, "_cost": round(meta["cost_usd"] or 0, 4),
                                 "_routed": meta["model_routed"], "refreshed_at": _today()}

    # A CARRIED VALUE MUST CARRY ITS LABELS WITH IT (2026-08-30). `btb` fell back to the
    # prior when the leg did not pull, but `vrt_method` was read from the CURRENT pull
    # only and `quarter` was never lifted into the record at all — so a validated,
    # returned quarter label was discarded on arrival and the carried 2.9 sat beside
    # `vrt_method: null` with no period on it. The stale-print guard was doing its job
    # in the validator and then losing the answer in the assembly, which is the same
    # shape as the newsletter spec's pnl-input bug: the field exists, the plumbing
    # drops it. Nothing can say how old a carried number is if its label does not
    # travel with it, and this factor's whole difficulty is that its number is old.
    _vrt = per_source.get("vrt_btb", {})
    _fresh_btb = "book_to_bill" in _vrt
    btb = _vrt["book_to_bill"] if _fresh_btb else prev.get("vrt_book_to_bill")
    if btb is None:
        raise ValueError("infra_backlog: VRT book-to-bill extraction failed, no prior")

    # GEV: a fresh stated stock advances the numeric diff (prev_total <- last good
    # total); null/rejection carries the prior stock/totals forward (no news != a
    # changed stock). The management-stated DIRECTION (facet 2) carries the same way
    # — the deriver uses it only when the numeric delta can't be computed.
    prev_stock = prev.get("gev_available_gw")
    prev_total = prev.get("gev_total_available_gw")
    gev_src = per_source.get("gev_gw", {})
    gev_failed = gev_src.get("failed")
    new_stock = None if gev_failed else gev_src.get("gev_available_gw")
    new_dir = None if gev_failed else gev_src.get("gev_stated_direction")
    if new_stock:
        gev_stock = new_stock
        gev_total = schemas.gev_total_available_gw(new_stock)
        gev_prev_total = prev_total                       # diff new vs last good
    else:
        gev_stock, gev_total = prev_stock, prev_total     # carry forward, no news
        gev_prev_total = prev.get("gev_prev_total_available_gw")
    gev_dir = new_dir or prev.get("gev_stated_direction")  # last good management call

    rec = {
        "vrt_book_to_bill": btb,
        "vrt_method": (_vrt.get("method") if _fresh_btb                  # stated | orders_over_revenue
                       else prev.get("vrt_method")),
        "vrt_quarter": (_vrt.get("quarter") if _fresh_btb                # the period the number IS
                        else prev.get("vrt_quarter")),
        # ONLY A FRESH PRINT ADVANCES `prev` (2026-08-30). This used to be an
        # unconditional `prev.get("vrt_book_to_bill")`, which on a CARRIED run set the
        # previous print to the carried current one — the same number twice. That
        # defeats the green rule, whose entire point is that b-t-b is lumpy and one
        # sub-0.9 print is a data point while two are a turn: after a single sub-0.9
        # print, any later run that carried VRT (a GEV-only earnings refresh, say)
        # would have made `prev` sub-0.9 as well and the factor would have gone GREEN
        # off ONE print confirming itself. A carry is not an observation.
        "prev_book_to_bill": (prev.get("vrt_book_to_bill") if _fresh_btb
                              else prev.get("prev_book_to_bill")),
        "gev_available_gw": gev_stock,                    # the verbatim stock (or None)
        "gev_total_available_gw": gev_total,              # combined else sum(by_year)
        "gev_prev_total_available_gw": gev_prev_total,    # prior total, for the deriver's diff
        "gev_stated_direction": gev_dir,                  # management's own trend call (or None)
        "asof": _today(),
        "provenance": "multi-search per-source (VRT book-to-bill + GEV available-GW stock/direction)",
        "failed_sources": failed,
        "unavailable_sources": unavailable,   # asked-for period not published yet
        "sources": per_source,
    }
    write_input("infra_backlog", rec)
    return rec, round(total_cost, 4)


# --- Capex spigot: PER-COMPANY guidance (soft) over PINNED priors (deterministic) -
# Only the FORWARD guidance is LLM-pulled (genuinely soft/forward). The prior-year
# actual is a HISTORICAL FACT, pinned as a documented constant — because MSFT/META
# report capex on multiple bases (GAAP vs incl. finance leases) and the LLM couldn't
# pick one consistently, swinging the denominator run-to-run (medium reasoning did
# not fix it — it's source ambiguity, not a reasoning budget). Python aggregates
# dollar-weighted: yoy = sum(guidance) / sum(PINNED_prior) - 1.
_CAPEX_COMPANIES = ["MSFT", "GOOGL", "AMZN", "META", "ORCL"]

# Prior-year (most-recent completed FY) capex, $B, INCLUDING finance leases (to
# match the lease-inclusive basis the hyperscalers headline their AI-infra guidance
# on). Documented constants — UPDATE ANNUALLY as each FY closes. Basis note:
# GOOGL/ORCL are ~all GAAP PP&E (minimal leases); MSFT/AMZN/META add finance leases.
# (Set 2026-07-19 from FY2025 actuals; reproduces the ~+80% aggregate on-basis.)
PINNED_CAPEX_PRIORS = {"MSFT": 88.7, "GOOGL": 91.4, "AMZN": 125.0,
                       "META": 72.0, "ORCL": 55.7}


def _capex_company_source(sym):
    return {
        "system": ("Today is {today}. Report " + sym + "'s FORWARD capital-expenditure "
                   "GUIDANCE for its COMING year, in $B, on a basis INCLUDING finance "
                   "leases (the total AI-infrastructure capex the company has GUIDED / "
                   "plans to spend). This is a FORWARD number from earnings-call "
                   "guidance, NOT trailing reported capex. State the basis and set "
                   "guidance_disclosed true ONLY if the guided figure was explicitly "
                   "stated (not constructed/estimated). Respond ONLY with JSON: "
                   '{"capex_guidance_b": float, "basis": str, "guidance_disclosed": '
                   'bool, "source": str, "url": str}.'),
        "query": (sym + " forward capex guidance coming year total capital expenditure "
                  "including finance leases 2026 datacenter AI earnings call"),
    }


def run_capex_spigot_multi(only=None):
    """Per-company basis-consistent guidance + PINNED prior; Python aggregates the
    dollar-weighted YoY over ALL usable legs. No yfinance (basis would mismatch).

    `only` = companies to (re)pull; None = all. A company NOT in `only` CARRIES its
    prior guidance from the stored per_company record — a GOOGL refresh re-pulls only
    GOOGL and re-aggregates over the carried MSFT/AMZN/META/ORCL. Returns (rec, cost).
    (Per-source makes the old cluster-wait unnecessary — each leg refreshes the day
    its company reports; the caller no longer needs to hold for the whole cluster.)"""
    only = None if only is None else set(only)
    prev_per = (read_input("capex_spigot").get("per_company") or {})
    per, total_cost, failed, refreshed = {}, 0.0, [], []
    for sym in _CAPEX_COMPANIES:
        prior = prev_per.get(sym)
        if (only is not None and sym not in only
                and isinstance(prior, dict) and "guidance_b" in prior):
            per[sym] = prior                     # carry — no new data for this leg
            continue
        src = _capex_company_source(sym)
        # Per-company resilience: a single company returning non-JSON must not
        # kill the whole aggregate. One retry, then carry-prior / exclude-with-note.
        data = meta = None
        attempt_cost, last_err = 0.0, None
        for _ in range(2):
            try:
                data, meta = llm.extract_sampled(
                    f"capex:{sym}", "extract",
                    [{"role": "system", "content": src["system"].replace("{today}", _today())},
                     {"role": "user", "content": src["query"]}],
                    model=llm.STAGE2_MODEL, validate=schemas.validate_capex_guidance,
                    web_search=True, max_results=5, samples=3)
                break
            except ValueError as e:
                attempt_cost += getattr(e, "cost_usd", 0) or 0   # rejected still billed
                last_err = str(e)[:200]
                continue
        if data is None:
            failed.append(sym)
            total_cost += attempt_cost
            # A failed pull carries the prior if we have one; else drop from the aggregate.
            # Either way stamp `attempted_at` — carrying `prior` verbatim would also
            # carry its OLD refreshed_at, leaving the billed queue owed forever.
            base = prior if (isinstance(prior, dict) and "guidance_b" in prior) else {"failed": True}
            carried = (prior.get("cost") or 0) if (isinstance(prior, dict)
                       and prior.get("attempted_at") and not prior.get("refreshed_at")) else 0
            per[sym] = {**base, "attempted_at": _today(),
                        "cost": round(carried + attempt_cost, 6),
                        "attempts": ((prior or {}).get("attempts") or 0) + 1,
                        "reason": last_err or "extraction failed"}
            continue
        total_cost += meta["cost_usd"] or 0
        guidance_b = data["value_b"]
        prior_b = PINNED_CAPEX_PRIORS[sym]           # deterministic historical anchor
        per[sym] = {"guidance_b": guidance_b, "prior_b": prior_b, "prior_pinned": True,
                    "basis": data.get("basis"),
                    "disclosed": data.get("guidance_disclosed"),
                    "yoy_pct": round((guidance_b / prior_b - 1) * 100, 1),
                    "sampled": data.get("_sampled"), "url": data.get("url"),
                    "refreshed_at": _today()}
        refreshed.append(sym)

    # Aggregate over every company with a usable guidance (carried + freshly pulled).
    usable = [v for v in per.values() if isinstance(v, dict) and "guidance_b" in v]
    total_guidance = sum(v["guidance_b"] for v in usable)
    total_prior = sum(v["prior_b"] for v in usable)
    if total_prior <= 0:
        raise ValueError(f"capex_spigot: no usable company guidance ({failed})")
    yoy = round((total_guidance / total_prior - 1) * 100, 1)
    rec = {"guidance_yoy_pct": yoy, "total_guidance_b": round(total_guidance),
           "total_prior_b": round(total_prior), "per_company": per, "asof": _today(),
           "failed_companies": failed,
           "refreshed_companies": (None if only is None else refreshed),
           "provenance": "per-company forward guidance (LLM) over PINNED prior-year actuals"}
    write_input("capex_spigot", rec)
    return rec, round(total_cost, 4)


# --- Regulatory: PER-SOURCE (statute roster + DCW blocks as separate searches) ----
# The legacy run_regulatory() folded the DCW blocked-project count INTO the stage-2
# statute-classify call — two different sources (legislative databases vs the Data
# Center Watch tracker) multiplexed into one prompt (doctrine #1 violation). Split
# them. The statute leg keeps a cheap-sweep -> escalate detector, but the sweep now
# surfaces DELTAS (new enactments beyond the roster + repeals of roster states), the
# classify PROVES each delta (citation + date), and PYTHON maintains a PERSISTED
# ROSTER — applying add/remove deltas and deriving count = len(roster). No search has
# to recreate the whole list, and the count can move up OR down. DCW (updates more
# often) gets its own focused STAGE2 search.
_REG_SWEEP_MULTI_SYS = (
    "You are a regulatory sweep for US STATE-LEVEL government action on large "
    "electrical loads / data centers. Using web search, return the CURRENT FULL LIST "
    "of states that have such an action IN FORCE today, plus any previously-tracked "
    "action that has ENDED.\n"
    "COUNT an action when ALL FOUR hold:\n"
    "(1) IN FORCE — signed, issued or adopted, with an effective date. A bill that "
    "PASSED but is not signed does NOT count. A draft rule or an open docket does NOT "
    "count.\n"
    "(2) ANY BRANCH — a statute, a governor's executive order, or a utility-commission "
    "rule or order of general application all count equally.\n"
    "(3) STATE-WIDE — it binds every utility / all large loads in the state. A single "
    "utility's tariff does NOT count, however large that utility is.\n"
    "(4) ABOUT LARGE-LOAD POWER — cost allocation, a large-load rate class, "
    "interconnection standards, or siting/permitting. A tax measure does NOT count. A "
    "study or report mandate does NOT count, because nothing is required of anyone.\n"
    "A TEMPORARY action (a moratorium or pause) DOES count while it is in force.\n"
    "Currently tracked, for your reference only — verify rather than assume, and "
    "include them in the list if they still qualify: {known}\n"
    "Respond ONLY with JSON: {\"current_actions\": [{\"state\": str, "
    "\"description\": str, \"url\": str}], \"ended_candidates\": [{\"state\": str, "
    "\"description\": str, \"url\": str}]}."
)
# The sweep's SEARCH QUERY. It had none: its user message was "Sweep now: every state
# action in force today", and that message is what gets searched. Survivable while the
# job was a yes/no delta check -- "nothing new" is a cheap answer to reach with poor
# results -- and not survivable once the job became enumerating a national picture. The
# first run under the new prompt returned an EMPTY full list, asserting there are no
# state actions in force anywhere, with six of them quoted in its own prompt.
# Multi-angle on purpose: a roundup phrasing to catch the trackers that maintain these
# lists, then one clause per BRANCH, since the whole point of the rebuild is that the
# instrument can be a statute, an order or a rule.
_REG_QUERY = ("which US states have enacted data center large load energy laws 2025 "
              "2026 list by state; state large-load rate class cost allocation statute "
              "data centers; governor executive order data center moratorium pause "
              "permitting statewide; public utility commission large load tariff rule "
              "order applies to all utilities")

_REG_STATUTE_CLASSIFY_SYS = (
    "You prove US state-level actions on large electrical loads / data centers. "
    "Return only what you can CITE.\n"
    "An action qualifies when ALL FOUR hold:\n"
    "(1) IN FORCE — signed / issued / adopted, with an effective date. Passed-but-"
    "unsigned, draft, and pending do NOT qualify.\n"
    "(2) ANY BRANCH — statute, executive order, or commission rule of general "
    "application.\n"
    "(3) STATE-WIDE — binds all utilities / all large loads in the state. Prove it "
    "from the INSTRUMENT'S OWN TEXT, not from an article about it: give a verbatim "
    "`scope_quote` from the statute, order or rule showing who it binds, and set "
    "`binds` to one of \"all_utilities\", \"named_utility\", \"voluntary\". ONLY "
    "\"all_utilities\" qualifies. Three ways an instrument fails this even though "
    "coverage of it will say the state acted:\n"
    "  - it NAMES a particular utility or covers one service territory. It does not "
    "qualify however large that utility is.\n"
    "  - it is a MODEL, framework, guidance or recommendation utilities may adopt. "
    "Adopted is not binding; voluntary does not qualify.\n"
    "  - it DIRECTS someone to propose, study, consider or report rather than imposing "
    "the requirement itself. A duty to propose is not the rule.\n"
    "(4) ABOUT LARGE-LOAD POWER — cost allocation, rate class, interconnection, or "
    "siting/permitting. Tax-only and study-only measures do NOT qualify.\n"
    "For each: instrument_type is exactly one of \"statute\", \"executive_order\", "
    "\"commission_rule\". citation is the bill number, executive order number, or "
    "docket/order number. effective_date is ISO. threshold_mw is the megawatt "
    "threshold if the action defines one, else null. expires is an ISO date ONLY if "
    "the action has a stated end date, else null. statewide must be true.\n"
    "OMIT anything you cannot prove — do NOT pad with pending bills or with states "
    "that are merely 'considering' one.\n"
    "Respond ONLY with JSON: {\"actions\": [{\"state\": str, \"instrument_type\": "
    "str, \"citation\": str, \"effective_date\": str, \"binds\": str, \"scope_quote\": str, "
    "\"threshold_mw\": number|null, \"expires\": str|null, \"url\": str, "
    "\"note\": str}], \"ended\": [{\"state\": str, \"citation\": str, "
    "\"ended_date\": str, \"url\": str}]}."
)
# FUTURE WORK — option C, decided 2026-07-20 (DOCUMENTED, not built): broaden the
# blocked-projects signal BEYOND a single Data Center Watch source. Today this leg is
# single-SOURCED to DCW (the query + prompt anchor it there, though the Exa crawl
# itself is broad). DCW publishes a COMBINED "blocked-or-delayed" figure + a $ number
# but rarely a clean blocked-ONLY count, so the strict validator returns null and we
# carry the prior — the metric is often stale. The hard part any broad build MUST
# solve: a naive multi-source aggregate breaks the period-over-period delta (each
# source counts differently = noise). The right shape is the SAME roster pattern used
# for the statute count above — a PYTHON-OWNED ledger of DISTINCT blocked projects,
# deduped by project identity across sources, so the count is a Python-arbitrated
# accumulation, not any one source's headline number. Until then this stays
# single-sourced to DCW (a quarantined footnote arrow; the light dominates).
_DCW_SYS = (
    "Today is {today}. Report the Data Center Watch tracker's COUNT of US data-center "
    "projects stopped by local opposition, and say exactly WHICH count you are "
    "giving.\n"
    "- It is a COUNT OF PROJECTS (integer), never a dollar figure: '$64 billion' is "
    "not a count.\n"
    "- metric_basis is \"blocked_only\" when the figure counts projects definitively "
    "blocked (rejected, denied, cancelled or withdrawn) and NOTHING else, or "
    "\"blocked_or_delayed\" when it is the combined blocked-and-delayed figure. BOTH "
    "are acceptable answers. Reporting the wrong LABEL for the figure is not.\n"
    "- period_label is the period the figure covers, verbatim as the source states it "
    "(for example \"Q1 2026\", or \"cumulative since 2023\"). If the source does not "
    "say what period its number covers, return null rather than guessing.\n"
    "- source_quote is a verbatim quote containing the number. No quote, return "
    "null.\n"
    "Respond ONLY with JSON: {\"dcw_blocked_projects\": int, \"metric_basis\": str, "
    "\"period_label\": str, \"source_quote\": str, \"url\": str} - or "
    "{\"dcw_blocked_projects\": null} if no count is cleanly stated."
)
_DCW_QUERY = ("Data Center Watch number of data center projects blocked rejected "
              "cancelled by local opposition count 2026")


def run_regulatory_multi():
    """Per-source regulatory (HARDENED 2026-07-19): (1) enacted state-wide statute
    COUNT — the cheap sweep detects new candidates beyond the known set, the classify
    returns the PROVEN new states (citation + enacted date required), and PYTHON
    derives the count = len(known UNION new, deduped by name), so the light's integer
    can't drift from the evidence and the baseline is never dropped; (2) the DCW
    blocked-project count as its OWN focused search (verbatim-quoted, null-safe). Each
    leg is resilient: a sweep/classify or DCW failure carries the prior value forward."""
    prev = read_input("regulatory")
    prev_actions = prev.get("actions") or []
    total_cost = 0.0
    roster_changed = False

    # Source 1 — the ROSTER of state-level actions in force (sweep -> classify) -----
    # Python owns the roster; the model only proposes and proves. What changed on
    # 2026-08-29 is the QUESTION: the sweep used to ask for states "beyond those
    # already tracked", so it could only ever append to a seed nobody had audited, and
    # the seed was wrong 2 of 3 (Ohio was a single-utility tariff, California a study
    # mandate). It now asks for the FULL current list, and Python reconciles:
    #   * ADD any proven action not already in the roster;
    #   * never REMOVE on absence — a sweep that misses a state is not evidence the
    #     state repealed anything, and one thin search must not empty the roster;
    #   * REMOVE only on a proven ending (citation + date).
    # So the roster converges upward on proof and only ever shrinks on evidence.
    known = ", ".join(f"{a.get('state')} ({a.get('citation')})" for a in prev_actions) \
        or "none tracked"
    actions = list(prev_actions)
    rejected = []
    try:
        sweep, m1 = llm.extract_json(
            "regulatory", "sweep",
            [{"role": "system", "content": _REG_SWEEP_MULTI_SYS.replace("{known}", known)},
             {"role": "user", "content": _REG_QUERY}],
            model=llm.STAGE1_MODEL, validate=schemas.validate_reg_sweep_multi, web_search=True)
        total_cost += m1["cost_usd"] or 0
        found, ended = sweep["current_actions"], sweep["ended_candidates"]
        if found or ended:
            classified, m2 = llm.extract_json(
                "regulatory", "classify",
                [{"role": "system", "content": _REG_STATUTE_CLASSIFY_SYS},
                 {"role": "user", "content": json.dumps({"candidates": found,
                                                         "ended": ended})}],
                model=llm.STAGE2_MODEL, validate=schemas.validate_reg_actions, web_search=True)
            total_cost += m2["cost_usd"] or 0
            # Keyed on (state, citation): one state can hold several actions at once —
            # Texas has SB 6 and the governor's audit order, and they are different
            # instruments with different lifetimes.
            by_key = {(a["state"].lower(), a["citation"].lower()): a for a in actions}
            for a in classified["actions"]:
                by_key[(a["state"].lower(), a["citation"].lower())] = a
            for e in classified["ended"]:
                by_key.pop((e["state"].lower(), e["citation"].lower()), None)
            # Rejections are EVIDENCE, not noise: each is a state the sweep found and
            # the gate refused, and a gate that is too strict shrinks this count in the
            # bubble-supportive direction. Logged and stored so a false negative shows up
            # instead of looking like the state never existed.
            for r in classified.get("rejected", []):
                print(f"[STOPLIGHT] regulatory rejected {r['state']} "
                      f"({r['citation']}): {r['why']}")
            rejected = classified.get("rejected", [])
            new_actions = list(by_key.values())
            roster_changed = new_actions != actions
            actions = new_actions
    except ValueError:
        pass                                              # sweep/classify failed -> keep prior

    # NOTE: no count is derived here. The FACTOR counts the roster daily and for
    # free, which is what lets a temporary action retire on its own expiry date
    # without waiting for the next billed run.

    # Source 2 — DCW opposition count (own focused search, null-safe) --------------
    # REBUILT 2026-08-29. Two faults, and they are independent:
    #
    #   1. The metric was not reliably OBSERVABLE. The prompt demanded a blocked-ONLY
    #      count; the source mostly publishes a combined blocked-or-delayed figure. The
    #      validator did exactly as told and returned null on 8 of 9 calls, each of them
    #      billed. Both figures are honest measures of local opposition -- what is
    #      dishonest is not knowing which one you are holding. So both are accepted now
    #      and the BASIS is recorded.
    #
    #   2. Two observations were compared with nothing recording whether they measured
    #      the same thing. `dcw_prev_blocked` took the previous RUN's value, so it was a
    #      run counter, not an observation counter. On 2026-08-18 a "Q1 2026 outright
    #      cancellations" 20 was set against a SEEDED "blocked per quarter" 75 and fired
    #      the factor's only arrow to date -- off a changed question, not a changed
    #      world.
    #
    # An observation is now a RECORD (value, basis, period, quote, url, date) and the
    # previous one is kept whole, replaced only when a new observation actually lands.
    # The factor compares them and refuses when they are unlike; see regulatory.py.
    dcw_obs = prev.get("dcw") or None
    dcw_prev_obs = prev.get("dcw_prev") or None
    dcw_failed = False
    try:
        dcw, m3 = llm.extract_json(
            "regulatory", "dcw",
            [{"role": "system", "content": _DCW_SYS.replace("{today}", _today())},
             {"role": "user", "content": _DCW_QUERY}],
            model=llm.STAGE2_MODEL, validate=schemas.validate_dcw_blocked, web_search=True)
        total_cost += m3["cost_usd"] or 0
        if dcw["dcw_blocked_projects"] is not None:   # null => no clean count, keep prior
            fresh = {"value": dcw["dcw_blocked_projects"],
                     "basis": dcw.get("metric_basis"),
                     "period": dcw.get("period_label"),
                     "quote": dcw.get("source_quote"),
                     "url": dcw.get("url"),
                     "date": _today()}
            # A restatement of the SAME period on the same basis is not a new
            # observation, so it must not push the real prior one out of the window.
            same = (dcw_obs and fresh["basis"] == dcw_obs.get("basis")
                    and fresh["period"] == dcw_obs.get("period"))
            if not same:
                dcw_prev_obs = dcw_obs
            dcw_obs = fresh
    except ValueError:
        dcw_failed = True

    rec = {
        # `actions` replaces `states`, and there is no stored count: the field names
        # changed because the MEANING did, and a same-named field with a new meaning is
        # the trap this codebase keeps writing down. `basis` says which rule a record
        # was built under so the two are never silently compared.
        "actions": actions,
        "basis": "any_branch_in_force_statewide",
        "classify_rejected": rejected,
        "dcw": dcw_obs,
        "dcw_prev": dcw_prev_obs,
        "asof": _today(),
        "roster_changed": roster_changed,
        "dcw_failed": dcw_failed,
        "provenance": "multi-search per-source (full-list sweep->prove, Python-reconciled + DCW blocked)",
    }
    write_input("regulatory", rec)
    return rec, round(total_cost, 4)


# --- Event-driven per-source entry point (part 1 of the Update-button feature) ---
_BILLED_RUNNERS = {
    "silicon_payback": run_silicon_multi,
    "capex_spigot":    run_capex_spigot_multi,
    "infra_backlog":   run_infra_backlog_multi,
    "regulatory":      run_regulatory_multi,   # not per-source; tickers ignored
}


def run_factor_only(factor, only, period_end=None):
    """Run a billed factor refreshing EXACTLY the source-id set `only` (None = full
    run). regulatory is not per-source, so it always runs whole. `period_end` pins a
    backward-looking quarterly leg to ONE fiscal period (infra's VRT book-to-bill
    today); runners that ask for forward guidance ignore it. Returns (rec, cost)."""
    runner = _BILLED_RUNNERS.get(factor)
    if runner is None:
        raise ValueError(f"unknown billed factor: {factor}")
    if factor == "regulatory":
        return runner()
    if factor == "infra_backlog":
        return runner(only, period_end=period_end)
    return runner(only)


def run_due(factor, tickers=None):
    """Refresh a billed factor, pulling ONLY the sources triggered by `tickers`
    (a set/iterable of reporting tickers). `tickers=None` -> full refresh (the weekly
    backstop). Returns (record, cost). regulatory is not earnings-fed, so it always
    runs whole. If `tickers` is given but none of them feed `factor`, nothing is
    pulled and the record is re-derived from carried values at $0."""
    runner = _BILLED_RUNNERS.get(factor)
    if runner is None:
        raise ValueError(f"unknown billed factor: {factor}")
    if factor == "regulatory" or tickers is None:
        return runner()
    return runner(sources_triggered_by(factor, tickers))


def run(factor):
    if factor == "silicon_payback_multi":
        return run_silicon_multi()[0]
    if factor == "capex_spigot_multi":
        return run_capex_spigot_multi()[0]
    if factor == "infra_backlog_multi":
        return run_infra_backlog_multi()[0]
    if factor == "regulatory_multi":
        return run_regulatory_multi()[0]
    if factor == "regulatory":
        return run_regulatory_multi()[0]
    if factor in _EARNINGS:
        return run_earnings(factor)
    raise ValueError(f"unknown extractor: {factor}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    factors = (["regulatory", "infra_backlog", "silicon_payback", "capex_spigot"]
               if target == "all" else [target])
    for f in factors:
        print(json.dumps(run(f), indent=2))
