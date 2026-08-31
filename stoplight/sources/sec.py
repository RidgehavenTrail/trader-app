"""
SEC XBRL — as-reported quarterly financials, from the filings themselves.

WHY THIS EXISTS (2026-08-30, user's call). capex_pressure read `yfinance`'s
quarterly cashflow on every poll and accepted whatever window it happened to serve.
A vendor window is not a record, and this one was ragged in three separate ways,
all measured:

  MSFT  7 quarters   GOOGL 5   AMZN 6   META 6   ORCL 6

  1. The factor's DOCUMENTED primary arrow basis — TTM against the year-ago TTM —
     needs 8 quarters and could therefore never fire for any name. Every one of the
     43 stored readings was on the FY fallback the docstring calls occasional.
  2. AMZN's newest column was 2026-03-31 while everyone else had 2026-06-30, so its
     TTM was a quarter behind the basket it was being read against — and the board
     stamped the basket's `max()` asof over it.
  3. META's frame was missing 2025-03-31 from the middle. Today's slice happens to
     be contiguous; a deeper one would have summed straight across the hole.

Capex and operating cash flow for a CLOSED quarter are immutable facts. Re-asking a
vendor for them every poll, and taking whatever it has this week, is the mistake
`PINNED_CAPEX_PRIORS` and heavy_haul's fixed base date already record in two other
places in this repo. So we take them from the filings and keep them.

WHAT SEC SERVES. `data.sec.gov/api/xbrl/companyconcept` returns every fact a company
has filed for one concept, each with its own period, form, accession and filing date.
Most quarters arrive as DISCRETE 3-month facts (MSFT: 76 of them for operating cash
flow); the rest are cumulative year-to-date durations, because a 10-Q reports YTD and
no 10-Q is filed for Q4. Both are handled below.

NO API KEY, NO ACCOUNT, NO CHARGE. `data.sec.gov` serves this endpoint to any
declared User-Agent — verified 2026-08-30, a plain descriptive string returns 200.
(`www.sec.gov`, which hosts the ticker->CIK file, is stricter and wants an email in
the UA; we do not use that host, and the CIKs below are constants verified against
the submissions endpoint instead. Set SEC_USER_AGENT to add your own contact if you
would rather declare one — SEC's fair-access policy asks for it, and this default
declares what the tool is without carrying anybody's address into a request header.)
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

_UA = os.environ.get("SEC_USER_AGENT") or "trader-app stoplight research tool"
_BASE = "https://data.sec.gov"

# Verified 2026-08-30 against /submissions/CIK<cik>.json — each one's `tickers` list
# contains the symbol below. `verify_ciks()` re-runs that check; it is cheap and it is
# the only thing standing between a transposed digit and a silently wrong company.
CIKS = {"MSFT": "0000789019", "GOOGL": "0001652044", "AMZN": "0001018724",
        "META": "0001326801", "ORCL": "0001341439"}

# Tag preference per concept, IN ORDER — the first one a company actually files wins.
# Measured 2026-08-30, not assumed: four of the five file capex as
# PaymentsToAcquirePropertyPlantAndEquipment, and AMZN files
# PaymentsToAcquireProductiveAssets (its PP&E tag has no fact newer than 2017). A
# company that files neither raises rather than silently reporting a zero.
TAGS = {
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    # OPTIONAL third leg. The hyperscalers headline capex "including finance leases",
    # and what they mean by it -- META says so in as many words -- is the PRINCIPAL
    # PAYMENTS on those leases: a cash outflow that buys the same steel and silicon as
    # a purchase does, booked under financing instead of investing. Not the ROU-asset
    # tag, which is a non-cash addition and a different quantity.
    "fin_lease": ["FinanceLeasePrincipalPayments"],
}

_QUARTER_DAYS = (80, 100)      # a "3-month" duration, allowing for 13-week calendars


def _get(url, tries=3):
    """GET with SEC's declared User-Agent and a short backoff.

    SEC asks for no more than 10 requests a second; this module makes ten calls on a
    full refresh, once a day at most, so the politeness that matters is the UA rather
    than the rate. 404 is returned as None because "this company does not file that
    tag" is an ANSWER — it is how the capex tag preference above resolves — while any
    other error is raised."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept-Encoding": "gzip"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                # urllib does NOT decompress for you — asking for gzip and then
                # decoding as utf-8 gets you 0x8b in position 1. Worth asking for:
                # a companyconcept payload is a few hundred KB of JSON and these
                # are ten calls a refresh.
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def verify_ciks(symbols=None):
    """Re-prove every CIK constant against SEC's own submissions record.

    -> {sym: {"cik", "name", "ok"}}. `ok` is whether SEC lists this symbol among that
    CIK's tickers. Kept as a callable check rather than a comment, because a constant
    that was right when it was written is not the same thing as a constant that is
    right now."""
    out = {}
    for sym in (symbols or CIKS):
        cik = CIKS[sym]
        sub = _get(f"{_BASE}/submissions/CIK{cik}.json") or {}
        out[sym] = {"cik": cik, "name": sub.get("name") or sub.get("entityName"),
                    "ok": sym in (sub.get("tickers") or [])}
    return out


