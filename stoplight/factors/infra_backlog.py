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
import datetime
import re

from ..extractors import read_input

RED_ABOVE = 1.0
YELLOW_AT = 0.9
GEV_DEADBAND_GW = 5

_QUARTER_RE = re.compile(r"^\D*Q([1-4])\D{0,3}((?:19|20)?\d\d)\s*$")


def _quarter_end(label):
    """'Q4 2025' / "Q4'25" -> date(2025, 12, 31). None when the label is not that
    shape, because a label we cannot read must not become a guessed date — the whole
    reason the quarter is recorded is to say how old the number is, and a wrong date
    would answer that question confidently and wrongly.

    VRT's fiscal year is the calendar year, so the quarter ends are the calendar ones.
    That is an assumption about ONE company, written down rather than assumed silently;
    a second name on this leg would need its own map."""
    m = _QUARTER_RE.match(label or "")
    if not m:
        return None
    q, y = int(m.group(1)), int(m.group(2))
    if y < 100:
        y += 2000
    return datetime.date(y, q * 3, (31, 30, 30, 31)[q - 1])


def _light(btb, prev, undisclosed):
    """The ladder AND the non-disclosure cap — ONE implementation, called by compute()
    and by ledger(). Returns (light, state, raw_light, raw_state): the capped answer
    plus what the number ALONE would have said. The gap between the two is the entire
    content of the Cap view, and a second copy of this rule would be free to disagree
    with the light it is supposed to explain."""
    if btb > RED_ABOVE:
        raw, raw_state = "red", "orders_flooding"
    elif btb >= YELLOW_AT:
        raw, raw_state = "yellow", "softening"
    elif prev is not None and prev < YELLOW_AT:
        raw, raw_state = "green", "orders_evaporating"    # two consecutive sub-0.9
    else:
        raw, raw_state = "yellow", "sub0.9_unconfirmed"   # first sub-0.9 print
    if raw == "red" and undisclosed:
        return "yellow", "orders_undisclosed", raw, raw_state
    return raw, raw_state, raw, raw_state


def _gev_direction(cur, prv, stated):
    """GEV's available-GW direction -> (direction, source, arrow). ONE implementation,
    for the same reason as _light.

    The user's hardened 2026-07-19 spec: the model emits STATED primitives and this
    code resolves the trend, never the other way round. Numeric delta is PRIMARY and
    wins when both exist; management's own stated direction is the FALLBACK that lets
    the glyph light off a single reading; anything else leaves it dark."""
    direction = source = None
    if isinstance(cur, (int, float)) and isinstance(prv, (int, float)):
        delta = cur - prv
        direction = ("shrinking" if delta < -GEV_DEADBAND_GW
                     else "growing" if delta > GEV_DEADBAND_GW else "flat")
        source = "computed_delta"
    elif (stated or {}).get("direction") in ("shrinking", "flat", "growing"):
        direction = stated["direction"]
        source = "stated_management"
    # shrinking (unsold GW falling) = demand strong = AGREES with red -> plus
    # growing   (slots reopening)   = demand evaporating = contradicts red -> minus
    return direction, source, {"shrinking": "plus", "growing": "minus"}.get(direction)


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

    light, state, _raw_light, _ = _light(btb, prev, undisclosed)

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
    direction, dir_source, arrow = _gev_direction(cur, prv, stated)

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


