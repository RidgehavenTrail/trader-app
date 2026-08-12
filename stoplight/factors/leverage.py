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
    df = margin_statistics()

    date_col = df.columns[0]
    debit_col = _find_col(df.columns, "debit")
    fc_cash_col = _find_col(df.columns, "free credit", "cash")
    fc_margin_col = _find_col(df.columns, "free credit", "margin")
    if not all([debit_col, fc_cash_col, fc_margin_col]):
        raise ValueError(f"FINRA xlsx: columns not recognized: {list(df.columns)}")

    for c in (debit_col, fc_cash_col, fc_margin_col):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[debit_col])

    # latest row = most recent reference month (verify orientation, don't assume)
    dates = pd.to_datetime(df[date_col], errors="coerce")
    latest_idx = dates.idxmax()
    row = df.loc[latest_idx]
    asof = dates.loc[latest_idx].date().isoformat()

    debit = float(row[debit_col])
    denom = float(row[fc_cash_col]) + float(row[fc_margin_col])
    if denom <= 0:
        raise ValueError("FINRA xlsx: free-credit denominator not positive")
    ratio = round(debit / denom, 2)

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


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
