"""
Factor #9 — MEMORY CANARY (memory-glut sub-mechanism; WHEN factor). Rank 9.

Watches memory-market HEALTH, not HBM alone (DDR5 strength is AI-CAUSED — HBM
diverted capacity starved commodity DRAM; a real crack = HBM AND DDR5 rolling
TOGETHER).

PRIMARY METRIC: of the last 5 forward-EPS revisions POOLED across MU + SK Hynix,
count the DOWNWARD ones:
  RED    <= 1 down   : estimates holding/rising = bubble-supportive
  YELLOW 2-3 down
  GREEN  >= 4 down   : estimates cracking = pro-burst

BASKET (load-bearing): MU (~90% commodity — the DDR5 read) + SK Hynix 000660.KS
(56% HBM share — the HBM read; the KOREAN line, which carries analyst coverage —
NOT SKHYV/ADRs). MU alone hides HBM softness under DDR5 strength. NVDA out
(commoditization target, not memory); Samsung out (too diversified).

HORIZON — WHICH ESTIMATES COUNT (user, 2026-08-29). The feed carries four
estimate periods (0q, +1q, 0y, +1y) and this factor used to sum all four, which
pooled horizons a month out with horizons sixteen months out and weighted them
equally. The market prices roughly six months ahead, so TWO estimates per name
are counted and the other two are recorded but excluded:

  * `+1q` — the NEXT quarter, always. The upcoming quarter (`0q`) reports within
    weeks and is substantially priced; the one after it is where a revision still
    moves something.
  * the FISCAL YEAR that reports 6+ months out — `0y` when its results are still
    that far away, otherwise `+1y`.

The 6-month test is on the REPORT DATE, not the period end, because the report is
the event the estimate is tested at: a period that ended yesterday but reports in
a month is entirely forward-looking, and a year that ends in four months does not
settle until it is reported a month after that. (The literal "ends 6+ months out"
reading differs only for a fiscal year ending between ~5 and ~6 months away — a
window each name passes through for about a month a year. HORIZON_DAYS and the
report lag are the two constants to move if that call is ever revisited.)

Consequence worth knowing: this makes MU's and SK Hynix's selections DIFFERENT
labels at the same horizon whenever their fiscal calendars diverge — which is the
point. MU's fiscal year closes with the September print while SK Hynix's runs to
January, so `0y` means +1 month for one and +5 for the other. Selecting by date
is what lets the two be pooled at all.

REFERENCE DISCONTINUITY (2026-08-29): every reading before this date pooled all
four periods; readings after it pool two. The series is NOT continuous across
that line — same bands, different denominator. `extras.basis` names which rule a
stored day was computed under ("all_periods" is implied by its absence), and
`extras.per_period` keeps all four periods' counts from here on, so a later
re-basing has the inputs and does not need a re-pull.

MECHANICS: yfinance eps_revisions = true EPS estimate DIRECTION counts (NOT
upgrades_downgrades = rating-action noise). Counts arrive broken out per period
and are summed across the two SELECTED ones; they are analyst-PERIOD counts, so
with two periods one analyst revising a full model counts at most twice (it was
four times under the old rule). Counts come as 7d/30d windows, not a timestamped
list, so "last 5" is APPROXIMATED from the 7d down-share (30d fallback when <5
revisions in 7d). The scheduler's daily snapshot log turns these counts into a
real event stream over time (diff recovers events). Label matching is
orientation-agnostic (yfinance frames vary).

Reference (2026-07-18 spec): RED, 0-of-5 down — pooled ~31 up / 0-1 down, a
live DDR5 UP-burst. Earnings: SK Hynix ~07-28, MU ~09-23.
"""
import datetime

import yfinance as yf

from .. import store

TICKERS = ["MU", "000660.KS"]

