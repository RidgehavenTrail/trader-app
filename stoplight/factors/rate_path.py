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
    piv_w = (d2.resample("W-THU").mean() - ff.reindex(d2.index, method="ffill")
             .resample("W-THU").mean()).dropna()
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
        "extras": {"delta_6mo": floored_delta, "source": "FRED DGS2/FEDFUNDS"},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
