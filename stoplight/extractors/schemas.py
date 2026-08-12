"""
Extractor output schemas + validators (Phase D).

Each validator is `fn(data: dict) -> (ok: bool, cleaned | reason)`. On ok it
returns ONLY the typed primitive fields (no asof/provenance — the extractor adds
those); on failure a short reason string that lands in the llm_calls ledger.
This is the deterministic guard that lets a cheap/free stage-1 model be safe:
malformed or out-of-range output fails here and triggers the Sonnet fallback,
so inference can never write a bad primitive into a light.
"""


def _num(d, key, lo, hi):
    v = d.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None, f"{key} not a number"
    if not (lo <= v <= hi):
        return None, f"{key}={v} out of [{lo},{hi}]"
    return v, None


def validate_regulatory_sweep(d):
    """Stage-1 detector: did anything new appear? Cheap yes/no + candidates."""
    if not isinstance(d.get("new_candidates"), bool):
        return False, "new_candidates not bool"
    cands = d.get("candidates", [])
    if not isinstance(cands, list):
        return False, "candidates not a list"
    return True, {"new_candidates": d["new_candidates"], "candidates": cands}


def validate_regulatory_classify(d):
    """Stage-2: the 3-test-classified state-wide cost-shift count + DCW blocks."""
    states, err = _num(d, "enacted_states", 0, 50)
    if err:
        return False, err
    blocked, err = _num(d, "dcw_blocked_projects", 0, 100000)
    if err:
        return False, err
    return True, {"enacted_states": int(states), "dcw_blocked_projects": int(blocked),
                  "states": d.get("states", [])}


def validate_infra_backlog(d):
    btb, err = _num(d, "vrt_book_to_bill", 0, 20)
    if err:
        return False, err
    trend = d.get("gev_available_gw_trend")
    if trend not in ("shrinking", "flat", "growing"):
        return False, f"gev trend invalid: {trend!r}"
    if not d.get("source_quote"):
        return False, "missing source_quote (provenance required)"
    return True, {"vrt_book_to_bill": float(btb), "gev_available_gw_trend": trend,
                  "source_quote": d["source_quote"], "url": d.get("url")}


def validate_book_to_bill(d):
    """VRT book-to-bill leg of the per-source infra extractor. The number is a
    DIMENSIONLESS FLOW ratio (orders/billings, ~0.8-3x) — NOT backlog in $B, so the
    field is named book_to_bill (not the silicon value_b, whose $-billions suffix
    would invite the very backlog-in-dollars confusion the prompt warns against).
    Range 0-5 brackets a plausible ratio and REJECTS a mis-pulled dollar backlog
    (VRT's is ~$7-8B, which would read as 7-8 and fail here). Requires the labeled
    quarter so a stale print is visible (the silicon nvda_dc 'old-quarter' lesson).

    METHOD guard (user's 2026-07-19 sourcing rule, enforced not hoped): the number
    must be management-STATED or computed orders÷revenue same-period/same-basis.
    Deriving it from the change in backlog (ΔBacklog = orders − shipments) is
    REJECTED — scan-sourced backlog figures are routinely non-comparable (RPO vs
    backlog vs different dates), which once implied a bogus ~0.25x right after 2.9x.
    The implausibility WAS the tell that the two backlog numbers weren't apples-to-
    apples, so we ban the path rather than trust a swing. `method` is required so the
    sourcing path lands on the record. (No swing-vs-prior reject on purpose: a real
    orders collapse IS the green signal this factor exists to catch — masking it
    would defeat the light. Method integrity is the right guard, not plausibility.)"""
    btb, err = _num(d, "book_to_bill", 0, 5)
    if err:
        return False, err
    method = d.get("method")
    if method not in ("stated", "orders_over_revenue"):
        return False, (f"method must be stated|orders_over_revenue, got {method!r} "
                       "(backlog-delta derivation is banned)")
    q = d.get("quarter")
    if not isinstance(q, str) or not q.strip():
        return False, "missing quarter label (stale-print guard)"
    return True, {"book_to_bill": btb, "method": method, "quarter": q.strip(),
                  "source": d.get("source"), "url": d.get("url")}


