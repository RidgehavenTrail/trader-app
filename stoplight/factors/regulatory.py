"""
Factor #10 — REGULATORY (earnings-durability DRAG, not a timing canary). Rank 10.

PRIMARY: count of states with a STATE-WIDE cost-shift policy (datacenters fund
their own power infra / higher rate class instead of socializing onto
ratepayers). The 3-test counting rule (state-wide + general/threshold-defined +
not project/single-utility) is the extractor's classification job — this
deriver just reads the resulting count.

  RED    < 10 states  — below 10, hyperscalers relocate to a free-ride state
  YELLOW 10-20        — relocation gets hard ("start of a movement")
  GREEN  20+          — essentially federal, nowhere to run = free ride over

KEY DISCIPLINE (upstream, in the extractor): GATE ON ENACTED LAW, not the loud
pipeline (300+ bills / 27 "considering"). Vibe says yellow; statute count says
red. Direction: green = constraint rising = pro-burst; red = free ride on.

+/- ENHANCER — Data Center Watch blocked-project count as a DIRECTIONAL ARROW
(physical-stoplight: more blocks = down/toward burst, fewer = up). Monitors the
populist swell under the slow statutory primary. Quarantined by the
light-dominates rule — the arrow never changes the color.

INPUTS (extractors/ — billed refresh; seeded now): enacted_states,
dcw_blocked_projects, dcw_prev_blocked. Reference (2026-07-18 spec): 3 states
(red, CA/OH/UT), blocks 20->75/qtr (arrow down).
"""
from ..extractors import read_input

GREEN_AT = 20
YELLOW_AT = 10


def compute():
    d = read_input("regulatory")
    states = d["enacted_states"]

    if states >= GREEN_AT:
        light, state = "green", "nowhere_to_run"
    elif states >= YELLOW_AT:
        light, state = "yellow", "movement_starting"
    else:
        light, state = "red", "free_ride_on"

    # DCW blocked-project ARROW: more blocks -> down (toward burst)
    blocked = d.get("dcw_blocked_projects")
    prev = d.get("dcw_prev_blocked")
    arrow = None
    if blocked is not None and prev is not None:
        arrow = "down" if blocked > prev else ("up" if blocked < prev else None)

    return {
        "id": "regulatory",
        "light": light,
        "value": states,
        "metric": f"{states} states",
        "state": state,
        "asof": d["asof"],
        "extras": {
            "arrow": arrow,
            "dcw_blocked_projects": blocked,
            "dcw_prev_blocked": prev,
            "provenance": d.get("provenance"),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
