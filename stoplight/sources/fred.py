"""
FRED fetcher — the fredgraph.csv template (no key), with retry.

FRED is intermittent (curl-28-style timeouts, NOT rate limits — see the
tooling-failure-modes history), so every pull gets retries with backoff.
Values come back in the series' NATIVE unit: rates in PERCENT (x100 for bps),
WALCL/WTREGEN in $ MILLIONS, RRPONTSYD in $ BILLIONS — unit alignment is the
CALLER's job (see net_liquidity's unit trap).
"""
import io
import time

import pandas as pd
import requests

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


# THE CHANGE IS COMPARED AS IT IS QUOTED (user, 2026-09-11): three decimals. Yahoo prices
# are float32 underneath, so a change sitting exactly on a threshold at the quote's
# precision can land in the double a hair either side of it, and a strict comparison
# would then call the regime on rounding noise. Rounding once, here, means the regime, the near-threshold ring,
# the chart's coloured segments and the number on screen all read the same value. The
# RATE is not rounded -- it keeps full precision, and the panels still show two decimals.
CHANGE_DECIMALS = 3


def lookback_base(series, months):
    """The print ON OR BEFORE `months` back, for every bar -- the fixed baseline a change
    is measured from. Kept EXACT so a live reading is measured against it and rounded
    once, instead of being rebuilt from values that were each rounded for display."""
    import pandas as pd
    back = series.reindex(series.index - pd.DateOffset(months=months), method="ffill")
    return pd.Series(back.to_numpy(), index=series.index)


def change_from(rate, base):
    """One reading against its baseline, rounded exactly as lookback_change rounds."""
    return round(float(rate) - float(base), CHANGE_DECIMALS)


def lookback_change(series, months):
    """Change over a trailing `months` window, anchored on the CALENDAR DATE.

    THE ONE DEFINITION, shared by the Rocket Strategy dial and the Charts-tab dial so
    the two cannot drift (2026-09-10). They used to compute this separately and
    disagreed on screen — +0.22 in the sidebar against +0.19 on the chart for the same
    2026-09-08 print of DTB3, because one measured back to the same calendar day six
    months earlier (2026-03-06, 3.58) and the other to the last print of that MONTH
    (2026-03-31, 3.61). DTB3 drifted +0.03 across late March and that drift was the
    whole discrepancy. Two conventions, one label, and near a band edge they could
    disagree about the REGIME rather than just the decimal.

    Reindexing onto the index shifted back by `months` with method="ffill" takes the
    last print ON OR BEFORE each target date, so holidays and gaps resolve BACKWARDS.
    Never forwards — that would read a rate that had not printed yet.

    Returns a Series on the SAME index as `series`, NaN before the window is seeded.
    """
    import pandas as pd
    base = lookback_base(series, months)
    # Rounded to CHANGE_DECIMALS -- see the constant above.
    return pd.Series(series.to_numpy() - base.to_numpy(),
                     index=series.index).round(CHANGE_DECIMALS)


def fred_series(sid, retries=3, timeout=30):
    """Return the series as a pandas Series indexed by date, NaNs dropped."""
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(FRED_CSV.format(sid=sid), timeout=timeout)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["date", sid]
            df["date"] = pd.to_datetime(df["date"])
            df[sid] = pd.to_numeric(df[sid], errors="coerce")
            s = df.set_index("date")[sid].dropna()
            if s.empty:
                raise ValueError(f"FRED {sid}: empty series")
            return s
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"FRED {sid} failed after {retries} attempts: {last_err}")
