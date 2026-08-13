"""The FIGURE for a scheduled economic release, from the publisher — never from search.

WHY (2026-08-13, session 44). The macro briefing asked a search-grounded model what PPI
printed. At 08:37 the crawlable copy did not exist yet -- BLS's own summary page was
still indexed under the PREVIOUS month -- so the model honestly answered "RELEASED figure
not found", and the headline then described the print as awaited for the next hour. The
figure was never hard to get. We were asking the wrong instrument: a scheduled release is
a primitive with an authoritative feed, and the model's job is prose, not lookup.

SOURCE ORDER, and it is not arbitrary -- both halves were measured at 09:32-09:40 ET on
the morning of the 2026-08-13 PPI print:

  1. BLS API (api.bls.gov)   HAD July PPI.       <- real time, the publisher itself
  2. FRED (fredgraph.csv)    still had June.     <- a MIRROR; correct, but it ingests later

FRED is not wrong, it is late: at 09:32, an hour after the 08:30 print, PPIFIS was still
on June while api.bls.gov served July. Where FRED HAS landed the values agree exactly
(CPIAUCSL == CUSR0000SA0 == 332.813), which is what makes it a safe fallback rather than
a second opinion. It also lags in VINTAGE, not just timing: FRED's June PPI read 156.566
where BLS now reads 156.607, and BLS footnotes every value "Preliminary -- subject to
monthly revisions up to four months after original publication." Store the vintage.

NOTE api.bls.gov is a DIFFERENT HOST from www.bls.gov, which returns 403 to non-browser
fetches. The website being closed says nothing about the API being closed.

PENDING IS NOT ZERO, AND IT IS NOT FAILURE. Three distinct outcomes, never collapsed:
    ok           the publisher has the expected period
    pending      the source answered, but its newest period predates the print
    unavailable  the fetch itself failed -- we do not know anything
Session 43 lost five paid AV calls because a failure and an empty answer returned the
same value and a card said "No news surfaced today." A briefing that says "PPI came in
flat" because a request timed out is the same bug with a bigger blast radius.

RATE LIMIT. BLS v1 is keyless at 25 queries/day/IP. One POST carries up to 25 SERIES, so
a whole release morning is ONE query -- `latest_releases()` batches deliberately for that
reason. A free registered v2 key raises the ceiling to 500/day if it is ever wanted.
Retries here are bounded at 2 and never loop; the failure mode to avoid is not the
ceiling, it is a retry storm underneath it.
"""

import argparse
import json
from datetime import date, datetime, timedelta

import requests

try:
    from engine.common import ET
except Exception:
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except Exception:
        import pytz
        ET = pytz.timezone("America/New_York")

BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_TIMEOUT = 45
BLS_ATTEMPTS = 2                      # bounded. never a loop.


