"""
Factor #6 — LEVERAGE (how violent the unwind; LOADED not fired). Rank 6.

Formula: margin debt / free credit balances — leverage vs investors' cash
cushion. Self-contained in ONE FINRA xlsx, no FRED.

  GREEN  > 2.0x   — leverage MAXED = tank full = primed to unwind = pro-burst
                    (NOT "crack fired" — loaded)
  YELLOW 1.5-2.0x
  RED    < 1.5x   (near-moot BY DESIGN: at a record ratio the bubble pops long
                   before leverage bleeds back to 1.5)

The 2.0 line is ANCHORED, not chosen: avg of the two peaks that matter —
2000 dot-com 1.85x and 2021 mania 2.19x. Reference: current 3.41x is the
ALL-TIME RECORD, 100th pctile 1997-2026, driven by the NUMERATOR (margin debt
$936B->$1.50T while free credit ~flat).

CAVEATS (spec-locked): FINRA = CUSTOMER margin — excludes prime brokerage,
repo, total-return swaps (Archegos-invisible) -> UNDERSTATES system leverage
(bias runs safe for a burst board). Post-2020 idle-cash sweeps modestly
understate the denominator (footnote; the numerator does the work).

SOURCE: FINRA margin-statistics xlsx via sources/finra.py (Akamai-gated;
needs curl_cffi TLS impersonation — see that module). DENOMINATOR = cash
free-credit + margin free-credit SUMMED. Values in $ MILLIONS. PARSE CAVEAT:
pre-2010 rows combine the two free-credit columns into one — irrelevant here
(we read the LATEST row) but never naively time-series the raw columns.
Cadence: MONTHLY, released ~3rd week for the prior month -> new-tag on
arrival (the canonical pinned-monthly example).
"""
import pandas as pd

from .. import store
from ..sources.finra import margin_statistics

GREEN_ABOVE = 2.0
YELLOW_ABOVE = 1.5


def _find_col(cols, *needles):
    for c in cols:
        name = str(c).lower()
        if all(n in name for n in needles):
            return c
    return None


def compute():
    # Sorted ascending by _ratio_frame, so the last row is the most recent reference
    # month. Same frame, same denominator rule, as the graph in ledger().
    f = _ratio_frame()
    if f.empty:
        raise ValueError("FINRA xlsx: no usable rows")
    row = f.iloc[-1]
    asof = row["d"].date().isoformat()
    debit = float(row["debit"])
    denom = float(row["denom"])
    ratio = float(row["ratio"])

    if ratio > GREEN_ABOVE:
        light, state = "green", "maxed"
    elif ratio >= YELLOW_ABOVE:
        light, state = "yellow", "elevated"
    else:
        light, state = "red", "modest"

    return {
        "id": "leverage",
        "light": light,
        "value": ratio,
        "metric": f"{ratio:.2f}x",
        "state": state,
        "asof": asof,
        "extras": {
            "margin_debt_b": round(debit / 1e3, 1),      # $M -> $B
            "free_credit_b": round(denom / 1e3, 1),
            "refs": {"2000_peak": 1.85, "2007": 1.17, "2021_peak": 2.19,
                     "2008_bottom": 0.61},
            "source": "FINRA margin-statistics xlsx",
        },
    }


# The month FINRA split free credit into two columns. Before it, the CASH column
# carries the combined figure and the margin column is empty; from it, the two are
# separate and must be summed. Summing naively across the join understates every
# denominator before 2010 -- which is what sources/finra.py means by "never naively
# time-series the raw columns", and why nothing had drawn this history until now.
FREE_CREDIT_SPLIT = "2010-02-01"

# Where each pinned reference sits in the series. The VALUES are the factor's own
# constants; these windows only say which era to look in, so the view can mark them on
# the line at the month they actually happened rather than as free-floating levels.
# Each one is checked against its pinned value on every build -- a mismatch means the
# denominator rule has drifted, and it is reported rather than drawn over.
ANCHOR_WINDOWS = {
    "2000_peak":   ("1999-01-01", "2001-06-30", "max"),
    "2007":        ("2007-01-01", "2007-12-31", "max"),
    "2008_bottom": ("2008-06-01", "2009-06-30", "min"),
    "2021_peak":   ("2021-01-01", "2022-06-30", "max"),
}
ANCHOR_LABEL = {"2000_peak": "2000 peak", "2007": "2007",
                "2008_bottom": "2008 bottom", "2021_peak": "2021 peak"}


