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

from ..sources.yfin import (batched_closes, bars_since_52wk_high,
                           market_caps, project_gate_date)

TICKERS = ["ODFL", "SAIA", "XPO", "ARCB",                    # LTL
           "KNX", "WERN", "HTLD", "MRTN", "SNDR", "CVLG",    # truckload
           "LSTR",                                           # flatbed/oversize
           "JBHT",                                           # intermodal
           "UNP", "CSX", "NSC",                              # rail
           "CTOS"]                                           # utility equipment
GATE_BARS = 63

# --- CONSTITUENT METADATA (display name + sub-sector) --------------------------
# The GROUPING is a fact about the basket and lives here beside the tickers; the
# COLOURS are display and live in the frontend. Four groups, and the fourth is a
# residue rather than a peer: LSTR is flatbed/oversize brokerage, JBHT intermodal,
# CTOS utility fleet — three different specialisations with one name each, which is
# "Other", not a sector.
#
# WHY FOUR AND NOT SIX (the natural reading of the ticker comments): three of them
# get a hue and the residue gets the neutral, because THREE is what this surface
# will carry. `validate_palette.js` (dataviz skill) passes #6366f1/#ec4899/#0e9fbf
# all-pairs on the panel's #0f172a — worst CVD ΔE 8.2 deutan, normal-vision 18.5 —
# and FAILS the moment a fourth hue joins them: violet against indigo measures ΔE
# 14.1 to NORMAL vision, under the hard floor of 15. Measured, not eyeballed, and
# it is the same ceiling session 48 hit on silicon_payback's pies.
NAMES = {
    "ODFL": ("Old Dominion",   "ltl"),
    "SAIA": ("Saia",           "ltl"),
    "XPO":  ("XPO",            "ltl"),
    "ARCB": ("ArcBest",        "ltl"),
    "KNX":  ("Knight-Swift",   "truckload"),
    "WERN": ("Werner",         "truckload"),
    "HTLD": ("Heartland",      "truckload"),
    "MRTN": ("Marten",         "truckload"),
    "SNDR": ("Schneider",      "truckload"),
    "CVLG": ("Covenant",       "truckload"),
    "LSTR": ("Landstar",       "specialised"),
    "JBHT": ("J.B. Hunt",      "specialised"),
    "UNP":  ("Union Pacific",  "rail"),
    "CSX":  ("CSX",            "rail"),
    "NSC":  ("Norfolk Southern", "rail"),
    "CTOS": ("Custom Truck",   "specialised"),
}
GROUP_LABELS = {"rail": "Rail", "ltl": "LTL",
                "truckload": "Truckload", "specialised": "Specialised"}


def _ladder(level, ma50, ma200, bars_since, gate_bars=GATE_BARS):
    """The 4-state ladder — ONE implementation, called by both compute() and ledger().

    Extracted 2026-08-29 when the ledger needed to replay the rule on past bars. A
    second copy of a state machine is free to disagree with the first, which is the
    same reason events.py reads the factor's own gate projection instead of
    recomputing one: the evidence view must show the rule the light actually ran."""
    if level < ma200:
        return {"light": "green", "state": "below_trend",
                "cond_below50": False, "cond_no_high": False, "n_conds": 0}
    c50, chigh = level < ma50, bars_since >= gate_bars
    n = int(c50) + int(chigh)
    light, state = (("yellow", "distribution_top") if n == 2 else
                    ("orange", "weakening") if n == 1 else ("red", "humming"))
    return {"light": light, "state": state,
            "cond_below50": c50, "cond_no_high": chigh, "n_conds": n}

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
    gate_date, gate_remaining = project_gate_date(idx, GATE_BARS)

    lad = _ladder(last, ma50, ma200, bars_since)
    light, state = lad["light"], lad["state"]

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
            # Same 63-bar gate as copper, so the same drift applies: recomputed every
            # pass so the calendar row is refreshed rather than pinned.
            "gate_date": gate_date,
            "gate_bars_remaining": gate_remaining,
            "n_names": len(TICKERS),
            "index_level": round(last, 2),
            "base_date": BASE_DATE,
            "rebalance": "quarterly (3rd Friday Mar/Jun/Sep/Dec, XTN schedule)",
            "source": "yfinance equal-weight 16-name index, quarterly rebalance",
        },
    }