def _concepts(cik, tags):
    """EVERY tag the company files for this concept -> [(tag, [USD facts])], the one
    with the most recent coverage last. Raises if none.

    Not "the first tag with any facts" — that was wrong, and measurably so. AMZN files
    BOTH capex tags, so first-wins picked PaymentsToAcquirePropertyPlantAndEquipment
    and stopped its history at 2017-03-31, silently losing nine years including every
    quarter this factor reads. The two are a SWITCH, not a rivalry: PP&E covers
    2008-06-30 -> 2017-03-31 and ProductiveAssets 2017-09-30 -> 2026-06-30, with ZERO
    overlapping periods (measured 2026-08-30), so merging them is lossless and keeps
    the full history. Each row records the tag it came from.

    Ordering by newest coverage sets the tie-break for a company that DOES file two
    overlapping tags: the one still in use wins. There is no such case in this basket
    today, which is exactly why the rule is written down rather than left to whichever
    order the list happened to be in."""
    out = []
    for tag in tags:
        d = _get(f"{_BASE}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json")
        facts = (d or {}).get("units", {}).get("USD") or []
        if facts:
            out.append((tag, facts, max(f["end"] for f in facts)))
    if not out:
        raise ValueError(f"CIK {cik}: none of {tags} filed")
    out.sort(key=lambda t: t[2])
    return [(tag, facts) for tag, facts, _ in out]


def _dedupe(facts):
    """One fact per (start, end). A period is re-reported in every later filing that
    carries it as a comparative, so duplicates are the NORM and almost always carry an
    identical value.

    Where the values DIFFER the company restated, and the LATEST filing wins — a
    restatement is a correction, and the lesson from infra_backlog's snapshot collapse
    is that the right tie-break follows from WHY two records disagree: keep the earlier
    for a re-pricing, the later for a correction. The superseded value is kept on the
    row as `restated_from` rather than dropped, so a correction is visible instead of
    silent."""
    best = {}
    for f in facts:
        key = (f["start"], f["end"])
        cur = best.get(key)
        if cur is None or (f.get("filed") or "") > (cur.get("filed") or ""):
            if cur is not None and cur["val"] != f["val"]:
                f = dict(f, restated_from=cur["val"])
            elif cur is not None and cur.get("restated_from") is not None:
                f = dict(f, restated_from=cur["restated_from"])
            best[key] = f
        elif cur["val"] != f["val"] and cur.get("restated_from") is None:
            best[key] = dict(cur, restated_from=f["val"])
    return list(best.values())