def _ratio_frame():
    """The whole FINRA table as a monthly ratio series -> DataFrame(d, debit, denom, ratio).

    ONE denominator rule, used by compute() for the light and by ledger() for the
    graph, so the two cannot disagree about the arithmetic behind a number the reader
    sees twice.

    VALIDATED against this factor's own pinned anchors, which is what makes the
    pre-2010 handling trustworthy rather than merely plausible: it reproduces the
    2000 peak 1.85 (2000-02), 2007's 1.17 (2007-06), the 2008 bottom 0.61 (2008-08)
    and the 2021 peak 2.19 (2021-10) exactly, and three of those four fall on the far
    side of the column split."""
    df = margin_statistics()
    date_col = df.columns[0]
    debit_col = _find_col(df.columns, "debit")
    fc_cash_col = _find_col(df.columns, "free credit", "cash")
    fc_margin_col = _find_col(df.columns, "free credit", "margin")
    if not all([debit_col, fc_cash_col, fc_margin_col]):
        raise ValueError(f"FINRA xlsx: columns not recognized: {list(df.columns)}")
    for c in (debit_col, fc_cash_col, fc_margin_col):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["d"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["d", debit_col]).sort_values("d")

    split = pd.Timestamp(FREE_CREDIT_SPLIT)
    margin = df[fc_margin_col].fillna(0.0)
    df["denom"] = df[fc_cash_col].where(df["d"] < split, df[fc_cash_col] + margin)
    df = df[df["denom"] > 0].copy()
    df["debit"] = df[debit_col]
    df["ratio"] = (df["debit"] / df["denom"]).round(2)
    return df[["d", "debit", "denom", "ratio"]]


def ledger(days=10, top=10):
    """The ratio against its own history, and the anchors the 2.0 line is set from.

    Per-day rows are SNAPSHOT-DERIVED -- ratio, margin debt and free credit all ride in
    the day's own extras. The monthly SERIES is re-derived from the same FINRA file
    compute() reads, through the same `_ratio_frame`, and the endpoint caches it for the
    ET day so the panel pulls at most once however often it is opened.

    The series rides only when days > 1, for the reason rate_path's cloud does: the
    scheduler captures with days=1 and whatever it gets is stored permanently, and 300+
    static monthly points do not need writing to disk again every day. The panel asks
    for more than one day; the scheduler asks for exactly one."""
    out = []
    for day in store.history_payloads("leverage", days):
        ex = day.get("extras") or {}
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "ratio": day.get("value"),
            "margin_debt_b": ex.get("margin_debt_b"),
            "free_credit_b": ex.get("free_credit_b"),
            "green_above": GREEN_ABOVE, "yellow_above": YELLOW_ABOVE,
            "refs": ex.get("refs") or {},
            "source": ex.get("source"),
        })

    if out and days > 1:
        try:
            f = _ratio_frame()
            f = f[f["d"] >= "1999-01-01"]
            out[0]["series"] = [[r.d.date().isoformat(), float(r.ratio)]
                                for r in f.itertuples()]
            # The record, computed rather than asserted. The module header calls the
            # current reading the all-time high; it was, and then it came off -- so the
            # view states the peak and its date instead of inheriting a claim that goes
            # stale the first month the series turns.
            top_i = f["ratio"].idxmax()
            out[0]["peak"] = {"ratio": float(f.loc[top_i, "ratio"]),
                              "date": f.loc[top_i, "d"].date().isoformat()}
            out[0]["series_from"] = f["d"].min().date().isoformat()
            out[0]["n_months"] = int(len(f))

            refs = out[0]["refs"] or {}
            anchors = []
            for key, (lo, hi, how) in ANCHOR_WINDOWS.items():
                w = f[(f["d"] >= lo) & (f["d"] <= hi)]
                if w.empty:
                    continue
                i = w["ratio"].idxmax() if how == "max" else w["ratio"].idxmin()
                val = float(w.loc[i, "ratio"])
                pinned = refs.get(key)
                anchors.append({
                    "key": key, "label": ANCHOR_LABEL.get(key, key),
                    "date": w.loc[i, "d"].date().isoformat(), "ratio": val,
                    "pinned": pinned,
                    # True when the series still reproduces the constant. It does today,
                    # on all four -- and three of them sit on the far side of the 2010
                    # column split, which is what makes that handling trustworthy.
                    "matches": pinned is None or abs(val - pinned) < 0.005,
                })
            out[0]["anchors"] = anchors
        except Exception as e:          # a dead FINRA costs the CONTEXT, not the reading
            out[0]["series_error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
