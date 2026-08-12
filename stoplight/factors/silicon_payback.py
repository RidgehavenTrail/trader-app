"""
Factor #5 — SILICON PAYBACK (WHETHER-leg 1: is the demand real?). Rank 5.

Measure: AI *services* revenue / total accelerator spend — can the spend be
recovered? Numerator = OpenAI + Anthropic + MSFT Copilot + GOOGL Gemini
(services, NOT rails; AMZN excluded — it sells rails). Denominator = NVDA
data-center revenue / NVDA accelerator share (RUN-RATE: latest quarter x4,
never TTM; re-pull the share, custom silicon grows ~3x faster).

  GREEN  < 0.2   — spend NOT recovering (=1/5yr break-even, deliberately
                   generous) = demand not real = pro-burst
  YELLOW 0.2-0.5
  RED    > 0.5   — chips paying for themselves = demand real = supportive

CAVEAT: SILICON-ONLY (power/shells/networking sit on top — RED means "chips
pay for themselves," not "healthy"). It's a FLOOR: 3rd-party enterprise
consumption on Azure OpenAI/Bedrock/Vertex is real demand but invisible, so
the error runs toward less-green.

INPUTS (extractors/ — billed refresh; seeded now): services_rev_b,
nvda_dc_qtr_b, nvda_accel_share. Reference (2026-07-18 spec): 0.21 (yellow),
num $86.5B / den $412B ($75.2B x4 / 0.73).
"""
from ..extractors import read_input

GREEN_BELOW = 0.2
RED_ABOVE = 0.5


def compute():
    d = read_input("silicon_payback")
    denom = d["nvda_dc_qtr_b"] * 4 / d["nvda_accel_share"]
    ratio = round(d["services_rev_b"] / denom, 2)

    if ratio < GREEN_BELOW:
        light, state = "green", "spend_unrecovered"
    elif ratio <= RED_ABOVE:
        light, state = "yellow", "partial_recovery"
    else:
        light, state = "red", "chips_self_funding"

    return {
        "id": "silicon_payback",
        "light": light,
        "value": ratio,
        "metric": f"{ratio:.2f}",
        "state": state,
        "asof": d["asof"],
        "extras": {
            "numerator_b": d["services_rev_b"],
            "denominator_b": round(denom, 1),
            "components": d.get("components"),
            "provenance": d.get("provenance"),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
