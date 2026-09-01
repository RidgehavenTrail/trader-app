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


def daily_closes(symbol, period="2y", start=None):
    """Daily closes for one symbol.

    `start` (YYYY-MM-DD) fetches from an ABSOLUTE date instead of the rolling
    `period`, for the same reason batched_closes takes one: a display window
    anchored to a fixed year cannot ride a period that advances every day."""
    kw = {"start": start} if start else {"period": period}
    h = yf.Ticker(symbol).history(**kw)
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


def project_gate_date(closes, gate_bars):
    """When does "no new 52-week high for `gate_bars` bars" become true?

    -> (iso_date, bars_remaining). Copper and heavy_haul both flip state on elapsed
    TIME rather than on new information, so their transition date is knowable in
    advance -- which is the only reason a self-gate has a calendar row at all.

    IT MUST BE RECOMPUTED, NOT PINNED. The date is a function of the LAST 52-week
    high, so any new high resets it. Observed 2026-08-13: the calendar still carried
    copper's gate at 2026-09-01, computed on 2026-07-18 off a 2026-06-02 high, while
    copper had actually made a new high on 2026-08-05 and pushed the real gate out by
    roughly two months. The light was right the whole time -- it recomputes hourly
    from data -- and only the stored date drifted.

    bars_remaining <= 0 means the gate is already open, and the returned date is the
    bar it opened on. Otherwise the date is projected forward over WEEKDAYS; without a
    holiday calendar that runs slightly EARLY, which is the same direction the news
    freshness cutoff errs and is stated for the same reason.
    """
    from datetime import timedelta

    px = closes.tail(252)
    high_pos = px.index.get_loc(px.idxmax())
    gate_pos = high_pos + int(gate_bars)
    remaining = gate_pos - (len(px) - 1)

    if remaining <= 0:
        return px.index[gate_pos].date().isoformat(), int(remaining)

    d = px.index[-1].date()
    left = remaining
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d.isoformat(), int(remaining)


def market_caps(tickers, workers=8):
    """Current market cap in $ per ticker -> {ticker: float | None}.

    `fast_info`, never `.info` — the full info dict is a much heavier scrape for one
    number. It still costs ~0.6s a name, so the reads run in a small thread pool:
    sixteen of them in series would put ten seconds in front of a panel open, and
    they are independent network calls with nothing to serialise.

    A name that fails comes back None instead of raising, which is the OPPOSITE of
    `batched_closes` above and deliberately so. A missing close silently skews an
    equal-weight index, so that one fails loud; a missing cap is composition colour
    that feeds no light, so it must never cost a caller the rest of its ledger. The
    view says which name it could not size rather than quietly dropping it from the
    total."""
    from concurrent.futures import ThreadPoolExecutor

    def one(sym):
        try:
            fi = yf.Ticker(sym).fast_info
            cap = fi.get("marketCap") if hasattr(fi, "get") else fi["market_cap"]
            return sym, (float(cap) if cap else None)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, tickers))
