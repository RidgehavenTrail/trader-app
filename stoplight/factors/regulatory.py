"""
Factor #10 — REGULATORY (earnings-durability DRAG, not a timing canary). Rank 10.

PRIMARY: count of states with a STATE-LEVEL ACTION IN FORCE against the free ride —
data centers made to fund their own power infrastructure, pay a dedicated large-load
rate class, meet interconnection standards, or wait behind a permitting pause.

  RED    < 10 states  — below 10, hyperscalers relocate to a free-ride state
  YELLOW 10-20        — relocation gets hard ("start of a movement")
  GREEN  20+          — essentially federal, nowhere to run = free ride over

Direction: green = constraint rising = pro-burst; red = free ride on.

WHAT COUNTS (REBUILT 2026-08-29, user's definition). Four tests, all required:
  (1) IN FORCE — signed, issued or adopted, with an effective date. A bill that PASSED
      but is unsigned does not count (NY's Responsible Data Center Development Act,
      passed 2026-06-04, unsigned). Nor does a draft rule or an open docket (NY PSC's
      Energize NY proceeding).
  (2) ANY BRANCH — statute, governor's executive order, or a utility-commission rule of
      general application, counted alike. **This is what changed.** The old rule read
      "Only ENACTED statutes count, not proposed bills", which welded a correct test
      (in force, not proposed) to a wrong one (statutes only) — and the wrong half made
      the factor blind to Hochul's EO 62 and to commission rulemaking.
  (3) STATE-WIDE — binds every utility / all large loads in the state, PROVEN from the
      instrument's own words: the extractor must return a verbatim `scope_quote` and a
      `binds` of "all_utilities". Three shapes fail this and every one of them reads as
      state action in coverage of it:
        * aimed at ONE NAMED UTILITY, however large — AEP Ohio (PUCO, Jul 2025),
          Dominion's GS-5 class (VA SCC, Nov 2025), and Virginia's own SB 253/HB 1393,
          which directs Dominion alone to PROPOSE a >=25MW allocation. Dominion is
          roughly two thirds of Virginia including all of Data Center Alley, so this
          test has a real cost, accepted with eyes open.
        * VOLUNTARY — a model, framework or guidance utilities may adopt. Pennsylvania's
          PUC framework (final order 2026-05-13) is explicitly non-binding.
        * a duty to PROPOSE, study or report rather than the requirement itself.
      All are recorded under `excluded` with their reason, not forgotten.
  (4) ABOUT LARGE-LOAD POWER — cost allocation, rate class, interconnection, or
      siting/permitting. A tax measure is out (IN HB 1210, 1% of sales-tax savings
      shared with localities). A study mandate is out because nothing is required of
      anyone (CA SB 57 orders a CPUC report due 2027 and shifts no costs).

A TEMPORARY action counts while it is in force (user). The clock is applied HERE, in
compute(), not by the extractor: the engine recomputes daily and free, so a moratorium
retires itself the day it expires instead of waiting for the next billed run.

REFERENCE DISCONTINUITY (2026-08-29). The roster before this date was a PINNED BASELINE
of three states — California, Ohio, Utah — carrying no statute, no date and no citation
for any of them, seeded from a MultiState read and never held to the proof gate that
every later addition faced. Audited against the four tests it was right about ONE:
Utah. Ohio was a single-utility tariff; California was a study mandate. Meanwhile Texas
SB 6 (Jun 2025), Minnesota HF 16 (Jun 2025) and Oregon's POWER Act (Aug 2025) were all
in force BEFORE the baseline and were missing — which the old sweep could never have
caught, because it was asked only for enactments "beyond those already tracked". Nine
billed sweeps returned "nothing new" and each may have been a correct answer to the
wrong question. Same bands either way: 3 was red and 7 is red, so the correction moves
the number without moving the light.

+/- ENHANCER — Data Center Watch blocked-project count as a DIRECTIONAL ARROW (more
blocks = down/toward burst, fewer = up). Quarantined by the light-dominates rule — the
arrow never changes the color. ⚠ Its one firing to date (2026-08-18) came off a CHANGED
QUESTION, not a changed world: the leg returned 20 quoted as "Projects outright
cancelled after pushback, Q1 2026", replacing a SEEDED 75 that had counted blocked
projects per quarter. The quote is now stored beside the number so that is visible.

PROVENANCE OF THE CURRENT ROSTER (2026-08-29). The five states in it were assembled
by hand from public sources in one session, not by the extractor, and they carry no
`scope_quote` — the proof requirement above governs what the SWEEP may add, and the
seed predates it. Two entries assembled the same way failed verification within hours,
both because coverage generalised what the instrument did. Treat the five as good but
unaudited until a sweep re-verifies them; the sweep enumerates the full list every run
precisely so it can.

INPUTS (extractors/ — billed refresh): actions[], dcw_blocked_projects,
dcw_prev_blocked, dcw_source_quote.
"""
import datetime

