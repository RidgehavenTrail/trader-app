"""
Factor #11 — HEAVY HAUL (custom freight index; the ORANGE factor). Rank 11.

Equal-weight index of freight that PHYSICALLY moves the buildout — 16 names,
per-name rebased to 100 then meaned (cap-weighting would shrink marginal names
to rounding error). Deliberately EXCLUDES airlines (consumer travel), parcel
(e-commerce), and general forwarders.

THE 4-STATE LADDER (unique on the board — hysteresis is the whole point).
Two conditions, evaluated ONLY while index > 200-bar MA:
  cond1: index below the 50-bar MA
  cond2: no new 52-week CLOSE high for 63 TRADING BARS (same gate as copper)

  GREEN  : index below the 200MA — ANY breach. Dominates everything.
  YELLOW : above 200MA AND BOTH conditions true (rare ~2.5%: price between the
           50 and 200 with momentum dead = classic distribution top)
  ORANGE : above 200MA AND exactly ONE condition true (the day-to-day worker:
           86% of post-green episodes land here — a brief 200-breach that
           recovers CANNOT snap straight back to red)
  RED    : above 200MA AND neither (humming)

Direction (inverted board): GREEN = freight rolling = pro-burst; RED = humming.

SOURCE: yfinance batched Close of the 16. Reference (2026-07-18 spec): red,
+32.7-33.6% vs 200MA, +6.5-7% vs 50MA, 52wk high 2026-06-11 -> self-executing
orange gate ~Sep 10 absent a new high.
"""
import pandas as pd

from ..sources.yfin import batched_closes, bars_since_52wk_high

TICKERS = ["ODFL", "SAIA", "XPO", "ARCB",                    # LTL
           "KNX", "WERN", "HTLD", "MRTN", "SNDR", "CVLG",    # truckload
           "LSTR",                                           # flatbed/oversize
           "JBHT",                                           # intermodal
           "UNP", "CSX", "NSC",                              # rail
           "CTOS"]                                           # utility equipment
GATE_BARS = 63

# --- INDEX METHODOLOGY (matched to XTN / S&P Select Industry, 2026-08-01) -------
# Equal weight, RESET QUARTERLY on the third Friday of Mar/Jun/Sep/Dec (XTN's
# schedule), buy-and-hold drift within the quarter, chain-linked from a FIXED base.
#
# Why fixed base: the old build rebased each name at the first bar of the FETCH
# WINDOW, so the index level was an artifact of the lookback — the same day printed
# 175.70 / 129.03 / 149.71 under 5y / 2y / 1y fetches, and vs200 moved up to 0.59pt
# with it. Harmless for a light read off ratios, fatal for a chart's y-axis and for
# any comparison across time. A fixed base date makes the series reproducible and
# stable as history extends.
#
# Why quarterly reset: averaging rebased series is equal weight only AT the anchor —
# weights then drift with performance (measured 2026-08-01: CTOS had drifted to
# 10.54% against a 6.25% target, a 2.6x max/min spread). Quarterly is the industry
# convention AND deliberately not daily: daily rebalancing harvests volatility and
# would flatter the index's return. Disclosed, not silent.
#
# Why equal and NOT cap weight: three US Class I rails (UNP/CSX/NSC) are 71.4% of
# this basket's market cap, and they are the entire investable rail universe — BNSF
# sits inside Berkshire, KSU merged into CPKC, GWR went private. Cap weight would
# make the light a rail proxy: measured 2026-08-01, 13 of 16 names sat below their
# own 50-bar MA while cap weight still read +1.64% ABOVE its 50MA (equal weight:
# -6.42% below), i.e. cap weight would have printed RED "humming" into a broad
# rollover. Equal weight is the breadth detector; cap weight masks it.
#   CAVEAT on the rails, live 2026-08-01: UNP/NSC are the principals of an $85B
#   transcontinental merger (STB accepted 2026-05-28, decision expected 2027) and
#   CSX is the remaining consolidation candidate, so all three carry a deal premium
#   unrelated to freight demand — UNP's own Q1 had freight revenue +4% on volumes
#   DOWN 1%. They are 18.8% of the index by design; read rail strength accordingly.
BASE_DATE = "2021-08-02"      # all 16 names have continuous data from here
BASE_LEVEL = 100.0
# The fetch is ANCHORED TO THE BASE (start=BASE_DATE), not a rolling period — and that
# is structural, not a preference. period="Ny" measures back from TODAY, so it advances
# a year every year while the base stays put: the margin between them is a countdown.
# The original period="5y" put the base ON the window edge and it broke in ~10 days;
# widening to 10y only reset the clock to ~2031. Fetching FROM the base removes the
# mismatch entirely — the two dates can no longer diverge, because they are the same
# date. It is also exactly the data the index needs: nothing before the base is used.
FETCH_START = BASE_DATE


