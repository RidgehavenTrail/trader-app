"""A second, quota-free news source: Yahoo's per-ticker RSS headline feed.

WHY (2026-08-13, session 44). AVEX reported Q2 after the close on 08-12 and the card
said the results were unknown. That was not a pipeline fault -- ONE AV call dumping the
raw feed showed 10 articles total, 1 of them fresh, and it was a content-mill summary
of the 10-Q. AV never carried the earnings at all. AVEX IPO'd in April, and Alpha
Vantage's corpus for a four-month-old micro-cap is close to empty.

Yahoo's RSS feed for the same ticker, same moment, carried the company's OWN release --
"AEVEX Corp. Announces Financial Results for Second Quarter 2026", timestamped 16:01,
one minute after the close AV's freshness window opens.

Measured across the 31-name watchlist: 566 items, 200 fresh, ~6.5 fresh per ticker,
zero fresh on six genuinely quiet staples. Free, no key, no quota.

THIS IS A SUPPLEMENT, NOT A REPLACEMENT, and the reason is precision. AV supplies
`ticker_sentiment` -- a per-ticker relevance score and the list of co-tagged names --
which is what the ranking layer sorts on and what the shared-coverage penalty needs.
Yahoo RSS supplies neither, and it is noticeably less ticker-precise: measured live, it
filed "The Sharpest Exchanges From ABBV's Earnings Call" under PFE, "Telephone And Data
Systems (TDS) Reports Strong Q2 Profit" under VZ, and served one Cerebras piece to
MRVL, INTC and AMD alike.

So relevance for an RSS item is DERIVED from what is observable -- whether the headline
names the company, whether it leads with it, whether it reads as the company's own
announcement -- rather than defaulted to a constant. A constant is a silent thumb on the
scale in whichever direction it is set: too low and these items never surface, too high
and the less precise population outranks the more precise one.

The derived score is deliberately arranged so the engine's EXISTING `relevance < 0.5`
gate does the rejecting. An item whose headline never names us scores 0.35 and is
dropped by a filter that already exists -- no special case, no new branch.

MATCH ON THE COMPANY NAME, NOT ONLY THE TICKER. The headline that started all this says
"AEVEX Corp."; the ticker is AVEX. Ticker-only matching would have scored the one
article we were chasing at 0.35 and thrown it away.
"""

import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone

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

YAHOO_RSS = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
             "?s={ticker}&region=US&lang=en-US")
RSS_TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Derived-relevance rungs. Tuned so the engine's existing 0.5 gate rejects the
# not-about-us rung and nothing else needs to change.
REL_OWN_RELEASE = 1.00      # leads AND reads as the company's own announcement
REL_LEADS = 0.95            # headline opens with the company/ticker
REL_NAMED = 0.80            # named somewhere in the headline
REL_UNNAMED = 0.35          # never named -> below the gate -> dropped

# The verbs a company uses about itself. "AEVEX Corp. ANNOUNCES Financial Results"
# is a press release; "Aevex Remains Well Positioned ... RBC Says" is commentary.
ANNOUNCE_RE = re.compile(
    r"\b(announces?|announced|reports?|reported|posts?|declares?|provides?|"
    r"completes?|closes?|prices?|appoints?|names?|to acquire|acquires?|"
    r"launches?|awards?|secures?|receives?)\b", re.I)

# Stripped when turning a display name into match tokens.
_SUFFIXES = re.compile(
    r"\b(corp|corporation|inc|incorporated|co|company|companies|holdings?|"
    r"group|plc|ltd|limited|sa|nv|ag|class\s+[abc]|common\s+stock|"
    r"the|and|&)\b\.?", re.I)


def company_aliases(ticker, display_name=None):
    """Lowercase tokens a headline might use for this company.

    Always includes the ticker. A display name contributes its cleaned form and its
    leading word, which is what headlines actually use -- "Kraft Heinz Co" gives both
    "kraft heinz" and "kraft"; "AEVEX Corp." gives "aevex".
    """
    out = {str(ticker).lower()}
    if display_name:
        cleaned = _SUFFIXES.sub(" ", str(display_name))
        cleaned = re.sub(r"[^\w\s&-]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        if len(cleaned) >= 3:
            out.add(cleaned)
            first = cleaned.split(" ")[0]
            if len(first) >= 3:
                out.add(first)
    return sorted(out, key=len, reverse=True)


def _match(title, aliases):
    """(named, leads) for the first alias that hits."""
    named = leads = False
    for a in aliases:
        pat = re.escape(a)
        if re.search(rf"(?<![\w]){pat}(?![\w])", title, re.I):
            named = True
            if re.match(rf"^\W*{pat}(?![\w])", title, re.I):
                leads = True
                break
    return named, leads


def derive_relevance(title, ticker, aliases=None):
    """-> (relevance, named, leads). Observable features only; nothing invented."""
    aliases = aliases or company_aliases(ticker)
    named, leads = _match(title or "", aliases)
    if not named:
        return REL_UNNAMED, False, False
    if leads and ANNOUNCE_RE.search(title or ""):
        return REL_OWN_RELEASE, True, True
    if leads:
        return REL_LEADS, True, True
    return REL_NAMED, True, False


def _parse_pubdate(raw):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        except (ValueError, TypeError):
            continue
    return None


def fetch_yahoo_rss(ticker, timeout=RSS_TIMEOUT):
    """[{title, published(ET-aware), publisher, link, source}], newest first.

    Returns [] on any failure. A second source must never be able to break the pull it
    is supplementing -- the same rule the derived-context builders follow.
    """
    try:
        r = requests.get(YAHOO_RSS.format(ticker=ticker), headers=UA, timeout=timeout)
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
    except Exception as e:
        print(f"[NEWS RSS] {ticker}: feed unavailable ({type(e).__name__}) — "
              f"continuing on Alpha Vantage alone")
        return []

    items = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        pub = _parse_pubdate((node.findtext("pubDate") or "").strip())
        items.append({
            "title": title,
            "published": pub.astimezone(ET) if pub else None,
            # Yahoo's headline feed usually omits <source>; absence is normal, and
            # nothing downstream may depend on having a publisher.
            "publisher": (node.findtext("source") or "").strip() or None,
            "link": (node.findtext("link") or "").strip(),
            "source": "yahoo_rss",
        })
    return items


# CORROBORATION lives in the ENGINE's existing dedupe pass, not here. That pass
# already collapsed reprints (it had to -- one DDOG story once took two of three
# slots); it now counts distinct sources instead of silently discarding the copy.
# A second implementation in this module would be a competing mechanism over the
# same data, which is how dead code gets made.
