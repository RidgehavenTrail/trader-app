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
burning more = arrow DOWN toward burst. Per name, this TTM against the YEAR-AGO
TTM — one basis for every name, always. Majority decides.

SOURCE: SEC XBRL, as-reported, accumulated in the `financials` table
(`sources/sec.py`, `store.record_financials`). NOT a vendor frame.

  WHY IT CHANGED (2026-08-30, user's call). This read yfinance's quarterly
  cashflow on every poll and took whatever rolling window it served. Measured:
  MSFT 7 quarters, GOOGL 5, AMZN 6, META 6, ORCL 6 — against the 8 the year-ago
  TTM needs. So the basis documented above as primary COULD NEVER FIRE, and all
  43 stored readings silently used an FY-vs-prior-FY fallback while recording a
  TTM ratio beside a fiscal-YEAR one as though they were comparable. They were
  not: GOOGL's stored pair read 71 against 42 (+29pt) where the comparison
  actually performed was 56 against 42 (+14pt). Two more faults rode along —
  AMZN's newest column was a quarter behind the rest of the basket (its TTM was
  stale and the board stamped the basket's max() asof over it), and META's frame
  was missing 2025-03-31 from the middle, which a deeper window would have summed
  straight across.

  Capex and operating cash flow for a closed quarter are IMMUTABLE FACTS. They are
  now taken from the filings and kept: 315 quarters seeded on 2026-08-30, 47-72 per
  name, back to 2008 for MSFT and AMZN. Cross-checked against yfinance on the 30
  overlapping quarters — 25 agree within 0.5%, 0 differ, and the other 5 are periods
  where yfinance holds a NaN and SEC has a real number (`sec.cross_check`).

  What moved when it switched: nothing on the board (still red, 2/5 thru, 2g/0y/3r,
  arrow down), but AMZN's ratio went 102 -> 107 because the yfinance TTM was a
  quarter stale — and 102 sat two points above the 100% gate that makes it one of
  the two greens. Every prior_pct is now a real year-ago TTM: MSFT 47, GOOGL 50,
  AMZN 89, META 51, ORCL 102.

Reference (2026-07-18 spec, TTM): MSFT 57%R GOOGL 63%R META 61%R AMZN 102%G
ORCL 174%G -> majority RED, arrow DOWN (all five deteriorating YoY).
"""
from datetime import date

from .. import store
from ..sources import sec

BASKET = ["MSFT", "GOOGL", "AMZN", "META", "ORCL"]

YELLOW_AT = 75       # capex/OCF %: at or above this, burning too much
GREEN_ABOVE = 100    # ...and above this, funding the bet off the balance sheet

# THE READING COUNTS THE NAMES DRIVING THE COLOUR, AND NAMES THE COLOUR (user, 2026-09-12).
# It used to count the names through the 100% gate -- a real number, but one that could
# not explain the light beside it: on 3 red / 0 yellow / 2 green the rail read "2/5 thru"
# under a RED dot, and the panel captioned that 2 with red's own label, "self-funding",
# which describes the OTHER three. The count now follows the majority band.
#
# The word is the COLOUR, not this factor's own vocabulary: "3/5 red" says what is going
# on under the hood at a glance, while "thru" (and any coinage like it) lands only for a
# reader who already knows the factor's gates. The rail is the wrong place to learn them
# -- the detail panel carries the meaning, where there is room to say "self-funding,
# under 75% of cash flow".


def _name_light(pct):
    if pct > GREEN_ABOVE:
        return "green"
    if pct >= YELLOW_AT:
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


_QGAP = (80, 100)          # days between consecutive fiscal quarter-ends


def sync():
    """Pull SEC's as-reported quarters into the store -> {sym: counts} (or an error).

    Called at the top of compute(). SEC being unreachable must NOT fail the factor:
    the STORE is the record and SEC is only how it grows, so a dead network costs the
    newest quarter, never the reading. That is the whole point of keeping the history
    ourselves instead of re-asking a vendor for it every poll."""
    out = {}
    for sym in BASKET:
        try:
            out[sym] = store.record_financials(sec.quarters(sym))
        except Exception as e:                      # noqa: BLE001 - see docstring
            out[sym] = {"error": f"{type(e).__name__}: {e}"}
    return out


def _contiguous_tail(rows, n):
    """The last `n` rows, but only if they are CONSECUTIVE fiscal quarters.

    Returns None rather than a sum across a hole. yfinance's META frame was missing
    2025-03-31 from the middle and the old code would have summed straight through it
    the moment the window reached that far — a four-quarter total covering five
    quarters' worth of calendar, presented as a TTM. A gap is a reason to decline, not
    a rounding issue."""
    tail = rows[-n:]
    if len(tail) < n:
        return None
    for a, b in zip(tail, tail[1:]):
        gap = (date.fromisoformat(b["period_end"])
               - date.fromisoformat(a["period_end"])).days
        if not (_QGAP[0] <= gap <= _QGAP[1]):
            return None
    return tail


def _ratio(window):
    """capex / operating cash flow x100 over a window of quarters."""
    ocf = sum(r["ocf"] for r in window)
    if not ocf:
        return None
    return round(sum(r["capex"] for r in window) / ocf * 100)


def compute():
    # The refresh report is ENGINE BOOKKEEPING and stays out of `extras`. A factor with
    # no evidence view falls back to the panel's generic grid, which renders whatever
    # extras carries -- so a per-symbol dict of added/changed/unchanged counts became
    # 398px of raw JSON on screen (2026-08-31). Logged when something actually moved,
    # silent when it did not, and never displayed.
    sync_report = sync()
    moved = {k: v for k, v in sync_report.items()
             if v.get("error") or v.get("added") or v.get("changed")}
    if moved:
        print(f"[STOPLIGHT] capex_pressure financials sync: {moved}")
    per_name, deteriorating, notes = {}, [], []
    newest = None

    for sym in BASKET:
        rows = store.financials(sym)
        ttm_w = _contiguous_tail(rows, 4)
        if ttm_w is None:
            raise ValueError(f"{sym}: no four contiguous quarters in the store")
        ttm = _ratio(ttm_w)
        if ttm is None:
            raise ValueError(f"{sym}: operating cash flow sums to zero")

        # THE PRIMARY BASIS, AND NOW IT ACTUALLY FIRES. This comparison is documented
        # as the factor's arrow basis but could never run against yfinance, which
        # served 5-7 quarters where it needs 8 -- so every one of the 43 readings
        # before 2026-08-30 silently used the FY fallback the docstring calls
        # occasional, and stored a TTM next to a prior-FY number as though the two
        # were comparable. They were not: GOOGL's stored pair read +29pt where the
        # comparison actually made was +14.
        prior_w = _contiguous_tail(rows[:-4], 4)
        prior = _ratio(prior_w) if prior_w else None
        if prior is None:
            notes.append(f"{sym}: no year-ago TTM (needs 8 contiguous quarters)")
        else:
            deteriorating.append(ttm > prior)

        end = ttm_w[-1]["period_end"]
        newest = max(newest or end, end)
        per_name[sym] = {
            "pct": ttm, "light": _name_light(ttm),
            # Same basis as `pct`, always -- both are four contiguous quarters of the
            # same company, one window apart. The old `prior_pct` was a fiscal-YEAR
            # ratio sitting beside a TTM one.
            "prior_pct": prior, "arrow_basis": "ttm_yoy",
            "period_end": end, "ttm_start": ttm_w[0]["period_start"],
            "prior_period_end": prior_w[-1]["period_end"] if prior_w else None,
            # How the numbers reached us: 'filed' is a 3-month fact as the company
            # reported it, 'derived' is differenced out of the year-to-date facts,
            # which is the only way Q4 exists at all.
            "derived_quarters": sum(1 for r in ttm_w
                                    if "derived" in (r["ocf_basis"], r["capex_basis"])),
            "restated_quarters": sum(1 for r in ttm_w if r["restated"]),
            "quarters_stored": len(rows),
        }

    # A name whose latest quarter trails the newest in the basket by more than one
    # quarter is BEHIND, and says so rather than being averaged in silently. This is
    # the AMZN case: against yfinance its newest column was 2026-03-31 while the rest
    # had 2026-06-30, so its TTM was a quarter stale and the board stamped the
    # basket's max() asof over it. Fiscal calendars differ by design (ORCL ends in
    # May), so the test is a ~100-day tolerance, not equality.
    behind = [s for s, v in per_name.items()
              if (date.fromisoformat(newest)
                  - date.fromisoformat(v["period_end"])).days > _QGAP[1]]

    lights = [v["light"] for v in per_name.values()]
    light = _majority(lights)
    arrow = None
    if deteriorating:
        n_down = sum(deteriorating)
        arrow = "down" if n_down > len(deteriorating) / 2 else (
            "up" if n_down < len(deteriorating) / 2 else None)

    through = [s for s, v in per_name.items() if v["light"] == "green"]
    driving = [s for s, v in per_name.items() if v["light"] == light]
    counts = f"{lights.count('green')}g/{lights.count('yellow')}y/{lights.count('red')}r"
    return {
        "id": "capex_pressure",
        "light": light,
        # VALUE STAYS THE GATE COUNT. It is the recorded series -- every stored day
        # since this factor shipped means "names through 100%" by it -- and re-pointing
        # it at the majority would leave one column holding two meanings. The reading on
        # screen comes from `metric`; the gate count keeps its own name in extras.
        "value": len(through),                # the queue: names through the 100% gate
        # ASCII-only: Windows console logs choke on glyph arrows (cp1252); the
        # frontend renders the arrow from extras["arrow"].
        "metric": f"{len(driving)}/5 {light}",
        "state": counts,
        "asof": newest,                       # newest quarter-end in the basket
        "extras": {
            "per_name": per_name, "arrow": arrow,
            # What the reading counts, named rather than left to be re-derived: the
            # companies in the band the light landed on.
            "driving": driving, "through": through,
            # Diagnostics ride only when they have something to say. An empty list
            # renders as a "none" row in the generic grid, which is a line of chrome
            # asserting nothing -- and both of these are silent in the normal case.
            **({"behind": behind} if behind else {}),
            **({"notes": notes} if notes else {}),
            "source": "SEC XBRL companyconcept (as-reported), stored quarterly",
        },
    }


def _tie_break(counts):
    """Which majority rule decided the light, or None when one tier won outright.

    Named rather than inferred at render time: the tie-breaks are the least obvious
    part of this factor (five lights can deadlock, and the resolution defers toward
    red on purpose), and a view that showed only the winning colour would hide the
    fact that a rule fired at all."""
    top = max(counts.values())
    leaders = [c for c, n in counts.items() if n == top]
    if len(leaders) == 1:
        return None
    if set(leaders) == {"green", "red"}:
        return "extremes cancel -> yellow"
    if "red" in leaders:
        return "adjoining tiers tie -> defer up to red"
    return "yellow/green tie -> yellow"


def ledger(days=10, top=10):
    """The five companies behind the majority: each against its own gates, and each
    against itself a year ago.

    SNAPSHOT-DERIVED, like memory_canary and unlike silicon_payback's. Every figure
    this light is computed from already rides in the day's own `extras.per_name`, so
    this is a RE-SHAPE of the record rather than a re-derivation of it — the strongest
    form of the guarantee the ledgers table exists to give. It costs nothing (no SEC
    round-trip, on the panel or in the scheduler's capture) and it cannot disagree
    with the light it explains, because it is reading the numbers that light was
    decided on.

    `top` is accepted for signature parity and ignored: the basket is five names by
    definition and trimming it would remove the evidence."""
    out = []
    for day in store.history_payloads("capex_pressure", days):
        ex = day.get("extras") or {}
        per = ex.get("per_name") or {}
        if not per:
            continue                    # a row written before per_name existed

        names = []
        for sym in BASKET:
            v = per.get(sym) or {}
            pct = v.get("pct")
            if pct is None:
                continue
            prior = v.get("prior_pct")
            names.append({
                "key": sym, "pct": pct, "prior_pct": prior,
                "light": v.get("light") or _name_light(pct),
                # The move, in POINTS of the ratio. Only meaningful when both windows
                # sit on the same basis, which they now always do; a row written
                # before 2026-08-31 carries an FY prior against a TTM current and is
                # marked so rather than being quietly differenced.
                "delta": (pct - prior) if isinstance(prior, (int, float)) else None,
                "basis": v.get("arrow_basis"),
                "comparable": v.get("arrow_basis") == "ttm_yoy",
                "period_end": v.get("period_end"),
                "prior_period_end": v.get("prior_period_end"),
            })

        counts = {c: sum(1 for n in names if n["light"] == c)
                  for c in ("green", "yellow", "red")}
        through = [n["key"] for n in names if n["light"] == "green"]
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "through": len(through), "through_names": through,
            # The panel's reading counts the band the light landed on -- same rule the
            # rail uses, computed here so the two cannot drift apart.
            "driving": counts.get(day.get("light")) or 0,
            "n_names": len(names), "counts": counts,
            "tie_break": _tie_break(counts),
            "arrow": ex.get("arrow"),
            "yellow_at": YELLOW_AT, "green_above": GREEN_ABOVE,
            "names": names,
            "source": ex.get("source"),
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