# What each name is IN the basket. The two are not interchangeable reads and the panel
# has to say which is which: MU is ~90% commodity (the DDR5 line) and SK Hynix carries
# 56% of HBM (the AI line). A crack that counts shows up in BOTH -- DDR5 strength on its
# own is AI-CAUSED, since diverted capacity starved commodity DRAM.
NAMES = {
    "MU":        ("Micron", "~90% commodity - the DDR5 read"),
    "000660.KS": ("SK Hynix", "56% of HBM - the AI read"),
}

# Fiscal-year end (month, day) and the median lag from period end to REPORT, in days.
# PINNED, and safe to pin: a fiscal calendar is a definitional property of a company,
# not a measurement -- unlike a market share it does not drift, and the basket is two
# names by definition. The lags are MEASURED off the last four prints of each name
# (MU 20/20/27/33 -> 25; SK Hynix 28/22/28/27 -> 27), not assumed.
# MU runs a 52/53-week year ending the Thursday nearest 31 Aug, so its end date walks a
# few days year to year; against a six-MONTH threshold that drift cannot change an
# answer, and dating it exactly would cost a second network call per run.
FISCAL = {
    "MU":        (8, 28, 25),
    "000660.KS": (12, 31, 27),
}

# How far out a fiscal year must REPORT to be the one worth counting. Six months is the
# user's call (2026-08-29) and the market's usual discounting horizon.
HORIZON_DAYS = 183

# The estimate periods the feed publishes. The near quarter is deliberately NOT here.
PERIOD_KEYS = ("0q", "+1q", "0y", "+1y")


def _fy_dates(sym, today):
    """(end, report) for the fiscal year `0y` currently refers to.

    `0y` does not roll at the fiscal year END, it rolls at the PRINT that closes it --
    Micron's FY2026 ended 2026-08-28 and is still `0y` until the 2026-09-30 report. So:
    the most recent year-end if its results are not out yet, otherwise the next one."""
    m, d, lag = FISCAL[sym]

    def occ(year):
        try:
            return datetime.date(year, m, d)
        except ValueError:              # 29 Feb on a non-leap year
            return datetime.date(year, m, 28)

    last = occ(today.year) if occ(today.year) <= today else occ(today.year - 1)
    end = last if last + datetime.timedelta(days=lag) > today else occ(last.year + 1)
    return end, end + datetime.timedelta(days=lag)


def _periods_for(sym, today):
    """The two estimate periods this name is counted on, newest-relevant first."""
    _, report = _fy_dates(sym, today)
    year_key = "0y" if (report - today).days >= HORIZON_DAYS else "+1y"
    return ["+1q", year_key]


def _frame_periods(frame):
    """{period -> {up7, down7, up30, down30}} from an eps_revisions frame.

    Orientation-agnostic like the pooled version it replaces: whichever axis carries
    the up/down labels is the MEASURE axis and the other one carries the periods."""
    def has_updown(labels):
        return any("up" in str(l).lower() or "down" in str(l).lower() for l in labels)

    if has_updown(frame.columns):
        periods, measures, get = frame.index, frame.columns, lambda p, c: frame.loc[p, c]
    elif has_updown(frame.index):
        periods, measures, get = frame.columns, frame.index, lambda p, c: frame.loc[c, p]
    else:
        raise ValueError("eps_revisions: no up/down axis")

    out = {}
    for p in periods:
        rec = {"up7": 0.0, "down7": 0.0, "up30": 0.0, "down30": 0.0}
        for c in measures:
            key = str(c).lower()
            if "up" not in key and "down" not in key:
                continue
            try:
                val = float(get(p, c))
            except (TypeError, ValueError):
                continue
            side = "up" if "up" in key else "down"
            if "7" in key:
                rec[side + "7"] += val
            elif "30" in key:
                rec[side + "30"] += val
        out[str(p).strip().lower()] = rec
    return out


def _band(downs_of_5):
    """downs-of-5 -> (light, state). One definition, used by compute() and by the
    ledger's per-name and per-window what-if columns, so nothing on the panel can
    disagree with the light about where a band edge sits."""
    if downs_of_5 <= 1:
        return "red", "estimates_holding"
    if downs_of_5 <= 3:
        return "yellow", "cracking_partial"
    return "green", "estimates_cracking"


