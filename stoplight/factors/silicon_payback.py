"""
Factor #5 — SILICON PAYBACK (WHETHER-leg 1: is the demand real?). Rank 5.

Measure: AI *services* revenue / total accelerator spend — can the spend be
recovered? Numerator = OpenAI + Anthropic + MSFT Copilot + GOOGL Gemini
(services, NOT rails; AMZN excluded — it sells rails). Denominator = NVDA
data-center revenue / NVDA accelerator share (RUN-RATE: latest quarter x4,
never TTM; RE-PULL the share -- and MEASURE its direction rather than assume
it. The extractor prompt used to assert "~70-75% and drifting down"; asked to
confirm a stated range the model returned 0.73 on every pull across seven
prints while only the revenue moved. The anchor is gone (2026-08-28) and the
ledger records accel_share per print, so the trend is now observable. Note the
sign: holding the share too LOW overstates the denominator and reads the light
GREENER than truth).

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


# Which extractor sources make up the numerator, in the order the spec names them,
# with the display name each carries on the panel. A LIST, not a scan of the input
# dict, because the numerator is a definition (services, not rails -- AMZN is excluded
# on purpose) and a new key appearing in the store must not silently join the sum.
NUM_PARTS = [
    ("openai",   "OpenAI",          "openai_rev_b"),
    ("anthropic", "Anthropic",      "anthropic_rev_b"),
    ("copilot",  "Microsoft Copilot", "copilot_rev_b"),
    ("gemini",   "Google Gemini",   "gemini_rev_b"),
]


def ledger(days=10, top=10):
    """The arithmetic behind the light: what the ratio is made of, and where each
    number came from.

    NOT a re-slice of a multi-day source. premium_share's ledger works because
    rankings_daily() hands back ~30 days on every call; the extractor store holds ONE
    record -- the latest print -- and pretending otherwise would mean re-deriving old
    quarters from today's inputs, which is the exact error the ledgers table exists to
    prevent. So this returns the single current period and the history accumulates
    print by print as the scheduler records it. For a quarterly factor that is the
    right shape anyway: a row per REPORTED PERIOD, not per calendar day.

    The two sides are shaped differently ON PURPOSE, because the arithmetic is:
      * the numerator is a SUM -- four service lines that add up, so each carries its
        share of the total and reads as a bar;
      * the denominator is a CHAIN -- one quarter annualised, then grossed up for the
        share of the market NVDA is not -- so it reads as steps, each showing what it
        did to the running figure. Drawing the denominator as a share table would
        invent parts that do not exist.

    `days` and `top` are accepted for signature parity with the other builders and
    ignored: there is one period to hand back and six inputs inside it, and trimming
    either would hide part of the computation this view exists to show."""
    d = read_input("silicon_payback")
    src = d.get("sources") or {}
    num = d["services_rev_b"]
    dc_qtr = d["nvda_dc_qtr_b"]
    share = d["nvda_accel_share"]
    run_rate = dc_qtr * 4
    den = run_rate / share
    ratio = round(num / den, 2)

    def _src(key, extra=None):
        s = src.get(key) or {}
        return {
            "source": s.get("source") or s.get("seat_source") or "",
            "url": s.get("url") or "",
            "refreshed_at": s.get("refreshed_at") or "",
            # When the SOURCE was published, which is a different question from when we
            # pulled it -- a fresh pull off a years-old market-sizing press release reads
            # identically to a fresh pull off this week's research unless both are kept.
            # Absent on every leg extracted before 2026-08-28.
            "published_at": s.get("published_at") or "",
            # An estimate the extractor could not pin to a disclosure is flagged rather
            # than averaged in silently -- the spec calls Anthropic the swing input and
            # a reader deserves to see which lines are soft.
            "soft": bool(s.get("low_confidence")) or (s.get("seat_disclosed") is False),
        }

    parts = []
    for key, name, field in NUM_PARTS:
        val = d.get(field)
        if val is None:
            continue
        parts.append(dict(key=key, name=name, value_b=val,
                          share=round(val / num * 100, 1) if num else 0.0, **_src(key)))

    build = [
        dict(label="NVDA data-center revenue",
             detail=d.get("nvda_dc_quarter") or "latest quarter",
             op="", value_b=round(dc_qtr, 1), **_src("nvda_dc")),
        dict(label="Annualised to a run rate",
             detail="latest quarter x4, never TTM",
             op="x4", value_b=round(run_rate, 1), source="", url="",
             refreshed_at="", published_at="", soft=False),
        dict(label="Grossed up past NVDA's share",
             detail=f"NVDA is {share:.0%} of industry GPU spend",
             op=f"/ {share:.2f}", value_b=round(den, 1), **_src("nvda_share")),
    ]

    return [{
        "date": d["asof"],
        "ratio": ratio,
        "light": ("green" if ratio < GREEN_BELOW
                  else "yellow" if ratio <= RED_ABOVE else "red"),
        "num_b": round(num, 1),
        "den_b": round(den, 1),
        "dc_qtr_b": round(dc_qtr, 1),
        "accel_share": share,
        "quarter": d.get("nvda_dc_quarter") or "",
        "num_parts": parts,
        "den_build": build,
    }]


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
