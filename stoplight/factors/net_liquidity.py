"""
Factor #16 — NET LIQUIDITY (softest macro leg; monetary cluster). Rank 16.

Measure: net_liq = WALCL - WTREGEN(TGA) - RRPONTSYD, in $T, weekly. Signal on
the 3-MONTH (13-week) change vs a +/-$0.2T noise band, 6mo-confirmed.

>> UNIT TRAP (build-critical, the -$749T bug): WALCL & WTREGEN are in $MILLIONS,
>> RRPONTSYD is in $BILLIONS. Align: WALCL/1e6 - WTREGEN/1e6 - RRPONTSYD/1e3.

STATES (on the 13wk change; inverted board):
  GREEN  draining  : chg_13wk < -0.2T AND 6mo trend also negative (sustained)
  YELLOW flat      : chg_13wk within +/-0.2T
  RED    expanding : chg_13wk > +0.2T AND 6mo trend also positive (sustained)
The sustain clause is LOAD-BEARING: TGA swings +/-$200-400B/qtr dominate — never
flip on one Treasury-account move. Band calibrated 2026-07-18: last-3yr 13wk-chg
SD = $0.176T -> +/-$0.2T (the 2018+ window was inflated by the COVID explosion).

CAVEAT: RRP buffer ~empty (~$0 vs ~$2.5T in 2022) — a drain from here hits bank
reserves DIRECTLY; same color, worse bite.

SOURCE: FRED WALCL (weekly Wed, H.4.1), WTREGEN (weekly), RRPONTSYD (daily,
ffill to weekly). Reference (2026-07-18 spec): ~$5.99T, 13wk chg +$0.03T ->
solidly flat, yellow.
"""
import pandas as pd

from .. import store
from ..sources.fred import fred_series

BAND_T = 0.2
WEEKS_3MO = 13
WEEKS_6MO = 26

# THE PICTURE'S WINDOW: 2020, so the COVID explosion, the QT drain and the TGA
# rebuilds are all in frame. The FETCH is the full series and the trim happens after
# the 13-week difference, so the change line is seeded at the left edge instead of
# starting a quarter into the window.
CHART_START = "2020-01-01"


def _net_frame():
    """WALCL - TGA - RRP in $T, weekly -> a frame with the components and the total.

    ONE definition, used by the light AND by the picture, for the same reason
    heavy_haul's chart calls the factor's own build_index: two derivations of "what
    net liquidity is" can drift apart, and the one on screen would be the one nobody
    checks.

    >> THE UNIT TRAP LIVES HERE AND NOWHERE ELSE: WALCL and WTREGEN are in $MILLIONS,
    >> RRPONTSYD is in $BILLIONS."""
    walcl = fred_series("WALCL")
    tga = fred_series("WTREGEN")
    rrp = fred_series("RRPONTSYD")

    df = pd.DataFrame({
        "walcl_T": walcl / 1e6,
        "tga_T": tga.reindex(walcl.index, method="ffill") / 1e6,
        "rrp_T": rrp.reindex(walcl.index, method="ffill") / 1e3,
    }).dropna()
    df["net_T"] = df["walcl_T"] - df["tga_T"] - df["rrp_T"]

    # The About box tells the reader this alignment is ASSERTED in the builder. This
    # is that assertion, and it was prose until now. A mixed unit misses by orders of
    # magnitude (the -$749T bug), so a plausibility gate on the level catches it here
    # rather than on a card.
    last = float(df["net_T"].iloc[-1])
    if not 1.0 <= last <= 15.0:
        raise ValueError(
            f"net liquidity {last:.3f}T outside the plausible range - unit mix?")
    return df


def _delta_metric(chg_3mo):
    """The 13-week change as the row reads it: "-0.09T", "+1.07T".

    LEADING ZERO KEPT (user, 2026-09-01) so the row matches every other factor's
    number. Six characters against a rail that holds nine, so unlike the earlier
    stripped form this has room for a $1T-plus move without wrapping."""
    return f"{chg_3mo:+.2f}T"