from ..extractors import read_input

GREEN_AT = 20
YELLOW_AT = 10


def _in_force(action, today):
    """Is this action still in force today? Only an `expires` date in the PAST retires
    one — a null expiry means in force until something says otherwise, which is the
    normal case (NY's EO 62 runs until the DPS finishes a study, with no date in the
    order itself). A malformed date is treated as no expiry: never drop a proven action
    because its date field could not be parsed."""
    exp = action.get("expires")
    if not exp:
        return True
    try:
        return datetime.date.fromisoformat(str(exp)[:10]) >= today
    except ValueError:
        return True


def _band(n):
    """states -> (light, state). One definition, used by compute() and by ledger(), so
    nothing the panel shows can disagree with the light about where an edge sits."""
    if n >= GREEN_AT:
        return "green", "nowhere_to_run"
    if n >= YELLOW_AT:
        return "yellow", "movement_starting"
    return "red", "free_ride_on"



def _arrow(d):
    """The DCW opposition arrow, and the reason when there isn't one.

    More projects stopped = more local opposition = `down`, toward burst. The arrow
    never changes the colour (light-dominates), so its whole job is to be RIGHT or to
    be absent.

    It compares two observations only when they are actually comparable, because the
    one arrow this factor has ever fired was not: on 2026-08-18 a "Q1 2026 outright
    cancellations" 20 was set against a SEEDED "blocked per quarter" 75, and the
    direction it produced was an artefact of the question changing. Three refusals,
    all mechanical:
      * different BASIS - blocked-only against blocked-or-delayed counts different
        things, and the source publishes both;
      * the same PERIOD - a restatement of one period is one observation, not two;
      * one CUMULATIVE and one not - a running total and a quarter are not a series.
    A pre-2026-08-29 record carries no basis at all, which is itself a refusal: we do
    not know what those numbers counted, so they cannot support a direction.

    Returns (arrow, why, current_observation, previous_observation)."""
    cur, was = d.get("dcw"), d.get("dcw_prev")
    if not cur and d.get("dcw_blocked_projects") is not None:
        # Pre-rebuild shape: a bare number with no basis and no period.
        cur = {"value": d.get("dcw_blocked_projects"), "basis": None, "period": None,
               "quote": d.get("dcw_source_quote"), "url": d.get("dcw_url")}
    if not cur or cur.get("value") is None:
        return None, "no observation yet", cur, was
    if not was or was.get("value") is None:
        return None, "only one observation so far", cur, was
    if not cur.get("basis") or cur["basis"] != was.get("basis"):
        return None, "not comparable: different basis", cur, was
    if cur.get("period") and cur["period"] == was.get("period"):
        return None, "same period restated", cur, was
    cum = lambda o: "cumulative" in (o.get("period") or "").lower()
    if cum(cur) != cum(was):
        return None, "not comparable: cumulative against period figure", cur, was
    if cur["value"] == was["value"]:
        return None, "unchanged", cur, was
    return ("down" if cur["value"] > was["value"] else "up"), None, cur, was

