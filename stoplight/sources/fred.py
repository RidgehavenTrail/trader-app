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
