"""
Factor #2 — CONCENTRATION (magnitude of what's inflated). Rank 2.

Measure: semiconductor weight in the S&P 500 = sum of the GICS-semi members'
index weights, read as the RUNNING PEAK (not the current print — the board is
a pre-burst instrument; the peak is the magnitude the unwind starts from).

  GREEN  peak > 20%
  YELLOW peak 15-20%
  RED    peak < 15%   (structurally unreachable BY DESIGN — pre-burst gauge)

BASIS (decided 2026-07-19 build session — see sources/ssga.py): FLOAT-ADJUSTED
index weights from the SSGA SPY daily holdings file (the spec's "correct
concentration convention"; iShares IVV is bot-gated). The spec session's
16.01% / 18.03%-peak figures were RAW-cap basis and read ~1.09x lower — kept
in extras as reference, NEVER mixed into this factor's running max. Snapshot
`value` = the CURRENT daily pct; the peak is derived as max over the log.

BACKFILL (2026-07-19, user-directed): the snapshot log carries RECONSTRUCTED
float-basis rows for 2026-04-15..07-17 (payload {"reconstructed": true}) —
each name's 2026-07-19 float weight scaled by its price ratio back through
the window (float shares ~constant over 3 months). Validated two ways: the
reconstruction's latest value (17.41%) matched the live file's direct read
(17.40%), and the peak lands on the SAME date as the raw-basis peak.
FLOAT-BASIS PEAK: 19.83% on 2026-06-22 — a whisker under the 20% green line.

MEMBERSHIP — GICS filter, self-maintaining, NO rotting hand list:
- Cache (inputs/semi_membership.json) maps ticker -> bool. Seeded with the
  2026-07-18 spec scrub's 19 names (14 semis + 5 equipment, incl FSLR and Q).
- A holdings ticker NOT in the cache (a rebalance newcomer) is classified via
  yfinance info.industry containing "semiconductor" and appended to the cache.
  CAVEAT: Yahoo's taxonomy is not GICS (Yahoo files FSLR under Solar; GICS
  says Semiconductors) — newcomer classifications land in extras for audit.
- Departures need nothing: absent from the holdings file = not summed.
"""
import json
import os

from .. import store
from ..sources.ssga import spy_holdings

GREEN_ABOVE = 20.0
YELLOW_ABOVE = 15.0

# 2026-07-18 spec-scrub resolution (the SEED of the membership cache, not a
# maintained hand list — newcomers are auto-classified, leavers auto-drop).
SEED_SEMIS = ["NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC", "MU", "ADI", "NXPI",
              "MCHP", "MPWR", "ON", "MRVL", "FSLR",            # semiconductors
              "AMAT", "KLAC", "LRCX", "TER", "Q"]              # materials & equipment

# Raw-cap-basis history from the spec session — reference only, different basis.
RAW_BASIS_REF = {"peak_pct": 18.03, "peak_date": "2026-06-22",
                 "current_on_2026_07_18": 16.01}

_CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "inputs", "semi_membership.json")


def _load_membership():
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_membership(cache):
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    from engine.common import atomic_write_json
    atomic_write_json(_CACHE_FILE, cache)


def _classify_newcomer(ticker):
    """Yahoo-industry classification for a rebalance newcomer. Yahoo != GICS
    (FSLR-type mismatches possible) — result is audited via extras."""
    try:
        import yfinance as yf
        industry = (yf.Ticker(ticker).info.get("industry") or "")
        return "semiconductor" in industry.lower(), industry
    except Exception:
        return False, "classification_failed"


def compute():
    df, asof = spy_holdings()
    tickers = df["Ticker"].tolist()

    cache = _load_membership()
    if not cache:  # first run: seed semis true, every other current member false
        cache = {t: (t in SEED_SEMIS) for t in tickers}
        for t in SEED_SEMIS:
            cache[t] = True
        _save_membership(cache)

    newcomers = {}
    for t in tickers:
        if t not in cache:
            is_semi, industry = _classify_newcomer(t)
            cache[t] = is_semi
            newcomers[t] = {"is_semi": is_semi, "yahoo_industry": industry}
    if newcomers:
        _save_membership(cache)

    members = [t for t in tickers if cache.get(t)]
    current_pct = round(float(df[df["Ticker"].isin(members)]["Weight"].sum()), 2)

    # Running peak = max over our own float-basis observations (snapshot log
    # holds current_pct per day) and today.
    prior = [v for _, v in store.history("concentration", limit=2000) if v is not None]
    peak_pct = round(max([current_pct] + prior), 2)

    if peak_pct > GREEN_ABOVE:
        light, state = "green", "dominant"
    elif peak_pct >= YELLOW_ABOVE:
        light, state = "yellow", "elevated"
    else:
        light, state = "red", "modest"

    extras = {
        "current_pct": current_pct,
        "peak_pct": peak_pct,
        "n_members": len(members),
        "members": members,
        "basis": "float_adjusted_spy_weights",
        "raw_basis_reference": RAW_BASIS_REF,
        "source": "SSGA SPY daily holdings xlsx",
    }
    if newcomers:
        extras["newcomers_classified"] = newcomers

    return {
        "id": "concentration",
        "light": light,
        "value": current_pct,        # snapshot logs the DAILY print; peak derives
        "metric": f"{peak_pct:.2f}%",  # display shows the PEAK (mockup contract)
        "state": state,
        "asof": asof,
        "extras": extras,
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(compute(), indent=2))
