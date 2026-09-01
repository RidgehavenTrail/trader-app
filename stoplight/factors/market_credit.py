"""
Factor #7 — MARKET CREDIT (the spark). Rank 7.

Measure: ICE BofA US High-Yield Option-Adjusted Spread, in bps (up = stress).

STATES (inverted board: GREEN = pro-burst):
  RED    < ~400bps       : tight, firewall holding, complacency
  YELLOW ~400-500bps     : widening off lows / brief scare
  GREEN  > ~500bps AND STAYS WIDE (doesn't heal within weeks)

The "AND STAYS WIDE" clause is LOAD-BEARING. Implemented as: every one of the
last 10 trading prints > 500bps — a two-week hold, so a one-day spike reads
YELLOW (widening, unconfirmed), not green. ONE worked example is inside the data
we can see: Apr-2025 spiked to 461bps, into the yellow band, and correctly never
fired. The spec's "two historical false alarms healed" refers to a second one
outside the retrievable window — RECALLED, not checkable here (see the note below).

CAVEATS (from spec): RED = "no stress NOW", NOT "safe" — 2007 echo: record
tights right before the blowout. And the asymmetry: tights -> 600+ took WEEKS in
2008/2020; it gaps, it doesn't drift.

SOURCE: FRED BAMLH0A0HYM2 (daily, PERCENT — x100 for bps), ARCHIVED LOCALLY in
`store.series_archive` and read back from there. Reference (2026-07-18 spec):
272bps, deeply red, at/near record tights.

>> THE VENDOR WINDOW ROLLS, AND IT IS NOT 1996 (measured 2026-09-01). The spec says
>> "FRED series starts ~1996" and quotes long-run avg ~500, 2020 ~1100, 2008 ~2000.
>> The pull returns 785 prints starting 2023-09-01 — exactly 1095 days, a rolling
>> THREE-YEAR licence window. It is family-wide, not a dead series with a successor:
>> BAMLH0A0HYM2, BAMLC0A0CM, BAMLH0A3HYC, BAMLHE00EHYIOAS and BAMLEMCBPIOAS all start
>> on the same day, while DGS2 comes back from 1976 through the identical helper. The
>> spec half-saw this — it noted its own pull averaged 318bps, not ~500, and explained
>> it as the long-run figure "blending broader history".
>>
>> SO THE HISTORICAL ANCHORS ARE RECALLED, NOT PULLED: long-run ~500, stress 600-800,
>> 2020 ~1100, 2008 ~2000, and the 2007 echo. Treat them as documentation, never as
>> something this factor measured. In the retrievable window the max is 461bps, so the
>> 500 green line HAS NEVER BEEN CROSSED in data we can see and the sustain clause has
>> fired zero times.
>>
>> WHY THE ARCHIVE EXISTS: the window is ROLLING, so the record gets shorter the longer
>> you wait — 2020 has already fallen out. `_oas_bps()` files every pull into
>> `series_archive` and reads it back, so what we hold only grows. It cannot recover
>> 2008 or 2020; it stops the loss from here.
>>
>> THE SOURCE CHOICE ITSELF STANDS and should not be re-litigated: the OAS was picked
>> because it IS the credit risk premium, against a fallback (HYG/IEF) that is
>> rates-contaminated — IEF is 7-10yr duration, so the ratio moves on yields with zero
>> credit change. Depth was never the criterion; measurement quality was.
"""
import pandas as pd

from .. import store
from ..sources.fred import fred_series

GREEN_BPS = 500
YELLOW_BPS = 400
SUSTAIN_DAYS = 10


SERIES_ID = "BAMLH0A0HYM2"


def _oas_bps():
    """The spread in bps, from the ARCHIVE rather than the pull -> pandas Series.

    Every pass pulls the vendor's current window and files it into `series_archive`,
    then reads the archive back. Today the two are identical because the archive was
    seeded from the window; they diverge the moment the vendor drops its oldest day,
    and from then on the archive is the longer record. Nothing is deleted, so this only
    ever grows.

    A dead FRED costs the NEW day, not the series: on a failed pull the archive still
    answers, which is the second reason to read it rather than the response."""
    try:
        fresh = (fred_series(SERIES_ID) * 100).dropna().round()
        store.archive_series(SERIES_ID,
                             ((d.date().isoformat(), float(v)) for d, v in fresh.items()))
    except Exception as e:                    # noqa: BLE001 - archive still serves
        print(f"[STOPLIGHT] market_credit: FRED pull failed, using archive only: "
              f"{type(e).__name__}: {e}")
    rows = store.series_archive(SERIES_ID)
    if not rows:
        raise ValueError("market_credit: no archived spreads and the pull failed")
    return pd.Series([v for _, v in rows],
                     index=pd.to_datetime([d for d, _ in rows]))


