"""
Factor #12 — CAPEX PRESSURE (the ORCL canary lives here). Rank 12.

Measure: capex / operating cash flow, PER COMPANY, TTM (last 4 quarters summed —
season-complete, smooths Q4-vs-Q1 capex patterns). Basket: MSFT GOOGL AMZN META
ORCL, UNWEIGHTED (dollar-weighting would shrink ORCL from canary to rounding
error) — individual lights, then a MAJORITY read.

PER-COMPANY THRESHOLDS (inverted board):
  RED    < 75%    : self-funding = supportive
  YELLOW 75-100%  : burning too much
  GREEN  > 100%   : funding the bet with the balance sheet = pro-burst

MAJORITY TIE-BREAKS (5 lights can deadlock; conservative = toward red):
  RULE 1: green/red tie -> YELLOW (extremes cancel)
  RULE 2: two ADJOINING tiers tied -> defer UP toward red
          (2R/2Y -> RED ; 2Y/2G -> YELLOW)

ARROW (stoplight-POSITION mnemonic, not raw metric direction): ratios RISING =
burning more = arrow DOWN toward burst. Computed per name vs the year-ago TTM
when 8 quarters are available; falls back to FY-vs-prior-FY (annual cashflow)
when yfinance serves fewer quarters. Majority of computable names decides.

SOURCE: yfinance quarterly_cashflow ("Operating Cash Flow" / "Capital
Expenditure" rows, substring match — names vary). Reference (2026-07-18 spec,
TTM): MSFT 57%R GOOGL 63%R META 61%R AMZN 102%G ORCL 174%G -> majority RED,
arrow DOWN (all five deteriorating YoY).
"""
import yfinance as yf

BASKET = ["MSFT", "GOOGL", "AMZN", "META", "ORCL"]


def _ratio_from_rows(cf, start, count=4):
    """capex/OCF x100 from `count` quarters starting at column offset `start`.
    None if the frame doesn't reach that far."""
    ocf_row = [r for r in cf.index if "Operating Cash Flow" in r]
    capex_row = [r for r in cf.index if "Capital Expenditure" in r]
    if not ocf_row or not capex_row or cf.shape[1] < start + count:
        return None
    ocf = cf.loc[ocf_row[0]].iloc[start:start + count].sum()
    capex = abs(cf.loc[capex_row[0]].iloc[start:start + count].sum())
    if not ocf:
        return None
    return round(float(capex / ocf * 100))


def _name_light(pct):
    if pct > 100:
        return "green"
    if pct >= 75:
        return "yellow"
    return "red"


def _majority(lights):
    counts = {c: lights.count(c) for c in ("green", "yellow", "red")}
    top = max(counts.values())
    leaders = [c for c, n in counts.items() if n == top]
    if len(leaders) == 1:
        return leaders[0]
    if set(leaders) == {"green", "red"}:      # rule 1: extremes cancel
        return "yellow"
    if "red" in leaders:                      # rule 2: adjoining ties defer up
        return "red"
    return "yellow"                           # yellow/green tie


def compute():
    per_name, deteriorating = {}, []
    latest_quarter = None
    for sym in BASKET:
        cf = yf.Ticker(sym).quarterly_cashflow
        try:
            q = cf.columns[0].date().isoformat()
            latest_quarter = max(latest_quarter or q, q)
        except Exception:
            pass
        ttm = _ratio_from_rows(cf, 0)
        if ttm is None:
            raise ValueError(f"{sym}: cashflow rows/quarters unavailable")
        prior = _ratio_from_rows(cf, 4)       # year-ago TTM (needs 8 quarters)
        basis = "ttm_yoy"
        if prior is None:                     # fallback: FY vs prior FY
            acf = yf.Ticker(sym).cashflow
            prior = _ratio_from_rows(acf, 1, count=1)
            this_fy = _ratio_from_rows(acf, 0, count=1)
            basis = "fy_yoy"
            if prior is not None and this_fy is not None:
                deteriorating.append(this_fy > prior)
        else:
            deteriorating.append(ttm > prior)
        per_name[sym] = {"pct": ttm, "light": _name_light(ttm),
                         "prior_pct": prior, "arrow_basis": basis}

    lights = [v["light"] for v in per_name.values()]
    light = _majority(lights)
    arrow = None
    if deteriorating:
        n_down = sum(deteriorating)
        arrow = "down" if n_down > len(deteriorating) / 2 else (
            "up" if n_down < len(deteriorating) / 2 else None)

    through = [s for s, v in per_name.items() if v["light"] == "green"]
    counts = f"{lights.count('green')}g/{lights.count('yellow')}y/{lights.count('red')}r"
    return {
        "id": "capex_pressure",
        "light": light,
        "value": len(through),                # the queue: names through the 100% gate
        # ASCII-only: Windows console logs choke on glyph arrows (cp1252); the
        # frontend renders the arrow from extras["arrow"].
        "metric": f"{len(through)}/5 thru",
        "state": counts,
        "asof": latest_quarter,               # most recent reported quarter-end
        "extras": {"per_name": per_name, "arrow": arrow,
                   "source": "yfinance quarterly_cashflow, TTM"},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