def ledger(days=10):
    """The evidence behind the light: every constituent against its OWN trend, and
    what the basket is made of.

    RE-DERIVED, from the same `batched_closes` pull compute() makes — but the word
    carries less weight here than it does for premium_share, and the difference is
    worth stating because the panel labels a re-derived day. premium_share re-prices
    old token volumes against TODAY's price list, so a recomputed day can land in a
    different BAND than the recorded one. This ledger reads historical CLOSES, which
    are not restated: replaying 2026-08-07 gives the numbers the light saw on
    2026-08-07. The reconstruction is faithful, and `AB_VIEWS.heavy_haul.reconLabel`
    says so instead of borrowing premium_share's "re-priced today".

    FREE — one yfinance batch, the same one the light and the chart already make.

    Two things ride on the NEWEST day only, because neither is a property of a day:
      - `cap`, the market cap per name. Attaching today's caps to a three-week-old
        row would present today's composition as that day's. The scheduler captures
        with days=1, so each RECORDED day does end up holding the caps that were
        true when it was written — a real composition history, accumulated rather
        than back-filled.
      - nothing else; the index series is NOT stored here. The chart the view draws
        is `/get_board_charts`'s heavy_haul entry, built by `_build_heavy_haul` from
        this module's own `build_index` — so the picture and the light cannot
        disagree, and 252 bars are not re-stored once a day forever."""
    df = batched_closes(TICKERS, start=FETCH_START)
    idx = build_index(df)

    # ROLLING, not tail() — the generalisation of compute()'s `idx.tail(200).mean()`
    # to a past bar. At the last bar the two are the same number by construction.
    i50, i200 = idx.rolling(50).mean(), idx.rolling(200).mean()
    n50, n200 = df.rolling(50).mean(), df.rolling(200).mean()

    caps = {}
    try:
        caps = market_caps(TICKERS)
    except Exception:
        caps = {}           # composition greys out; the ladder view is unaffected

    out = []
    for k, pos in enumerate(range(len(idx) - 1, max(len(idx) - 1 - days, -1), -1)):
        dt = idx.index[pos]
        level, ma50, ma200 = float(idx.iloc[pos]), float(i50.iloc[pos]), float(i200.iloc[pos])
        hist = idx.iloc[:pos + 1]
        _, high_date, bars_since = bars_since_52wk_high(hist)
        gate_date, gate_remaining = project_gate_date(hist, GATE_BARS)
        lad = _ladder(level, ma50, ma200, bars_since)

        names = []
        for sym in TICKERS:
            px = float(df[sym].iloc[pos])
            m50, m200 = float(n50[sym].iloc[pos]), float(n200[sym].iloc[pos])
            nm, grp = NAMES[sym]
            row = {"key": sym, "name": nm, "group": grp, "last": round(px, 2),
                   "vs50": round((px / m50 - 1) * 100, 1),
                   "vs200": round((px / m200 - 1) * 100, 1),
                   "below50": px < m50, "below200": px < m200}
            if k == 0:                       # newest day only — see the docstring
                row["cap"] = caps.get(sym)
            names.append(row)

        out.append({
            "date": dt.date().isoformat(),
            "index": round(level, 2),
            "ma50": round(ma50, 2), "ma200": round(ma200, 2),
            "vs50": round((level / ma50 - 1) * 100, 1),
            "vs200": round((level / ma200 - 1) * 100, 1),
            "high_date": high_date, "bars_since_high": bars_since,
            "gate_bars": GATE_BARS, "gate_date": gate_date,
            "gate_bars_remaining": gate_remaining,
            # The BREADTH counts — the number this factor is equal-weighted in order
            # to see, and the hero of the Constituents view. Cap weight reads the
            # basket through three rails and cannot report it (see the header).
            "below50_n": sum(1 for r in names if r["below50"]),
            "below200_n": sum(1 for r in names if r["below200"]),
            "n_names": len(names),
            "names": names,
            **lad,
        })
    return out

if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
