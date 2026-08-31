"""
Factor #13 — CAPEX SPIGOT (the confirming half of the capex pair). Rank 13.

Measure: hyperscaler forward capex GUIDANCE growth, YoY, basket aggregate —
"is the money still flowing?"

  RED    > +10%       — spigot wide open = bubble-supportive
  YELLOW -10% to +10% — flat / decelerating
  GREEN  < -10%       — guidance CUT = the demand-side flip = pro-burst

NO ARROW (correct): the measure is a RATE, so direction is already in the number
— an arrow would be the 2nd derivative. (Contrast capex-pressure #12, a LEVEL,
which does carry one.) The CONFIRMING half of the pair: pressure greens first
(names breach 100% capex/OCF), THEN the spigot greens (the forced guidance cut).
Given the lag, a green here is CONFIRMATION, not warning — the warning is one
layer up (pressure + infra-backlog).

INPUTS (extractors/ — billed refresh; seeded now): guidance_yoy_pct.
Reference (2026-07-18 spec): +73% YoY (deeply red; reported-capex basket
anchor, guidance runs ahead).
"""
from datetime import date

from .. import store
from ..extractors import read_input

RED_ABOVE = 10
GREEN_BELOW = -10

# Which period each company's GUIDANCE covers, and therefore which period its prior has
# to be. NOT derivable from the fiscal calendar: MSFT's fiscal year ends in JUNE but it
# guides on the CALENDAR year — its old pinned prior matched calendar-2025 ($83.1B GAAP)
# and not fiscal-2025 ($64.6B), which is a 29% difference and would have been a silent
# one. ORCL is the only name here guiding on its own fiscal year. Typed rather than
# parsed out of the `basis` prose, per the extract-vs-derive rule: Python never reads a
# sentence to make a decision.
PRIOR_PERIOD = {"MSFT": 12, "GOOGL": 12, "AMZN": 12, "META": 12, "ORCL": 5}


def _prior_from_store(sym):
    """The prior full year for one name, from the SEC store -> dict or None.

    CAPEX PLUS FINANCE-LEASE PRINCIPAL PAYMENTS, which is what these companies mean by
    "capex including finance leases" — META says so in as many words, and its old pin
    lands within $0.2B of this basis, which is what identified the convention. The
    ROU-asset tag was tested and rejected: it is a NON-CASH addition, and it puts MSFT
    $19.6B off its own pin.

    WHY THIS IS DERIVED AND NO LONGER PINNED (2026-08-31, user's call). The five pinned
    constants were never on one basis — measured against the filings, GOOGL and ORCL
    were pure GAAP, META was GAAP plus principal payments, MSFT was neither, and AMZN
    was its GUIDANCE figure rather than an actual, $6.8B under its own filed number and
    understated in the direction that inflates this factor's reading. That is exactly
    the multi-basis problem `run.py`'s comment describes; pinning inherited it instead
    of solving it. Deriving from one stated convention makes every denominator
    comparable, self-updating as each year closes, and checkable against the filings —
    which the pins, by construction, were not.

    The year end is found in the data rather than hardcoded: the most recent stored
    quarter whose month is the company's year-end month, then the four contiguous
    quarters ending there. Nothing to update when the calendar turns."""
    rows = store.financials(sym)
    if not rows:
        return None
    month = PRIOR_PERIOD.get(sym, 12)
    ends = [r["period_end"] for r in rows if int(r["period_end"][5:7]) == month]
    if not ends:
        return None
    year_end = ends[-1]
    i = next(i for i, r in enumerate(rows) if r["period_end"] == year_end)
    window = rows[max(i - 3, 0):i + 1]
    if len(window) < 4:
        return None
    # Refuse a window with a hole in it rather than summing across one — the same rule
    # capex_pressure applies to its TTM, and for the same reason.
    for a, b in zip(window, window[1:]):
        gap = (date.fromisoformat(b["period_end"])
               - date.fromisoformat(a["period_end"])).days
        if not (80 <= gap <= 100):
            return None
    return {
        "prior_b": round(sum(r["capex"] + r["fin_lease"] for r in window) / 1e9, 1),
        "capex_b": round(sum(r["capex"] for r in window) / 1e9, 1),
        "lease_b": round(sum(r["fin_lease"] for r in window) / 1e9, 1),
        "period_start": window[0]["period_start"], "period_end": year_end,
        "lease_filed": all(r["fin_lease_filed"] for r in window),
        "derived_quarters": sum(1 for r in window
                                if "derived" in (r["ocf_basis"], r["capex_basis"])),
    }


