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

from ..sources.fred import fred_series

BAND_T = 0.2
WEEKS_3MO = 13
WEEKS_6MO = 26


def compute():
    walcl = fred_series("WALCL")
    tga = fred_series("WTREGEN")
    rrp = fred_series("RRPONTSYD")

    df = pd.DataFrame({
        "walcl_T": walcl / 1e6,
        "tga_T": tga.reindex(walcl.index, method="ffill") / 1e6,
        "rrp_T": rrp.reindex(walcl.index, method="ffill") / 1e3,
    }).dropna()
    net = df["walcl_T"] - df["tga_T"] - df["rrp_T"]

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
        "metric": f"${level:.2f}T",   # 13wk change lives in extras (mockup rail is 72px)
        "state": state,
        "asof": asof,
        "extras": {
            "chg_3mo_T": chg_3mo,
            "chg_6mo_T": chg_6mo,
            "rrp_T": round(float(df["rrp_T"].iloc[-1]), 4),
            "source": "FRED WALCL/WTREGEN/RRPONTSYD",
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
