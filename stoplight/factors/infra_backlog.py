"""
Factor #8 — INFRA BACKLOG (MOST-LEADING factor of the capex complex). Rank 8.

PRIMARY: VRT book-to-bill = NEW orders booked (a FLOW) / shipments-billings in
the period (a FLOW) — NOT cumulative backlog (a STOCK). Sits UPSTREAM of the
capex pair (orders move before guidance).

  RED    > 1.0
  YELLOW 0.9-1.0  (or a single sub-0.9 print — unconfirmed)
  GREEN  < 0.9 AND two CONSECUTIVE prints under 0.9 (b-t-b is lumpy: one print
         is a data point, two is a turn)

The green needs confirmation because VRT's backlog is only ~0.9 YEARS of
revenue — no cushion, so you need b-t-b >1 just to hold ground. A green can't
be faked by share loss: for b-t-b to fall 2.9x -> <0.9, orders must drop ~70%.

+/- CORROBORATOR (glyph on VRT's color; light DOMINATES): GEV AVAILABLE-GW
(hardened 2026-07-19). The extractor emits only STATED primitives; THIS deriver
resolves the direction two ways: (1) PRIMARY — the period-over-period delta of the
verbatim unsold-GW STOCK (+/-5 GW deadband; needs two prints); (2) FALLBACK — used
only when the delta can't be computed — management's OWN stated direction (a
single-reading seed). shrinking (unsold GW falling) = demand strong = AGREES with
red (+); growing (rising = slots reopening) = demand evaporating = contradicts red
(-); flat / neither stated = no glyph. Read the TIMING (spec): a - next to today's
red is GEV latency (ignore); a + returning AFTER VRT greens is the real sector-wide
confirmation.

INPUTS (extractors/ — billed refresh; seeded now): vrt_book_to_bill,
prev_book_to_bill, gev_available_gw (stock), gev_total_available_gw,
gev_prev_total_available_gw, gev_stated_direction. Reference (2026-07-18 spec): 2.9x
(red), VRT Q4'25 (verified); GEV glyph pends a stated stock-diff OR a stated
management direction. Catalysts: GEV Jul 22, VRT Jul 29.
"""
from ..extractors import read_input

RED_ABOVE = 1.0
YELLOW_AT = 0.9


def compute():
    d = read_input("infra_backlog")
    btb = d["vrt_book_to_bill"]
    prev = d.get("prev_book_to_bill")

    # NON-DISCLOSURE CAP (user, 2026-07-30). A carried-forward strong print must not
    # keep asserting maximum bubble-support after the company has STOPPED PUBLISHING
    # the metric. VRT touted +252% orders and a 2.9x book-to-bill in Q4'25; in Q1'26
    # management said outright "we do not disclose orders", and the Q2'26 call (which
    # IS published) gives only qualitative language — "robust orders growth", "strong
    # backlog coverage" — with no number. Going from effusive-and-quantified to
    # qualitative-only is itself information, and it points AWAY from conditions being
    # as favorable as 2.9x implies.
    #
    # So: while the leg is flagged undisclosed, RED is capped to YELLOW. Deliberately
    # a cap and not a downgrade — silence is soft evidence, enough to withdraw the
    # strongest claim but NOT enough to manufacture a pro-burst signal, so it never
    # reaches green. A yellow/green earned from real prints is left alone.
    # Keyed off the extractor's typed `unavailable` flag (set when a period-pinned
    # pull came back with no figure), NOT off prose or a date heuristic.
    leg = (d.get("sources") or {}).get("vrt_btb") or {}
    undisclosed = bool(leg.get("unavailable"))

    if btb > RED_ABOVE and undisclosed:
        light, state = "yellow", "orders_undisclosed"
    elif btb > RED_ABOVE:
        light, state = "red", "orders_flooding"
    elif btb >= YELLOW_AT:
        light, state = "yellow", "softening"
    elif prev is not None and prev < YELLOW_AT:
        light, state = "green", "orders_evaporating"   # two consecutive sub-0.9
    else:
        light, state = "yellow", "sub0.9_unconfirmed"  # first sub-0.9 print

    # +/- corroborator: GEV available-GW direction, CODE-resolved (user's hardened
    # spec 2026-07-19 — the model emits STATED primitives, never an inferred trend).
    # Two stated paths, resolved here:
    #   PRIMARY  — numeric: compare this period's total unsold GW to prior (+/-5 GW
    #              deadband). Objective; needs two stated stock prints.
    #   FALLBACK — management's own stated direction, used ONLY when the numeric delta
    #              can't be computed (a single-reading seed for the glyph).
    #   shrinking (unsold GW falling)  -> demand strong  -> agrees with red  -> plus
    #   growing   (unsold GW rising)   -> slots reopening -> contradicts red -> minus
    #   flat / neither stated          -> no glyph
    cur = d.get("gev_total_available_gw")
    prv = d.get("gev_prev_total_available_gw")
    stated = d.get("gev_stated_direction") or {}
    GEV_DEADBAND_GW = 5
    direction = dir_source = None
    if isinstance(cur, (int, float)) and isinstance(prv, (int, float)):
        delta = cur - prv
        direction = ("shrinking" if delta < -GEV_DEADBAND_GW
                     else "growing" if delta > GEV_DEADBAND_GW else "flat")
        dir_source = "computed_delta"
    elif stated.get("direction") in ("shrinking", "flat", "growing"):
        direction = stated["direction"]                  # management's stated trend
        dir_source = "stated_management"
    arrow = {"shrinking": "plus", "growing": "minus"}.get(direction)  # flat/None -> None

    # standalone GEV reading in the board's inverted scheme (shrinking demand-strong
    # = red/bubble-supportive; growing = green/pro-burst) — display only; the LIGHT
    # is VRT's, GEV is the corroborator glyph.
    gev_light = {"shrinking": "red", "flat": "yellow", "growing": "green"}.get(direction)
    gev_stock = d.get("gev_available_gw") or {}

    return {
        "id": "infra_backlog",
        "light": light,
        "value": btb,
        "metric": f"{btb:.1f}x",
        "state": state,
        "asof": d["asof"],
        "extras": {
            "arrow": arrow,
            "prev_book_to_bill": prev,
            # why the light may be capped below what the number alone implies
            "undisclosed": undisclosed,
            "undisclosed_since": leg.get("period_end") if undisclosed else None,
            "gev_direction": direction,
            "gev_direction_source": dir_source,           # computed_delta | stated_management
            "gev_light": gev_light,
            "gev_total_available_gw": cur,
            "gev_prev_total_available_gw": prv,
            "gev_as_of": gev_stock.get("as_of") or stated.get("as_of"),
            "provenance": d.get("provenance"),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
