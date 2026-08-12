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
from ..extractors import read_input

RED_ABOVE = 10
GREEN_BELOW = -10


def compute():
    d = read_input("capex_spigot")
    yoy = d["guidance_yoy_pct"]

    if yoy > RED_ABOVE:
        light, state = "red", "spigot_open"
    elif yoy >= GREEN_BELOW:
        light, state = "yellow", "flat_decelerating"
    else:
        light, state = "green", "guidance_cut"

    return {
        "id": "capex_spigot",
        "light": light,
        "value": yoy,
        "metric": f"{yoy:+.0f}%",
        "state": state,
        "asof": d["asof"],
        "extras": {"provenance": d.get("provenance")},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