def _select_window(up7, down7, up30, down30):
    """Which window the reading is taken from, and its down-share. The 7d count is
    preferred and the 30d one is the fallback when 7d holds fewer than 5 revisions --
    "last 5" is being APPROXIMATED from a share, so a window thinner than 5 cannot
    carry it. Returns (window, down_share)."""
    if up7 + down7 >= 5:
        return "7d", down7 / (up7 + down7)
    if up30 + down30 >= 5:
        return "30d", down30 / (up30 + down30)
    return "30d", (down30 / (up30 + down30)) if (up30 + down30) else 0.0


def compute():
    today = datetime.date.today()
    up7 = down7 = up30 = down30 = 0
    per_ticker, per_period = {}, {}
    for sym in TICKERS:
        er = yf.Ticker(sym).get_eps_revisions()
        if er is None or er.empty:
            raise ValueError(f"{sym}: eps_revisions unavailable")
        periods = _frame_periods(er)
        per_period[sym] = periods
        picks = [k for k in _periods_for(sym, today) if k in periods]
        if not picks:
            # Never silently fall back to summing everything: that would put the OLD
            # basis into a row labelled with the new one, which is the one thing the
            # discontinuity note cannot help a reader with.
            raise ValueError(f"{sym}: none of the selected estimate periods "
                             f"{_periods_for(sym, today)} present in {sorted(periods)}")
        u7 = sum(periods[k]["up7"] for k in picks)
        d7 = sum(periods[k]["down7"] for k in picks)
        u30 = sum(periods[k]["up30"] for k in picks)
        d30 = sum(periods[k]["down30"] for k in picks)
        per_ticker[sym] = {"up7": u7, "down7": d7, "up30": u30, "down30": d30,
                           "periods": picks}
        up7 += u7
        down7 += d7
        up30 += u30
        down30 += d30

    window, downs_share = _select_window(up7, down7, up30, down30)
    downs_of_5 = round(downs_share * 5)
    light, state = _band(downs_of_5)

    return {
        "id": "memory_canary",
        "light": light,
        "value": downs_of_5,
        "metric": f"{downs_of_5}/5 dn",
        "state": state,
        "asof": today.isoformat(),
        # `basis` names the counting rule this row was computed under. Absent on every
        # row written before 2026-08-29, which is exactly what "all_periods" means --
        # see the REFERENCE DISCONTINUITY note above.
        "extras": {"window": window, "basis": "two_estimates",
                   "pooled_up7": up7, "pooled_down7": down7,
                   "pooled_up30": up30, "pooled_down30": down30,
                   "per_ticker": per_ticker,
                   # All four periods, including the two NOT counted. Kept so the
                   # evidence view can show what was excluded and a later re-basing has
                   # its inputs without a re-pull.
                   "per_period": per_period,
                   "source": "yfinance eps_revisions MU+000660.KS"},
    }



def _window_row(key, label, up, down, used):
    """One window read as a complete reading: its counts, its down-share, the
    downs-of-5 that share rounds to, and the light that band implies."""
    up, down = int(round(up)), int(round(down))
    total = up + down
    share = (down / total) if total else 0.0
    downs = round(share * 5)
    light, _ = _band(downs)
    return {"key": key, "label": label, "up": up, "down": down, "total": total,
            "share": round(share * 100, 1), "downs": downs, "light": light,
            "used": used, "thin": total < 5}