# --- The releases -------------------------------------------------------------
# Every id below was VERIFIED live against both sources on 2026-08-13 before being
# written here; two would have been wrong if guessed (FRED 404s on WPSFD49104 -- core
# PPI is PPIFES there -- and on LNS14000000, which is UNRATE). Do not add a row from
# memory; probe it first.
#
# transform:
#   mom_pct     index series -> month-over-month percent (CPI/PPI/PCE/AHE/retail)
#   mom_level_k level in thousands -> the CHANGE, which is the headline (payrolls)
#   level_pp    a rate already in percent -> report the level, change in pp (unemployment)
#   level_count a count -> report the level, change vs prior period (claims)
RELEASES = {
    "cpi": {
        "label": "CPI", "agency": "BLS", "cadence": "monthly",
        "bls": "CUSR0000SA0", "fred": "CPIAUCSL", "transform": "mom_pct"},
    "core_cpi": {
        "label": "Core CPI", "agency": "BLS", "cadence": "monthly",
        "bls": "CUSR0000SA0L1E", "fred": "CPILFESL", "transform": "mom_pct"},
    "ppi": {
        "label": "PPI final demand", "agency": "BLS", "cadence": "monthly",
        "bls": "WPSFD4", "fred": "PPIFIS", "transform": "mom_pct"},
    "core_ppi": {
        "label": "Core PPI", "agency": "BLS", "cadence": "monthly",
        # FRED's PPIFES tracks the same concept but not the same vintage -- it read
        # 153.996 for June where BLS read ~154.08. Fallback only.
        "bls": "WPSFD49104", "fred": "PPIFES", "transform": "mom_pct"},
    "payrolls": {
        "label": "Nonfarm payrolls", "agency": "BLS", "cadence": "monthly",
        "bls": "CES0000000001", "fred": "PAYEMS", "transform": "mom_level_k"},
    "unemployment": {
        "label": "Unemployment rate", "agency": "BLS", "cadence": "monthly",
        "bls": "LNS14000000", "fred": "UNRATE", "transform": "level_pp"},
    "avg_hourly_earnings": {
        "label": "Average hourly earnings", "agency": "BLS", "cadence": "monthly",
        "bls": "CES0500000003", "fred": "CES0500000003", "transform": "mom_pct"},

    # Not BLS -- no real-time leg wired, so FRED is primary. Claims proved FAST on FRED
    # (today's 08:30 DOL print was already there at 09:32); PCE/GDP/retail come from
    # BEA/Census, whose own APIs are the real-time path if that is ever needed.
    "initial_claims": {
        "label": "Initial jobless claims", "agency": "DOL", "cadence": "weekly",
        "bls": None, "fred": "ICSA", "transform": "level_count"},
    "continuing_claims": {
        "label": "Continuing claims", "agency": "DOL", "cadence": "weekly",
        "bls": None, "fred": "CCSA", "transform": "level_count", "period_lag": 1},
    "pce": {
        "label": "PCE price index", "agency": "BEA", "cadence": "monthly",
        "bls": None, "fred": "PCEPI", "transform": "mom_pct"},
    "core_pce": {
        "label": "Core PCE price index", "agency": "BEA", "cadence": "monthly",
        "bls": None, "fred": "PCEPILFE", "transform": "mom_pct"},
    "retail_sales": {
        "label": "Retail sales", "agency": "Census", "cadence": "monthly",
        "bls": None, "fred": "RSAFS", "transform": "mom_pct"},
}


# --- Expected period ----------------------------------------------------------
def expected_period(name, now=None):
    """The period THIS release should be reporting if it has printed.

    Monthly releases report the PREVIOUS calendar month (July CPI prints in August).
    Weekly claims report the week ending the most recent Saturday; continuing claims
    lag one further week. Returns a `date` on the period's first day (monthly) or the
    week-ending Saturday (weekly), matching how each source keys its observations.
    """
    now = now or datetime.now(ET)
    today = now.date()
    spec = RELEASES[name]
    lag = spec.get("period_lag", 0)
    if spec["cadence"] == "monthly":
        y, m = today.year, today.month - 1 - lag
        while m < 1:
            y, m = y - 1, m + 12
        return date(y, m, 1)
    # weekly: most recent Saturday strictly before today, minus any extra lag
    sat = today - timedelta(days=(today.weekday() + 2) % 7)
    if sat >= today:
        sat -= timedelta(days=7)
    return sat - timedelta(weeks=lag)


# --- Sources ------------------------------------------------------------------
def _bls_batch(series_ids, year=None):
    """One POST for many series. -> {sid: [obs newest-first]} or raises.

    Batching is the rate-limit strategy: 25 series per query against a 25-query day
    means an entire release morning costs one of them.
    """
    if not series_ids:
        return {}
    year = year or datetime.now(ET).year
    payload = {"seriesid": list(series_ids),
               "startyear": str(year - 1), "endyear": str(year)}
    last = None
    for attempt in range(BLS_ATTEMPTS):
        try:
            r = requests.post(BLS_URL, json=payload, timeout=BLS_TIMEOUT)
            r.raise_for_status()
            d = r.json()
            if d.get("status") != "REQUEST_SUCCEEDED":
                # Includes the daily-threshold refusal. A refusal is UNAVAILABLE, and
                # must never reach a caller as "no data for this period".
                raise RuntimeError(f"BLS refused: {d.get('status')} {d.get('message')}")
            return {s["seriesID"]: s.get("data", [])
                    for s in d.get("Results", {}).get("series", [])}
        except Exception as e:
            last = e
    raise RuntimeError(f"BLS failed after {BLS_ATTEMPTS} attempts: {last}")