def ledger(days=10, top=10):
    """The evidence behind the light: what each leg was asked, what it answered, and
    how old the answer is.

    ONE CURRENT RECORD, like regulatory and silicon_payback and unlike premium_share.
    The extractor store keeps only the latest record, so there is no honest way to
    reconstruct what the legs said last Tuesday; this returns today's and the history
    accumulates print by print as the scheduler records it. `days`/`top` are accepted
    for signature parity and ignored — there are two legs, and trimming them would
    remove the evidence.

    FREE: re-reads the SAME input record compute() reads, through the same `_light`,
    so the pane cannot disagree with the board.

    THE POINT OF THIS VIEW is that both legs are currently answering with a SILENCE,
    and a silence renders as nothing at all unless something draws it. VRT's
    book-to-bill is a Q4'25 print the company has since declined to restate — it says
    outright that it does not disclose orders — and the light is capped to yellow
    because of it. GEV's glyph is dark not for want of a reading but because the one
    reading it has changed year scope between prints. Neither fact is visible on a
    board row that says '2.9x'."""
    d = read_input("infra_backlog")
    btb = d["vrt_book_to_bill"]
    prev = d.get("prev_book_to_bill")
    legs_in = d.get("sources") or {}
    vrt_leg = legs_in.get("vrt_btb") or {}
    gev_leg = legs_in.get("gev_gw") or {}
    undisclosed = bool(vrt_leg.get("unavailable"))
    light, state, raw_light, raw_state = _light(btb, prev, undisclosed)

    asof = d.get("asof")
    q_end = _quarter_end(d.get("vrt_quarter"))
    # Aged against the READING's own date, not against today — the house rule from the
    # Sources view. A quarter recorded in July must not look staler every time the
    # panel is opened; it was that old when it was read, and that is the fact.
    age_days = None
    if q_end and asof:
        try:
            age_days = (datetime.date.fromisoformat(asof) - q_end).days
        except ValueError:
            age_days = None

    # How far the orders line has to fall to reach the green threshold. The factor's
    # header makes this argument in prose ("orders must drop ~70%"); this is the same
    # claim as a live number, so it moves if the reading ever does.
    to_green_pct = round((YELLOW_AT / btb - 1) * 100, 1) if btb else None

    gev_stock = d.get("gev_available_gw") or {}
    cur, prv = d.get("gev_total_available_gw"), d.get("gev_prev_total_available_gw")
    stated = d.get("gev_stated_direction") or {}
    direction, dir_source, arrow = _gev_direction(cur, prv, stated)
    # Why the glyph is dark, in the deriver's own terms rather than as an absence.
    # 'awaiting a second stated stock' is a different state from 'management called it
    # flat', and a view that showed both as a blank would hide which one is true.
    if direction:
        gev_why = None
    elif cur is not None:
        gev_why = ("one stated stock so far — the delta needs two, and the glyph does "
                   "not fire off a single print")
    else:
        gev_why = "no stated unsold-GW figure on the record yet"

    return [{
        "date": asof,
        "light": light, "state": state,
        # What the NUMBER alone says, before the cap. Equal to `light` when nothing
        # was capped, so the view can simply compare them.
        "raw_light": raw_light, "raw_state": raw_state,
        "capped": light != raw_light,
        "btb": btb, "prev_btb": prev,
        "method": d.get("vrt_method"), "quarter": d.get("vrt_quarter"),
        "quarter_end": q_end.isoformat() if q_end else None,
        "age_days": age_days,
        "red_above": RED_ABOVE, "yellow_at": YELLOW_AT,
        "to_green_pct": to_green_pct,
        "undisclosed": undisclosed,
        "undisclosed_since": vrt_leg.get("period_end") if undisclosed else None,
        "undisclosed_reason": vrt_leg.get("reason") if undisclosed else None,
        "unavailable_reason": vrt_leg.get("unavailable_reason") if undisclosed else None,
        "attempted_at": vrt_leg.get("attempted_at"),
        "attempts": vrt_leg.get("attempts"),
        # What chasing a number that is not published has cost so far. It accumulates
        # across consecutive failures on purpose (run.py), so it answers "how much has
        # this cost me", not "what did the last try cost".
        "cost": vrt_leg.get("cost"),
        "vrt_source": vrt_leg.get("source"), "vrt_url": vrt_leg.get("url"),
        "gev": {
            "total": cur, "prev_total": prv,
            "direction": direction, "direction_source": dir_source,
            "arrow": arrow,
            "as_of": gev_stock.get("as_of") or stated.get("as_of"),
            "method": gev_stock.get("method"),
            "quote": gev_stock.get("source_quote") or stated.get("source_quote"),
            "url": gev_stock.get("url") or gev_leg.get("url"),
            "by_year": gev_stock.get("by_year") or [],
            "deadband": GEV_DEADBAND_GW,
            "why_dark": gev_why,
        },
        "provenance": d.get("provenance"),
    }]


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