def ledger(days=10, top=10):
    """The evidence behind the light: which name supplied which revisions, and which
    window the reading was taken from.

    READ OFF THE SNAPSHOT LOG, not off a fresh pull. Every figure this factor's light
    is computed from already rides in the day's own `extras` (per-ticker up/down counts
    for both windows), so the ledger is a RE-SHAPE of the record rather than a
    re-derivation of it. That is the strongest form of the guarantee the ledgers table
    exists to give: premium_share's ledger can disagree with its recorded light because
    it re-prices old volumes at today's list, and this one cannot disagree at all --
    it is reading the same numbers the light was decided on. It also costs nothing:
    no yfinance round-trip, on the panel or in the scheduler's daily capture.

    `top` is accepted for signature parity and ignored -- the basket is two names by
    definition (§ the docstring above), and trimming it would remove half the evidence.

    KNOWN EDGE, for the troubleshooting pass: this factor is not `asof_keyed`, so its
    SNAPSHOT is last-run-wins on the ET date while `store.record_ledger` keeps the
    FIRST capture of a date. A same-day re-run that lands different counts would leave
    the two disagreeing with no marker, because `basis` reads 'recorded' either way.
    Aligning them means deciding which capture the day owns -- the same question
    `keep_first` answers for the asof-keyed factors."""
    out = []
    for day in store.history_payloads("memory_canary", days):
        ex = day.get("extras") or {}
        per = ex.get("per_ticker") or {}
        if not per:
            continue            # a row from before the per-ticker extras existed
        up7 = sum(t.get("up7", 0) for t in per.values())
        down7 = sum(t.get("down7", 0) for t in per.values())
        up30 = sum(t.get("up30", 0) for t in per.values())
        down30 = sum(t.get("down30", 0) for t in per.values())

        # The window the light was actually taken on is the STORED one; the rule is
        # re-run only to fill it in for a row that predates the field. Recomputing it
        # would let a later change to the rule silently rewrite what a past light says
        # about itself.
        window = ex.get("window") or _select_window(up7, down7, up30, down30)[0]
        wins = [_window_row("7d", "last 7 days", up7, down7, window == "7d"),
                _window_row("30d", "last 30 days", up30, down30, window == "30d")]
        sel = next(w for w in wins if w["used"])

        pool = sel["total"]
        names = []
        for sym in TICKERS:
            t = per.get(sym) or {}
            up = int(round(t.get("up7", 0) if window == "7d" else t.get("up30", 0)))
            down = int(round(t.get("down7", 0) if window == "7d" else t.get("down30", 0)))
            n = up + down
            share = (down / n) if n else 0.0
            alone = round(share * 5)
            nm, role = NAMES.get(sym, (sym, ""))
            names.append({
                "key": sym, "name": nm, "role": role,
                # Which estimate periods this name was counted on. Empty on a row
                # written before the horizon rule, where the answer was "all of them".
                "periods": list(t.get("periods") or []),
                "up": up, "down": down, "total": n,
                "share": round(share * 100, 1),
                # What the pooled figure would read if this name were the whole basket.
                # The point of pooling two names is that neither owns the light, and
                # this column is where you can see whether that is true today.
                "alone": alone, "alone_light": _band(alone)[0],
                # An unweighted pool is a COUNT pool: a name that files four times as
                # many revisions carries four times the weight, whatever its place in
                # the memory market.
                "weight": round(n / pool * 100, 1) if pool else 0.0,
            })

        # WHICH RULE THIS DAY WAS COUNTED UNDER. Absent means the pre-2026-08-29 rule
        # that summed all four estimate periods, so a rail day from before the change
        # says so rather than being read as if it were on today's basis.
        basis = ex.get("basis") or "all_periods"
        picks = [n["periods"] for n in names if n["periods"]]
        estimates = (" \u00b7 ".join(picks[0]) if picks and all(x == picks[0] for x in picks)
                     else ("mixed" if picks else "all four"))

        out.append({
            "date": day["date"],
            "light": day.get("light"),
            "downs": int(day["value"]) if day.get("value") is not None else None,
            "metric": day.get("metric"),
            "window": window,
            "basis_rule": basis,
            "estimates": estimates,
            "share": sel["share"],
            "pool_up": sel["up"], "pool_down": sel["down"], "pool_total": pool,
            "names": names,
            "windows": wins,
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