def compute():
    d = read_input("capex_spigot")
    per = d.get("per_company") or {}

    # GUIDANCE is model-pulled and genuinely soft — a forward number stated on a call.
    # The PRIOR is derived here from the filings, every pass, so it needs no billed
    # re-pull to stay current and cannot go quietly stale. Model extracts, Python
    # derives: the same split the newsletter spec sets out.
    guided, prior_sum, missing = 0.0, 0.0, []
    for sym, v in per.items():
        g = v.get("guidance_b")
        pr = _prior_from_store(sym)
        if g is None or pr is None:
            missing.append(sym)
            continue
        guided += g
        prior_sum += pr["prior_b"]
    if not prior_sum:
        raise ValueError("capex_spigot: no derivable priors in the financials store")

    yoy = round((guided / prior_sum - 1) * 100, 1)
    light, state = _light(yoy)

    return {
        "id": "capex_spigot",
        "light": light,
        "value": yoy,
        "metric": f"{yoy:+.0f}%",
        "state": state,
        "asof": d["asof"],
        "extras": {
            "provenance": d.get("provenance"),
            "prior_basis": "SEC capex + finance-lease principal payments, derived",
            **({"no_prior": missing} if missing else {}),
        },
    }


def _light(yoy):
    """The band — ONE implementation, called by compute() and by ledger(), so the pane
    cannot explain the light with a second copy of the rule that decided it."""
    if yoy > RED_ABOVE:
        return "red", "spigot_open"
    if yoy >= GREEN_BELOW:
        return "yellow", "flat_decelerating"
    return "green", "guidance_cut"


def ledger(days=10, top=10):
    """Where the aggregate comes from: five companies' forward guidance against the
    prior year, and where each figure was read.

    ONE CURRENT RECORD, like silicon_payback and regulatory. The extractor store keeps
    only the latest print, so there is no honest way to reconstruct what a company
    guided last month; this returns today's and the history accumulates print by print
    as the scheduler records it. For a quarterly, earnings-driven factor that is the
    right shape anyway — a row per reported period, not per calendar day. `days`/`top`
    are accepted for signature parity and ignored: the basket is five names.

    FREE: re-reads the SAME input record compute() reads, through the same `_light`.

    THE WEIGHT IS THE POINT OF THE FIRST VIEW. This aggregate is DOLLAR-weighted —
    sum(guidance) / sum(prior) — which is the opposite of capex_pressure's unweighted
    majority next door, and deliberately: the question here is whether the money is
    still flowing, and a dollar is a dollar whoever spends it. The consequence is that
    the names are not equal contributors, so each row carries its share of the basket
    and the view draws it."""
    d = read_input("capex_spigot")
    per = d.get("per_company") or {}
    total_g = sum(v.get("guidance_b") or 0 for v in per.values())

    names = []
    for sym, v in per.items():
        g = v.get("guidance_b")
        pr = _prior_from_store(sym) or {}
        prior = pr.get("prior_b")
        names.append({
            "key": sym,
            "guidance_b": g, "prior_b": prior,
            "prior_capex_b": pr.get("capex_b"), "prior_lease_b": pr.get("lease_b"),
            "prior_period_start": pr.get("period_start"),
            "prior_period_end": pr.get("period_end"),
            # What the retired constant said, kept so the pane can show the correction
            # rather than just quietly reading differently than it did yesterday.
            "pinned_prior_b": v.get("prior_b"),
            "yoy_pct": round((g / prior - 1) * 100, 1) if (g and prior) else None,
            # Share of the basket's guided dollars — how much this name moves the light.
            "weight_pct": round(g / total_g * 100, 1) if (g and total_g) else None,
            # DERIVED from the filings now, not pinned. Kept as a field because the
            # pane distinguishes the soft half (guidance, model-pulled) from the hard
            # half (prior, computed off SEC) and says which is which.
            "prior_derived": bool(prior),
            "disclosed": v.get("disclosed") is not False,
            "basis": v.get("basis"),
            "url": v.get("url"),
            "refreshed_at": v.get("refreshed_at"),
        })
    names.sort(key=lambda n: -(n["guidance_b"] or 0))
    # Recomputed from the SAME derived priors compute() uses, never read back off the
    # stored record — so the pane and the light cannot disagree about the denominator.
    ps = sum(n["prior_b"] or 0 for n in names)
    yoy = round((sum(n["guidance_b"] or 0 for n in names) / ps - 1) * 100, 1) if ps else 0
    light, state = _light(yoy)

    return [{
        "date": d.get("asof"),
        "light": light, "state": state,
        "yoy": yoy,
        "total_guidance_b": round(total_g, 1),
        "total_prior_b": round(sum(n["prior_b"] or 0 for n in names), 1),
        "total_pinned_prior_b": round(sum(n["pinned_prior_b"] or 0 for n in names), 1),
        "prior_basis": "SEC capex + finance-lease principal payments",
        "red_above": RED_ABOVE, "green_below": GREEN_BELOW,
        "n_names": len(names),
        "names": names,
        # A name that did not guide is not a zero — it is a hole in a dollar-weighted
        # sum, and it has to be visible rather than averaged away.
        "undisclosed": [n["key"] for n in names if not n["disclosed"]],
        "failed": d.get("failed_companies") or [],
        "refreshed": d.get("refreshed_companies") or [],
        "provenance": d.get("provenance"),
    }]


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