def make_book_to_bill_validator(period_end):
    """validate_book_to_bill PINNED to one fiscal period, plus an explicit
    'not published yet' path (user, 2026-07-29).

    WHY: asking for "the most recent quarter" is an open-ended request, so the model
    always finds SOMETHING and calls it done. On 2026-07-29 VRT reported Q2, coverage
    had not been indexed an hour later, and the extractor returned a Q1 figure of 1.4
    that no public source states — while claiming method='orders_over_revenue' even
    though management had declined to disclose orders. Two honest failures, then one
    that told the validator what it wanted to hear.

    So the period is now PINNED and unavailability is a FIRST-CLASS answer:
      - a ratio whose `period_end` matches the pinned quarter  -> accepted
      - {'unavailable': true, 'book_to_bill': null}            -> accepted as "not
        published yet"; the caller keeps the prior value and leaves the pull queued
      - anything else (wrong period, banned method)            -> rejected
    Note the mismatch check runs on period_end, a DATE, not on the free-text quarter
    label, so a company's fiscal naming cannot smuggle a wrong period through."""
    def _validate(d):
        if d.get("unavailable") is True and d.get("book_to_bill") is None:
            # WHY it is unavailable decides the human's next move, so it is a typed
            # field, not prose: 'not_published' means ask again later, 'not_disclosed'
            # means the source is out and the company simply did not give the number —
            # asking again will not help. Anything unrecognised degrades to the
            # wait-and-see reading rather than asserting the company withheld it.
            why = d.get("unavailable_reason")
            if why not in ("not_published", "not_disclosed"):
                why = "not_published"
            return True, {"book_to_bill": None, "unavailable": True,
                          "unavailable_reason": why,
                          "period_end": period_end,
                          "note": str(d.get("note") or "no figure given")[:200],
                          "source": d.get("source"), "url": d.get("url")}
        ok, res = validate_book_to_bill(d)
        if not ok:
            return False, res
        got = str(d.get("period_end") or "")[:10]
        if period_end and got != period_end:
            return False, (f"wrong period: asked for the quarter ended {period_end}, "
                           f"got period_end={got!r} / quarter={res.get('quarter')!r}. "
                           "Return unavailable:true rather than an earlier quarter.")
        res["period_end"] = got
        return True, res
    return _validate


_GEV_DIRECTIONS = ("shrinking", "flat", "growing")


def _validate_gev_stock(obj):
    """The numeric leg: GE Vernova's REMAINING AVAILABLE (unsold) capacity in GW by
    delivery year — a STOCK of unsold GW, nothing else. Returns (True, obj|None) or
    (False, reason). null is a VALID answer (nothing stated this period).

    HARD REJECTS (the three creativity leaks this shape plugs):
      1. method must equal the literal "stated_available_gw" — a derived/computed
         value can't masquerade as stated.
      2. source_quote must be a non-empty verbatim sentence carrying the GW number —
         no real quote => the number is NOT stated => null.
      3. by_year entries are {int year, numeric available_gw}; a year with no stated
         figure is omitted, never fabricated, and a lone `combined` is NOT split."""
    if obj is None:
        return True, None
    if not isinstance(obj, dict):
        return False, "gev_available_gw must be an object or null"
    if obj.get("method") != "stated_available_gw":
        return False, (f"available_gw.method must be literal 'stated_available_gw', "
                       f"got {obj.get('method')!r} (derived/computed is banned)")
    q = obj.get("source_quote")
    if not isinstance(q, str) or not q.strip():
        return False, "available_gw missing verbatim source_quote (unstated => null)"
    as_of = obj.get("as_of")
    if not isinstance(as_of, str) or not as_of.strip():
        return False, "available_gw missing as_of (fiscal quarter of the reading)"
    by_year_raw = obj.get("by_year") or []
    if not isinstance(by_year_raw, list):
        return False, "by_year must be a list"
    by_year = []
    for e in by_year_raw:
        if not isinstance(e, dict):
            return False, "by_year entry not an object"
        yr = e.get("year")
        if not isinstance(yr, int) or isinstance(yr, bool):
            return False, f"by_year.year not an int: {yr!r}"
        gw, err = _num(e, "available_gw", 0, 1000)
        if err:
            return False, f"by_year {yr}: {err}"
        by_year.append({"year": yr, "available_gw": gw})
    combined = obj.get("combined")
    if combined is not None:
        combined, err = _num(obj, "combined", 0, 10000)
        if err:
            return False, err
    if combined is None and not by_year:
        return False, "no GW figure: need combined or >=1 by_year entry (else null)"
    return True, {"as_of": as_of.strip(), "by_year": by_year, "combined": combined,
                  "method": "stated_available_gw", "source_quote": q.strip(),
                  "url": obj.get("url")}