def _months(f):
    return (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days


def quarterly(cik, concept):
    """Discrete 3-month values for one concept -> {period_end: row}, newest last.

    Two sources, and each row says which produced it:

      FILED    — the company filed a 3-month fact for that period. Preferred, because
                 it is the number as reported rather than a number we computed.
      DERIVED  — differenced out of the cumulative year-to-date facts that share a
                 fiscal-year `start`: quarter_n = YTD(end_n) - YTD(end_(n-1)). This is
                 what recovers Q4, which no 10-Q reports (MSFT FY2026: the 10-K's
                 12-month 182,935 less the Q3 10-Q's 9-month 127,494 = 55,441).

    Deriving only ever fills a gap; a filed fact is never overwritten by a computed
    one. Where both exist they agree, and `cross_check()` is what proves it rather
    than this docstring."""
    rows = {}
    # Tags in order of coverage, newest-covering LAST, so a later tag's row overwrites
    # an earlier one's on any period both claim (see _concepts).
    for tag, raw in _concepts(cik, TAGS[concept]):
        facts = _dedupe(raw)
        for f in facts:                                # filed 3-month facts first
            if _QUARTER_DAYS[0] <= _months(f) <= _QUARTER_DAYS[1]:
                rows[f["end"]] = {"period_start": f["start"], "period_end": f["end"],
                                  "val": float(f["val"]), "basis": "filed",
                                  "tag": tag, "form": f.get("form"),
                                  "accn": f.get("accn"), "filed": f.get("filed"),
                                  "fy": f.get("fy"), "fp": f.get("fp"),
                                  "restated_from": f.get("restated_from")}

        by_start = {}
        for f in facts:
            by_start.setdefault(f["start"], []).append(f)
        for start, group in by_start.items():
            group.sort(key=lambda x: x["end"])
            prev = None
            for f in group:
                if prev is not None:
                    # (prev.end, f.end] — the slice this filing added to the year to date.
                    pstart = (date.fromisoformat(prev["end"])
                              + timedelta(days=1)).isoformat()
                    val = float(f["val"]) - float(prev["val"])
                else:
                    pstart, val = f["start"], float(f["val"])
                if not (_QUARTER_DAYS[0] <= (date.fromisoformat(f["end"])
                                             - date.fromisoformat(pstart)).days
                        <= _QUARTER_DAYS[1]):
                    prev = f                          # not a quarter-shaped slice
                    continue
                rows.setdefault(f["end"], {
                    "period_start": pstart, "period_end": f["end"], "val": val,
                    "basis": "derived", "tag": tag, "form": f.get("form"),
                    "accn": f.get("accn"), "filed": f.get("filed"),
                    "fy": f.get("fy"), "fp": f.get("fp"), "restated_from": None})
                prev = f
    return dict(sorted(rows.items()))


def quarters(sym):
    """The concepts for one symbol, joined on the period -> [row], oldest first.

    A period is emitted only when BOTH the cash-flow and capex legs have it. A ratio
    needs a numerator and a denominator from the same period, and half a quarter is not
    a usable record — it would sit in the store looking like data and divide into
    nothing.

    FINANCE LEASES ARE OPTIONAL and never gate a row: a company that does not file the
    tag keeps all of its capex quarters and reports `fin_lease_filed: False`, so the
    caller can tell "no leases" from "not disclosed" instead of reading a zero as
    either."""
    cik = CIKS[sym]
    ocf = quarterly(cik, "ocf")
    cap = quarterly(cik, "capex")
    try:
        lease = quarterly(cik, "fin_lease")
    except ValueError:
        lease = {}
    out = []
    for end in sorted(set(ocf) & set(cap)):
        o, c = ocf[end], cap[end]
        fl = lease.get(end)
        out.append({
            "symbol": sym, "period_end": end, "period_start": o["period_start"],
            "ocf": o["val"], "capex": abs(c["val"]),
            "fin_lease": abs(fl["val"]) if fl else 0.0,
            "fin_lease_filed": bool(fl),
            "ocf_basis": o["basis"], "capex_basis": c["basis"],
            "ocf_tag": o["tag"], "capex_tag": c["tag"],
            "form": o.get("form"), "accn": o.get("accn"), "filed": o.get("filed"),
            "fy": o.get("fy"), "fp": o.get("fp"),
            "restated": bool(o.get("restated_from") or c.get("restated_from")),
        })
    return out


def cross_check(sym, tol_pct=0.5):
    """Compare this module's quarters against yfinance's on the periods BOTH have.

    The migration's proof, and the reason it is a function rather than a paragraph:
    the whole claim is that SEC is the better record, and a claim like that should be
    checkable on demand rather than asserted once in a commit message. Returns
    [{period_end, sec_*, yf_*, agree}] — `agree` within tol_pct on both legs."""
    import yfinance as yf

    cf = yf.Ticker(sym).quarterly_cashflow
    ocf_row = [r for r in cf.index if "Operating Cash Flow" in r]
    cap_row = [r for r in cf.index if "Capital Expenditure" in r]
    yfq = {}
    if ocf_row and cap_row:
        for col in cf.columns:
            try:
                yfq[col.date().isoformat()] = (float(cf.loc[ocf_row[0]][col]),
                                               abs(float(cf.loc[cap_row[0]][col])))
            except (TypeError, ValueError):
                continue

    def near(a, b):
        return b == b and b and abs(a - b) / abs(b) * 100 <= tol_pct   # b==b: not NaN

    out = []
    for r in quarters(sym):
        y = yfq.get(r["period_end"])
        if not y:
            continue
        # A yfinance COLUMN with a NaN in it is not a disagreement — it is a hole, and
        # calling it a mismatch would count the vendor's own gaps against the source
        # replacing it. Measured 2026-08-30: five of the thirty overlapping quarters
        # are NaN on the yfinance side (MSFT 2024-12-31 and 2025-03-31, AMZN and META
        # 2024-12-31, ORCL 2025-02-28) and SEC has a real filed or derived number for
        # every one of them. Reported as its own verdict so the summary can say so.
        missing = not (y[0] == y[0] and y[1] == y[1])
        out.append({"period_end": r["period_end"],
                    "sec_ocf": r["ocf"], "yf_ocf": y[0],
                    "sec_capex": r["capex"], "yf_capex": y[1],
                    "basis": r["ocf_basis"] + "/" + r["capex_basis"],
                    "verdict": "yf_missing" if missing
                    else "agree" if (near(r["ocf"], y[0]) and near(r["capex"], y[1]))
                    else "differ"})
    return out
