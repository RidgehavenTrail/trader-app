"""
yfinance helpers shared by the market-data factors.

Conventions (locked in the session-31 specs):
- All MAs are TRADING-bar means (px.tail(n).mean()), never calendar-day windows.
  Pull period must comfortably exceed the longest MA (we use 2y for a 200-bar MA).
- 52-week highs are CLOSE-based over the last 252 bars — matching the verified
  scratch scripts (check_copper.py / check_heavyhaul.py) that produced the
  spec's reference values.
"""
import yfinance as yf


def daily_closes(symbol, period="2y"):
    h = yf.Ticker(symbol).history(period=period)
    if h.empty:
        raise ValueError(f"yfinance {symbol}: empty history")
    return h["Close"].dropna()


def batched_closes(tickers, period="2y", start=None):
    """Close matrix for a basket, one column per ticker. Raises if any ticker
    came back entirely empty (a silently missing member skews an equal-weight
    index — fail loud instead).

    `start` (YYYY-MM-DD) fetches from an ABSOLUTE date instead of a rolling
    `period`. Use it whenever the caller holds a FIXED reference date — a rebase
    anchor, a pinned base. `period` measures backwards from TODAY and therefore
    advances every day, so a fixed anchor sitting inside it is on a countdown:
    heavy_haul pinned a 2021-08-02 base against period="5y", and ~10 days later
    the window had slid past the base and the factor refused to build. Widening
    the period only buys years; anchoring the FETCH to the same date as the base
    removes the mismatch entirely, because the two can no longer diverge."""
    kw = {"start": start} if start else {"period": period}
    df = yf.download(tickers, progress=False, **kw)["Close"]
    missing = [t for t in tickers if t not in df.columns or df[t].isna().all()]
    if missing:
        raise ValueError(f"yfinance batch missing: {missing}")
    return df


def annual_capex_b(symbol):
    """Latest-FY reported capital expenditure in $B (deterministic prior anchor
    for capex spigot — the just-completed year's actual spend). yfinance annual
    cashflow, 'Capital Expenditure' row (negative -> abs)."""
    import yfinance as yf
    cf = yf.Ticker(symbol).cashflow
    row = [r for r in cf.index if "Capital Expenditure" in r]
    if not row:
        raise ValueError(f"{symbol}: no Capital Expenditure row in annual cashflow")
    return round(abs(float(cf.loc[row[0]].iloc[0])) / 1e9, 1)


def bars_since_52wk_high(closes):
    """(high, high_date, bars_since) on the last 252 CLOSE bars."""
    px = closes.tail(252)
    high = px.max()
    high_idx = px.idxmax()
    bars_since = len(px) - 1 - px.index.get_loc(high_idx)
    return float(high), high_idx.date().isoformat(), int(bars_since)