def _validate_gev_direction(obj):
    """The stated-direction leg: MANAGEMENT'S OWN verbatim characterization of the
    trend in available/unsold capacity (shrinking/flat/growing), when they EXPLICITLY
    state it. A single-reading seed for the glyph, used by the deriver only when the
    numeric delta can't be computed. Returns (True, obj|None) or (False, reason).
    null is VALID (management did not characterize it — the model must NOT infer a
    direction from a sold-out date or booking color; if not stated, leave it alone).
    Guarded identically: a literal method + a verbatim quote."""
    if obj is None:
        return True, None
    if not isinstance(obj, dict):
        return False, "gev_stated_direction must be an object or null"
    if obj.get("method") != "stated_direction":
        return False, (f"stated_direction.method must be literal 'stated_direction', "
                       f"got {obj.get('method')!r} (inference is banned)")
    dr = obj.get("direction")
    if dr not in _GEV_DIRECTIONS:
        return False, f"stated_direction.direction invalid: {dr!r}"
    q = obj.get("source_quote")
    if not isinstance(q, str) or not q.strip():
        return False, "stated_direction missing verbatim source_quote (management's words)"
    return True, {"direction": dr, "method": "stated_direction",
                  "source_quote": q.strip(), "as_of": obj.get("as_of"),
                  "url": obj.get("url")}


def validate_gev(d):
    """GEV leg (HARDENED per user spec 2026-07-19). TWO stated primitives, both
    optional/null — the model reports whichever the source actually states, and CODE
    resolves the direction downstream (numeric delta primary; management-stated
    direction as a single-reading fallback; else no glyph):
      - gev_available_gw:     verbatim UNSOLD-GW STOCK (numbers) — see _validate_gev_stock
      - gev_stated_direction: management's own verbatim trend call — see _validate_gev_direction
    Both-null is a legitimate 'nothing stated' outcome, not a schema failure. The
    FORBIDDEN substitutes (a sold-out DATE, TOTAL backlog GW, orders/revenue/BtB, or
    any computed number) can supply neither a stated GW quote nor a management trend
    quote, so they can't sneak in as either leg."""
    stock_ok, stock = _validate_gev_stock(d.get("gev_available_gw"))
    if stock_ok is False:
        return False, stock
    dir_ok, direction = _validate_gev_direction(d.get("gev_stated_direction"))
    if dir_ok is False:
        return False, direction
    return True, {"gev_available_gw": stock, "gev_stated_direction": direction}


def gev_total_available_gw(stock):
    """Total available (unsold) GW from a validated stock: `combined` if the source
    gave a single spanning figure, else the sum of the by_year entries; None if no
    stock. This is the quantity the deriver compares period-over-period."""
    if not stock:
        return None
    if stock.get("combined") is not None:
        return stock["combined"]
    ys = stock.get("by_year") or []
    return round(sum(e["available_gw"] for e in ys), 1) if ys else None


def validate_reg_sweep_multi(d):
    """Multi-path sweep: TWO delta lists — states that NEWLY ENACTED a cost-shift law
    (beyond the tracked roster) and states that REPEALED one. Either non-empty escalates
    to the billed classify. Code maintains the running roster across runs, so the sweep
    only has to surface what CHANGED, not recreate the whole national list."""
    adds = d.get("new_candidates", [])
    reps = d.get("repealed_candidates", [])
    if not isinstance(adds, list) or not isinstance(reps, list):
        return False, "new_candidates / repealed_candidates must be lists"
    return True, {"new_candidates": adds, "repealed_candidates": reps}


def _clean_proven(lst, required):
    """Keep only entries carrying every `required` proof field (non-empty strings);
    silently DROP the rest. Per-entry filter, not all-or-nothing: Python accumulates
    the roster across runs, so we apply whatever valid deltas we got rather than
    discarding a good addition because the model bundled one sloppy entry."""
    out = []
    for e in lst if isinstance(lst, list) else []:
        if not isinstance(e, dict):
            continue
        vals = {k: e.get(k) for k in required}
        if all(isinstance(v, str) and v.strip() for v in vals.values()):
            rec = {k: vals[k].strip() for k in required}
            rec["url"] = e.get("url")
            out.append(rec)
    return out


