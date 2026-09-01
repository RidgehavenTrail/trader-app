"""
Factor #3 — RATE PATH (formerly "Fed / real rates"). Rank 3.

Predictive Fed-expectation factor. Reads whether the MARKET is repricing toward
tightening (the burst CAUSE) or pricing cuts/inversion (the burst REACTION),
via the pivot = 2yr yield - fed funds. No inflation / real-rate leg (removed).

STATES (inverted board convention: GREEN = pro-burst):
  GREEN  tightening : floored-6mo-delta of pivot >= +0.50
  GREEN  inverted   : raw pivot < 0  (market pricing cuts)
  RED    quiet      : otherwise (status quo / higher-for-longer)

MEASURE:
  pivot     = mean(DGS2, last 5 trading days) - FEDFUNDS(latest)
  floored_d = pivot_now - max(pivot_26wk_ago, 0)   # negatives floored to 0 so a
              fading inversion is NOT read as tightening
STRENGTH: the delta amplitude (watch, not a threshold): +0.5 on, +1.0+ = 2022-grade.
CADENCE: weekly (Thu FOMC capture) — registry-owned; new-tag fires off asof.
SOURCE: FRED (DGS2 daily, FEDFUNDS monthly).
Post-'94 reference: mean ~+0.31, range ~ -1.5 (2024) .. +2.2 (2022).

Adapted from the validated root rate_path.py (session 31) to the factor contract.
"""
from .. import store
from ..sources.fred import fred_series

DELTA_TRIGGER = 0.50
LOOKBACK_WEEKS = 26

_STATE_ABBREV = {"tightening": "tght", "inverted": "invt", "quiet": "quiet"}


def compute():
    d2 = fred_series("DGS2")        # daily 2yr
    ff = fred_series("FEDFUNDS")    # monthly funds rate
    dgs2_5d = d2.tail(5).mean()
    funds = ff.iloc[-1]
    pivot_now = round(dgs2_5d - funds, 2)

    # pivot series (daily 2yr resampled weekly-Thu) minus funds, for the 26wk-ago point
    piv_w = _weekly_pivot(d2, ff)
    pivot_prior = piv_w.iloc[-1 - LOOKBACK_WEEKS] if len(piv_w) > LOOKBACK_WEEKS else 0.0
    floored_delta = round(pivot_now - max(pivot_prior, 0.0), 2)

    if floored_delta >= DELTA_TRIGGER:
        light, state = "green", "tightening"
    elif pivot_now < 0:
        light, state = "green", "inverted"
    else:
        light, state = "red", "quiet"

    sign = "+" if pivot_now >= 0 else ""
    return {
        "id": "rate_path",
        "light": light,
        "value": pivot_now,
        "metric": f"{sign}{pivot_now:.2f} {_STATE_ABBREV[state]}",
        "state": state,
        "asof": d2.index[-1].date().isoformat(),
        "extras": {
            "delta_6mo": floored_delta,
            # The prior pivot the six-month change is measured against. Recorded
            # 2026-08-31: without it nothing could say how the delta was arrived at,
            # and the factor's SECOND route to green -- a raw pivot below zero -- had
            # no distance on the record at all. The two visible numbers happened to be
            # equal, which hid that they are different quantities.
            "pivot_prior": round(float(pivot_prior), 2),
            "source": "FRED DGS2/FEDFUNDS",
        },
    }



def _weekly_pivot(d2, ff):
    """The pivot as a weekly (Thursday) series — ONE implementation, used both for the
    26-week lookback the light needs and for the history the view draws. A second copy
    would be free to disagree with the number that decides the light."""
    return (d2.resample("W-THU").mean()
            - ff.reindex(d2.index, method="ffill").resample("W-THU").mean()).dropna()


def ledger(days=10, top=10):
    """Where this reading sits against BOTH routes to green, and where the rule has
    spent its history.

    The per-day rows are SNAPSHOT-DERIVED — pivot, its floored six-month change and the
    prior pivot all ride in the day's own extras, so the reading cannot disagree with
    the light. The history CLOUD is re-derived from FRED, which is free and which the
    endpoint caches for the ET day, so the panel pulls at most once however often it is
    opened.

    WHY THE CLOUD ONLY RIDES WHEN days > 1. The scheduler captures with days=1 and
    whatever it gets is written to the ledgers table for good. The cloud is ~390 static
    points that do not change from one day to the next, so storing it daily would put
    the same history on disk several hundred times a year. The panel asks for more than
    one day; the scheduler asks for exactly one. So the capture stays small and the view
    still gets its context.

    THE 'TODAY' POINT IS THE FACTOR'S OWN, not the cloud's last dot, and the two are
    not identical: the light reads a FIVE-DAY mean of the daily 2-year against the
    latest funds print, while the cloud is a weekly Thursday resample. Plotting the
    weekly point as 'today' would put the marker somewhere the light never was."""
    out = []
    for day in store.history_payloads("rate_path", days):
        ex = day.get("extras") or {}
        pivot = day.get("value")
        delta = ex.get("delta_6mo")
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "pivot": pivot, "delta_6mo": delta,
            "pivot_prior": ex.get("pivot_prior"),
            "trigger": DELTA_TRIGGER, "lookback_weeks": LOOKBACK_WEEKS,
            # Distance to each route, so the dormant one stops being invisible. The
            # inverted route is simply how far the pivot is from zero; the tightening
            # route is how far the six-month change is from the trigger.
            "to_inverted": round(pivot, 2) if pivot is not None else None,
            "to_tightening": (round(DELTA_TRIGGER - delta, 2)
                              if delta is not None else None),
            "source": ex.get("source"),
        })

    if out and days > 1:
        try:
            d2 = fred_series("DGS2")
            ff = fred_series("FEDFUNDS")
            piv = _weekly_pivot(d2, ff)
            piv = piv[piv.index >= "1994-01-01"]
            vals = list(piv.items())
            seen, cloud = set(), []
            for i, (ts, v) in enumerate(vals):
                if i < LOOKBACK_WEEKS:
                    continue
                # One point a month: a background cloud needs shape, not resolution,
                # and monthly turns ~1700 weeks into ~390 points.
                key = (ts.year, ts.month)
                if key in seen:
                    continue
                seen.add(key)
                prior = vals[i - LOOKBACK_WEEKS][1]
                cloud.append([round(float(v), 2),
                              round(float(v) - max(float(prior), 0.0), 2)])
            out[0]["cloud"] = cloud
            out[0]["cloud_from"] = vals[LOOKBACK_WEEKS][0].date().isoformat()
            out[0]["cloud_to"] = vals[-1][0].date().isoformat()
        except Exception as e:            # a dead FRED costs the CONTEXT, not the reading
            out[0]["cloud_error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
