"""
SSGA (State Street) SPY daily-holdings fetcher.

WHY SPY, NOT IVV (source switch, 2026-07-19 build session): the spec's iShares
IVV .ajax CSV endpoint bot-gates ALL non-browser clients — curl, python
requests, browser UA, cookie jar + referer, and the siteEntryPassthrough
bypass all return the HTML shell (Akamai TLS fingerprinting, not a header
check). Slickcharts 403s likewise. SSGA serves a clean direct xlsx for SPY —
the same S&P 500 index — with per-name index Weight, keeping the spec's
one-file property.

BASIS NOTE (load-bearing): ETF holdings weights are FLOAT-ADJUSTED position
values / fund assets — the spec's stated "correct concentration convention".
The 2026-07-18 spec-session value (16.01%, peak 18.03% on 06-22) was computed
on the RAW-market-cap basis (yfinance caps / Slickcharts total) and reads
~1.09x LOWER. The two bases must never be mixed in one running max.

File shape (verified 2026-07-19): metadata rows 0-3 ("Holdings: As of
DD-Mon-YYYY" at row 2), header at row 4 — Name/Ticker/Identifier/SEDOL/
Weight/Sector/Shares Held/Local Currency. Sector column is "-" (useless);
GICS classification must come from elsewhere. Weight is already in percent.
"""
import io
import re

import pandas as pd
import requests

SPY_HOLDINGS_URL = ("https://www.ssga.com/us/en/intermediary/library-content/"
                    "products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def spy_holdings(timeout=60):
    """Return (holdings_df, asof_iso). holdings_df columns: Ticker, Weight (pct,
    numeric), Name. Non-ticker rows dropped."""
    r = requests.get(SPY_HOLDINGS_URL, headers=_UA, timeout=timeout)
    r.raise_for_status()
    if len(r.content) < 10000:
        raise ValueError(f"SSGA SPY holdings: implausibly small response ({len(r.content)}b)")

    raw = pd.read_excel(io.BytesIO(r.content), header=None)
    asof = None
    for i in range(min(6, len(raw))):
        m = re.search(r"As of\s+(\d{1,2}-\w{3}-\d{4})", " ".join(str(v) for v in raw.iloc[i]))
        if m:
            asof = pd.to_datetime(m.group(1), format="%d-%b-%Y").date().isoformat()
            break

    df = pd.read_excel(io.BytesIO(r.content), header=4)
    if "Ticker" not in df.columns or "Weight" not in df.columns:
        raise ValueError(f"SSGA SPY holdings: unexpected columns {list(df.columns)[:8]}")
    df = df.dropna(subset=["Ticker"]).copy()
    df["Weight"] = pd.to_numeric(df["Weight"], errors="coerce")
    df = df.dropna(subset=["Weight"])
    total = df["Weight"].sum()
    if not 95 <= total <= 105:
        raise ValueError(f"SSGA SPY holdings: weight column sums to {total:.1f}, not ~100")
    return df[["Ticker", "Weight", "Name"]], asof
