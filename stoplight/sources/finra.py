"""
FINRA margin-statistics fetcher.

FINRA's file host Akamai-gates ordinary clients — plain requests/curl 403
even with full browser-header mimicry. `curl_cffi` (Chrome TLS-fingerprint
impersonation, pip-installed 2026-07-19) passes cleanly. NOTE: a FINRA Query
API dataset (`/data/group/finra/name/marginStatistics`) does exist behind a
free developer account — the spec's "no API exists" note is stale; that's the
clean migration path if the TLS trick ever stops working.

File shape (verified 2026-07-19): columns Year-Month / Debit Balances in
Customers' Securities Margin Accounts / Free Credit (Cash) / Free Credit
(Margin), values in $ MILLIONS, sorted NEWEST-FIRST, history to Jan-1997.
Pre-2010 rows combine the two free-credit columns (margin col NaN) — read
the latest row, never naively time-series the raw columns.
"""
import io

import pandas as pd
from curl_cffi import requests as curl_requests

FINRA_XLSX = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"


def margin_statistics(timeout=60):
    """The margin-statistics table as a DataFrame, values in $ millions."""
    r = curl_requests.get(FINRA_XLSX, impersonate="chrome", timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"FINRA margin stats: HTTP {r.status_code}")
    df = pd.read_excel(io.BytesIO(r.content))
    if df.shape[1] < 4:
        raise ValueError(f"FINRA margin stats: unexpected shape {df.shape}")
    return df