def compute():
    d = read_input("regulatory")
    today = datetime.date.today()

    # `actions` is the rebuilt roster; `states` was the pre-2026-08-29 shape. Falling
    # back rather than crashing, but NOT pretending they are the same thing — a record
    # on the old shape reports its basis as such.
    roster = d.get("actions")
    basis = d.get("basis") or "any_branch_in_force_statewide"
    if roster is None:
        roster, basis = d.get("states") or [], "enacted_statutes_only"

    live = [a for a in roster if _in_force(a, today)]
    retired = [a for a in roster if not _in_force(a, today)]
    # One state can hold several actions at once (Texas has SB 6 and the governor's
    # audit order). The LIGHT counts states, not instruments — "nowhere left to run" is
    # about how much of the map is covered — while the panel can still show both.
    states = sorted({(a.get("state") or a.get("name") or "").strip()
                     for a in live} - {""})
    n = len(states)

    light, state = _band(n)

    arrow, arrow_why, cur, was = _arrow(d)

    by_branch = {}
    for a in live:
        by_branch[a.get("instrument_type", "unknown")] = \
            by_branch.get(a.get("instrument_type", "unknown"), 0) + 1

    return {
        "id": "regulatory",
        "light": light,
        "value": n,
        "metric": f"{n} states",
        "state": state,
        "asof": d["asof"],
        "extras": {
            "arrow": arrow,
            "basis": basis,
            "states": states,
            "n_actions": len(live),
            "by_branch": by_branch,
            "retired": [a.get("citation") for a in retired],
            "arrow_why": arrow_why,
            "dcw": cur,
            "dcw_prev": was,
            "provenance": d.get("provenance"),
        },
    }



def ledger(days=10, top=10):
    """The roster itself: every action the light counts, and every one it looked at and
    rejected.

    ONE CURRENT RECORD, like silicon_payback and unlike premium_share. The roster is a
    state-of-the-world object, not a per-day series -- there is no honest way to
    reconstruct what it held last Tuesday, because the extractor store keeps only the
    latest. So this returns today's roster and the history accumulates print by print
    as the scheduler records it. `days` and `top` are accepted for signature parity and
    ignored: there is one roster, and trimming it would hide the evidence this view
    exists to show.

    It re-derives from the SAME input record compute() reads, through the same
    `_in_force` clock and the same `_band`, so the pane cannot disagree with the light.

    The EXCLUDED list is evidence too, and arguably the more useful half: two of its
    entries (AEP Ohio, California SB 57) were counted as states until 2026-08-29, and
    one (Dominion GS-5) is the most economically consequential measure in the country.
    A view that showed only what qualified would make those look like oversights."""
    d = read_input("regulatory")
    today = datetime.date.today()
    roster = d.get("actions") or []

    actions = []
    for a in roster:
        live = _in_force(a, today)
        actions.append({
            "state": a.get("state"),
            "instrument_type": a.get("instrument_type") or "unknown",
            "citation": a.get("citation"),
            "effective_date": a.get("effective_date"),
            "threshold_mw": a.get("threshold_mw"),
            "expires": a.get("expires"),
            "temporary": bool((a.get("note") or "").startswith("TEMPORARY")),
            "url": a.get("url"),
            "note": a.get("note"),
            "in_force": live,
        })
    # Sorted by the date the action took effect: the roster reads as the movement
    # arriving, which is what the factor is watching for.
    actions.sort(key=lambda a: (a["effective_date"] or "", a["state"] or ""))

    live_states = sorted({a["state"] for a in actions if a["in_force"] and a["state"]})
    by_branch = {}
    for a in actions:
        if a["in_force"]:
            by_branch[a["instrument_type"]] = by_branch.get(a["instrument_type"], 0) + 1

    n = len(live_states)
    light, _ = _band(n)
    return [{
        "date": d.get("asof"),
        "light": light,
        "value": n,
        "metric": f"{n} states",
        "n_actions": sum(1 for a in actions if a["in_force"]),
        "by_branch": by_branch,
        "states": live_states,
        "actions": actions,
        "excluded": d.get("excluded") or [],
        "basis": d.get("basis") or "enacted_statutes_only",
        "dcw_blocked": d.get("dcw_blocked_projects"),
        "dcw_prev": d.get("dcw_prev_blocked"),
        "dcw_quote": d.get("dcw_source_quote"),
        "dcw_url": d.get("dcw_url"),
        "green_at": GREEN_AT,
        "yellow_at": YELLOW_AT,
    }]


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