def _fred(sid):
    try:
        from stoplight.sources.fred import fred_series
    except Exception:
        # Keeps this module runnable standalone (and from the CLI) without the
        # stoplight package on the path.
        import io
        import pandas as pd
        r = requests.get(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", sid]
        df["date"] = pd.to_datetime(df["date"])
        df[sid] = pd.to_numeric(df[sid], errors="coerce")
        return df.set_index("date")[sid].dropna()
    return fred_series(sid)


def _bls_period_date(obs):
    """BLS {'year':'2026','period':'M07'} -> date(2026, 7, 1)."""
    p = obs.get("period", "")
    if not p.startswith("M"):
        return None
    return date(int(obs["year"]), int(p[1:]), 1)


# --- Presentation -------------------------------------------------------------
def _derive(transform, value, previous):
    """-> (change, unit, display). `display` is rounded the way the agency prints it."""
    if previous is None:
        return None, None, None
    if transform == "mom_pct":
        chg = (value - previous) / previous * 100.0
        shown = round(chg, 1) + 0.0        # kills a displayed "-0.0"
        # A raw -0.028% rounds to zero, and "+0.0%" would put a plus sign on a negative
        # reading. The agencies call that "unchanged"; so do we, with no sign at all.
        disp = "0.0% m/m (unchanged)" if shown == 0 else f"{shown:+.1f}% m/m"
        return chg, "pct_mom", disp
    if transform == "mom_level_k":
        chg = value - previous
        return chg, "thousands_change", f"{chg:+,.0f}K"
    if transform == "level_pp":
        return value - previous, "pp_change", f"{value:.1f}% ({value - previous:+.1f}pp)"
    if transform == "level_count":
        return value - previous, "count_change", f"{value:,.0f} ({value - previous:+,.0f})"
    return None, None, None


def latest_releases(names=None, now=None):
    """Fetch several releases at once. -> {name: result dict}

    BLS legs go out as ONE batched query; FRED legs are per-series. A release whose BLS
    leg is `pending` falls through to FRED, which occasionally wins (DOL claims landed
    on FRED inside the hour today) -- but a release whose BLS leg is `unavailable` also
    tries FRED, because a failed request is not evidence about the data.
    """
    now = now or datetime.now(ET)
    names = list(names or RELEASES)
    out = {}

    bls_ids = [RELEASES[n]["bls"] for n in names if RELEASES[n].get("bls")]
    bls_data, bls_error = {}, None
    if bls_ids:
        try:
            bls_data = _bls_batch(sorted(set(bls_ids)), year=now.year)
        except Exception as e:
            bls_error = str(e)

    for name in names:
        spec = RELEASES[name]
        want = expected_period(name, now)
        res = {
            "name": name, "label": spec["label"], "agency": spec["agency"],
            "expected_period": want.isoformat(), "status": "unavailable",
            "source": None, "period": None, "value": None, "previous": None,
            "change": None, "change_unit": None, "display": None,
            "preliminary": None, "note": None,
            "fetched_at": now.isoformat(),
        }

        # 1. the publisher
        sid = spec.get("bls")
        if sid:
            obs = bls_data.get(sid)
            if obs:
                got = _bls_period_date(obs[0])
                if got and got >= want:
                    val = float(obs[0]["value"])
                    prev = float(obs[1]["value"]) if len(obs) > 1 else None
                    chg, unit, disp = _derive(spec["transform"], val, prev)
                    res.update({
                        "status": "ok", "source": "BLS", "period": got.isoformat(),
                        "value": val, "previous": prev, "change": chg,
                        "change_unit": unit, "display": disp,
                        "preliminary": any(f.get("code") == "P"
                                           for f in obs[0].get("footnotes", [])
                                           if isinstance(f, dict)),
                    })
                    out[name] = res
                    continue
                res.update({"status": "pending", "source": "BLS",
                            "note": f"BLS newest is {got}, expected {want}"})
            elif bls_error:
                res["note"] = f"BLS unavailable: {bls_error}"
            else:
                res.update({"status": "pending",
                            "note": "BLS returned no observations"})

        # 2. the mirror -- tried whether the publisher was pending OR unavailable
        fid = spec.get("fred")
        if fid:
            try:
                s = _fred(fid)
                got = s.index[-1].date()
                if got >= want:
                    val = float(s.iloc[-1])
                    prev = float(s.iloc[-2]) if len(s) > 1 else None
                    chg, unit, disp = _derive(spec["transform"], val, prev)
                    res.update({
                        "status": "ok", "source": "FRED", "period": got.isoformat(),
                        "value": val, "previous": prev, "change": chg,
                        "change_unit": unit, "display": disp,
                        "note": (res.get("note") or None),
                    })
                else:
                    if res["status"] != "pending":
                        res["status"] = "pending"
                    res["note"] = ((res.get("note") + "; ") if res.get("note") else "") \
                        + f"FRED newest is {got}, expected {want}"
            except Exception as e:
                res["note"] = ((res.get("note") + "; ") if res.get("note") else "") \
                    + f"FRED unavailable: {type(e).__name__}"

        out[name] = res
    return out


def latest_release(name, now=None):
    return latest_releases([name], now=now)[name]


def format_for_prompt(results, include_unpublished=False):
    """The released-figures block for the briefing prompt.

    ONLY `ok` ROWS ARE ASSERTED, and that is a correctness decision rather than
    brevity. `pending` is ambiguous in a way this module cannot resolve: with no
    release calendar it cannot tell "this printed at 08:30 and our sources are behind"
    from "this is not due for another fortnight". Both look identical here -- PCE and
    retail sales sit pending every single day of the month. Telling the model a pending
    release's "figure is not yet in hand" would be false for the second case, and
    inventing a schedule to disambiguate would be exactly the kind of guess this module
    was built to remove.

    So the division of labour is: Python asserts the figures it actually holds; the
    MODEL owns what is scheduled today, which it can see and we cannot. Pending and
    unavailable rows stay in the returned dict -- accurate structured state for the
    dashboard -- and simply are not claimed in the prompt. `include_unpublished=True`
    for a caller that does know the day's schedule.
    """
    if not results:
        return None
    ok = [r for r in results.values() if r["status"] == "ok"]
    lines = []
    for r in ok:
        prelim = " (preliminary)" if r.get("preliminary") else ""
        lines.append(f"  {r['label']} [{r['period']}]: {r['display']} "
                     f"-- from {r['source']}{prelim}")
    if include_unpublished:
        for r in results.values():
            if r["status"] == "pending":
                lines.append(f"  {r['label']}: printed but NOT YET IN HAND "
                             f"(expected period {r['expected_period']})")
            elif r["status"] == "unavailable":
                lines.append(f"  {r['label']}: SOURCE UNAVAILABLE - we do not know")
    if not lines:
        return None
    return (
        "RELEASED FIGURES (retrieved from the publishing agency, not from search):\n"
        + "\n".join(lines) +
        "\nUse these numbers verbatim; do not substitute a figure found elsewhere and do "
        "not compute your own. Every release listed above HAS PRINTED - never describe "
        "one as awaited or upcoming. This list is NOT the day's schedule: a release "
        "scheduled today may be absent from it, and absence says nothing either way - "
        "judge those yourself. Expectations/consensus are NOT given here; if you state "
        "one it must come from your own sources and be attributed as such."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull scheduled release figures.")
    ap.add_argument("names", nargs="*", help=f"any of: {', '.join(RELEASES)}")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    res = latest_releases(args.names or None)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{'release':<24} {'status':<12} {'src':<6} {'period':<12} figure")
        print("-" * 78)
        for r in res.values():
            print(f"{r['label']:<24} {r['status']:<12} {(r['source'] or '-'):<6} "
                  f"{(r['period'] or '-'):<12} {r['display'] or (r['note'] or '')}")
        print()
        print(format_for_prompt(res))