def compute():
    oas_bps = _oas_bps()
    latest = round(float(oas_bps.iloc[-1]))
    asof = oas_bps.index[-1].date().isoformat()
    sustained_wide = bool((oas_bps.tail(SUSTAIN_DAYS) > GREEN_BPS).all())

    if latest > GREEN_BPS and sustained_wide:
        light, state = "green", "stress_firing"
    elif latest > YELLOW_BPS:
        light, state = "yellow", "widening"
    else:
        light, state = "red", "complacent"

    return {
        "id": "market_credit",
        "light": light,
        "value": latest,
        "metric": f"{latest}bps",
        "state": state,
        "asof": asof,
        "extras": {
            "sustained_wide": sustained_wide,
            "min_1y_bps": round(float(oas_bps.tail(252).min())),
            # What we hold versus what the vendor would still serve. Equal today; the
            # gap is the whole reason the archive exists, and it opens on its own.
            "archived_points": int(len(oas_bps)),
            "archive_from": oas_bps.index[0].date().isoformat(),
            "source": "FRED BAMLH0A0HYM2 (archived locally; vendor window rolls)",
        },
    }


# Levels quoted in the 2026-07-18 spec. NONE of them is reachable from the data this
# factor can pull -- the window is a rolling three years and the max inside it is
# 461bps -- so they are carried as RECALLED and the view says so on their face. They
# are useful for scale and worthless as measurement; the distinction has to survive
# onto the screen, which is why they are not simply drawn as lines.
RECALLED_LEVELS = [
    {"label": "long-run average", "bps": 500, "note": "blends history the pull cannot reach"},
    {"label": "stress", "bps": 700, "note": "600-800 band"},
    {"label": "2020 COVID", "bps": 1100, "note": "outside the window since ~Sep 2023"},
    {"label": "2008", "bps": 2000, "note": "outside the window"},
]


def ledger(days=10, top=10):
    """Where the spread sits in the only history this factor can see, and how the
    sustain clause is actually doing.

    Per-day rows are SNAPSHOT-DERIVED. The SERIES comes from `store.series_archive` --
    already on disk, so unlike rate_path's cloud or leverage's frame this costs no pull
    at all, and it is the longer record the moment the vendor trims its far end.

    The series rides only when days > 1, for the usual reason: the scheduler captures
    with days=1 and stores what it gets permanently.

    THE SUSTAIN STRIP IS THE POINT. Green needs every one of the last ten prints above
    500 -- a two-week hold -- and until now that whole clause was a single boolean in
    extras with nothing showing its state. Ten pips make it legible."""
    out = []
    for day in store.history_payloads("market_credit", days):
        ex = day.get("extras") or {}
        bps = day.get("value")
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "bps": bps,
            "sustained_wide": bool(ex.get("sustained_wide")),
            "min_1y_bps": ex.get("min_1y_bps"),
            "green_bps": GREEN_BPS, "yellow_bps": YELLOW_BPS,
            "sustain_days": SUSTAIN_DAYS,
            "to_green": (GREEN_BPS - bps) if bps is not None else None,
            "archived_points": ex.get("archived_points"),
            "archive_from": ex.get("archive_from"),
            "source": ex.get("source"),
        })

    if out and days > 1:
        rows = store.series_archive(SERIES_ID)
        if rows:
            out[0]["series"] = [[d, v] for d, v in rows]
            vals = [v for _, v in rows]
            hi = max(range(len(vals)), key=lambda i: vals[i])
            out[0]["window_high"] = {"bps": vals[hi], "date": rows[hi][0]}
            out[0]["window_low"] = {"bps": min(vals),
                                    "date": rows[vals.index(min(vals))][0]}
            # The last N prints, so the two-week hold can be read rather than trusted.
            out[0]["sustain_strip"] = [[d, v] for d, v in rows[-SUSTAIN_DAYS:]]
            # How often the green gate has fired in what we can see. It is zero, and
            # that is a fact about the WINDOW, not about credit -- stated either way.
            wide = [1 if v > GREEN_BPS else 0 for v in vals]
            fired = sum(1 for i in range(SUSTAIN_DAYS, len(wide) + 1)
                        if all(wide[i - SUSTAIN_DAYS:i]))
            out[0]["gate_fired_days"] = fired
        out[0]["recalled_levels"] = RECALLED_LEVELS
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