def validate_reg_statute(d):
    """Statute leg of the per-source regulatory extractor (HARDENED 2026-07-19, repeal
    path added). The model returns PROVEN DELTAS to a Python-maintained roster — NOT a
    count and NOT the whole list:
      - enacted_states_list:  additions, each proven with statute citation + enacted_date
      - repealed_states_list: removals, each proven with repeal citation + repeal_date
    Python applies the deltas (union in additions, drop repeals) to its persisted roster
    and derives the count = len(roster), so the light can move UP or DOWN and never
    drifts from the evidence, and no single search has to recreate the list. Proof is
    mandatory (the gate-on-statute discipline; a proposed/pending bill has no enacted
    date and is dropped) — the regulatory analog of VRT's method literal. Per-entry
    filter: unproven entries are dropped, not fatal. Both lists may be empty."""
    if not isinstance(d.get("enacted_states_list"), list):
        return False, "enacted_states_list must be a list"
    if not isinstance(d.get("repealed_states_list", []), list):
        return False, "repealed_states_list must be a list"
    return True, {
        "enacted_states_list": _clean_proven(
            d.get("enacted_states_list"), ("name", "statute", "enacted_date")),
        "repealed_states_list": _clean_proven(
            d.get("repealed_states_list", []), ("name", "repeal_citation", "repeal_date")),
    }


def validate_dcw_blocked(d):
    """DCW leg of the per-source regulatory extractor (HARDENED 2026-07-19). The Data
    Center Watch definitively-BLOCKED project COUNT (a directional-arrow input, not the
    light). null is a VALID answer — blocked-alone not separable from the combined
    'blocked OR delayed' figure means don't guess. A real count MUST carry a verbatim
    source_quote containing the number, so the $ figure ('$64B') or the combined
    blocked-and-delayed count can't slip in as the project count."""
    v = d.get("dcw_blocked_projects")
    if v is None:
        return True, {"dcw_blocked_projects": None}
    blocked, err = _num(d, "dcw_blocked_projects", 0, 100000)
    if err:
        return False, err
    q = d.get("source_quote")
    if not isinstance(q, str) or not q.strip():
        return False, "missing verbatim source_quote (the blocked COUNT must be quoted)"
    return True, {"dcw_blocked_projects": int(blocked), "source_quote": q.strip(),
                  "url": d.get("url")}


def validate_silicon_payback(d):
    out = {}
    for k, lo, hi in [("openai_rev_b", 0, 500), ("anthropic_rev_b", 0, 500),
                      ("copilot_rev_b", 0, 200), ("gemini_rev_b", 0, 200),
                      ("nvda_dc_qtr_b", 0, 500), ("nvda_accel_share", 0.3, 1.0)]:
        v, err = _num(d, k, lo, hi)
        if err:
            return False, err
        out[k] = v
    # REQUIRED: the labeled quarter for nvda_dc_qtr_b, so a stale-quarter pull is
    # visible on the record (the 62.3-was-an-old-quarter failure). Captured, not
    # content-validated (fiscal-label parsing is brittle) — surfaced for eyeball.
    q = d.get("nvda_dc_quarter")
    if not isinstance(q, str) or not q.strip():
        return False, "missing nvda_dc_quarter (must label the quarter used)"
    out["nvda_dc_quarter"] = q.strip()
    out["services_rev_b"] = round(out["openai_rev_b"] + out["anthropic_rev_b"]
                                  + out["copilot_rev_b"] + out["gemini_rev_b"], 1)
    return True, out


def make_value_validator(lo, hi):
    """Factory: validate a single-source focused extraction returning value_b
    (+ optional provenance fields, which are kept). Used by the per-source
    multi-search silicon legs (spec STOPLIGHT_SCHEDULING §5)."""
    def _v(d):
        v, err = _num(d, "value_b", lo, hi)
        if err:
            return False, err
        return True, d           # keep the whole dict (source/url/build-up)
    return _v


# SEATS-x-PRICE-PLUS-ADDON build-up — the shared shape for revenue legs that are
# NOT disclosed and must be estimated: value_b = seats(M) x price($/mo) x 12/1000
# + a flat add-on ($B). PYTHON owns the arithmetic; the model pulls primitives
# ONLY (newsletter model->primitives->Python-derives doctrine, tightening §7), so
# the estimate can't drift on the model re-doing the math or dropping a term.
# Pinned fallbacks so a missing/implausible pulled value defaults sensibly instead
# of zeroing the estimate. Used by BOTH Gemini (enterprise seats + consumer) and
# MSFT Copilot (M365 seats + GitHub) — same methodology, one helper.
def _num_or(d, key, lo, hi, default):
    v = d.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
        return v, False           # pulled value used
    return default, True          # fell back to pinned default


