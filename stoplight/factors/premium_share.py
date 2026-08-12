"""
Factor #4 — PREMIUM SHARE (WHETHER-leg 2: does quality command a premium?).
Rank 4. The commoditization kill-mechanism gauge.

Formula: premium models' revenue / total revenue on OpenRouter, where
revenue(model) = token volume x blended price.

  RED    >= 50%  — premium tier earns the MAJORITY of the money = premium intact
  YELLOW 35-50%
  GREEN  < 35%   — premium eroding = commoditization firing = pro-burst
(~10% is the true zero-point: premium revenue-share converging to premium
token-share = no premium left. Thresholds anchored on the majority line.)

PREMIUM/COMMODITY CUTOFF (the load-bearing definition):
- Commodity floor = cheapest ranked model's OUTPUT price > 0 among models with
  >=1% TOKEN SHARE, RE-READ every pull (the floor deflates ~80%/yr — a fixed
  $ line would sweep models in from deflation alone; the 50x MULTIPLE
  self-adjusts. Same anti-rot principle as copper's no-absolute-price rule).
  The >=1% volume qualification was ADDED 2026-07-19 (build session): the raw
  min was poisoned by a legacy artifact (mistral-nemo, $0.03/M at 0.55% share
  -> line $1.50 -> Gemini Flash counted as "premium"). A floor should be a
  real commodity workhorse, not a stale listing.
- Premium = OUTPUT price >= 50x floor.

REFERENCE DISCONTINUITY (2026-07-19, mirrors the concentration basis note):
the spec's 57.1% was computed on a narrower model window whose premium set
was just Opus 4.7+4.8. The full keyed top-50 carries premium models that
window missed (Kimi K3 $15, GPT-5.5/5.6 $30, Fable 5 $50...) and reads
~77-82% on the same day. Same light (deep red), higher level; the forward
series is self-consistent from 2026-07-19. SONNET-INSIDE RATIFIED (user,
2026-07-19): with the floor at $0.196 the $9.80 line includes Sonnet 5
($10/M). User's ruling: a legitimate top-3 commodity model setting a new
price floor makes Sonnet READ as premium — "50x is generous, roll with it."
The 50x multiple is settled; do not re-litigate toward 75x.

METHODOLOGY RULES (spec-locked):
1. REVENUE not tokens for the light (cross-provider token counts are
   incommensurate; dollars compare).
2. OUTPUT price for the threshold; revenue uses the 80/20 in/out blend
   (rankings gives TOTAL tokens; robust: 57.1% @80/20 vs 58.1% @50/50).
3. :free variants earn $0 revenue (they ARE the commodity tide); "other" and
   unmatched rows priced at the commodity floor blend (conservative commodity
   assumption — counts noted in extras).
4. Opus "Fast"/priority SKUs are a red herring — the join prices each
   permaslug at its own listed standard pricing.

+/- ENHANCER (glyph, light DOMINATES, never softens the color): commodity
token share. plus = volume picture AGREES with the money picture (same side
of 50%); minus = contradicts ("red with a crack": premium keeps the money
while commodity takes the volume). Deterministic: sign of agreement between
premium_revenue_share>=50 and premium_token_share>=50.

SOURCE: OpenRouter rankings-daily (KEYED — free key) + /models (public).
Reference (2026-07-18 spec): RED- 57.1% (Opus 4.7+4.8), commodity token
share 83% and rising. Cadence: daily, state-change.
"""
from ..sources.openrouter import rankings_daily, model_prices

PREMIUM_MULTIPLE = 50.0
FLOOR_MIN_TOKEN_SHARE = 0.01   # floor candidates need >=1% of the day's tokens
GREEN_BELOW = 35.0
RED_AT_OR_ABOVE = 50.0
IN_OUT_BLEND = (0.8, 0.2)   # total-token split assumption: 80% input / 20% output


def compute():
    rows = rankings_daily()
    latest = max(r["date"] for r in rows)
    today = [r for r in rows if r["date"] == latest]
    prices = model_prices()

    # commodity floor: cheapest nonzero OUTPUT price among ranked models with
    # >=1% token share (volume-qualified — see docstring)
    day_total = sum(r["total_tokens"] for r in today)
    ranked_out_prices = [prices[r["model_permaslug"]]["completion_per_m"]
                         for r in today
                         if r["model_permaslug"] in prices
                         and r["total_tokens"] / day_total >= FLOOR_MIN_TOKEN_SHARE]
    floor = min(p for p in ranked_out_prices if p > 0)
    premium_line = floor * PREMIUM_MULTIPLE

    w_in, w_out = IN_OUT_BLEND
    # "other"/unmatched rows have no listed prices — priced at the floor for
    # both legs (conservative commodity assumption; in/out spread down there
    # is small relative to the 50x premium line).
    floor_blend = floor

    prem_rev = total_rev = prem_tok = total_tok = 0.0
    premium_models, unmatched = [], []
    for r in today:
        slug, tok = r["model_permaslug"], r["total_tokens"]
        total_tok += tok
        p = prices.get(slug)
        if p is None and slug.endswith(":free"):
            continue                     # $0 revenue; stays in token totals
        if p is None:                    # "other" aggregate + non-chat models
            unmatched.append(slug)
            total_rev += tok / 1e6 * floor_blend
            continue
        blended = w_in * p["prompt_per_m"] + w_out * p["completion_per_m"]
        rev = tok / 1e6 * blended
        total_rev += rev
        if p["completion_per_m"] >= premium_line:
            prem_rev += rev
            prem_tok += tok
            premium_models.append(slug)

    share = round(prem_rev / total_rev * 100, 1)
    commodity_tok_share = round((1 - prem_tok / total_tok) * 100, 1)

    if share >= RED_AT_OR_ABOVE:
        light, state = "red", "premium_intact"
    elif share >= GREEN_BELOW:
        light, state = "yellow", "premium_eroding"
    else:
        light, state = "green", "commoditized"

    # +/- : does the VOLUME picture agree with the MONEY picture?
    agree = (share >= 50) == ((100 - commodity_tok_share) >= 50)
    arrow = "plus" if agree else "minus"

    return {
        "id": "premium_share",
        "light": light,
        "value": share,
        "metric": f"{share:.1f}%",
        "state": state,
        "asof": latest,
        "extras": {
            "arrow": arrow,
            "commodity_token_share_pct": commodity_tok_share,
            "floor_out_per_m": round(floor, 3),
            "premium_line_out_per_m": round(premium_line, 2),
            "premium_models": premium_models,
            "n_unmatched_floor_priced": len(unmatched),
            "source": "OpenRouter rankings-daily + /models",
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
