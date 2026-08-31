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

# --- HISTORICAL ANALOGUES (pinned; session 28's derivation, 2026-07-15) -----------
# Not computable here and never will be: SSGA serves the CURRENT holdings file only,
# this factor's own log starts 2026-04-15, and the price-ratio backfill it uses is
# valid over ~3 months because float shares do not hold still over 25 years. So these
# are documented constants, each carrying the BASIS it was measured on and whether it
# was sourced or recalled — the PINNED_CAPEX_PRIORS pattern, with the provenance
# attached because two of these numbers are softer than the rest.
#
# THE POINT OF THE VIEW, and it is session 28's finding rather than a comparison:
# concentration detects the 2000 KIND of bubble and is BLIND to the 2007 kind. "Of the
# four epicentres only dot-com and AI are concentration bubbles our marker catches;
# 2008 was CREDIT, not equity concentration — it was LOW in '07." That is why the
# board carries market_credit and leverage as separate lights, and why the honest
# 2007 row here is an absence rather than a number.
#
# NO SINGLE MEASURE SPANS ALL FOUR ERAS, and the blanks are left blank rather than
# filled by proxy: RSP (equal-weight) was born in 2003, so 2000 has no RSP/SPY; the
# deep OEX/GSPC stand-in covers 2000 and today but was not recorded for 2007.
ANALOGUES = [
    {"era": "2000", "label": "Dot-com / telecom",
     "top10_pct": 25.0, "top10_src": "published",
     "breadth": 0.547, "breadth_metric": "OEX/GSPC",
     "semis_pct": 6.0, "semis_range": "5–7", "semis_src": "recalled",
     "detected": True,
     "note": "Concentration DID mark it. A violent spike — blew out, then collapsed."},
    {"era": "2007", "label": "Housing / banks",
     "top10_pct": None, "top10_src": None,
     "breadth": 0.339, "breadth_metric": "RSP/SPY",
     "semis_pct": None, "semis_range": None, "semis_src": None,
     "detected": False,
     "note": "Concentration MISSED it, and that is the finding: breadth sat at 0.339 "
             "against a 0.353 median — near normal. The bubble was in CREDIT, not in "
             "equity weight. Read market credit and leverage for this shape."},
    {"era": "2014–16", "label": "Tame baseline",
     "top10_pct": 17.5, "top10_src": "published",
     "breadth": 0.39, "breadth_metric": "RSP/SPY",
     "semis_pct": 3.0, "semis_range": "2–4", "semis_src": "recalled",
     "detected": False,
     "note": "The least concentrated stretch in decades — peak breadth. Included for "
             "scale: without it the other rows have no floor to be read against."},
]
# Today's row is not pinned — it is whatever the reading says, so the comparison can
# never quietly go stale against a hardcoded 'now'.
TODAY_TOP10_PCT = 38.0        # published top-10 S&P weight, session 28
TODAY_BREADTH = 0.283         # RSP/SPY
TODAY_BREADTH_DEEP = 0.494    # OEX/GSPC, the measure comparable with 2000
BREADTH_MEDIAN = 0.353        # RSP/SPY median over the 2003+ window

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



def ledger(days=10, top=10):
    """Peak against print, and the two bases that could have measured either.

    SNAPSHOT-DERIVED: every figure rides in the day's own `extras`, so this re-shapes
    the record rather than re-deriving it — free, and it cannot disagree with the light.

    ONE view, because there is only one thing here worth drawing. `members` is a list of
    nineteen TICKERS with no per-name weight attached, so a constituent chart would be
    nineteen labels and no data; the roster is listed as a roster and nothing pretends
    it is a breakdown."""
    out = []
    for day in store.history_payloads("concentration", days):
        ex = day.get("extras") or {}
        peak, cur = ex.get("peak_pct"), ex.get("current_pct")
        if peak is None or cur is None:
            continue
        raw = ex.get("raw_basis_reference") or {}
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "peak_pct": peak, "current_pct": cur,
            # How far today sits below the high-water mark. The light reads the peak, so
            # this gap is the whole reason the pane and the sparkline disagree.
            "off_peak": round(peak - cur, 2),
            "green_at": GREEN_ABOVE, "yellow_at": YELLOW_ABOVE,
            "basis": ex.get("basis"),
            "raw_peak_pct": raw.get("peak_pct"), "raw_peak_date": raw.get("peak_date"),
            "peak_date": raw.get("peak_date"),
            "members": ex.get("members") or [], "n_members": ex.get("n_members"),
            "reconstructed": bool(day.get("reconstructed")),
            # The eras this reading is being asked to compare against, and today's own
            # row built from the LIVE numbers rather than a hardcoded 'now'.
            "analogues": ANALOGUES,
            "today": {"era": "today", "label": "AI / semis",
                      "top10_pct": TODAY_TOP10_PCT, "top10_src": "published",
                      "breadth": TODAY_BREADTH, "breadth_metric": "RSP/SPY",
                      "breadth_deep": TODAY_BREADTH_DEEP,
                      "semis_pct": peak, "semis_src": "measured",
                      "detected": True},
            "breadth_median": BREADTH_MEDIAN,
        })
    return out


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(compute(), indent=2))