def compute():
    df = _net_frame()
    net = df["net_T"]

    level = round(float(net.iloc[-1]), 3)
    chg_3mo = round(float(net.diff(WEEKS_3MO).iloc[-1]), 3)
    chg_6mo = round(float(net.diff(WEEKS_6MO).iloc[-1]), 3)
    asof = net.index[-1].date().isoformat()

    if chg_3mo < -BAND_T and chg_6mo < 0:
        light, state = "green", "draining"
    elif chg_3mo > BAND_T and chg_6mo > 0:
        light, state = "red", "expanding"
    else:
        light, state = "yellow", "flat"

    return {
        "id": "net_liquidity",
        "light": light,
        "value": level,
        # THE READING IS THE DELTA (user, 2026-08-31), not the level it moved from.
        # This light is cut on the 13-week change and nothing else; the level is
        # context, and it was the only thing the row showed. Leading zero dropped so
        # the whole reading is five characters inside a 72px rail that holds nine --
        # a $1T-plus move simply uses the room. The LEVEL still rides in `value` and
        # in extras, and is named on the detail panel's identity line.
        "metric": _delta_metric(chg_3mo),
        "state": state,
        "asof": asof,
        "extras": {
            "chg_3mo_T": chg_3mo,
            "chg_6mo_T": chg_6mo,
            "rrp_T": round(float(df["rrp_T"].iloc[-1]), 4),
            "source": "FRED WALCL/WTREGEN/RRPONTSYD",
        },
    }


def ledger(days=10, top=10):
    """The tide since 2020, and the 13-week change that actually decides the light.

    TWO series because this factor reads one thing and DISPLAYS another: the board row
    carries the level ($T), the light is cut on the 13-week change against a +/-0.2T
    band. A picture of the level alone would not explain a single colour on this row.

    Per-day rows are SNAPSHOT-DERIVED. The series rides only when `days > 1` -- the
    scheduler captures with days=1 and stores what it gets permanently."""
    out = []
    for day in store.history_payloads("net_liquidity", days):
        ex = day.get("extras") or {}
        out.append({
            "date": day.get("asof") or day.get("date"),
            "light": day.get("light"), "state": day.get("state"),
            "level_T": day.get("value"),
            "chg_3mo_T": ex.get("chg_3mo_T"), "chg_6mo_T": ex.get("chg_6mo_T"),
            "rrp_T": ex.get("rrp_T"),
            "band_T": BAND_T, "weeks_3mo": WEEKS_3MO, "weeks_6mo": WEEKS_6MO,
            "source": ex.get("source"),
        })

    if out and days > 1:
        df = _net_frame()
        chg = df["net_T"].diff(WEEKS_3MO)
        series, outside = [], 0
        for ts in df.index:
            d = ts.date().isoformat()
            if d < CHART_START:
                continue
            c = chg.loc[ts]
            if c != c:                      # NaN -- the 13-week diff is not seeded yet
                continue
            series.append([d, round(float(df["net_T"].loc[ts]), 3), round(float(c), 3)])
            if abs(float(c)) > BAND_T:
                outside += 1
        if series:
            out[0]["series"] = series
            out[0]["chart_from"] = series[0][0]
            out[0]["n_weeks"] = len(series)
            # How often the 13-week move has actually cleared the noise band. The band
            # is one sigma, so "most weeks are inside it" is the expected result and
            # saying so stops a flat reading looking like a broken factor.
            out[0]["weeks_outside"] = outside
            hi = max(range(len(series)), key=lambda i: series[i][1])
            out[0]["peak"] = {"level_T": series[hi][1], "date": series[hi][0]}
            # The three components behind today's level, so the reader can see WHICH
            # leg is moving -- a TGA rebuild and a balance-sheet runoff look identical
            # in the total and mean opposite things.
            last = df.iloc[-1]
            out[0]["components"] = {
                "walcl_T": round(float(last["walcl_T"]), 3),
                "tga_T": round(float(last["tga_T"]), 3),
                "rrp_T": round(float(last["rrp_T"]), 4),
            }

    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