def make_buildup_validator(seats_key, price_key, addon_key,
                           price_fallback, addon_fallback,
                           seats_hi=1000, price_lo=5, price_hi=100, addon_hi=50):
    """Factory: a validator for a seats x price x 12 + addon revenue estimate.
    seats is mandatory-pulled (the number that actually moves); price and addon
    fall back to pinned constants if missing/implausible."""
    def _v(d):
        seats, err = _num(d, seats_key, 0, seats_hi)
        if err:
            return False, err
        price, price_pinned = _num_or(d, price_key, price_lo, price_hi, price_fallback)
        addon, addon_pinned = _num_or(d, addon_key, 0, addon_hi, addon_fallback)
        seat_rev_b = round(seats * price * 12 / 1000, 2)   # seats(M) x $/mo x 12 = $M -> /1000 = $B
        value_b = round(seat_rev_b + addon, 1)
        # LOW-CONFIDENCE signal (drives the sample-and-median retry): the seat
        # count did NOT come from an official disclosure, or a term fell back to
        # a pinned default. seat_disclosed is the model's own report of whether
        # it found an authoritative seat figure (a binary it can answer reliably).
        disclosed = bool(d.get("seat_disclosed"))
        low_conf = (not disclosed) or price_pinned or addon_pinned
        return True, {"value_b": value_b, seats_key: seats, price_key: price,
                      addon_key: addon, "seat_rev_b": seat_rev_b,
                      "price_pinned": price_pinned, "addon_pinned": addon_pinned,
                      "seat_disclosed": disclosed, "low_confidence": low_conf,
                      "seat_source": d.get("seat_source"), "url": d.get("url")}
    return _v


# Gemini: enterprise seats x blended price + consumer (Google One AI Premium).
validate_gemini = make_buildup_validator(
    "enterprise_seats_m", "avg_price_month", "consumer_b",
    price_fallback=30.0, addon_fallback=1.2)   # $30/seat/mo, $1.2B consumer

# MSFT Copilot: M365 Copilot seats x price + GitHub Copilot (flat).
validate_copilot = make_buildup_validator(
    "m365_seats_m", "m365_price_month", "github_b",
    price_fallback=30.0, addon_fallback=1.75)  # $30/seat/mo, ~$1.75B GitHub


def validate_nvda_dc(d):
    """NVIDIA DC-revenue source (HARD, from earnings): latest-quarter DC revenue
    + labeled quarter (so a stale quarter is visible)."""
    dc, err = _num(d, "dc_qtr_b", 0, 500)
    if err:
        return False, err
    q = d.get("quarter")
    if not isinstance(q, str) or not q.strip():
        return False, "missing quarter label"
    return True, {"dc_qtr_b": dc, "quarter": q.strip(), "url": d.get("url")}


def validate_nvda_share(d):
    """NVIDIA accelerator-share source (SOFT, market research). MUST be the
    all-accelerator share incl. custom silicon (~0.70-0.75), NOT merchant-GPU
    (~0.90). Keeps the definition/source for audit."""
    sh, err = _num(d, "accel_share", 0.3, 1.0)
    if err:
        return False, err
    return True, {"accel_share": sh, "definition": d.get("definition"),
                  "source": d.get("source"), "url": d.get("url")}


def validate_capex_guidance(d):
    """One hyperscaler's FORWARD capex guidance only (2026-07-19: the prior-year
    figure is now a PINNED historical constant — see run.PINNED_CAPEX_PRIORS —
    because MSFT/META report capex on multiple bases and the LLM couldn't pick one
    consistently run-to-run, swinging the denominator. The prior is a fact, not a
    forecast; only the forward guidance stays LLM-pulled/soft). value_b = the
    guided coming-year capex; low_confidence when not explicitly disclosed."""
    g, err = _num(d, "capex_guidance_b", 0, 1000)
    if err:
        return False, err
    disclosed = bool(d.get("guidance_disclosed"))
    return True, {"value_b": g, "basis": d.get("basis"),
                  "guidance_disclosed": disclosed, "low_confidence": not disclosed,
                  "source": d.get("source"), "url": d.get("url")}


def validate_capex_spigot(d):
    yoy, err = _num(d, "guidance_yoy_pct", -100, 500)
    if err:
        return False, err
    return True, {"guidance_yoy_pct": round(float(yoy), 1),
                  "per_name": d.get("per_name", {})}