def _rebalance_dates(dates):
    """XTN's schedule — third Friday of each quarter-ending month."""
    out = set()
    for year in range(dates[0].year, dates[-1].year + 1):
        for month in (3, 6, 9, 12):
            first = pd.Timestamp(year, month, 1)
            fridays = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="W-FRI")
            if len(fridays) >= 3:
                out.add(fridays[2])
    return out


def build_index(df, base_date=BASE_DATE):
    """Chain-linked equal-weight index, quarterly reset, fixed base = 100.

    Chain-linking returns (rather than summing prices against a divisor) is the
    equal-weight equivalent of the divisor method and handles a constituent change
    without a step: a name simply joins the return average on its first bar."""
    if base_date:
        base_ts = pd.Timestamp(base_date)
        # FAIL LOUD if the fetch does not REACH the base — otherwise the index
        # quietly rebases at the window start again and prints a wrong level
        # (measured: a 2y fetch gives 129.96 where the true level is 178.66),
        # which is exactly the anchor bug the fixed base exists to kill. Same
        # philosophy as batched_closes raising on a missing member.
        if df.index[0] > base_ts + pd.Timedelta(days=7):
            raise ValueError(
                f"heavy_haul: data starts {df.index[0].date()}, after the fixed base "
                f"{base_date} — the index would mis-level. Fetch with "
                f"start=BASE_DATE (absolute), never a rolling period=.")
        df = df[df.index >= base_ts]
    if df.empty:
        raise ValueError("heavy_haul: no data at or after the base date")
    rebals = _rebalance_dates(df.index)
    rets = df.pct_change()
    n = df.shape[1]
    w = pd.Series(1.0 / n, index=df.columns)
    level, levels = BASE_LEVEL, {}
    for i, dt in enumerate(df.index):
        if i:
            r = rets.loc[dt].fillna(0.0)
            port = float((w * r).sum())
            level *= (1 + port)
            if port > -0.99:                       # guard a degenerate wipeout
                w = w * (1 + r) / (1 + port)       # weights drift within the quarter
        if dt in rebals:
            w = pd.Series(1.0 / n, index=df.columns)   # quarterly reset to equal
        levels[dt] = level
    return pd.Series(levels).dropna()


def compute():
    df = batched_closes(TICKERS, start=FETCH_START)
    idx = build_index(df)

    last = float(idx.iloc[-1])
    ma200 = float(idx.tail(200).mean())
    ma50 = float(idx.tail(50).mean())
    vs200 = round((last / ma200 - 1) * 100, 1)
    vs50 = round((last / ma50 - 1) * 100, 1)
    high, high_date, bars_since = bars_since_52wk_high(idx)

    if last < ma200:
        light, state = "green", "below_trend"
    else:
        cond_below50 = last < ma50
        cond_no_high = bars_since >= GATE_BARS
        n_conds = int(cond_below50) + int(cond_no_high)
        if n_conds == 2:
            light, state = "yellow", "distribution_top"
        elif n_conds == 1:
            light, state = "orange", "weakening"
        else:
            light, state = "red", "humming"

    return {
        "id": "heavy_haul",
        "light": light,
        "value": vs200,
        "metric": f"{vs200:+.1f}%",   # vs 200-bar MA (mockup rail is 72px; detail in extras)
        "state": state,
        "asof": idx.index[-1].date().isoformat(),
        "extras": {
            "vs_50dma_pct": vs50,
            "high_date": high_date,
            "bars_since_high": bars_since,
            "gate_bars": GATE_BARS,
            "n_names": len(TICKERS),
            "index_level": round(last, 2),
            "base_date": BASE_DATE,
            "rebalance": "quarterly (3rd Friday Mar/Jun/Sep/Dec, XTN schedule)",
            "source": "yfinance equal-weight 16-name index, quarterly rebalance",
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
