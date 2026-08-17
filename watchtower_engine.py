import time
import json
import os
import re
import argparse
from dotenv import load_dotenv
# Load the .env sitting next to THIS script, not one relative to the launch cwd.
# A bare load_dotenv() keys off the current working directory, so launching the
# engine from anywhere but the project root silently loses ALL config (API keys,
# NEWSLETTER_PDF_DIR, etc.) with no error — every newsletter endpoint just returns
# 'not_configured'/empty. Anchoring to __file__ makes the launch location irrelevant.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import yfinance as yf
from volume_indicator import compute_volume_ratio, volume_check_slot, VOLUME_TRIGGER_MULTIPLE
from turtle_indicator import compute_turtle_snapshot, snapshot_from_series, turtle_signal_metrics, detect_breakout
import threading
import requests
from collections import deque
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# TICKERS_FILE / DATA_FILE moved to engine/common.py (split phase 4).
ACTIONABLE_FILE = 'actionable_moves.json'
ACTIONABLE_META_FILE = 'actionable_moves_meta.json'  # trading date the live set belongs to
ARCHIVE_DIR = 'archive'
NEWS_CACHE_FILE = 'news_cache.json'

# How many articles Alpha Vantage returns per call. Per-RESPONSE, not per-request —
# raising it does not consume extra quota, and the 3-headline cap in
# fetch_latest_news() means it does not widen the Claude prompt either.
NEWS_FETCH_LIMIT = 50

# --- News freshness -----------------------------------------------------------
# Nothing published before this can explain TODAY's move -- it was already in the
# price. Cutoff = 16:00 ET on the PRIOR TRADING DAY (user, 2026-08-11), so a Monday
# reaches back to Friday's close and the whole weekend is covered.
#
# Measured on ARM the morning of 2026-08-11: of 50 articles Alpha Vantage returned,
# ZERO were from that day and only two from the day before -- both published before
# the close. The rest ran back to July 20, and the ranker's top three were all from
# Aug 7. The model was being asked to explain a -5.21% move with four-day-old bullish
# commentary; the tepid write-up was structurally guaranteed.
#
# When nothing survives, fetch_latest_news returns None and the caller falls through
# to search_and_synthesize_fallback -- a LIVE web search, which is the right answer to
# "why is this down 5% today". That path REPLACES the normal synthesis rather than
# adding to it, so this costs no extra Claude calls.
NEWS_CUTOFF_HOUR_ET = 16

# time_published comes back as YYYYMMDDTHHMMSS with no zone marker. Treated as ET by
# the user's ruling. If it is really UTC this reads articles as NEWER than they are,
# which is the SAFE direction to be wrong in -- it admits a stale article rather than
# discarding a fresh one.
NEWS_TIME_FMT = "%Y%m%dT%H%M%S"

# The 1-sigma expected move is read off the ATM put of the nearest expiration that
# is MORE than this many CALENDAR days out. Strictly greater, so 7 means the chain
# used is 8+ DTE. Raise it to tighten the trigger further, lower it to loosen.
MIN_DTE_CALENDAR_DAYS = 7

# The weak-synthesis re-scan (WEAK_SYNTH_RE / WEAK_RESYNTH_DELAY_SECONDS /
# _is_weak_synthesis / _maybe_schedule_rescan) was RETIRED 2026-08-11, superseded
# by the T+30 / 15:00 schedule above. It retried on the CONTENT of a narrative;
# the schedule retries on TIME, which is the real variable -- the news cycle had
# not caught up yet. Retrying a stale feed just re-chewed the same articles
# (observed: ARM 2026-08-11, an identical narrative for one AV and two haiku calls).

# REMOVED 2026-08-11: there was a RESCAN_MIN_MOVE_PCT = 3.0 gate here, requiring a
# move of at least 3% before a weak synthesis earned a re-scan. It was wrong in kind.
#
# An ABSOLUTE percentage is the wrong unit for a system whose trigger is already
# volatility-normalised. A card only exists because the move exceeded that ticker's
# OWN option-implied expected move -- MO's bar is 1.60%, MU's is far wider. So by the
# time there is a card, the move is significant FOR THAT NAME, and a flat 3% just
# re-filters it on a cruder basis: a 3.5% move in MO passes while a genuinely notable
# MU move might not (user, 2026-08-11). The 8+ DTE floor already raised the bar in the
# right units.
#
# Cost of removing it: re-scans go from ~3.3/day back to ~7/day. Accepted deliberately
# -- "I would prefer to capture any news, rather than none at all" (user). If per-name
# tuning is ever wanted, it belongs on the TRIGGER as a per-ticker factor, not as a
# global threshold on the synthesis.

# --- Materiality ranking ------------------------------------------------------
# Alpha Vantage's relevance_score answers "is this article ABOUT this company",
# which is not the same question as "could this have moved the stock". A Form 144
# post scores maximally relevant -- it is exclusively about that company -- and
# explains nothing. Large caps with active 10b5-1 plans generate those daily, so
# they dominate the feed by volume and won on recency alone.
#
# Weight is applied on top of relevance to ORDER the candidates. Nothing is
# excluded: a demoted item still gets picked when the pool is thin, because a
# filing is genuinely useful in the absence of anything else (user, 2026-08-10).
#
# DILUTION IS NOT DEMOTED. A shelf, an ATM programme or a convertible is a filing
# and a real cause of a real decline. Only ROUTINE INSIDER SALES and backward-
# looking 13F position changes are pushed down. Insider BUYING is left alone --
# a CEO buying stock is a signal, not noise.
MATERIALITY_RULES = [
    # NOTE: bare "forecast" is deliberately absent. It matched "Lam Research
    # Corporation (LRCX) Stock forecasts" -- an SEO price-forecast page -- and
    # promoted it to the earnings tier, where it outranked a real peer earnings
    # report. "guidance" and "outlook" already carry the concept, and a genuine
    # "Company forecasts Q3 revenue above estimates" still matches on "revenue".
    # TIGHTENED 2026-08-12. The old pattern fired on the bare nouns "earnings",
    # "revenue", "guidance", "outlook" and "EPS", which appear in almost any
    # company summary. Measured on one live 50-article AMD pool: 72% of the feed
    # reached this tier while only 6% carried an earnings word in the TITLE, and
    # NONE of the 36 described an event inside the freshness window (median age of
    # the underlying report: 14 days, oldest 93). A tier that fires on 72% of a
    # pool has stopped ranking anything -- everything ties at the top and the sort
    # silently degenerates into relevance order.
    #
    # An ACTION is now required, not a noun: something must be reported, beaten,
    # missed, raised or cut. This also keeps the old anti-"forecast" property --
    # an SEO "Stock forecasts" page no longer matches, because `forecast` only
    # counts alongside a raise/cut verb.
    (4,  "earnings",      r"\b(reports?|posts?|announces?|delivers?)\b.{0,30}?"
                          r"\b(results|earnings|profit|loss|revenue)\b|"
                          r"\bearnings\b.{0,20}?\b(beat|miss|report|results|call|surprise)\b|"
                          r"\bquarterly results\b|"
                          r"\bQ[1-4]\b.{0,20}?\b(results|earnings|EPS|revenue)\b|"
                          r"\b(beats?|misses?|tops?|trails?)\b.{0,25}?"
                          r"\b(estimates?|expectations?|consensus|views?|street)\b|"
                          r"\b(raises?|lifts?|cuts?|lowers?|slashes?|reaffirms?|withdraws?)\b"
                          r".{0,20}?\b(guidance|outlook|forecast)\b"),
    (3,  "corp action",   r"acquisit|merger|to acquire|buyout|takeover|spin-?off|"
                          r"divest|tender offer|"
                          # a divestiture is often phrased as a sale of a business,
                          # not with the word "divest"
                          r"sells? .{0,30}?\b(division|unit|business|segment|assets)\b"),
    # WIDENED 2026-08-17. The pattern only knew the LATE stages of a regulatory story --
    # the lawsuit, the subpoena, the settlement. It had no word for the stage that moves
    # a stock first: a regulator taking an interest. SNAP 08-17 is the worked case --
    # "Snap (SNAP) Faces Fresh Youth Safety Scrutiny As Valuation Questions Grow" scored
    # (0, 'general'), the DEFAULT, meaning no rule matched rather than judged immaterial.
    # That zero made n_catalyst 0, which invited the macro tier in at 1, which then took
    # PRIMARY and blocked the last-resort aboutness promotion -- so the card reported "no
    # company-specific catalyst" while holding one. Rephrase the same event as
    # "investigation" or "lawsuit" and it already scored 3.
    #
    # `scrutiny` is the discriminating word; `safety` alone is NOT added -- it appears in
    # ordinary product marketing and would drag noise into the top catalyst tier. The
    # agency names are included because a headline often names the regulator instead of
    # the action ("FTC opens...", "state AGs press...").
    (3,  "regulatory",    r"\bFDA\b|approval|lawsuit|court|ruling|verdict|investigat|"
                          r"subpoena|recall|antitrust|settlement|probe|"
                          r"scrutin|regulator|regulatory|oversight|"
                          r"\bFTC\b|\bSEC\b|\bDOJ\b|\bCFPB\b|attorneys? general|"
                          r"\bsues?\b|sued|complaint|consent decree|"
                          r"congressional|senate|hearing"),
    (3,  "dilution",      r"public offering|shelf registration|convertible|"
                          r"at-the-market|dilut|secondary offering|prices? .*notes"),
    # business ABOVE analyst (user, 2026-08-10): a contract win or a product launch
    # is a real catalyst in a way a price-target tweak is not.
    (2,  "business",      r"contract|partnership|launch|unveil|collaborat|deal with"),
    # WIDENED 2026-08-12: a preferred/conviction/focus-list add is a real broker
    # action and was scoring 0. Observed live -- the GF Securities preferred-list
    # note was the ONLY article in AMD's 50-item feed that was actually about AMD,
    # and the one plausible explanation of its +3%; it ranked 39th of 50.
    (1,  "analyst",       r"upgrade|downgrade|price target|initiat\w+ coverage|reiterat|"
                          r"preferred list|conviction list|focus list|buy list|top pick|"
                          r"added to .{0,20}?list|resumes? coverage"),
    # SECTOR MOVE (added 2026-08-14). A story about the GROUP moving can explain our
    # move when nothing company-specific does -- and until now it could only ever score
    # 0, because no rule described it. Observed on DDOG 2026-08-14: "monday.com and
    # MongoDB lead AI software rally" (MongoDB is a listed DDOG peer) landed at tier 0
    # on a +4.7% day, while the card reached for day-old CPI/PPI instead.
    #
    # Tier 1, alongside `analyst`: it is market commentary, not a company event, and
    # that is honestly what it is worth. It does NOT need its own "penalise it if it
    # doesn't name us" clause -- SHARED_COVERAGE_PENALTY already does exactly that, and
    # simply had nothing above zero to bite on.
    #
    # Deliberately narrow. Measured over 501 live headlines it fires on 0.2%, and it
    # rejects "Nvidia rallies to a record high" (single name, not a sector) and "3
    # Stocks To Watch This Week" (SEO filler). Loose noun-matching here is what put 72%
    # of one pool in the top tier; this needs a MOVE word next to a GROUP word.
    (1,  "sector move",   r"\b(sector|group|peers?|complex)\b.{0,25}?"
                          r"\b(rally|rallies|rout|sell-?off|surge|slump|slide|tumble)\b|"
                          r"\b(rally|rallies|sell-?off|rout)\b.{0,30}?"
                          r"\b(sector|stocks|shares|software|semis|chips|names)\b|"
                          r"\b(stocks|shares|names)\b.{0,20}?"
                          r"\b(rally|rallies|sell-?off|slump|slide|surge)\b|"
                          r"\blead(s|ing)?\b.{0,20}?\b(rally|sell-?off|higher|lower)\b"),
]
# Matched against the TITLE only — the title is what an article is *about*.
# "CEO sells $36M ahead of earnings" is an insider-sale story, not an earnings one.
# Subtracted from a story's tier when it is co-tagged to peers at similar relevance.
# Under two full rungs on purpose: a shared story still outranks a single-ticker one
# two tiers below it (shared earnings 2.5 beats single business 2 / analyst 1 /
# general 0), but loses to a single-ticker corp action (3). The .5 guarantees a
# shared item never TIES a single-ticker item, so ordering between the two classes
# is fully determined instead of falling through to relevance.
# This is the one knob: raise it if sector coverage crowds out company news, lower it
# if real sector drivers stay buried.
SHARED_COVERAGE_PENALTY = 1.5

# RSS items that land at tier 0 are discounted (user, 2026-08-14). Tier 0 is not a
# judgement that a story is minor -- it is the DEFAULT, what you get when no rule
# matched and the classifier could not place the article at all. On the AV side an
# unclassified item still carries a relevance score to rank on; on the RSS side there
# is no such second axis, so an unclassified RSS item is one we know nothing about on
# EITHER dimension, and it should not sit level with an article we did classify.
#
# Applied ONLY at tier 0, not as a flat source penalty: a flat -1 dropped AVEX's own
# earnings release from a clear lead into a tie with a content-mill summary of its
# 10-Q, which is the exact failure adding the RSS source was meant to fix.
RSS_TIER0_DISCOUNT = 1.0

MATERIALITY_DEMOTIONS = [
    # The sell-verb pattern is deliberately loose about what sits between the verb
    # and the noun. An earlier version required the amount to be adjacent to
    # "shares" and so missed "sells $36.6M in Class A shares" — the exact DDOG
    # headline — which then scored as EARNINGS for mentioning earnings downstream.
    # "buys" is absent on purpose: insider buying is a signal, not noise.
    # STEM, not an exact alternation. Observed live 2026-08-11: the headline
    # "Datadog's CEO Sellls Over 127,000 Shares for $36.5 Million" -- publisher's
    # typo, three Ls -- did not match \bsells\b, so the demotion never fired. The
    # positive rules then ran over title+summary, the summary mentioned "Q2 earnings
    # report", and a routine share sale was promoted to the TOP tier and led the
    # card. A missed demotion becomes a maximal promotion, so this pattern has to be
    # forgiving. sell\w* covers sells / selling / sellls; "buys" is still absent, so
    # insider BUYING remains undemoted.
    (-2, "routine filing", r"form 144|10b5-1|insider (sell|sale)|"
                           r"\b(sell\w*|sold)\b.{0,45}?\b(shares|stock|stake)\b"),
]

# --- Institutional holdings changes (the old -3 "13F/stake" rule, rebuilt) -------
# The regex it replaces failed three independent ways, all observed live on
# 2026-08-12 in a single 50-article pool where 34 filings slipped through:
#   VOCABULARY  it knew boosts/trims/increases/reduces, but the headlines said
#               "Lowers", "Decreases", "Acquires", "Has", "Invests".
#   ADJACENCY   `reduces? (its )?(position)` needs the noun next to the verb, so
#               "Lowers STOCK Position" missed. The -2 rule above already learned
#               this and uses `.{0,45}?`; this rule never inherited the fix.
#   WORD ORDER  it assumed verb-then-noun, so the passive forms "Shares Sold by
#               Insight Wealth" and "Holdings Lowered by Wedge Capital" sailed past.
#
# THE ACTOR TEST IS THE POINT, not the verb list. "Buys ... shares" is noise from a
# fund and a signal from an officer, and the settled rule is that insider BUYING is
# never demoted. So the subject decides:
#   a PERSON  (CEO/CFO/Director/...) -> never demoted here. Insider SALES are still
#             caught by the -2 routine-filing rule above; insider BUYING survives.
#   a FIRM    (LLC/LP/Advisors/Capital/Management/...) -> demoted, it is a 13F.
#   UNKNOWN   -> left alone. A demotion that cannot identify its subject should not
#             fire, and a false negative here merely lets noise rank, while a false
#             positive would delete a real signal.
# The person test runs FIRST and wins outright, so "Goldman Sachs GROUP CEO Buys
# 5,000 Shares" is read as an insider story despite the firm token in the employer's
# name -- the same "demotions win outright" doctrine used above.
# TENSE, added 2026-08-17 — the fourth failure, and the one the rebuild missed.
# Every verb above was PRESENT tense with an optional `s`. The word-order fix landed but
# the tense fix did not, and passive voice is exactly where past participles appear, so
# the two halves never met: `lowers?` does not match "Lowered". The header's own worked
# example, "Holdings Lowered by Wedge Capital Management LLP", missed on the very rule
# that cites it -- only "Shares Sold by ..." passed, because `sold` happens to be listed
# separately.
#
# Observed live on MRVL, 2026-08-17: a +5.75% card whose ENTIRE pool was
# "$MRVL Position Increased by Nisa Investment Advisors LLC" and "$MRVL Stock Position
# Trimmed by Public Sector Pension Board" -- both scored (0, 'general'), the default,
# meaning no rule matched rather than a judgement that they were immaterial. Tier 0 is
# the aboutness-promotion rung and both headlines LEAD with the ticker, so on a quieter
# day either was one promotion away from being offered as the cause of the move. That is
# the insider-selling failure this rule exists to prevent.
#
# Written as explicit inflections rather than a trailing \w*: "trim" doubles its final
# consonant and a greedy suffix would over-match ("cuts" vs "cutting-edge"). The NOUN is
# still required, which is what keeps "Raises 2026 Guidance" out -- there is no holdings
# noun in it -- and the actor guard still decides who gets demoted.
# `takes` added 2026-08-17 from PM's live pool: "Janney Montgomery Scott LLC Takes
# $112.15 Million Position in Philip Morris" scored tier 0 on a verb list that had every
# other way of saying the same thing. Unambiguous BECAUSE the holdings noun is still
# required next to it -- "takes" alone appears in all sorts of headlines ("takes on",
# "takes aim"), none of which name a stake, position or holding.
_HOLD_VERB = (r"(buys?|bought|sell\w*|sold|acquir(e|es|ed)|purchas(e|es|ed)|"
              r"lower(s|ed)?|decreas(e|es|ed)|increas(e|es|ed)|reduc(e|es|ed)|"
              r"boost(s|ed)?|trim(s|med)?|rais(e|es|ed)|cuts?|adds? to|added to|"
              r"tak(e|es)|took|grow(s|n)?|grew|offload(s|ed)?|invest(s|ed)?|"
              r"has|have|had|hold(s)?|held|owns?|owned|maintain(s|ed)?)")
_HOLD_NOUN = r"(stake|position|holdings|shares|investment)"
# KNOWN RESIDUAL, left deliberately (2026-08-17): "First Trust Advisors LP Invests $2.26
# Million in Advance Auto Parts" is a 13F in substance and is NOT demoted, because it
# states no holdings noun -- the money goes straight to the company name. A noun-free
# `invests $N in` branch would catch it and would also catch "Nvidia Corp Invests $1B in
# ...", a genuine strategic-investment catalyst, since ACTOR_FIRM cannot tell an asset
# manager's firm token from an operating company's. A missed demotion lets noise rank; a
# false demotion deletes a real catalyst. The asymmetry decides it.
HOLDINGS_SHAPE = (rf"\b13F\b|{_HOLD_VERB}\W+(\w+\W+){{0,4}}?{_HOLD_NOUN}\b|"
                  rf"{_HOLD_NOUN}\W+(\w+\W+){{0,3}}?{_HOLD_VERB}\b")
ACTOR_PERSON = r"\b(CEO|CFO|COO|CTO|President|Director|Chairman|Chair|EVP|SVP|VP|" \
               r"officer|founder|insider)\b"
ACTOR_FIRM = (r"\b(LLC|L\.?L\.?C|LP|L\.?P|Inc|Ltd|PLC|Corp|Corporation|Advisors?|"
              r"Advisory|Capital|Management|Partners|Fonder|Trust|Bancorp|Bank|Asset|"
              r"Wealth\w*|Group|Fund|Investments?|Securities|Associates|Strategies|"
              r"Vanguard|BlackRock|State Street|Berkshire|Norges)\b")


def _is_institutional_holdings(title):
    """True for a fund's position change — a backward-looking quarter-end snapshot
    filed on a 45-day lag, which can never explain today's move."""
    t = title or ""
    if not re.search(HOLDINGS_SHAPE, t, re.I):
        return False
    if re.search(ACTOR_PERSON, t, re.I):
        return False
    return bool(re.search(ACTOR_FIRM, t, re.I))
# MACRO_FILE moved to engine/macro.py (split phase 3).
# PRICE_HISTORY_* config moved to engine/price_history.py (split phase 2).

# Minimum absolute % move required to post a card, on top of the expected-move
# breach. Prevents low-IV mega-caps and ETFs (tight ATM put premium) from
# triggering on moves that are statistically significant but not tradeable-sized.
MIN_ABSOLUTE_TRIGGER_PCT = 2.0

# --- Claude Rate Limiter (token-aware, Tier 1: 50 RPM / 50k TPM) ---
class RateLimiter:
    def __init__(self, max_calls, max_tokens_per_min, period_seconds=60):
        self.max_calls = max_calls
        self.max_tokens = max_tokens_per_min
        self.period = period_seconds
        self.call_times = deque()     # timestamps of recent calls
        self.token_log = deque()      # (timestamp, token_count) of recent calls
        self.lock = threading.Lock()

    def _prune(self, now):
        """Drop entries older than the rolling window."""
        while self.call_times and now - self.call_times[0] >= self.period:
            self.call_times.popleft()
        while self.token_log and now - self.token_log[0][0] >= self.period:
            self.token_log.popleft()

    def tokens_in_window(self):
        """Return total tokens consumed in the current rolling window."""
        with self.lock:
            now = time.time()
            self._prune(now)
            return sum(t for _, t in self.token_log)

    def wait_for_slot(self, estimated_tokens=8000):
        """Block until both RPM and TPM limits allow this call, then reserve a slot.
        estimated_tokens is a conservative upfront guess; call record_usage() after
        the real call completes to log actual token counts."""
        with self.lock:
            while True:
                now = time.time()
                self._prune(now)

                tokens_used = sum(t for _, t in self.token_log)
                calls_used = len(self.call_times)

                rpm_ok = calls_used < self.max_calls
                tpm_ok = (tokens_used + estimated_tokens) <= self.max_tokens

                # If this single call exceeds the TPM ceiling on its own,
                # no amount of waiting will help — let it through and rely
                # on the API's own 429 handling if it gets rejected.
                if estimated_tokens > self.max_tokens:
                    print(f"[RATE LIMITER] Single call ({estimated_tokens:,} tokens) exceeds TPM ceiling ({self.max_tokens:,}) — proceeding, 429 handler will retry if needed.")
                    self.call_times.append(now)
                    self.token_log.append((now, estimated_tokens))
                    return

                if rpm_ok and tpm_ok:
                    self.call_times.append(now)
                    self.token_log.append((now, estimated_tokens))
                    return

                # Determine how long to wait
                wait_reason = []
                sleep_time = 1.0  # minimum poll interval

                if not rpm_ok:
                    rpm_wait = self.period - (now - self.call_times[0]) + 0.1
                    sleep_time = max(sleep_time, rpm_wait)
                    wait_reason.append(f"RPM {calls_used}/{self.max_calls}")

                if not tpm_ok:
                    tokens_to_free = (tokens_used + estimated_tokens) - self.max_tokens
                    freed = 0
                    for ts, tok in self.token_log:
                        freed += tok
                        if freed >= tokens_to_free:
                            tpm_wait = self.period - (now - ts) + 0.1
                            sleep_time = max(sleep_time, tpm_wait)
                            break
                    wait_reason.append(f"TPM {tokens_used:,}+{estimated_tokens:,} > {self.max_tokens:,}")

                print(f"[RATE LIMITER] Waiting {sleep_time:.1f}s ({', '.join(wait_reason)})...")
                time.sleep(sleep_time)

    def record_usage(self, actual_tokens):
        """Replace the most recent token reservation with the actual count after a call completes."""
        with self.lock:
            if self.token_log:
                ts, _ = self.token_log[-1]
                self.token_log[-1] = (ts, actual_tokens)

claude_limiter = RateLimiter(max_calls=45, max_tokens_per_min=45000)  # 45k leaves 5k buffer under 50k TPM
actionable_file_lock = threading.Lock()
news_cache_lock = threading.Lock()
last_clear_lock = threading.Lock()
last_clear_time = 0.0

# Turtle channel levels + multi-year stats are heavy to compute, so cache the
# per-ticker snapshot once per trading day; the per-pass breakout check is then a
# cheap price-vs-level comparison. In-memory (recomputed after a restart); only
# fetch_loop touches it. Maps ticker -> {"date": date, "snapshot": dict|None}.
_turtle_cache = {}
fallback_semaphore = threading.Semaphore(2)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")

# --- Macro regime (generate + loop + /get_macro_regime): extracted to
#     engine/macro.py (Blueprint + start_macro_loop; 2026-07-21 split phase 3). ---

# get_tickers / save_tickers moved to engine/common.py (split phase 4).

def get_actionable_moves_local():
    if os.path.exists(ACTIONABLE_FILE):
        try:
            with open(ACTIONABLE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def read_actionable_trading_date():
    """Return the trading date (ET) the persisted actionable_moves belong to, or None."""
    if os.path.exists(ACTIONABLE_META_FILE):
        try:
            with open(ACTIONABLE_META_FILE, 'r') as f:
                stamp = json.load(f).get('trading_date')
            return datetime.fromisoformat(stamp).date() if stamp else None
        except Exception:
            return None
    return None

def write_actionable_trading_date(trading_date):
    """Stamp the trading date the current live actionable set belongs to."""
    try:
        with open(ACTIONABLE_META_FILE, 'w') as f:
            json.dump({"trading_date": trading_date.isoformat()}, f)
    except Exception as e:
        print(f"[META] Failed to write actionable trading-date stamp: {e}")

# --- News Cache (per-ticker, per-day) ---
def _load_news_cache():
    if os.path.exists(NEWS_CACHE_FILE):
        try:
            with open(NEWS_CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def _cache_key(ticker_symbol, label_date):
    return f"{label_date.isoformat()}:{ticker_symbol}"

def get_cached_news(ticker_symbol, label_date=None):
    """Returns cached news_text for this ticker today, or None if not cached."""
    if label_date is None:
        label_date = datetime.today().date()
    with news_cache_lock:
        cache = _load_news_cache()
        entry = cache.get(_cache_key(ticker_symbol, label_date))
        return entry.get("news_text") if entry else None

def set_cached_news(ticker_symbol, news_text, source, label_date=None, meta=None):
    """Stores news_text for this ticker/day so repeated triggers (e.g. across
    engine restarts during testing) don't re-hit Alpha Vantage.

    ALSO THE PULL'S DIAGNOSTIC RECORD (2026-08-17). `pool` and `chosen_sources` are
    computed in fetch_latest_news and were printed to stdout and then dropped, so a
    later review could see WHICH feeds supplied the chosen headlines but never how deep
    the pool behind them was -- and the source of an individual headline had to be
    inferred from the ABSENCE of a summary, since Yahoo RSS supplies none and Alpha
    Vantage does. Twice in one session that was the missing number.

    Cached rather than put on the card deliberately (user, 2026-08-17): this is
    diagnostics, and the card is display state. The cache is already keyed per
    ticker-day, already cleared at rollover, and is already the artifact you open when
    asking what a pull actually saw.

    `meta` is optional and additive -- a caller that omits it writes exactly what it
    wrote before, so the two synthesis paths that have no meta to give are unaffected.
    """
    if label_date is None:
        label_date = datetime.today().date()
    with news_cache_lock:
        cache = _load_news_cache()
        entry = {
            "news_text": news_text,
            "source": source,
            "cached_at": datetime.now().isoformat()
        }
        if meta:
            if meta.get("pool"):
                entry["pool"] = meta["pool"]
            if meta.get("chosen_sources"):
                entry["chosen_sources"] = meta["chosen_sources"]
        cache[_cache_key(ticker_symbol, label_date)] = entry
        with open(NEWS_CACHE_FILE, 'w') as f:
            json.dump(cache, f)

def clear_news_cache(reason="manual"):
    """Wipes the news cache. Called on startup and at midnight rollover,
    alongside clear_actionable_moves."""
    with news_cache_lock:
        with open(NEWS_CACHE_FILE, 'w') as f:
            json.dump({}, f)
    print(f"[CLEANUP] news_cache.json cleared ({reason}).")

def archive_actionable_moves(label_date):
    """
    Appends today's actionable moves (trimmed to ticker, trigger, price,
    percent move, and AI synthesis) to a dated archive file before they're
    cleared. Safe to call with an empty actionable_moves dict (no-op).
    """
    current = get_actionable_moves_local()
    if not current:
        return

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(ARCHIVE_DIR, f"{label_date.isoformat()}.json")

    # Load existing archive for the day (in case engine restarted mid-day)
    existing = {}
    if os.path.exists(archive_path):
        try:
            with open(archive_path, 'r') as f:
                existing = json.load(f)
        except:
            existing = {}

    for ticker, data in current.items():
        existing[ticker] = {
            "ticker": ticker,
            "status": data.get("status", ""),
            "price": data.get("price", ""),
            "price_change": data.get("price_change", ""),
            "why": data.get("why", ""),
            "structure": data.get("structure", ""),
            "impact": data.get("impact", "")
        }

    with open(archive_path, 'w') as f:
        json.dump(existing, f, indent=2)

    print(f"[ARCHIVE] {len(current)} move(s) archived to {archive_path}.")

def clear_actionable_moves(reason="manual", archive_date=None, clear_news_too=False):
    """Archives, then wipes ACTIONABLE_FILE clean. Called at midnight rollover and,
    conditionally, on startup (see startup_actionable_reconcile). News cache is only
    cleared when clear_news_too=True (an actual day change), since a restart shouldn't
    throw away still-valid cached news. After wiping, stamps the live set's trading
    date to today (ET) — the fresh slate always belongs to the current ET day."""
    if archive_date is None:
        archive_date = datetime.now(ET).date()
    with actionable_file_lock:
        archive_actionable_moves(archive_date)
        with open(ACTIONABLE_FILE, 'w') as f:
            json.dump({}, f)
    write_actionable_trading_date(datetime.now(ET).date())
    with last_clear_lock:
        global last_clear_time
        last_clear_time = time.time()
    print(f"[CLEANUP] actionable_moves.json cleared ({reason}).")
    if clear_news_too:
        clear_news_cache(reason=reason)

def _actionable_file_is_from_today(today):
    """True if actionable_moves.json was last written today (ET). Used only as a
    stamp-less fallback for the one-time transition onto the restart-tolerant
    scheme — steady-state reconciliation keys off the trading-date stamp, not mtime."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(ACTIONABLE_FILE), ET).date() == today
    except Exception:
        return False

def _backfill_legacy_conditions():
    """Stamp conditions:["1-sigma"] onto any preserved card that predates the
    multi-condition schema (the old engine had only the 1-sigma trigger, so every
    legacy card IS a 1-sigma card). Idempotent. Runs during startup BEFORE fetch_loop
    starts, so a preserved card reads as already-carded on the first pass — no
    re-card, no re-synthesis, no news fetch — keeping its existing why/price snapshot
    exactly as a normally-created card would. Returns the number of cards upgraded."""
    with actionable_file_lock:
        current = get_actionable_moves_local()
        upgraded = 0
        for card in current.values():
            if not card.get('conditions'):
                card['conditions'] = ["1-sigma"]
                upgraded += 1
        if upgraded:
            with open(ACTIONABLE_FILE, 'w') as f:
                json.dump(current, f)
    return upgraded

def startup_actionable_reconcile():
    """Make actionable moves restart-tolerant. On engine start, PRESERVE today's live
    set across a same-day restart; only archive+clear when the persisted set belongs
    to a prior trading day (engine was down across a day/weekend boundary) or when
    there is no usable trading-date stamp."""
    today = datetime.now(ET).date()
    stamped = read_actionable_trading_date()
    current = get_actionable_moves_local()

    if stamped == today:
        upgraded = _backfill_legacy_conditions()
        print(f"[STARTUP] Same-day restart — preserving {len(current)} live actionable move(s) for {today} "
              f"({upgraded} legacy card(s) tagged 1-sigma).")
        return

    if stamped is not None:
        # Persisted set belongs to a prior trading day: archive it under THAT day
        # (not today), clear the day-scoped news cache, and open a fresh slate.
        clear_actionable_moves(
            reason=f"startup: new trading day (persisted set was {stamped})",
            archive_date=stamped,
            clear_news_too=True,
        )
        return

    # No stamp yet (first run under this feature). If the existing file was written
    # today, it's the running engine's live set — adopt it, backfill legacy cards to
    # the multi-condition schema (so the first fetch pass won't re-synthesize them),
    # and stamp today so the very first restart onto this code is seamless.
    if current and _actionable_file_is_from_today(today):
        upgraded = _backfill_legacy_conditions()
        print(f"[STARTUP] No stamp yet; existing set was written today — adopting {len(current)} live move(s) "
              f"for {today} ({upgraded} legacy card(s) tagged 1-sigma).")
        write_actionable_trading_date(today)
        return
    clear_actionable_moves(reason="startup: no trading-date stamp")

def patch_actionable_move(ticker, updates):
    """Thread-safe read-modify-write for a single ticker's entry in ACTIONABLE_FILE.

    Most keys overwrite via dict.update(). The two multi-condition fields merge
    ADDITIVELY instead, so several triggers firing on one ticker accumulate into a
    single card (one card per ticker — see turtle-volume-indicators.md):
      - `conditions`      — list of trigger-tag strings, unioned (order-preserving).
      - `condition_meta`  — per-condition data dict, shallow-merged.
    """
    with actionable_file_lock:
        current = get_actionable_moves_local()
        if ticker in current:
            card = current[ticker]
            if 'conditions' in updates:
                merged = list(card.get('conditions', []))
                for c in updates['conditions']:
                    if c not in merged:
                        merged.append(c)
                updates = {**updates, 'conditions': merged}
            if 'condition_meta' in updates:
                meta = dict(card.get('condition_meta', {}))
                meta.update(updates['condition_meta'])
                updates = {**updates, 'condition_meta': meta}
            card.update(updates)
        else:
            current[ticker] = updates
        with open(ACTIONABLE_FILE, 'w') as f:
            json.dump(current, f)

# --- News pull scheduling -----------------------------------------------------
# A trigger no longer pulls news immediately. It schedules:
#
#   T+30min   first pull. The news cycle needs time to catch up -- an immediate pull
#             was reliably returning yesterday's articles.
#   15:00 ET  one retry, if the first found nothing fresh.
#   after     "No news surfaced today." and stop. PURE AV: no live-search fallback.
#
# The live search was TESTED and dropped (user, 2026-08-11). On ARM's unexplained
# -5.21% it ran three web searches, returned "insufficient company-specific catalyst
# identified" -- i.e. nothing Alpha Vantage had not already implied -- and cost
# $0.042 and 38.5k input tokens against a 45k TPM ceiling, forcing a 51-second
# limiter wait for a SINGLE ticker. As a routine sweep that is a serialized crawl
# consuming the whole Claude throughput. search_and_synthesize_fallback() is left in
# the file, unwired, in case it is ever wanted for a rare very large unexplained move.
#
# State lives ON THE CARD, not in a sleeping thread, so an engine restart resumes
# pending pulls instead of dropping them.
#   news_state: pending -> retry -> done | none
#   news_due_at: epoch of the next attempt
NEWS_FIRST_PULL_DELAY_MIN = 30
NEWS_SWEEP_HOUR_ET = 15
NEWS_PACER_SECONDS = 30     # minimum gap between ANY two Alpha Vantage calls

_av_pace_lock = threading.Lock()
_av_last_call = [0.0]


def _av_pace():
    """Serialise Alpha Vantage calls at least NEWS_PACER_SECONDS apart.

    Global rather than a 15:00-queue special case: two tickers triggering in the
    same fetch_loop pass would otherwise fire together too. At 30s the ceiling is
    120 calls/hour, so pacing is never the binding constraint -- the 25/day budget
    is. This only prevents rate-limit rejections.
    """
    with _av_pace_lock:
        wait = NEWS_PACER_SECONDS - (time.time() - _av_last_call[0])
        if wait > 0:
            print(f"[AV PACE] waiting {wait:.0f}s before the next Alpha Vantage call")
            time.sleep(wait)
        _av_last_call[0] = time.time()


# --- Alpha Vantage daily budget -------------------------------------------------
# The free tier allows 25 calls/day and the measured median usage is 24, so the
# engine runs at the wall most days. Before this existed there was NO counter: the
# pacer above tracks the last call's TIMESTAMP, not a count, and it dies with the
# process — so the day's usage could only be reverse-engineered from news_cache
# entries and card states after the fact.
#
# THE FAILURE THIS PREVENTS. A quota-exhausted call returns an "Information"/"Note"
# body, which the old code turned into `None` — indistinguishable from "the call
# succeeded and there was nothing fresh." `_advance_after_empty()` then wrote
# "No news surfaced today." onto the card. A billing failure was permanently
# recorded as a statement about the market. That string is the number being counted
# to answer how often a flagged move never gets a story (2026-08-11), so poisoning
# it corrupts the measurement as well as the card.
#
# So an unavailable call now returns AV_UNAVAILABLE, NOT None, and the card is left
# in its current state to be retried rather than being closed out with a false
# answer. `None` keeps its original meaning: asked, and nothing was there.
# Weight bonus for an article whose HEADLINE names our ticker. Applied to weight, not
# to tier, so it can lift a demoted item into view for situational awareness without
# ever making it eligible to be a CAUSE — the band is decided by tier alone.
# KEPT, ON NOTICE (user, 2026-08-14). Reviewed when the AV path gained company-name
# aliases, which widened the bonus's reach: articles naming the company in prose
# ("Pfizer CEO Buys...") now collect +3 where the bare-ticker match used to miss them.
# Decision was to keep it, and to make it THE FIRST THING CUT if garbage AV articles
# start outranking real events.
#
# If that day comes, check the sort key BEFORE touching this number. Measured
# 2026-08-14: "Pfizer Stock: 3 Things To Watch This Week" (tier 0, weight 3.0) already
# outranks "...Pfizer reports Q2 results above estimates" (tier 4, weight 5.5) -- not
# on the bonus, which loses that comparison, but on the `leads` boolean, which is the
# sort's PRIMARY key and beats every weight difference. Cutting the bonus would not fix
# it; demoting `leads` to a tiebreak would.
NAMED_BONUS = 3

# Backoff when a pull could not be MADE (AV_UNAVAILABLE). An unavailable attempt keeps
# the card's state but must push its due time out, or the card stays perpetually due and
# every 60s loop pass spends another call. Capped as well as delayed: after
# MAX_TRIES the card stops retrying for the day rather than grinding at the budget.
NEWS_UNAVAILABLE_BACKOFF_MIN = 20
NEWS_UNAVAILABLE_MAX_TRIES = 3

AV_DAILY_LIMIT = 25
AV_USAGE_FILE = 'av_usage.json'
_av_usage_lock = threading.Lock()


class _AVUnavailable:
    """The call could NOT be made — distinct from 'was made and found nothing'."""
    __slots__ = ()

    def __repr__(self):
        return "<AV_UNAVAILABLE>"


AV_UNAVAILABLE = _AVUnavailable()


def _av_usage_today():
    """The usage record for today, rolling over automatically at the ET date change.
    Callers hold _av_usage_lock."""
    try:
        with open(AV_USAGE_FILE, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    today = datetime.now(ET).date().isoformat()
    if d.get('date') != today:
        d = {"date": today, "calls": 0}
    return d


def av_calls_used():
    with _av_usage_lock:
        return int(_av_usage_today().get('calls', 0))


def av_calls_remaining():
    return max(0, AV_DAILY_LIMIT - av_calls_used())


def _av_count_call():
    """Record one Alpha Vantage call and return the running total.

    Counted when the request is ISSUED, not when it succeeds — a timeout may still
    have reached the far end, so counting on success would undercount toward the
    wall. Erring high is the safe direction for a hard daily cap.
    """
    from engine.common import atomic_write_json
    with _av_usage_lock:
        d = _av_usage_today()
        d['calls'] = int(d.get('calls', 0)) + 1
        d['last_call_at'] = datetime.now(ET).isoformat(timespec='seconds')
        atomic_write_json(AV_USAGE_FILE, d)
        return d['calls']


def _av_mark_exhausted(reason=""):
    """Alpha Vantage itself said we are out. It is the authority on our quota, so
    stop guessing from the local count and pin usage to the limit for the rest of
    the day — the local tally can be low if calls were made from anywhere else."""
    from engine.common import atomic_write_json
    with _av_usage_lock:
        d = _av_usage_today()
        d['calls'] = max(int(d.get('calls', 0)), AV_DAILY_LIMIT)
        d['exhausted_at'] = datetime.now(ET).isoformat(timespec='seconds')
        if reason:
            d['exhausted_reason'] = reason[:200]
        atomic_write_json(AV_USAGE_FILE, d)
    print(f"[AV BUDGET] Alpha Vantage reports the quota is spent — no further calls today")


def _sweep_time_today():
    now = datetime.now(ET)
    return now.replace(hour=NEWS_SWEEP_HOUR_ET, minute=0, second=0, microsecond=0)


def schedule_news_pull(ticker, delay_min=NEWS_FIRST_PULL_DELAY_MIN):
    """Mark a freshly-triggered card as awaiting its first pull. Idempotent — a
    second trigger on the same ticker the same day must not reset the clock."""
    card = (get_actionable_moves_local() or {}).get(ticker) or {}
    if card.get('news_state'):
        return
    due = datetime.now(ET) + timedelta(minutes=delay_min)
    patch_actionable_move(ticker, {
        "news_state": "pending",
        "news_due_at": due.timestamp(),
        "why": f"Awaiting news pull @ {due:%H:%M} ET.",
        "structure": "Catalyst scan pending.",
        "impact": "Levels shown; narrative follows the news pull.",
    })
    print(f"[NEWS SCHED] {ticker}: first pull due {due:%H:%M} ET")


def schedule_volume_news_pull(ticker):
    """A 2x-volume fire earns its OWN pull, once per ticker per day.

    NOT the same rule as schedule_news_pull, which no-ops the moment a ticker has any
    news state. That idempotence is correct for a second PRICE trigger — the same move
    does not deserve two looks — and wrong here. Volume usually arrives WITH definitive
    news (user, 2026-08-12), so a spike is positive evidence that something has printed
    SINCE the earlier attempt, which for a 1-sigma card was T+30 from the open and
    often found nothing. Observed live: NVDA pulled at 10:19, crossed 2x volume in the
    afternoon, and kept its morning narrative because the volume fire no-opped.

    REGRESSION NOTE. This behaviour shipped in `0033699` ("Phase A3b: once/day updated
    synthesis on 2x-volume") and was lost in `e776b3b`, the T+30/15:00 scheduling
    rework, which replaced the direct synthesis call with schedule_news_pull() and
    inherited its guard. `run_synthesis_in_background()` has had no caller since.

    Re-arms the shared state machine rather than running its own synthesis, so the
    news_loop, the AV budget counter, the banding and the context tiers all apply
    unchanged. Due NOW, not T+30: the delay exists to let news publish after a price
    move, and a volume spike that has been accumulating for hours is itself the
    evidence that it already has.
    """
    card = (get_actionable_moves_local() or {}).get(ticker) or {}
    if card.get('volume_news_pulled'):
        return
    prev = card.get('news_state')          # read BEFORE patching; the patch may mutate
    patch_actionable_move(ticker, {        # the very dict this reference points at
        "news_state": "pending",
        "news_due_at": datetime.now(ET).timestamp(),
        "volume_news_pulled": True,
    })
    print(f"[NEWS SCHED] {ticker}: 2x-volume fire — re-arming a fresh pull now "
          f"(was '{prev}')")


def _opt_from_card(card):
    """Rebuild the options payload from the stored card, so a pull after a restart
    does not need the original in-memory opt_data."""
    return {"expected_move_pct": card.get('expected_move'),
            "atm_strike": card.get('atm_strike'), "atm_put_price": card.get('atm_put_price'),
            "atm_expiration": card.get('atm_expiration'), "put_wall": card.get('put_wall'),
            "call_wall": card.get('call_wall'), "atm_iv": card.get('atm_iv')}


def _advance_after_empty(ticker, now=None):
    """No fresh news on this attempt — move the card to its next state.

    pending -> retry at 15:00, unless it is already past the sweep, in which case
    there is no second chance left and it goes straight to `none`.
    """
    now = now or datetime.now(ET)
    sweep = _sweep_time_today()
    if now < sweep:
        # STATUS IS DELIBERATELY LEFT ALONE HERE. A card in this branch still has a
        # pull due at the sweep, so "Synthesis Pending" is TRUE -- clearing it would
        # replace an accurate status with a finished-looking one and hide that
        # something is still coming. Only the terminal branch below is stale.
        patch_actionable_move(ticker, {
            "news_state": "retry", "news_due_at": sweep.timestamp(),
            "why": f"No news as of {now:%H:%M} ET — next pull @ {sweep:%H:%M} ET.",
        })
        print(f"[NEWS NONE] {ticker}: nothing fresh — retry at {sweep:%H:%M} ET")
    else:
        # Stable wording ON PURPOSE — this is the string to count when asking how
        # often a flagged move never got a story (user, 2026-08-11).
        done_patch = {
            "news_state": "none", "news_due_at": None,
            "why": "No news surfaced today.",
            "structure": "No catalyst found in two attempts.",
            "impact": "Move unexplained by available coverage.",
        }
        # CLEAR THE PENDING STATUS ON THE NO-NEWS PATH TOO. The matching clear in
        # run_due_news_pulls covers only a SUCCESSFUL synthesis, so a card that
        # definitively finished with no story kept advertising that it was waiting
        # -- observed on XNDU (2026-08-14), whose card read "No news surfaced today."
        # beside a status of "TRIGGERED - Synthesis Pending". The trigger itself was
        # real and is unchanged; only the narrative is absent, so it resolves to the
        # same status a successful pull would leave. Read here rather than taken as
        # an argument so a future caller cannot reintroduce this by omission.
        # Exact-match guarded, like the success branch: "Synthesis Pending" is only
        # ever set on the 1-sigma path, and a volume/turtle status must survive
        # untouched.
        card = (get_actionable_moves_local() or {}).get(ticker) or {}
        if (card.get('status') or '').strip() == "TRIGGERED - Synthesis Pending":
            done_patch["status"] = "TRIGGERED - 1-sigma Move"
        patch_actionable_move(ticker, done_patch)
        print(f"[NEWS NONE] {ticker}: no news surfaced today — closed out")


# --- Peer-earnings context (the FALLBACK tier) ----------------------------------
# WHY THIS EXISTS (2026-08-12). Six semis triggered on one day -- AMD +3.0, NVDA +2.9,
# MU +6.6, MRVL +5.1, LRCX +5.0, INTC +3.0 -- on one catalyst: SMCI, CRWV and LITE all
# reported after the prior close. Alpha Vantage put those articles in NVDA's feed and
# nobody else's, so NVDA got the only correct narrative on the board and the other five
# got filings about Ford. Verified: AMD's 50-article feed contained ZERO mentions of
# SMCI or CoreWeave.
#
# The fix is not to hunt harder for the article. The earnings calendar STATES the fact,
# for every ticker at once, for free. yfinance already backs `_next_earnings` in
# stoplight/events.py; this reads the same source backwards.
#
# STRICTLY A FALLBACK. Only consulted when a ticker's own feed yields nothing fresh.
# Always-on sector context would become the new insider-selling -- a plausible sentence
# available on every card regardless of whether it explains anything (the audit's own
# warning, 2026-08-10). An ungrouped ticker gets no context and the tier stays silent,
# which is the conservative default.
#
# Peer sets deliberately include names that are NOT on the watchlist. The company whose
# results move a sector is frequently not one we track -- that is exactly this session's
# case -- so a peer list limited to tickers.json would have missed all three drivers.
PEER_GROUPS = {
    "ai_semis": ["AMD", "NVDA", "INTC", "MU", "MRVL", "LRCX", "ARM", "XLK", "XNDU",
                 "AVGO", "TSM", "ASML", "AMAT", "KLAC", "QCOM", "TXN", "ADI", "ON",
                 "MCHP", "NXPI", "GFS", "CRDO", "SWKS", "TER", "WDC", "STX",
                 "SMCI", "CRWV", "LITE", "ANET", "DELL", "VRT"],
    "software":  ["DDOG", "GOOGL", "SNAP", "CRM", "NOW", "SNOW", "MDB", "NET",
                  "PANW", "CRWD", "ORCL", "MSFT", "META", "ADBE"],
    "staples":   ["MO", "PM", "KHC", "CAG", "TGT", "PG", "KO", "PEP", "CL", "GIS",
                  "K", "STZ", "BTI", "KMB"],
    "energy":    ["XLE", "ENB", "LYB", "XOM", "CVX", "COP", "SLB", "OXY", "PSX",
                  "VLO", "MPC", "EOG"],
    "power_ind": ["GEV", "UPS", "ETN", "PWR", "HUBB", "CAT", "HON", "EMR", "FDX"],
    "health":    ["PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY", "AMGN"],
    "telecom":   ["VZ", "T", "TMUS", "CMCSA", "CHTR"],
    "reits":     ["O", "VICI", "SPG", "PLD", "AMT", "WELL"],
    "retail":    ["SFIX", "AMZN", "M", "KSS", "GPS", "ANF", "URBN", "RL"],
    "auto_ev":   ["TSLA", "GM", "F", "RIVN", "LCID"],
}
# ticker -> its peers (itself excluded). Ungrouped tickers simply never get context.
TICKER_PEERS = {t: [p for p in members if p != t]
                for members in PEER_GROUPS.values() for t in members}
EARNINGS_CAL_FILE = 'earnings_calendar.json'
_earn_cal_lock = threading.Lock()

COMPANY_NAME_FILE = 'company_names.json'
_name_cache_lock = threading.Lock()


def _company_names(tickers):
    """{ticker: display name} for `tickers`, cached for the ET day.

    EXISTS BECAUSE HEADLINES USE NAMES, NOT TICKERS. The RSS source's precision filter
    matches a headline against the company it claims to be about, and the first
    implementation took that name from the actionable card. Measured 2026-08-13: only
    12 of 19 cards carried a real name -- CAG, ENB, MO, MU, PFE, PM and TGT had the
    TICKER in the name field. So PFE's aliases were ['pfe'], and "5 Insightful Analyst
    Questions From Pfizer's Q2 Earnings Call" -- a tier-4 article about its own
    earnings -- scored 0.35 and was thrown away. Cards also only exist for tickers that
    have already triggered, so anything without one degraded the same way.

    Same shape as _earnings_calendar deliberately: ~1s per name, paid once per ticker
    per ET day, cached to DISK so a restart does not re-pay it, and a name that fails
    to resolve is cached as "" so a bad symbol does not retry all day.
    """
    from engine.common import atomic_write_json
    today = datetime.now(ET).date().isoformat()
    with _name_cache_lock:
        try:
            with open(COMPANY_NAME_FILE, encoding='utf-8') as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        if cache.get('date') != today:
            cache = {"date": today, "names": {}}
        known = cache.setdefault('names', {})
        missing = [t for t in tickers if t not in known]
        if missing:
            print(f"[NEWS RSS] resolving {len(missing)} company name(s)...")
            for t in missing:
                try:
                    info = yf.Ticker(t).info or {}
                    known[t] = (info.get('longName') or info.get('shortName') or "")
                except Exception:
                    known[t] = ""
            atomic_write_json(COMPANY_NAME_FILE, cache)
        return known


def _earnings_calendar(tickers):
    """{ticker: [iso datetime strings]} for `tickers`, cached for the ET day.

    yfinance is ~1s per name and there is no batch endpoint, so the first card in a
    group pays for its whole peer set and every later card that day is free. Cached to
    disk rather than memory so an engine restart does not re-pay it.

    A FAILED LOOKUP CACHES `None`, NOT `[]` (2026-08-17). Both used to be the empty
    list, which made "yfinance threw" and "yfinance answered, this name has no dates"
    the same value -- and _reported_in_window reads that value to decide whether an
    earnings article may be a cause. Its fail-open branch only catches an exception
    ESCAPING this function, and this function catches everything per-ticker, so the
    open path was unreachable: one transient failure demoted every earnings article for
    that name until midnight, silently, which is the opposite of the documented rule
    that unknown is not the same as no.

    Still cached either way -- a missing calendar must not retry all day -- the two
    outcomes are just now distinguishable. `None` means unknown; `[]` means asked and
    answered with nothing.
    """
    from engine.common import atomic_write_json
    today = datetime.now(ET).date().isoformat()
    with _earn_cal_lock:
        try:
            with open(EARNINGS_CAL_FILE, encoding='utf-8') as f:
                cal = json.load(f)
        except (OSError, ValueError):
            cal = {}
        if cal.get('date') != today:
            cal = {"date": today, "tickers": {}}
        known = cal.setdefault('tickers', {})
        missing = [t for t in tickers if t not in known]
        if missing:
            print(f"[PEER EARNINGS] building calendar for {len(missing)} name(s)...")
            for t in missing:
                try:
                    df = yf.Ticker(t).get_earnings_dates(limit=8)
                    known[t] = ([d.astimezone(ET).isoformat() for d in df.index.to_pydatetime()]
                                if df is not None and len(df) else [])
                except Exception as e:
                    # None, not [] — see the docstring. Logged rather than swallowed
                    # silently, so a name that goes unknown all day leaves a trace.
                    print(f"[PEER EARNINGS] {t}: lookup failed "
                          f"({type(e).__name__}: {e}) — treated as UNKNOWN, not 'no dates'")
                    known[t] = None
            atomic_write_json(EARNINGS_CAL_FILE, cal)
        return known


# --- Macro context (the second FALLBACK tier) -----------------------------------
# The answer to "why did this move" is frequently already on disk and was never shown
# to the card synthesis. On 2026-08-12 the hourly briefing read "Markets rally on
# in-line CPI report and strong AI earnings" and carried the print itself -- CPI +0.1%
# m/m against +0.1% expected, released 8:30 ET -- while every card on the board was
# left guessing from institutional filings. The audit's own note: 52% of honest
# failures already reach for "sector weakness" or "broader market" with NO data.
#
# SAME FALLBACK DISCIPLINE as the peer tier, for the same reason: an always-on macro
# line would make "broader market concerns" the new insider-selling -- a plausible
# sentence available on every card whether or not it explains anything.
#
# Only RELEASED data is included. "NOT RELEASED" and "none scheduled" rows are noise,
# and a scheduled-but-unreleased print explains nothing, exactly as a future earnings
# date does not.
MACRO_CONTEXT_MAX_AGE_MIN = 180


def macro_context(now=None):
    """Market-wide context from the hourly macro briefing, or None.

    Read fresh from disk each time rather than cached here: engine/macro.py owns the
    file and rewrites it hourly, so anything cached in this module would go stale
    against it silently.
    """
    now = now or datetime.now(ET)
    try:
        from engine.macro import MACRO_FILE
    except Exception:
        MACRO_FILE = 'macro_regime.json'
    try:
        with open(MACRO_FILE, encoding='utf-8') as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict):
        return None

    # `data_releases` is MODEL-AUTHORED JSON with no schema enforcement, so its shape
    # varies between hourly regenerations. Observed live 2026-08-12: a dict at 14:05
    # ({"CPI (8:30 ET)": "RELEASED ..."}) and a LIST an hour later. Assuming dict cost
    # five AV calls — see the backoff note in run_due_news_pulls. Normalise anything.
    # PREFERRED PATH (session 44): `released_figures` is PYTHON-AUTHORED by
    # engine/release_data.py, straight from the publishing agency, with an explicit
    # per-release status. It is a contract, not a sentence, so nothing below has to
    # interpret wording to decide whether a number is real.
    # A FIGURE MUST BE FRESH BY THE SAME RULE AN ARTICLE IS (user, 2026-08-14). This
    # used to admit every figure the store held, so DDOG's 2026-08-14 card explained a
    # 4.7% move with CPI printed 08-12 and PPI printed 08-13 -- both BEFORE the
    # 08-13 16:00 cutoff that had already discarded 49 of AV's 50 articles as stale.
    # Articles were held to the window and macro was not.
    #
    # `first_seen` is when we OBSERVED the figure change (engine/release_data.py); an
    # `estimated` stamp is a first sighting whose true publication date is unknowable,
    # and unknown is NOT fresh -- it is excluded rather than assumed, which is the same
    # rule applied to an undated article.
    cutoff = _news_cutoff(now)
    released = []
    rf = m.get('released_figures')
    if isinstance(rf, dict):
        for r in rf.values():
            if not (isinstance(r, dict) and r.get('status') == 'ok' and r.get('display')):
                continue
            fs = r.get('first_seen')
            if not fs or r.get('first_seen_estimated'):
                continue
            try:
                if datetime.fromisoformat(fs) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            released.append(f"{r.get('label')}: {r['display']}")

    # FALLBACK: the model's own `data_releases`, which still covers releases we have no
    # deterministic source for (ISM, JOLTS, FOMC). Shape varies between regenerations
    # -- observed live 2026-08-12 as a dict at 14:05 and a LIST an hour later, and
    # assuming dict cost five AV calls. Normalise anything.
    # FALLBACK ONLY WHEN THE STRUCTURED FIELD IS ABSENT, never when it is present and
    # everything in it failed the freshness test. Keyed on `rf` rather than on
    # `released` being empty, because "all of today's figures are stale" is a RESULT --
    # falling through to undated prose there would reinstate the exact staleness the
    # filter above exists to remove, by a second route.
    if not released and not isinstance(rf, dict):
        dr = m.get('data_releases')
        if isinstance(dr, dict):
            rows = [f"{k}: {v}" for k, v in dr.items() if isinstance(v, str)]
        elif isinstance(dr, list):
            rows = []
            for x in dr:
                if isinstance(x, str):
                    rows.append(x)
                elif isinstance(x, dict):
                    # e.g. {"name": "CPI", "status": "RELEASED ..."} — join the values in
                    # a stable order rather than guessing at key names.
                    rows.append(": ".join(str(v) for v in x.values() if isinstance(v, (str, int, float))))
        elif isinstance(dr, str):
            # THIRD shape, observed 2026-08-13 10:31 — dict at 08:37, list at 09:37, a
            # bare comma-joined STRING at 10:31, from three consecutive runs of one
            # prompt. Split only on separators that cannot appear inside a figure.
            # NOT on commas, deliberately: "1,800K expected" would split mid-number and
            # manufacture a row stating a fragment. One un-splittable blob is a worse
            # row but an honest one, and the figure test below still gates it.
            rows = [x.strip() for x in re.split(r"[;\n]", dr) if x.strip()]
        else:
            rows = []
        # A ROW MUST CARRY AN ACTUAL FIGURE. "PPI (8:30 ET): RELEASED figure not found"
        # passes the RELEASED test and explains exactly nothing -- on 2026-08-13 three
        # such rows took three of the four context slots on every card. The comment
        # above already says an unreleased print explains nothing; a released print
        # with no figure is no different.
        #
        # "does it contain a digit" is NOT the test, and gets this exactly wrong: that
        # row carries digits in BOTH the schedule "(8:30 ET)" and the expectation
        # "(Expected +0.2% m/m)" while stating no actual number. Strip parenthesised
        # segments first -- schedule and expectation both live there, the actual figure
        # does not -- then require a digit in what remains.
        def _states_a_figure(row):
            bare = re.sub(r"\([^)]*\)", "", row)
            if "NOT FOUND" in bare.upper() or "NOT YET IN HAND" in bare.upper():
                return False
            return any(ch.isdigit() for ch in bare)

        released = [r for r in rows
                    if "RELEASED" in r.upper() and "NOT RELEASED" not in r.upper()
                    and _states_a_figure(r)]
    headline = (m.get('headline') or "").strip()

    # NO HARD PRINT, NO MACRO NARRATIVE (user, 2026-08-17).
    #
    # "Market chatter can drive prices up or down. On the other hand, it isn't directly
    # related to the stock. So unless there's hard news, let's not report it -- we can
    # just say moving with the market or against it, but let's not try to explain it on
    # the macro level."
    #
    # The briefing headline is model prose regenerated hourly, and with no release under
    # it there is nothing anchoring it. On 2026-08-17 "reduced Fed rate hike bets"
    # explained SNAP, UPS, DDOG and MRVL at 10:15 -- two down hard, one up 5.75% -- and
    # had disappeared from the 11:20 regeneration. No speaker, no print: every release
    # the store held was July, published the previous week. The freshness rule already
    # stopped those FIGURES reaching a card; their narrative walked back in through the
    # headline, which is the same publication-vs-event distinction the earnings gate
    # makes one layer down.
    #
    # A HARD PRINT KEEPS ITS NARRATIVE. CPI, PPI, PCE, jobs, the Fed -- when one of
    # those is genuinely in the window it belongs in the card if nothing company-specific
    # explains the move. That is what `released` being non-empty means here, and this
    # block does not touch that path.
    #
    # With no print, the card gets a FACT instead of a story: how the market itself
    # moved. Direction is checkable; "sentiment improved on rate-cut hopes" is not.
    if not released:
        spy_pct = m.get('spy_change_pct')
        if spy_pct is None:
            print("[MACRO CONTEXT] no released print and no market reference — omitted")
            return None
        print(f"[MACRO CONTEXT] no released print — supplying the market's move only "
              f"(SPY {spy_pct:+.2f}%)")
        return (
            "CONTEXT — MARKET-WIDE, NOT COMPANY NEWS.\n"
            f"The market itself moved {spy_pct:+.2f}% today (SPY).\n"
            "NOTE: there is NO macro release today. State only whether this company moved "
            "WITH the market or AGAINST it, and say nothing about why the market moved. "
            "Do not offer sentiment, rate expectations or policy as an explanation."
        )

    # Past the guard above, `released` is non-empty by construction — the old
    # `if not released and not headline: return None` line here could no longer fire and
    # was removed rather than left as a branch that reads like it still guards something.
    lines = []
    if released:
        # "released today" was a lie waiting to happen: `released_figures` carries every
        # print we hold, and payrolls/unemployment come from the month's first Friday.
        # We store the PERIOD a figure covers, never the date it was published, so
        # today-ness is not something this function can honestly assert. Say "recent"
        # and let the model weigh it -- an overstated date is how a card ends up
        # explaining a move with a week-old release.
        lines.append("Recent macro prints: " + "; ".join(released[:4]))
    if headline:
        stamp = (m.get('updated_at') or "").strip()
        lines.append(f"Market read{f' ({stamp})' if stamp else ''}: {headline}")
    print(f"[MACRO CONTEXT] supplying {len(released)} released print(s) "
          f"from {'released_figures' if rf else 'data_releases'}")
    return (
        "CONTEXT — MARKET-WIDE, NOT COMPANY NEWS.\n" + "\n".join(lines) + "\n"
        "NOTE: this describes the whole market, not this company. Offer it only if the "
        "move is consistent with a broad move, and say so explicitly as a market-wide "
        "explanation. Never present it as a company-specific catalyst."
    )


def _reported_in_window(ticker, now=None):
    """Did `ticker` actually report earnings inside the news freshness window?

    The gate behind the earnings tier. An article is published today; the results it
    describes may be three months old. Using publication time as a proxy for event
    time is what let a 93-day-old report hold the top tier.
    """
    if not ticker:
        return False
    now = now or datetime.now(ET)
    cutoff = _news_cutoff(now)
    try:
        cal = _earnings_calendar([ticker])
    except Exception as e:
        # Unknown is not the same as No. Failing OPEN here keeps a real earnings story
        # in PRIMARY when the calendar is unreachable; failing closed would silently
        # demote every earnings article the moment yfinance hiccuped.
        print(f"[NEWS BAND] earnings-window check unavailable for {ticker}: "
              f"{type(e).__name__}: {e}")
        return True
    # UNKNOWN IS NOT NO -- the same rule as the except branch above, applied to the
    # answer as well as to the failure. `None` (or an absent key) means the lookup did
    # not resolve, so the gate abstains and the tier stands; `[]` means yfinance
    # answered and this name has no dates, which IS a real "it did not report".
    dates = cal.get(ticker)
    if dates is None:
        print(f"[NEWS BAND] earnings-window unknown for {ticker} (no calendar data) "
              f"— leaving the tier alone")
        return True
    for iso in dates:
        try:
            d = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if cutoff <= d <= now:
            return True
    return False


def peer_earnings_context(ticker, now=None):
    """A context block naming in-window reporters, or None when there is nothing to say.

    'In-window' uses the SAME cutoff as article freshness, so this answers exactly the
    question the missing article would have: what happened since the last close that
    could move this name. Returns text shaped for the synthesis prompt, explicitly
    labelled as a calendar fact rather than a headline so the model cannot present it
    as reporting.
    """
    # An UNGROUPED ticker still gets its OWN earnings checked. Bailing out here on an
    # empty peer list -- as this used to -- meant a company with no sensible comparables
    # could report after the close and the board would never say so. SPCX is the case
    # that surfaced it (user, 2026-08-12: SpaceX is "very diversified to have a peer",
    # and BA/LMT would not move it absent a huge contract event) -- a correct decision
    # to leave it ungrouped that silently disabled the self-check too.
    peers = TICKER_PEERS.get(ticker) or []
    now = now or datetime.now(ET)
    cutoff = _news_cutoff(now)
    try:
        cal = _earnings_calendar([ticker] + peers)
    except Exception as e:
        print(f"[PEER EARNINGS] calendar unavailable for {ticker}: {type(e).__name__}: {e}")
        return None

    def reported(tk):
        out = []
        for iso in cal.get(tk) or []:
            try:
                d = datetime.fromisoformat(iso)
            except ValueError:
                continue
            if cutoff <= d <= now:
                out.append(d)
        return out

    self_hits = reported(ticker)
    peer_hits = [(p, d) for p in peers for d in reported(p)]
    if not self_hits and not peer_hits:
        return None

    lines = []
    if self_hits:
        # Its OWN earnings, with no article about them, is a stronger and stranger
        # fact than any peer's -- surface it first and say so plainly.
        lines.append(f"{ticker} ITSELF reported earnings at "
                     f"{self_hits[0]:%Y-%m-%d %H:%M} ET, since the prior close.")
    if peer_hits:
        peer_hits.sort(key=lambda x: x[1])
        named = ", ".join(f"{p} ({d:%Y-%m-%d %H:%M} ET)" for p, d in peer_hits[:6])
        lines.append(f"Sector peers that reported since the prior close: {named}.")

    # The attribution instruction must match WHICH hit fired. Telling the model to
    # credit "the sector" is right for a peer report and exactly wrong for the
    # company's own — its own earnings are the definition of a company-specific event.
    if self_hits and peer_hits:
        attribution = ("Distinguish this company's OWN report from its peers' when "
                       "attributing the move. ")
    elif self_hits:
        attribution = ("This company's own report is a COMPANY-SPECIFIC event — "
                       "attribute it to the company, not to the sector. ")
    else:
        attribution = ("If a sector-wide move is a plausible reading, say so and "
                       "attribute it to the sector rather than to this company. ")

    print(f"[PEER EARNINGS] {ticker}: {len(peer_hits)} peer(s), "
          f"{len(self_hits)} self — supplying fallback context")
    # Deliberately makes no claim about what else was retrieved. This block used to
    # open by asserting no article had cleared the filter, which was true when it only
    # fired on an empty feed and became FALSE once it could run alongside a PRIMARY.
    return (
        "CONTEXT — EARNINGS CALENDAR, NOT A NEWS ARTICLE.\n" + "\n".join(lines) + "\n"
        "NOTE: these are calendar facts, not reporting — no article about them was "
        "retrieved and their RESULTS are unknown here. " + attribution +
        "Do NOT state or imply whether those results beat or missed. If this does not "
        "plausibly explain the move, say the move is unexplained."
    )


def run_due_news_pulls():
    """One pass: execute any card whose next pull is due. Called by news_loop."""
    try:
        cards = get_actionable_moves_local() or {}
    except Exception as e:
        print(f"[NEWS LOOP] could not read cards: {type(e).__name__}: {e}")
        return
    now = datetime.now(ET)
    for ticker, card in list(cards.items()):
        state, due = card.get('news_state'), card.get('news_due_at')
        if state not in ('pending', 'retry') or not due:
            continue
        if now.timestamp() < float(due):
            continue
        # Checked BEFORE the pacer: _av_pace() sleeps up to 30s, and doing that only
        # to discover there is no budget would stall this pass for every due card.
        # break, not continue -- if the budget is gone it is gone for all of them.
        if av_calls_remaining() <= 0:
            print(f"[AV BUDGET] {AV_DAILY_LIMIT}/{AV_DAILY_LIMIT} spent — "
                  f"deferring due pulls (still waiting: {ticker})")
            break
        try:
            _av_pace()
            news_text, news_meta = fetch_latest_news(ticker)
            if news_text is AV_UNAVAILABLE:
                # Could not ask. The card keeps its STATE — advancing it toward "no news
                # surfaced today" would assert something we never earned. But it must
                # NOT stay due, or this becomes a spend loop: news_due_at is already in
                # the past, so every 60s pass re-selects the card and every attempt
                # costs an API call.
                #
                # THIS EXACT LOOP RAN LIVE (2026-08-12). A crash in the new macro-context
                # builder propagated to fetch_latest_news' outer handler, which returns
                # AV_UNAVAILABLE, so TSLA sat in `pending` and burned one call a minute
                # from 20/25 to 25/25 in five minutes. The original code always advanced
                # the card, which self-limited by accident; removing the advance removed
                # the limit with it.
                # A post-response code fault is DETERMINISTIC — the next attempt crashes
                # in the same place and spends another call. Stop immediately; there is
                # nothing to wait for. Only a genuine wire failure earns the backoff.
                if news_meta.get("retryable") is False:
                    patch_actionable_move(ticker, {"news_due_at": None})
                    print(f"[NEWS PULL] {ticker}: failure is not retryable (code fault "
                          f"after a good response) — stopping, card left in '{state}'")
                    continue

                tries = int(card.get('news_unavailable_tries') or 0) + 1
                if tries >= NEWS_UNAVAILABLE_MAX_TRIES:
                    # Stop retrying today. due=None makes run_due_news_pulls skip it
                    # (`if ... or not due: continue`) while the state and text stand.
                    patch_actionable_move(ticker, {"news_due_at": None,
                                                   "news_unavailable_tries": tries})
                    print(f"[NEWS PULL] {ticker}: Alpha Vantage unavailable {tries}x — "
                          f"giving up for today, card left in '{state}'")
                else:
                    retry_at = now + timedelta(minutes=NEWS_UNAVAILABLE_BACKOFF_MIN)
                    patch_actionable_move(ticker, {"news_due_at": retry_at.timestamp(),
                                                   "news_unavailable_tries": tries})
                    print(f"[NEWS PULL] {ticker}: Alpha Vantage unavailable "
                          f"({tries}/{NEWS_UNAVAILABLE_MAX_TRIES}) — backing off to "
                          f"{retry_at:%H:%M} ET, card left in '{state}'")
                continue

            if news_text is None:
                # NOT A SUCCESSFUL PULL, and the derived context tiers do not change
                # that (user, 2026-08-12). Peer-earnings and macro context are built
                # INSIDE fetch_latest_news and ranked alongside the articles, so they
                # are colour on a real pull and never a substitute for one: a card with
                # nothing published against it goes back to the 15:00 sweep for a
                # second look at the wire rather than being closed out on a calendar
                # entry.
                _advance_after_empty(ticker, now)
                continue

            # NAME THE SOURCES THAT ACTUALLY SUPPLIED THE CHOSEN HEADLINES. This was
            # hardcoded "Alpha Vantage", which stopped being true the moment the pool
            # gained a second feed -- a card could be attributed to AV while carrying a
            # headline only Yahoo had. Falls back to the old label when meta is absent
            # so a cached/degraded path still reads sensibly.
            _SRC_LABELS = {"alpha_vantage": "Alpha Vantage", "yahoo_rss": "Yahoo RSS"}
            _srcs = (news_meta or {}).get("sources") or ["alpha_vantage"]
            news_source = " + ".join(_SRC_LABELS.get(s, s) for s in _srcs)
            _corr = (news_meta or {}).get("corroborated") or 0
            if _corr:
                print(f"[NEWS PULL] {ticker}: {_corr} chosen headline(s) carried by "
                      f"more than one source")
            # meta carries `pool` + `chosen_sources` — cached alongside the text so a
            # later review can answer how thin the pool was without re-pulling.
            set_cached_news(ticker, news_text, news_source, meta=news_meta)
            # POOL LINE. The source label alone said WHICH feeds contributed but never how
            # thin the pool was -- an AV corpus of 50 with 1 fresh article reads identically
            # to a healthy one. These counts are the difference between "ranked badly" and
            # "had nothing to rank", which is the distinction this pipeline keeps turning on.
            _pool = (news_meta or {}).get("pool") or {}
            if _pool:
                _av, _rs = _pool.get("alpha_vantage", {}), _pool.get("yahoo_rss", {})
                print(f"[NEWS POOL] {ticker}: "
                      f"AV {_av.get('raw', 0)} raw/{_av.get('kept', 0)} kept "
                      f"({_av.get('stale', 0)} stale, {_av.get('undated', 0)} undated) · "
                      f"RSS {_rs.get('raw', 0)} raw/{_rs.get('kept', 0)} kept "
                      f"({_rs.get('stale', 0)} stale, {_rs.get('unnamed', 0)} not about us) · "
                      f"chose {', '.join((news_meta or {}).get('chosen_sources') or []) or 'none'}")
            print(f"[NEWS PULL] {ticker}: {news_source.lower()} ({state} attempt) — synthesising")
            ai = generate_ai_synthesis(ticker, _opt_from_card(card), news_text,
                                       round(float(card.get('price_change') or 0), 2))
            why = ai.get('why', '')
            if not why.strip():
                _advance_after_empty(ticker, now)
                continue
            # CLEAR THE PENDING STATUS. "TRIGGERED - Synthesis Pending" is set when the
            # card fires and was never cleared when the synthesis arrived, so a finished
            # card kept advertising that it was still waiting -- observed on AVEX
            # (2026-08-13) and DDOG (2026-08-14), both `news_state: done` with a written
            # narrative and a status still claiming pending. Only that one string is
            # rewritten; a volume/turtle status is left exactly as its trigger set it.
            done_patch = {
                "news_source": news_source, "why": why,
                "structure": ai.get('structure', ''), "impact": ai.get('impact', ''),
                "news_state": "done", "news_due_at": None,
            }
            if (card.get('status') or '').strip() == "TRIGGERED - Synthesis Pending":
                done_patch["status"] = "TRIGGERED - 1-sigma Move"
            patch_actionable_move(ticker, done_patch)
            print(f"[NEWS PULL] {ticker}: synthesis complete ({news_source})")
        except Exception as e:
            print(f"[NEWS PULL ERROR] {ticker}: {type(e).__name__}: {e}")


def news_loop():
    """Poll for due news pulls. Separate daemon rather than riding fetch_loop, so it
    cannot slow the price path, and it re-derives everything from card state — a
    restart resumes pending pulls instead of losing them."""
    while True:
        time.sleep(60)
        try:
            run_due_news_pulls()
        except Exception as e:
            print(f"[NEWS LOOP] error: {type(e).__name__}: {e}")


def start_news_loop():
    t = threading.Thread(target=news_loop, daemon=True, name="news_loop")
    t.start()
    return t


def run_synthesis_in_background(ticker, opt_data, pct_change, is_update=False):
    """Fetches news + runs Claude synthesis off the main loop, then patches the card in place.

    is_update=True marks a re-synthesis (the once/day 2x-volume refresh, which
    often runs after the initial move to catch news that has since hit the tape).
    In that mode a failed/empty result must NOT overwrite good existing card text,
    and the card's `status` is left untouched — only why/structure/impact/news_source
    are refreshed on a genuine success.
    """
    triggered_at = time.time()
    try:
        # A volume re-synthesis must PULL FRESH NEWS, not re-chew the cache.
        # The cache is keyed per-day, and on a 2x-volume day it was almost always
        # populated hours earlier by the 1-sigma trigger — volume is not pro-rated
        # for time of day, so it lands mid-afternoon while 1-sigma fires at the open.
        # Reading that cache made the second look a no-op: it re-ran the LLM over the
        # SAME headlines and reached the same conclusion, which is exactly what this
        # function's docstring says it exists to avoid. Observed on MO 2026-07-30:
        # -9.09% on 2.1x volume, both syntheses chewing the same Q1 13F filings and
        # both concluding the move "cannot be explained by the provided headlines".
        # Bypassing is safe from a cost angle because the caller gates this to ONCE
        # PER DAY PER TICKER (`volume_synth_ran`, reset by the midnight clear); a
        # successful fetch below refreshes the cache for everyone else.
        cached = None if is_update else get_cached_news(ticker)
        if cached is not None:
            print(f"[NEWS CACHE HIT] {ticker}: reusing today's cached news (no API call).")
            news_text = cached
            news_source = "Cached"
        else:
            news_text, _news_meta = fetch_latest_news(ticker)
            news_source = "Alpha Vantage"

            if news_text is AV_UNAVAILABLE:
                # No call was made, so there is nothing to explain a fallback FROM.
                # Escalating to the Claude live search here would spend a far more
                # expensive budget to answer a question Alpha Vantage was never asked.
                print(f"[NEWS PULL] {ticker}: Alpha Vantage unavailable — leaving the "
                      f"card unchanged rather than escalating to a live search.")
                return

            if news_text is None:
                print(f"[NEWS FALLBACK] {ticker}: Alpha Vantage had nothing, using Claude search+synthesize...")
                ai_synthesis = search_and_synthesize_fallback(ticker, opt_data, round(pct_change, 2))
                news_source = "Claude Search"
                why = ai_synthesis.get('why', '')
                failure_phrases = ("synthesis failed", "timed out", "api error", "n/a", "unavailable")
                looks_failed = (not why.strip()) or any(p in why.lower() for p in failure_phrases)
                if looks_failed:
                    print(f"[CACHE SKIP] {ticker}: synthesis result looks like a failure, not caching.")
                    if is_update:
                        print(f"[VOLUME SYNTH] {ticker}: update synthesis empty/failed — keeping existing card text.")
                        return
                else:
                    set_cached_news(ticker, why, news_source)
                with last_clear_lock:
                    cleared_after_trigger = last_clear_time > triggered_at
                if cleared_after_trigger:
                    print(f"[STALE THREAD] {ticker}: midnight clear fired after this thread started — discarding synthesis.")
                    return
                patch = {
                    "news_source": news_source,
                    "why": why,
                    "structure": ai_synthesis.get('structure', ''),
                    "impact": ai_synthesis.get('impact', '')
                }
                if not is_update:
                    patch["status"] = "TRIGGERED - Exceeded Premium"
                patch_actionable_move(ticker, patch)
                print(f"[SYNTHESIS COMPLETE] {ticker} (news via {news_source})")
                return

        ai_synthesis = generate_ai_synthesis(ticker, opt_data, news_text, round(pct_change, 2))
        failure_phrases = ("synthesis failed", "timed out", "api error", "n/a", "unavailable")
        why = ai_synthesis.get('why', '')
        looks_failed = (not why.strip()) or any(p in why.lower() for p in failure_phrases)
        if looks_failed:
            print(f"[CACHE SKIP] {ticker}: synthesis result looks like a failure, not caching.")
            if is_update:
                print(f"[VOLUME SYNTH] {ticker}: update synthesis empty/failed — keeping existing card text.")
                return
        else:
            set_cached_news(ticker, news_text, news_source)
        with last_clear_lock:
            cleared_after_trigger = last_clear_time > triggered_at
        if cleared_after_trigger:
            print(f"[STALE THREAD] {ticker}: midnight clear fired after this thread started — discarding synthesis.")
            return
        patch = {
            "news_source": news_source,
            "why": why,
            "structure": ai_synthesis.get('structure', ''),
            "impact": ai_synthesis.get('impact', '')
        }
        if not is_update:
            patch["status"] = "TRIGGERED - Exceeded Premium"
        patch_actionable_move(ticker, patch)
        print(f"[SYNTHESIS COMPLETE] {ticker} (news via {news_source})")
    except Exception as e:
        print(f"[SYNTHESIS THREAD ERROR] {ticker}: {e}")
        if is_update:
            print(f"[VOLUME SYNTH] {ticker}: update synthesis errored — keeping existing card text.")
            return
        with last_clear_lock:
            cleared_after_trigger = last_clear_time > triggered_at
        if cleared_after_trigger:
            print(f"[STALE THREAD] {ticker}: midnight clear fired after this thread started — discarding failed synthesis.")
            return
        patch_actionable_move(ticker, {
            "status": "TRIGGERED - Synthesis Failed",
            "why": "AI synthesis failed to complete.",
            "structure": "N/A",
            "impact": "N/A"
        })

# --- AI Synthesis Logic ---
def _news_cutoff(now=None):
    """16:00 ET on the prior TRADING day.

    Trading, not calendar: from a Monday this walks back past the weekend to Friday's
    close. Holidays are not modelled -- a holiday makes the window slightly NARROWER
    than intended, which errs toward fresher news rather than staler.
    """
    now = now or datetime.now(ET)
    d = now.date() - timedelta(days=1)
    while d.weekday() >= 5:                      # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, NEWS_CUTOFF_HOUR_ET, 0, 0, tzinfo=ET)


def _published_at(item):
    """Parsed publication time, or None when absent/malformed."""
    tp = (item or {}).get("time_published") or ""
    try:
        return datetime.strptime(tp, NEWS_TIME_FMT).replace(tzinfo=ET)
    except (ValueError, TypeError):
        return None


def _is_about_us(c, ticker_symbol):
    """Is this candidate about the company whose card we are building?

    THE GAP THIS CLOSES (2026-08-17). `_band` decided PRIMARY vs BACKGROUND on TIER
    alone. Tier answers "is this the KIND of thing that moves a stock" -- it never
    answered WHOSE stock. So on 2026-08-17 a Truist price target on DYNATRACE was
    banded PRIMARY on DDOG's card and offered to the model as a candidate cause for a
    -4% move, and the card duly reached for it.

    The engine already knew better. Every AV candidate carries `top_ticker` -- the
    company AV itself scores as the article's subject -- which was DT. It also carries a
    negative `gap` and a shared-coverage penalty that had driven the item's WEIGHT to
    -0.5. Weight orders items inside a band; tier chooses the band; nothing reconciled
    them, so an article the ranker scored below zero was still eligible to explain a
    move.

    EXEMPTION: the RSS peer read-across sets `top_ticker` to the PEER deliberately (see
    where it is appended), because that is how it reuses _band's in-window earnings
    guard. Those candidates are BUILT as sector context, already carry the shared-
    coverage penalty, and their attribution note says to read them as sector-wide -- so
    they stay eligible. They are identified by their own `peer` key, not by the ticker
    comparison, which is exactly what tells a deliberate read-across apart from an
    article that simply is not about us.

    Anything without a `top_ticker` (the macro block, the peer-earnings block, the RSS
    self path) defaults to the card's own ticker and passes.
    """
    if c.get("peer"):
        return True
    return (c.get("top_ticker") or ticker_symbol) == ticker_symbol


def _materiality(title):
    """(weight, label) for how much this story could plausibly MOVE a stock.

    EVERYTHING is now tested against the TITLE alone (changed 2026-08-12). Demotions
    always were, on the reasoning that the title is what an article is ABOUT -- but
    the positive rules read title+summary, and that asymmetry was the single largest
    ranking defect measured: 33 of 50 articles in one live pool were promoted to the
    top tier purely by summary boilerplate ("revenue" appeared in 25 summaries, "EPS"
    in 21) while their titles were institutional filings about other companies.
    An aggregator's summary recites the covered company's financials as background
    colour; treating that as evidence of an earnings story is a category error.

    Demotions still win outright, so an insider-sale story is not promoted to the
    earnings tier for mentioning earnings in passing.
    """
    t = title or ""
    for weight, label, pattern in MATERIALITY_DEMOTIONS:
        if re.search(pattern, t, re.I):
            return weight, label
    if _is_institutional_holdings(t):
        return -3, "13F/stake"
    best, best_label = 0, "general"
    for weight, label, pattern in MATERIALITY_RULES:
        if weight > best and re.search(pattern, t, re.I):
            best, best_label = weight, label
    return best, best_label


def fetch_latest_news(ticker_symbol):
    """Returns (text, meta).

    text: the banded headline block on success; None if the call was MADE and nothing
          usable came back; AV_UNAVAILABLE if the call could not be made at all
          (budget spent, quota message, transport failure). Callers must not treat the
          last case as an absence of news — see the AV budget block above for why.
    meta: {"n_primary", "n_background"} — how many of the sent articles may be offered
          as a CAUSE versus how many are awareness-only, plus n_catalyst: PRIMARIES that
          earned it on materiality rather than by last-resort aboutness promotion.
          n_catalyst == 0 is the signal that nothing here explains the move, and is
          what triggers the peer-earnings fallback."""
    remaining = av_calls_remaining()
    if remaining <= 0:
        print(f"[AV BUDGET] {ticker_symbol}: daily limit of {AV_DAILY_LIMIT} reached — "
              f"no call made, card left for a later attempt")
        return AV_UNAVAILABLE, {"retryable": True}
    got_response = False
    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=NEWS_SENTIMENT"
            f"&tickers={ticker_symbol}"
            # limit is per-RESPONSE, not per-request: 50 costs the same single API
            # call as 10 and does not touch the quota. It also does not widen the
            # prompt — the loop below still stops at 3 headlines, so this changes
            # what we choose FROM, not what we send. At 10, a day of filing-
            # aggregator posts could fill the whole window and a real catalyst was
            # never seen rather than ranked below (observed: DDOG 2026-08-06, an
            # 18.7% earnings gap explained as routine insider selling).
            f"&limit={NEWS_FETCH_LIMIT}"
            f"&apikey={ALPHA_VANTAGE_KEY}"
        )
        used = _av_count_call()
        print(f"[AV BUDGET] call {used}/{AV_DAILY_LIMIT} — {ticker_symbol} "
              f"({AV_DAILY_LIMIT - used} left today)")
        resp = requests.get(url, timeout=10)
        data = resp.json()
        got_response = True      # past this line, any failure is OURS, not the wire's

        # Missing/invalid API key or quota exhaustion. NOT None: we never got to ask,
        # so the card must not be closed out as "no news surfaced today".
        if "Information" in data or "Note" in data:
            msg = str(data.get("Information") or data.get("Note"))
            print(f"[NEWS WARNING] Alpha Vantage API issue: {msg[:200]}")
            if re.search(r"rate limit|call frequency|premium plan|higher API call", msg, re.I):
                _av_mark_exhausted(msg)
            return AV_UNAVAILABLE, {"retryable": True}

        feed = data.get("feed", [])
        if not feed:
            return None, {"n_primary": 0, "n_catalyst": 0, "n_background": 0, "top_tier": -99}

        # Collect every candidate that clears the relevance bar, THEN rank. The old
        # loop broke at the first 3 that passed, which -- because the feed arrives
        # newest-first -- meant selection by recency. On a day of filing-aggregator
        # posts all three slots filled before a real catalyst was ever examined.
        # ALIASES ARE RESOLVED ONCE, FOR BOTH PATHS. Headlines name COMPANIES, not
        # tickers, and until now only the RSS path knew that. The AV path matched
        # `\bAVEX\b` against "AEVEX Corp. Announces..." and scored named=False,
        # leads=False -- forfeiting the +3 bonus and the lead key on an article plainly
        # about the company. It is not an AVEX quirk: "Pfizer CEO Buys $1 Million of
        # Stock" does not contain the string PFE either, so AV has been systematically
        # under-scoring the company-specific articles it does carry, which is part of
        # why its pools read as off-target filler.
        #
        # Falls back to ticker-only if the name lookup fails -- worse aboutness, but the
        # article path must never break for want of a display name.
        try:
            from engine.news_rss import company_aliases, derive_relevance
            _alias_peers = TICKER_PEERS.get(ticker_symbol) or []
            _names = _company_names([ticker_symbol] + _alias_peers)
            self_aliases = company_aliases(ticker_symbol, _names.get(ticker_symbol))
        except Exception as e:
            print(f"[NEWS ALIAS] {ticker_symbol}: name lookup unavailable "
                  f"({type(e).__name__}: {e}) — matching on the ticker alone")
            _names, _alias_peers = {}, []
            self_aliases = [ticker_symbol.lower()]
            company_aliases = derive_relevance = None

        candidates = []
        cutoff = _news_cutoff()
        stale = undated = 0
        for item in feed:
            # FRESHNESS FIRST -- cheapest and most decisive filter. An article from
            # before the prior close cannot explain today's move; it was already in
            # the price.
            pub = _published_at(item)
            if pub is None:
                undated += 1
                continue
            if pub < cutoff:
                stale += 1
                continue

            title = item.get("title", "")
            summary = item.get("summary", "")
            ticker_sentiments = item.get("ticker_sentiment", [])

            relevance = next(
                (float(t.get("relevance_score", 0)) for t in ticker_sentiments
                 if t.get("ticker") == ticker_symbol), 0.0
            )

            # How many OTHER tickers in this article scored similarly high?
            # A sector/comparison piece (e.g. "AMD vs INTC: who wins AI?")
            # can score both tickers above 0.6 even though it's not really
            # "about" either one individually. If other tickers are scoring
            # within shouting distance of this one, treat it as shared
            # coverage rather than a dedicated story about ticker_symbol.
            # Co-tagged peers, by NAME not just score — the names are the useful part.
            # "also covers AMAT, KLAC" is what tells the synthesis this is a sector
            # move, which is the sentence it otherwise writes with no evidence.
            co_tagged = [
                (t.get("ticker"), float(t.get("relevance_score", 0))) for t in ticker_sentiments
                if t.get("ticker") != ticker_symbol and float(t.get("relevance_score", 0)) >= relevance - 0.05
            ]

            # Which company the article is really ABOUT, by AV's own scoring, and how
            # far behind it we sit. The gap is a continuous aboutness measure (0.00
            # means we ARE the subject; -0.14 means someone else is) and replaces the
            # flat co-tag penalty as the tiebreak.
            _ranked = sorted(((t.get("ticker"), float(t.get("relevance_score", 0)))
                              for t in ticker_sentiments), key=lambda x: -x[1])
            top_ticker, top_relevance = _ranked[0] if _ranked else (ticker_symbol, relevance)

            if relevance < 0.5:
                print(f"[NEWS FILTER] {ticker_symbol}: skipped '{title[:60]}...' (relevance {relevance:.2f} < 0.5)")
                continue

            # Shared coverage is PENALISED, not discarded. It used to be dropped
            # outright, on the theory that co-tagging meant the article was not
            # really about this company. For a SECTOR move that reasoning inverts:
            # co-tagging is evidence it is the right article. Observed on LRCX
            # 2026-08-10 — 40 of 50 articles discarded as shared, leaving a kept
            # pool of stock-forecast filler and the CEO's share sales, while the
            # discards held AMAT's 11% fall, KLA's outlook and MKSI's earnings.
            weight, label = _materiality(title)

            # ABOUTNESS. Two distinct signals, both cheap and both stronger than the
            # relevance score, which is too crude to separate them: on one live pool
            # seven of the eight HIGHEST-relevance articles were filings about other
            # companies, and the single top-scoring article (0.82) never mentioned
            # our ticker at all.
            #   leads  -- our ticker opens the headline. Only 1 of 50 qualified, so
            #             this is a scalpel, not a filter, and it is the strongest
            #             available evidence that a piece is genuinely about us.
            #   named  -- our ticker appears anywhere in the headline. Used for the
            #             PRIMARY override below, so a piece plainly about this
            #             company is never demoted to background merely because its
            #             wording missed every catalyst keyword.
            # Matched against COMPANY ALIASES (ticker + resolved name), not the bare
            # ticker -- see the alias block above. Reuses derive_relevance's matcher
            # rather than keeping a second copy of the same regexes on this side; only
            # its named/leads verdicts are taken, since AV supplies its own relevance.
            if derive_relevance is not None:
                _, named, leads = derive_relevance(title, ticker_symbol, self_aliases)
            else:
                leads = bool(re.match(rf"^\W*({re.escape(ticker_symbol)})\b", title, re.I))
                named = bool(re.search(rf"\b{re.escape(ticker_symbol)}\b", title, re.I))

            # The shared-coverage penalty is SUPPRESSED when our ticker leads. It
            # fired on 100% of one measured pool, which makes a flat penalty
            # arithmetically a no-op -- subtracting the same number from everything
            # ranks nothing. Suppressing it where aboutness is strongest restores
            # the discrimination it was meant to provide.
            penalty = SHARED_COVERAGE_PENALTY if (co_tagged and not leads) else 0

            # NAMED BONUS. Aboutness counts even when an item can NEVER be a cause
            # (user, 2026-08-12: negative tiers are "useful SA in the absence of
            # everything else" when the ticker is genuinely called out). "AMD Shares
            # Sold by Insight Wealth" is a routine filing and stays BACKGROUND — the
            # band keys off `tier`, which this does not touch — but it is genuinely
            # ABOUT AMD, which makes it better awareness than a Hold rating on an
            # unrelated mortgage REIT. Without this it sits at -4.5 and is never seen.
            #
            # +3 is chosen so a demoted-but-on-topic item lands level with unrelated
            # general coverage and the gap/relevance tiebreak decides — it does not leap
            # over real news. It also lifts POSITIVE named items, which is the same
            # principle: an article about THIS company should outrank another company's
            # earnings report, since the latter cannot explain our move either.
            bonus = NAMED_BONUS if named else 0
            candidates.append({
                "title": title, "summary": summary, "relevance": relevance,
                "tier": weight, "label": label, "co_tagged": co_tagged,
                "leads": leads, "named": named, "top_ticker": top_ticker,
                "gap": round(relevance - top_relevance, 2),
                "weight": weight - penalty + bonus,
                "source": "alpha_vantage",
            })

        if stale or undated:
            print(f"[NEWS FRESH] {ticker_symbol}: dropped {stale} published before "
                  f"{cutoff:%Y-%m-%d %H:%M} ET"
                  + (f" and {undated} undated" if undated else "")
                  + f" (of {len(feed)}).")

        # --- SECOND SOURCE: Yahoo RSS, free and quota-less --------------------
        # AV is precise but can be EMPTY. On 2026-08-13 its whole corpus for AVEX was
        # 10 articles, 1 of them fresh -- a content-mill 10-Q summary -- and it never
        # carried the Q2 results at all. Yahoo's feed for the same ticker at the same
        # moment had the company's own release, timestamped 16:01. AVEX IPO'd in April;
        # for a young micro-cap AV's coverage is close to empty, and no amount of
        # ranking fixes an empty pool.
        #
        # Ranked in the SAME pool rather than used as a fallback (user, 2026-08-13). A
        # "only when AV is thin" gate is an arbitrary threshold: a name with three
        # mediocre AV filings and a wire release on Yahoo would fail it and lose the
        # release -- the same failure one notch up.
        #
        # RSS carries no ticker_sentiment, so relevance is DERIVED from the headline
        # (see engine/news_rss.py) rather than defaulted to a constant, which would be
        # a silent thumb on the scale whichever way it was set. The derived score is
        # arranged so the EXISTING `relevance < 0.5` gate above rejects the
        # not-about-us rung -- measured live, RSS filed an ABBV earnings call under
        # PFE, a TDS results piece under VZ, and one Cerebras story under MRVL, INTC
        # and AMD alike. Those score 0.35 and never enter the pool.
        # INITIALIZED OUTSIDE THE TRY so the pool counts survive an RSS failure. Zeroes
        # then mean "the feed contributed nothing", which is true, rather than the meta
        # build blowing up on an unbound name and taking a paid AV pull down with it.
        rss_raw = r_kept = r_peer = r_stale = r_unnamed = 0
        try:
            from engine.news_rss import fetch_yahoo_rss
            if derive_relevance is None:
                raise RuntimeError("alias resolution unavailable")
            # Reuses the aliases resolved once above; the name cache is per-ET-day, so
            # the peer lookups are already paid for by this point.
            aliases = self_aliases
            peer_aliases = {p: company_aliases(p, _names.get(p)) for p in _alias_peers}
            rss_items = fetch_yahoo_rss(ticker_symbol)
            rss_raw = len(rss_items)
            for it in rss_items:
                pub = it.get('published')
                if pub is None or pub < cutoff:
                    r_stale += 1
                    continue
                rtitle = it['title']
                rweight, rlabel = _materiality(rtitle)
                rrel, rnamed, rleads = derive_relevance(rtitle, ticker_symbol, aliases)

                if rrel >= 0.5:
                    # NO SHARED-COVERAGE PENALTY ON THE RSS PATH AT ALL (user,
                    # 2026-08-14). Two attempts at one both failed for the same reason --
                    # neither had anything real to key on:
                    #   1. "does not LEAD with the ticker" -- that is how an editor chose
                    #      to word a headline, not a fact about the article. "Does Datadog
                    #      Still Trade Below Fair Value" is wholly about Datadog and was
                    #      docked 1.5 for opening with "Does".
                    #   2. "names one of our peers" -- better, but partial: it misses any
                    #      comparison against a company not on our peer list (The Trade
                    #      Desk, in the case that prompted this).
                    # The AV path can penalise because AV SUPPLIES the co-tag set and a
                    # per-ticker relevance score. Here there is no equivalent, and the
                    # correct response to having no evidence is to score no adjustment.
                    #
                    # Peer detection is KEPT, as annotation rather than punishment: a
                    # detected peer populates `co_tagged`, which fires the existing "Also
                    # covers X -- may indicate a sector-wide move" note in the prompt. That
                    # is what this file's own LRCX finding argues for -- co-tagging is
                    # EVIDENCE for a sector story, so surface it to the model instead of
                    # ranking the article down for it.
                    rco = [(p, 0.0) for p, al in peer_aliases.items()
                           if derive_relevance(rtitle, p, al)[1]]
                    rpenalty = RSS_TIER0_DISCOUNT if rweight == 0 else 0
                    # NO NAMED_BONUS ON THE RSS SIDE (user, 2026-08-14). On the AV path
                    # naming is EVIDENCE -- some articles name us, most do not, so +3
                    # discriminates. Here it is the ADMISSION CRITERION: derive_relevance
                    # scores anything that does not name the company at 0.35, below the
                    # 0.5 gate, so every surviving RSS item would earn the bonus. A
                    # constant across a whole population ranks nothing within it, and
                    # lifts all of it 3 points over AV's.
                    #
                    # Measured on DDOG 2026-08-14: three RSS pieces -- a valuation
                    # think-piece, a peer comparison and a Cramer segment, none of them
                    # analyst RATINGS, none a catalyst -- each scored 3.0 purely for
                    # saying "Datadog", while AV's one fresh item (an AI-software rally
                    # naming MongoDB, a listed peer) sat at -1.5. The bonus was worth
                    # more than the entire distance from `general` to `corp action`.
                    #
                    # Without it an RSS item competes on MATERIALITY alone, which is the
                    # point: AVEX's own earnings release still leads at tier 4, and
                    # generic commentary no longer outranks a sector story.
                    candidates.append({
                        "title": rtitle, "summary": "", "relevance": rrel,
                        "tier": rweight, "label": rlabel, "co_tagged": rco,
                        "leads": rleads, "named": rnamed, "top_ticker": ticker_symbol,
                        # gap is "how far behind the article's real subject we sit", which
                        # AV measures from its relevance scores. RSS supplies nothing to
                        # measure it with, so it stays 0.0 rather than carrying a number
                        # we made up.
                        "gap": 0.0,
                        "weight": rweight - rpenalty,
                        "source": "yahoo_rss",
                    })
                    r_kept += 1
                    continue

                # PEER READ-ACROSS (user, 2026-08-13). A headline that names none of our
                # aliases may still be a PEER's event, and the board already prices that
                # in: the derived peer-earnings block ranks at 2.5, which is tier-4
                # earnings minus SHARED_COVERAGE_PENALTY. Applying that same offset to
                # every tier generalises it -- a peer's corp action or FDA decision
                # reads across too, and dropping it was the whitelist's blind spot:
                #     earnings 4 -> 2.5    corp action / regulatory 3 -> 1.5
                #     business 2 -> 0.5    general 0 -> below zero, never admitted
                # The .5 is load-bearing (see the constant's own note): a peer item can
                # never TIE an own-ticker item, so the ordering is fully determined.
                hit = next((p for p, al in peer_aliases.items()
                            if derive_relevance(rtitle, p, al)[1]), None)
                if hit is None:
                    r_unnamed += 1
                    continue
                peer_tier = rweight - SHARED_COVERAGE_PENALTY
                if peer_tier <= 0:
                    r_unnamed += 1
                    continue
                # top_ticker is the PEER on purpose: it makes _band's in-window earnings
                # guard check whether THAT company actually reported, reusing the
                # existing mechanism rather than adding a second one. No such gate for
                # corp action / regulatory -- those headlines describe something that
                # just happened, where an earnings piece routinely rehashes an old one.
                candidates.append({
                    "title": rtitle, "summary": "", "relevance": 0.6,
                    "tier": peer_tier, "label": rlabel, "co_tagged": [(hit, 0.0)],
                    "leads": False, "named": False, "top_ticker": hit,
                    "gap": -0.10, "weight": peer_tier,
                    "source": "yahoo_rss", "peer": hit,
                })
                r_peer += 1
            if rss_items:
                print(f"[NEWS RSS] {ticker_symbol}: {len(rss_items)} items — "
                      f"{r_kept} kept, {r_peer} peer read-across, {r_stale} stale, "
                      f"{r_unnamed} not about us or peers")
        except Exception as e:
            # A supplement must never break the pull it supplements.
            print(f"[NEWS RSS] {ticker_symbol}: unavailable ({type(e).__name__}: {e}) "
                  f"— continuing on Alpha Vantage alone")

        if not candidates:
            # NO ARTICLES IS NOT A SUCCESSFUL PULL, and the derived context tiers below
            # do not change that (user, 2026-08-12). They are colour on a real pull,
            # never a substitute for one -- a card with nothing published against it
            # must go back to the 15:00 sweep and get a second look at the wire, not be
            # closed out on an earnings-calendar entry. So this returns BEFORE the
            # pseudo-candidates are built.
            print(f"[NEWS FRESH] {ticker_symbol}: nothing published since the prior "
                  f"close — not a successful pull, deferring.")
            return None, {"n_primary": 0, "n_catalyst": 0, "n_background": 0, "top_tier": -99}

        # --- DERIVED CONTEXT, RANKED ALONGSIDE THE ARTICLES -------------------
        # PEER EARNINGS AT TIER 2.5 (user, 2026-08-12: "peer related earnings are
        # definitely relevant"). Not appended unconditionally -- it COMPETES. Sitting
        # between business(2) and corp-action/regulatory/dilution(3) means a genuine
        # company event still outranks it, while an analyst note (1) does not. That is
        # the whole disagreement from earlier resolved by ranking rather than by a
        # suppression threshold.
        # DERIVED CONTEXT MUST NEVER BREAK THE ARTICLE PATH. Both builders read files
        # and call yfinance, and macro_regime.json in particular is model-authored with
        # a shape that changes between regenerations. A throw here used to propagate to
        # this function's outer handler, which returns AV_UNAVAILABLE — so a cosmetic
        # context failure discarded a PAID, successful article pull and left the card
        # to be retried a minute later. Context is a bonus; degrade to none.
        try:
            peer_block = peer_earnings_context(ticker_symbol)
        except Exception as e:
            print(f"[NEWS CONTEXT] {ticker_symbol}: peer-earnings unavailable "
                  f"({type(e).__name__}: {e}) — continuing without it")
            peer_block = None
        if peer_block:
            candidates.append({
                "title": f"{ticker_symbol} sector peers reported since the prior close",
                "summary": "", "relevance": 1.0, "tier": 2.5, "label": "peer earnings",
                "co_tagged": [], "leads": False, "named": False,
                "top_ticker": ticker_symbol, "gap": 0.0, "weight": 2.5,
                "raw": peer_block,
            })

        # MACRO AT TIER 1 (user, 2026-08-12). Ranked, not gated: it sits above tier-0
        # filler and the demoted filings, and below business(2), peer earnings(2.5) and
        # any real company event(3-4).
        #
        # THE TIER IS THE KNOB FOR THE HOMOGENEITY RISK, and it is the whole reason it
        # is not higher: a released macro print is true of every stock on the board at
        # once, so ranking it up would put the SAME sentence on every card and recreate
        # the "broader market concerns" failure the audit warned about -- the exact
        # shape of the insider-selling problem, one level up. At 1 it surfaces only on
        # cards whose own coverage is weak, which is precisely when a market-wide
        # explanation is the honest one. Move this number if the balance is wrong; it is
        # the single lever.
        #
        # An earlier draft gated this on "no other candidate at tier >= 0", which in
        # practice meant never -- tier 0 is the DEFAULT for anything unmatched, and one
        # live pool carried 15 of them, so CPI would have been suppressed on the very
        # day the engine's own briefing led with it.
        try:
            macro_block = macro_context()
        except Exception as e:
            print(f"[NEWS CONTEXT] {ticker_symbol}: macro context unavailable "
                  f"({type(e).__name__}: {e}) — continuing without it")
            macro_block = None
        if macro_block:
            candidates.append({
                "title": "Market-wide context", "summary": "", "relevance": 1.0,
                "tier": 1, "label": "macro", "co_tagged": [], "leads": False,
                "named": False, "top_ticker": ticker_symbol, "gap": 0.0,
                "weight": 1, "raw": macro_block,
            })

        # ABOUTNESS FIRST, then materiality, then how much of the article is really
        # about us, then relevance. The lead key is gated on tier >= 0 so a demoted
        # filing that happens to open with our ticker ("AMD Shares Sold by ...")
        # cannot ride it to the top. Measured: this moves the one genuinely relevant
        # article in a 50-item pool from 39th to 1st.
        candidates.sort(key=lambda c: (c["leads"] and c["tier"] >= 0,
                                       c["weight"], c["gap"], c["relevance"]),
                        reverse=True)

        # DEDUPE. Aggregators reprint the same story, and with only three slots a
        # duplicate is a slot spent saying nothing new. Observed 2026-08-11: DDOG's
        # feed gave the SAME CEO-share-sale piece twice, taking two of three slots.
        # Compared on a normalised title prefix -- reprints share a headline even
        # when the summary is reworded.
        # CORROBORATION (user, 2026-08-13): with two sources a duplicate stops being
        # pure waste. If the same story comes back from more than one feed at the same
        # tier, that is evidence it is the event worth reporting. So a duplicate is
        # MERGED and the survivor counts how many distinct sources carried it, instead
        # of being dropped and forgotten.
        #
        # What that number does NOT mean: several outlets rewriting one wire release
        # are not several confirmations, they are one fact echoed. It measures how much
        # the press CARED, not whether it is true -- so it ranks as a TIEBREAK among
        # equals below, never as a promoter across tiers.
        seen_titles, deduped = {}, []
        for c in candidates:
            key = re.sub(r"[^a-z0-9 ]", "", (c["title"] or "").lower())
            key = " ".join(key.split())[:60]
            if key and key in seen_titles:
                kept = seen_titles[key]
                src = c.get("source", "alpha_vantage")
                if src not in kept["sources"]:
                    kept["sources"].append(src)
                    kept["corroboration"] = len(kept["sources"])
                    print(f"[NEWS RANK] {ticker_symbol}: '{c['title'][:45]}...' also "
                          f"carried by {src} — corroboration {kept['corroboration']}")
                else:
                    print(f"[NEWS RANK] {ticker_symbol}: duplicate '{c['title'][:55]}...' — skipped")
                continue
            c["sources"] = [c.get("source", "alpha_vantage")]
            c["corroboration"] = 1
            if key:
                seen_titles[key] = c
            deduped.append(c)
        candidates = deduped

        # Re-rank now that corroboration is known — it cannot be part of the first
        # sort because it is only discovered by deduping, and deduping keeps the
        # best-ranked copy, which requires the first sort to have run. Inserted AFTER
        # weight so it separates equals and never lifts a story over a higher tier.
        candidates.sort(key=lambda c: (c["leads"] and c["tier"] >= 0, c["weight"],
                                       c.get("corroboration", 1), c["gap"],
                                       c["relevance"]),
                        reverse=True)

        # --- BANDS ------------------------------------------------------------
        # Tiers exist to PRIORITISE by likely price impact, not to delete coverage:
        # a low-tier item still carries information worth knowing (user, 2026-08-12).
        # So nothing is cut for being low-tier -- each article is LABELLED instead,
        # and the prompt is told which band may be offered as a cause. This
        # generalises a mechanism already in this file: the "routine filing ...
        # background only" note did exactly this for one case.
        #
        #   PRIMARY     may be offered as the cause of the move.
        #   BACKGROUND  awareness only; never the explanation.
        #
        # Two things can make an article PRIMARY. A real, dated catalyst (tier > 0),
        # or ABOUTNESS -- our ticker opening the headline, which rescues a piece
        # plainly about this company whose wording missed every catalyst keyword.
        # A demoted filing is background no matter how it is worded.
        def _band(c):
            if c["tier"] < 0:
                return "BACKGROUND"
            if c["tier"] > 0:
                # An earnings claim must be backed by an event INSIDE the window.
                # Publication freshness is not event freshness: every article in one
                # measured pool was published today while the results they described
                # were a median of 14 days old (oldest 93), and one was a notice about
                # a report still a week in the FUTURE.
                if c["label"] == "earnings" and not _reported_in_window(c["top_ticker"]):
                    print(f"[NEWS BAND] {ticker_symbol}: '{c['title'][:45]}...' claims "
                          f"earnings but {c['top_ticker']} did not report in-window")
                    return "BACKGROUND"
                # ABOUTNESS. A catalyst tier says what KIND of event this is, never whose
                # company it happened to. An article whose own subject is someone else can
                # still be useful sector context -- it just cannot be offered as the cause
                # of THIS ticker's move. See _is_about_us for the case that prompted it.
                if not _is_about_us(c, ticker_symbol):
                    print(f"[NEWS BAND] {ticker_symbol}: '{c['title'][:45]}...' is about "
                          f"{c.get('top_ticker')}, not {ticker_symbol} — background only")
                    return "BACKGROUND"
                return "PRIMARY"
            if c["label"] == "macro":
                # Only ever present when nothing else reached tier 0, so the choice is
                # this or silence. Usable as an explanation -- but its own NOTE forces
                # the attribution to be market-wide, never company-specific.
                return "PRIMARY"
            # tier 0 is BACKGROUND here. Aboutness can still promote it, but only as a
            # LAST RESORT -- see the promotion pass below.
            return "BACKGROUND"

        def _why(c):
            """tier + modifier = total, so an effective weight is always traceable
            back to an authored number rather than appearing from nowhere."""
            share = f" shared(-{SHARED_COVERAGE_PENALTY})" if c["co_tagged"] else ""
            lead = " LEADS" if c["leads"] else ""
            return (f"{c['label']}({c['tier']}){share}{lead} = {c['weight']}, "
                    f"rel={c['relevance']:.2f}, gap={c['gap']:+.2f}")

        # Band a bounded slice, then fill the three slots PRIMARY-FIRST. Banding has to
        # happen BEFORE selection or a high-tier background item -- an "expected to
        # announce earnings" notice, say -- takes a slot from an article that could
        # actually explain the move. The slice is bounded because the earnings gate
        # costs a calendar lookup per candidate; six is enough to fill three slots even
        # when every leader turns out to be background.
        BAND_POOL = 6
        banded = [(c, _band(c)) for c in candidates[:BAND_POOL]]

        # ABOUTNESS PROMOTION — last resort only. An article whose headline OPENS with
        # our ticker is plainly about this company, and dropping it to background just
        # because its wording missed every catalyst keyword would lose the one piece
        # actually on topic. But promoting it unconditionally lets SEO filler
        # ("AMD Stock: 3 Things To Watch This Week") be offered as a cause, so it only
        # applies when nothing else earned PRIMARY on its own merits.
        if not any(b == "PRIMARY" for _, b in banded):
            promoted = [(c, "PRIMARY" if (c["leads"] and c["tier"] >= 0) else b)
                        for c, b in banded]
            if any(b == "PRIMARY" for _, b in promoted):
                print(f"[NEWS BAND] {ticker_symbol}: no catalyst found — promoting a "
                      f"headline that leads with the ticker")
                banded = promoted

        ordered = ([x for x in banded if x[1] == "PRIMARY"] +
                   [x for x in banded if x[1] == "BACKGROUND"])
        chosen = ordered[:3]
        dropped = [c for c, _ in ordered[len(chosen):]] + candidates[BAND_POOL:]

        for c in dropped:
            print(f"[NEWS RANK] {ticker_symbol}: below the cut '{c['title'][:55]}...' [{_why(c)}]")

        headlines, n_primary, n_catalyst, top_tier = [], 0, 0, -99
        for c, band in chosen:
            n_primary += (band == "PRIMARY")
            # A CATALYST is a PRIMARY that earned it on materiality, not one promoted
            # by aboutness as a last resort. The peer-earnings fallback keys off this
            # rather than n_primary, so a "3 Things To Watch" piece cannot suppress a
            # genuine sector explanation just by leading with the ticker.
            n_catalyst += (band == "PRIMARY" and c["tier"] > 0)
            if band == "PRIMARY":
                top_tier = max(top_tier, c["tier"])
            print(f"[NEWS RANK] {ticker_symbol}: chose [{band}] '{c['title'][:50]}...' [{_why(c)}]")
            notes = []
            if c.get("peer"):
                # A peer ARTICLE needs firmer framing than a co-tag note: this headline
                # is ABOUT another company, and the model will otherwise write "Pfizer
                # announced" off an AbbVie headline. Same rule the derived peer block
                # carries, stated harder because an article invites the mistake more.
                notes.append(
                    f"This is {c['peer']}'s news, NOT {ticker_symbol}'s — sector "
                    f"read-across only. Attribute it to the sector, and never state or "
                    f"imply {ticker_symbol} did this.")
            elif c["co_tagged"]:
                peers = ", ".join(tk for tk, _ in c["co_tagged"][:5] if tk)
                notes.append(f"Also covers {peers} — may indicate a sector-wide move "
                             f"rather than a company-specific one.")
            if c["tier"] < 0:
                notes.append("Routine filing/position disclosure.")
            if band == "BACKGROUND":
                notes.append("BACKGROUND ONLY — informational context. Do NOT present "
                             "this as the cause of the move.")
            note = ("\nNOTE: " + " ".join(notes)) if notes else ""
            if c.get("raw"):
                # A derived context block carries its own framing and guard text; it is
                # not an article and must not be dressed as one with a Relevance line.
                headlines.append(f"[{band}] {c['raw']}")
            else:
                headlines.append(
                    f"[{band}] Headline: {c['title']}\nSummary: {c['summary']}\n"
                    f"Relevance: {c['relevance']:.2f}{note}"
                )

        if not headlines:
            return None, {"n_primary": 0, "n_catalyst": 0, "n_background": 0, "top_tier": -99}
        # WHICH SOURCES ACTUALLY CONTRIBUTED. Without this the two-source pool is
        # unauditable: DDOG's 2026-08-14 pull chose two headlines that BOTH feeds could
        # plausibly have supplied, and nothing in the card, the cache or the prompt
        # recorded which one did -- so "is the RSS source earning its place?" could not
        # be answered from the artifacts at all. Derived from the CHOSEN items, not the
        # pool, because a source that only ever supplies also-rans is not contributing.
        picked_sources = []
        for c, _b in chosen:
            for s in (c.get("sources") or [c.get("source")] or []):
                if s and s not in picked_sources:
                    picked_sources.append(s)
        # POOL COMPOSITION (added 2026-08-17). Every number here was already computed
        # while filtering and then thrown away when the function returned -- so "how many
        # articles did each feed supply?" could not be answered from any artifact, and the
        # source of a CHOSEN item had to be inferred from the absence of a summary. The
        # counters existed; nothing preserved them.
        #
        # `kept` is what entered the ranking pool, not what was fetched: an AV pull of 50
        # with 1 fresh and an RSS pull of 12 with 4 fresh are very different situations
        # that both read as "Alpha Vantage + Yahoo RSS" today.
        av_kept = sum(1 for c in candidates if c.get("source", "alpha_vantage") == "alpha_vantage")
        pool = {
            "alpha_vantage": {"raw": len(feed), "kept": av_kept,
                              "stale": stale, "undated": undated},
            "yahoo_rss": {"raw": rss_raw, "kept": r_kept, "peer": r_peer,
                          "stale": r_stale, "unnamed": r_unnamed},
        }
        return "\n---\n".join(headlines), {
            "n_primary": n_primary, "n_catalyst": n_catalyst, "top_tier": top_tier,
            "n_background": len(headlines) - n_primary,
            "sources": picked_sources,
            "pool": pool,
            # Per-CHOSEN-item source, in slot order. `sources` says which feeds
            # contributed at all; this says which feed supplied which headline, which is
            # what actually settles "is RSS earning its place" without deduction.
            "chosen_sources": [c.get("source", "alpha_vantage") for c, _ in chosen],
            "corroborated": sum(1 for c, _ in chosen if (c.get("corroboration") or 1) > 1)}

    except Exception as e:
        # WHERE the failure happened decides whether retrying is sane.
        #
        # AFTER a successful response, this is OUR bug: the call was spent, real
        # articles came back, and we crashed formatting them. It is deterministic —
        # retrying crashes identically and spends another call every time. That is
        # exactly what drained the budget on 2026-08-12: a macro-context crash was
        # reported as "Alpha Vantage unavailable" and retried once a minute.
        # Not retryable; surface it loudly as the code fault it is.
        #
        # BEFORE a response (timeout, DNS, connection reset), the wire genuinely failed
        # and a later attempt may well succeed. Retryable, with backoff.
        #
        # Neither case returns None: writing "no news surfaced today" off a failure
        # would be a false statement about the market and would pollute the count of
        # that string.
        if got_response:
            print(f"[NEWS BUG] {ticker_symbol}: crashed AFTER a good Alpha Vantage "
                  f"response — {type(e).__name__}: {e}. Call spent, articles discarded. "
                  f"NOT retryable (it would fail the same way); fix the code path.")
            return AV_UNAVAILABLE, {"retryable": False}
        print(f"[NEWS ERROR] Alpha Vantage fetch failed for {ticker_symbol} before any "
              f"response: {type(e).__name__}: {e}")
        return AV_UNAVAILABLE, {"retryable": True}

def search_and_synthesize_fallback(ticker, opt_data, pct_change):
    """
    Two-turn search-and-synthesize fallback for when Alpha Vantage has no news.
    Matches the pattern used in market_data_engine_claude.py.
    Turn 1: web search for the catalyst.
    Turn 2: structured JSON synthesis using text summary only (raw search blocks stripped).
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return {"why": "API Key Missing.", "structure": "N/A", "impact": "N/A"}

    with fallback_semaphore:
        claude_limiter.wait_for_slot(estimated_tokens=8000)

        search_prompt = (
            f"What's driving the {pct_change}% move in {ticker} during the most recent trading session? "
            f"Do not answer from memory — search for today's news before responding. "
            f"Focus on company-specific catalysts: earnings, guidance, analyst actions, product news, "
            f"regulatory decisions, executive commentary. Summarize your findings in 3-5 sentences."
        )

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        search_payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": search_prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
        }

        try:
            response = requests.post(url, headers=headers, json=search_payload, timeout=45)

            if response.status_code == 429:
                print(f"[RATE LIMIT] {ticker}: waiting 30s...")
                time.sleep(30)
                response = requests.post(url, headers=headers, json=search_payload, timeout=45)

            result = response.json()

            if 'error' in result:
                print(f"[SEARCH ERROR] {ticker}: {result['error'].get('message', 'Unknown')}")
                return {"why": f"Search failed: {result['error'].get('message')}", "structure": "N/A", "impact": "N/A"}

            t1_usage = result.get('usage', {})
            t1_in = t1_usage.get('input_tokens', 0)
            t1_out = t1_usage.get('output_tokens', 0)
            print(f"[TOKENS] {ticker} Turn 1 (search):    in={t1_in:,}  out={t1_out:,}")
            claude_limiter.record_usage(t1_in + t1_out)

            block_types = [b.get('type') for b in result.get('content', [])]
            print(f"[SEARCH DEBUG] {ticker} response blocks: {block_types}")
            if not any(t in ('server_tool_use', 'web_search_tool_result') for t in block_types):
                print(f"[SEARCH DEBUG] {ticker}: model did not invoke web_search.")

            # Strip raw search blocks — keep only text summary for Turn 2
            summary_only = [b for b in result.get('content', []) if b.get('type') == 'text']

            claude_limiter.wait_for_slot(estimated_tokens=t1_in + t1_out)

            # opt_data is None for a volume-triggered name with no listed options
            # chain (e.g. a micro-cap on a volume spike) — build a volume/price
            # prompt instead of indexing options fields that don't exist.
            if opt_data:
                options_block = (
                    f"Options Structure Data for {ticker}:\n"
                    f"- Put Wall: {opt_data['put_wall']}\n"
                    f"- Call Wall: {opt_data['call_wall']}\n"
                    f"- ATM IV: {opt_data['atm_iv']}%\n\n"
                )
                structure_key = '"structure": 1-2 sentence options mechanics explanation.\n'
            else:
                options_block = (
                    f"{ticker} has no listed options chain — this is a volume/price-driven "
                    f"move, not an options signal.\n\n"
                )
                structure_key = '"structure": 1-2 sentence on what the volume/price action implies.\n'

            synthesis_prompt = (
                f"Based on your search findings above, synthesize"
                f"{' with the options data' if opt_data else ''} "
                f"and return ONLY a valid JSON object with exactly three keys — no preamble, no markdown fences:\n\n"
                f"{options_block}"
                f'"why": 2-3 sentence company-specific reason. Say so plainly if insufficient.\n'
                f"{structure_key}"
                f'"impact": 1-2 sentence actionable trading rule.'
            )

            synthesis_payload = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "messages": [
                    {"role": "user", "content": search_prompt},
                    {"role": "assistant", "content": summary_only},
                    {"role": "user", "content": synthesis_prompt}
                ]
            }

            synth_response = requests.post(url, headers=headers, json=synthesis_payload, timeout=30)

            if synth_response.status_code == 429:
                print(f"[RATE LIMIT] {ticker}: waiting 30s on synthesis...")
                time.sleep(30)
                synth_response = requests.post(url, headers=headers, json=synthesis_payload, timeout=30)

            synth_result = synth_response.json()

            if 'error' in synth_result:
                print(f"[SYNTHESIS ERROR] {ticker}: {synth_result['error'].get('message', 'Unknown')}")
                return {"why": f"Synthesis failed: {synth_result['error'].get('message')}", "structure": "N/A", "impact": "N/A"}

            t2_usage = synth_result.get('usage', {})
            t2_in = t2_usage.get('input_tokens', 0)
            t2_out = t2_usage.get('output_tokens', 0)
            total_in = t1_in + t2_in
            total_out = t1_out + t2_out
            print(f"[TOKENS] {ticker} Turn 2 (synthesis): in={t2_in:,}  out={t2_out:,}")
            print(f"[TOKENS] {ticker} TOTAL:              in={total_in:,}  out={total_out:,}  "
                  f"(est. cost: ${(total_in * 0.000001) + (total_out * 0.000005):.5f})")

            text = "".join(
                b.get('text', '') for b in synth_result.get('content', []) if b.get('type') == 'text'
            )
            if text:
                text = text.replace('```json', '').replace('```', '').strip()
                return json.loads(text)

            print(f"[SYNTHESIS ERROR] {ticker}: no text in synthesis response.")
            return {"why": "Synthesis returned no data.", "structure": "N/A", "impact": "N/A"}

        except json.JSONDecodeError as e:
            print(f"[SYNTHESIS ERROR] {ticker}: JSON parse failed - {e}")
            return {"why": "Synthesis output was not valid JSON.", "structure": "N/A", "impact": "N/A"}
        except Exception as e:
            print(f"[SYNTHESIS ERROR] {ticker}: {e}")
            return {"why": "Synthesis failed or timed out.", "structure": "N/A", "impact": "N/A"}

def generate_ai_synthesis(ticker, opt_data, news_text, pct_change):
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return {"why": "API Key Missing.", "structure": "N/A", "impact": "N/A"}

    claude_limiter.wait_for_slot()

    # opt_data is None for a volume-triggered name with no listed options chain —
    # drop the options mechanics from the prompt rather than indexing fields that
    # don't exist (would crash a volume-only synthesis on a micro-cap).
    # DIRECTION MUST BE STATED, NOT INFERRED (2026-08-12). `pct_change` is signed, but
    # a POSITIVE value rendered as "has just moved 3.01%" — a sentence containing no
    # directional word at all — leaving the model to infer up-or-down from the tone of
    # whatever article it was handed. The asymmetry was measured on one day's board:
    # all three DOWN moves were narrated correctly, because the minus sign carried the
    # direction; of six UP moves, four refused to state a direction and the one that
    # committed got it BACKWARDS. INTC's card read "Intel's 4.6% decline is directly
    # driven by the $20 billion capital raise" on a +3.01% day, having inherited
    # "Slips" from its top headline. Naming the direction removes the inference.
    direction = "RISEN" if pct_change >= 0 else "FALLEN"
    magnitude = abs(pct_change)

    if opt_data:
        # The put-premium relationship is deliberately NOT stated here (user,
        # 2026-08-12). The 1-sigma breach is a FILTER for deciding what is worth
        # looking at, not content for the narrative — the premium is already on the
        # card. Asserting it was also becoming false: the clause was hardcoded as
        # "exceeding", but a card keeps its trigger while the price drifts back, so
        # AMD's prompt claimed 3.03% "exceeded" a 3.48% premium. PM, KHC and DDOG were
        # all in the same state that day. The move and its direction are what the
        # synthesis needs; whether it still exceeds is not the model's question.
        move_line = f"The stock {ticker} has just {direction} {magnitude}%."
        options_block = (
            "\nOptions Structure Data:\n"
            f"- Put Wall (Highest OI): {opt_data['put_wall']}\n"
            f"- Call Wall (Highest OI): {opt_data['call_wall']}\n"
            f"- ATM Put Premium Implied Volatility: {opt_data['atm_iv']}%\n"
        )
        structure_key = '"structure": A 1-2 sentence explanation of the options mechanics.'
    else:
        move_line = f"The stock {ticker} has just {direction} {magnitude}% on a volume spike and has no listed options chain."
        options_block = ""
        structure_key = '"structure": A 1-2 sentence explanation of what the volume/price action implies (no options data available).'

    prompt = f"""You are an elite quantitative market analyst.
{move_line}
{options_block}
Latest News:
{news_text}

Each item is tagged [PRIMARY] or [BACKGROUND]. ONLY a [PRIMARY] item may be offered as
the cause of the move. [BACKGROUND] items are context you may mention for awareness —
never as the explanation. An item marked as a routine filing or position disclosure is
never a cause. If a CONTEXT block from the earnings calendar is present, it states only
THAT a company reported, never how: do not assert or imply results you were not given.
If nothing here can explain the move, say so plainly.

Synthesize this data and return ONLY a valid JSON object with EXACTLY these three keys, and nothing else - no preamble, no markdown fences:
"why": A 2-3 sentence fundamental or news-driven reason for the move, drawn from the [PRIMARY] items. If there are none, or they do not account for the move, say so plainly rather than speculating.
{structure_key}
"impact": A strict 1-2 sentence actionable trading rule or portfolio impact warning."""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 429:
            print(f"[RATE LIMIT] Hit limit for {ticker}. Waiting 30s to recover...")
            time.sleep(30)
            response = requests.post(url, headers=headers, json=payload, timeout=30)

        result = response.json()

        if 'error' in result:
            print(f"\n[API ERROR] for {ticker}: {result['error'].get('message', 'Unknown Error')}")
            return {"why": f"API Error: {result['error'].get('message')}", "structure": "Failed", "impact": "Failed"}

        content_blocks = result.get('content', [])
        text = "".join(
            block.get('text', '') for block in content_blocks if block.get('type') == 'text'
        )
        if text:
            text = text.replace('```json', '').replace('```', '').strip()
            return json.loads(text)

        print(f"[AI STRUCTURE ERROR] {ticker}: Unexpected response structure.")
        return {"why": "Synthesis returned no data.", "structure": "N/A", "impact": "N/A"}

    except Exception as e:
        print(f"\n[SYNTHESIS ERROR] Failed parsing for {ticker}: {e}")
        return {"why": "Synthesis failed or timed out.", "structure": "N/A", "impact": "N/A"}

# --- Options Analysis (SIMPLIFIED PREMIUM METHOD) ---
def analyze_options_structure(ticker_symbol, current_price):
    try:
        stock = yf.Ticker(ticker_symbol)
        expirations = stock.options
        if not expirations: return None

        # 1. Require DTE > MIN_DTE_CALENDAR_DAYS, not merely > 0.
        #
        # The 1-sigma bound is the ATM put premium as a % of price, so a near-dated
        # chain produces a tiny bound and almost everything breaches it -- too many
        # tickers came through on a given day (user, 2026-08-10). It also made the
        # threshold a lottery on WHICH expiry happened to be nearest: a name with
        # weeklies expiring tomorrow was held to a far lower bar than one whose next
        # expiry was the monthly ten days out, for no reason related to the stock.
        #
        # Pushing the floor out equalises that and raises the bar to moves that are
        # genuinely noteworthy. Calendar days, not trading days -- the premium decays
        # over the weekend too.
        cutoff = (datetime.today() + timedelta(days=MIN_DTE_CALENDAR_DAYS)).strftime('%Y-%m-%d')
        valid_exps = [exp for exp in expirations if exp > cutoff]

        if not valid_exps:
            # NOT a thin-options case -- this branch is effectively unreachable in
            # normal operation. Every optionable US name carries monthlies and LEAPS:
            # checked 2026-08-10, the sparsest tickers on the watchlist (ENB 5
            # expirations, SFIX 6) still had ALL of them beyond 7 DTE, out to 2028.
            # So reaching here means yfinance returned a truncated or stale list --
            # a data failure, not a market condition. Skip rather than fall back to a
            # near-dated chain, which would reintroduce the low bar this removes.
            print(f"[OPTIONS] {ticker_symbol}: expiration list looks degenerate — "
                  f"nothing beyond {MIN_DTE_CALENDAR_DAYS} DTE in {list(expirations)[:5]}. "
                  f"Treating as a data failure and skipping.")
            return None

        # 2. Nearest expiration that clears the DTE floor
        nearest_exp = valid_exps[0]
        opt_chain = stock.option_chain(nearest_exp)
        puts, calls = opt_chain.puts, opt_chain.calls

        # 3. Find the ATM Put and extract its premium price
        atm_put = puts.iloc[(puts['strike'] - current_price).abs().argsort()[:1]]
        if atm_put.empty: 
            return None

        atm_put_price = float(atm_put['lastPrice'].values[0])
        bid = float(atm_put['bid'].values[0]) if 'bid' in atm_put.columns else 0
        ask = float(atm_put['ask'].values[0]) if 'ask' in atm_put.columns else 0
        if bid > 0 and ask > 0:
            atm_put_price = (bid + ask) / 2  # use mark price — lastPrice is stale
        
        # Calculate what percentage of the stock price that premium represents
        expected_move_pct = (atm_put_price / current_price) * 100

        # Wall Logic: Retained for the AI to understand market structure
        otm_puts = puts[puts['strike'] < current_price]
        put_wall_strike = float(otm_puts.loc[otm_puts['openInterest'].idxmax()]['strike']) if not otm_puts.empty else None

        otm_calls = calls[calls['strike'] > current_price]
        call_wall_strike = float(otm_calls.loc[otm_calls['openInterest'].idxmax()]['strike']) if not otm_calls.empty else None

        return {
            "expected_move_pct": round(expected_move_pct, 2),
            "atm_strike": round(float(atm_put['strike'].values[0]), 2),
            "atm_put_price": round(atm_put_price, 2),
            "atm_expiration": nearest_exp,
            "put_wall": put_wall_strike,
            "call_wall": call_wall_strike,
            "atm_iv": round(float(atm_put['impliedVolatility'].values[0]) * 100, 2)
        }
    except Exception as e:
        print(f"Debug: Options analysis failed for {ticker_symbol}: {e}")
        return None

# --- Price History (chart tab): extracted to engine/price_history.py
#     (Blueprint; 2026-07-20 engine split phase 2 — get_asset_class, the cache
#     helpers, and /get_price_history all live there now). ---

# --- Endpoints ---
# --- /get_market_data + ticker-management routes: extracted to engine/market.py
#     (Blueprint; 2026-07-22 split phase 4). ---

@app.route('/get_actionable_moves', methods=['GET'])
def get_actionable_moves():
    if os.path.exists(ACTIONABLE_FILE):
        try:
            with open(ACTIONABLE_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

@app.route('/dismiss_actionable', methods=['POST'])
def dismiss_actionable():
    """Remove a single actionable card by ticker (user dismiss — e.g. an
    --as-of-date test card, or any card they want cleared). Goes through
    actionable_file_lock so it can't race the engine's own patch writes."""
    ticker = (request.json or {}).get('ticker', '').upper()
    dismissed = False
    with actionable_file_lock:
        current = get_actionable_moves_local()
        if ticker in current:
            del current[ticker]
            with open(ACTIONABLE_FILE, 'w') as f:
                json.dump(current, f)
            dismissed = True
    if dismissed:
        print(f"[DISMISS] {ticker} card removed by user.")
    return jsonify({"status": "success", "dismissed": dismissed, "ticker": ticker})

# --- Newsletter ingestion + trade-quote routes: extracted to engine/newsletter.py
#     (Blueprint; 2026-07-13 engine split phase 1). Self-contained, no circular import. ---
from engine.newsletter import bp as newsletter_bp
app.register_blueprint(newsletter_bp)

# --- Price-history route: extracted to engine/price_history.py
#     (Blueprint; 2026-07-20 engine split phase 2). Same pattern. ---
from engine.price_history import bp as price_history_bp
app.register_blueprint(price_history_bp)

# --- Macro regime: extracted to engine/macro.py (Blueprint + background loop;
#     2026-07-21 split phase 3). First phase to move a thread, so it exports a
#     starter too — start_macro_loop() is called from __main__ below. ---
from engine.macro import bp as macro_bp, start_macro_loop
app.register_blueprint(macro_bp)

# --- Market data + ticker management: extracted to engine/market.py
#     (Blueprint; 2026-07-22 split phase 4). Routes only, no thread —
#     fetch_loop still produces what they serve. ---
from engine.market import bp as market_bp
app.register_blueprint(market_bp)

# --- AI Bubble Stoplight: self-contained package (stoplight/), same pattern.
# Endpoint serves persisted state only; the scheduler thread (started in
# __main__) does all computing. See .claude/rules/stoplight-build.md.
from stoplight import bp as stoplight_bp, start_scheduler as start_stoplight_scheduler
app.register_blueprint(stoplight_bp)

# --- Rocket Strategy: the left panel's Fed-dial status (engine/strategy.py,
# Blueprint, routes only). No thread — the dial is TTL-cached in-process and
# recomputed on demand, since the dial's series prints once a business day. ---
from engine.strategy import bp as strategy_bp
app.register_blueprint(strategy_bp)

# --- Per-ticker news archive: the history behind the "Why" box. Reads what the
# engine already writes (archive/*.json + the live card) — no new capture. ---
from engine.news_archive import bp as news_archive_bp
app.register_blueprint(news_archive_bp)


# --- Market Hours: ET + market_state() promoted to engine/common.py (split
#     phase 3) — fetch_loop and the macro blueprint both need them. ---
from engine.common import ET, market_state, DATA_FILE, TICKERS_FILE, get_tickers, save_tickers

# --- Data Fetching Loop ---
def get_turtle_snapshot(ticker, stock, today):
    """Today's cached Turtle snapshot for `ticker`, computing the heavy 5y pull at
    most once per trading day. Caches None too (insufficient history / data gap) so
    a non-eligible ticker isn't re-pulled every pass."""
    entry = _turtle_cache.get(ticker)
    if entry and entry["date"] == today:
        return entry["snapshot"]
    snap = compute_turtle_snapshot(stock)
    _turtle_cache[ticker] = {"date": today, "snapshot": snap}
    return snap

def run_turtle_asof(ticker, as_of):
    """--as-of-date test injection: evaluate the Turtle trigger for `ticker` as if
    `as_of` (a date) were today, using REAL history through that date, and write a
    real card via patch_actionable_move if a breakout fired — same path as live.
    Lets a rare breakout be summoned from history for on-demand UI verification."""
    stock = yf.Ticker(ticker)
    start = (as_of - timedelta(days=int(5.5 * 365))).isoformat()
    end = (as_of + timedelta(days=1)).isoformat()  # yfinance end is exclusive
    hist = stock.history(start=start, end=end)
    if hist.empty:
        print(f"[AS-OF] No history for {ticker} through {as_of}.")
        return
    highs = [float(x) for x in hist['High'].tolist()]
    lows = [float(x) for x in hist['Low'].tolist()]
    closes = [float(x) for x in hist['Close'].tolist()]
    snap = snapshot_from_series(highs, lows, closes)
    if not snap:
        print(f"[AS-OF] Not enough history for {ticker} through {as_of} (need ~57+ sessions).")
        return
    price = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else price
    direction = detect_breakout(price, snap['channel_high'], snap['channel_low'])
    if not direction:
        print(f"[AS-OF] {ticker} as of {as_of}: NO breakout — close {price:.2f} is inside the "
              f"55-day channel [{snap['channel_low']:.2f} .. {snap['channel_high']:.2f}].")
        return
    meta = turtle_signal_metrics(snap, direction)
    pct = ((price - prev) / prev * 100) if prev else 0.0
    arrow = "↑" if direction == "long" else "↓"
    card = {
        "name": ticker,
        "conditions": ["turtle-trade"],
        "condition_meta": {"turtle-trade": meta},
        "price": f"${price:,.2f}",
        "price_change": round(pct, 2),
        "status": f"AS-OF {as_of} - Turtle {direction.capitalize()} Breakout",
        "why": f"[TEST as of {as_of}] 55-day {direction} breakout {arrow} (Turtle System 2).",
        "structure": f"Breakout {meta['breakout_level']:.2f} · N={meta['atr']:.2f} · stop {meta['suggested_stop']:.2f}.",
        "impact": "Test injection — open the card's Trade Data for pyramid + historical stats.",
    }
    patch_actionable_move(ticker, card)
    s = meta['stats']
    print(f"[AS-OF] {ticker} {direction} breakout @ {meta['breakout_level']:.2f} (close {price:.2f}) — card written.")
    print(f"        N={meta['atr']:.2f}  stop={meta['suggested_stop']:.2f}  20d-exit={meta['opposite_channel']:.2f}  "
          f"pyramid={[round(x, 2) for x in meta['pyramid']]}")
    print(f"        {direction} 5y history: {s['n_success']}W/{s['n_fail']}L  "
          f"exp {s['expectancy_R']:+.2f}R  avg {s['avg_units']:.1f}u")


def price_refresh_slot(now):
    """Identify the current :30 price-refresh window as a once-per-window key, or
    None outside it.

    Window is [:30,:45) — deliberately DISJOINT from the volume sweep's [:15,:30)
    and [:45,:60) so the two cadences never land in the same window — and wide
    enough that a 60s poll can't miss it. Yields one refresh per hour at :30
    (9:30, 10:30, 11:30, ... 15:30) while the market is open.
    """
    return (now.date(), now.hour, 30) if 30 <= now.minute < 45 else None


def fetch_loop(test_mode=False):
    last_seen_date = datetime.now(ET).date()
    last_volume_slot = None  # last :15/:45 window the 2x-volume sweep ran in
    last_price_slot = None   # last :30 window the card price-refresh ran in

    if test_mode:
        print("[TEST MODE] Market hours guard disabled. Using last two trading session closes for price data.")

    while True:
        now_et = datetime.now(ET)
        current_date = now_et.date()
        state = market_state()

        # Midnight rollover — only on weekday transitions (Mon-Fri) and
        # the specific Sunday→Monday midnight. Skip Fri→Sat and Sat→Sun.
        if current_date != last_seen_date:
            weekday = current_date.weekday()  # 0=Mon, 6=Sun
            should_clear = weekday not in (5, 6)  # not Saturday or Sunday
            if should_clear:
                clear_actionable_moves(
                    reason=f"midnight rollover to {current_date}",
                    archive_date=last_seen_date,
                    clear_news_too=True
                )
                print(f"[MARKET] Slate cleared for {current_date} ({state})")
            else:
                print(f"[MARKET] Weekend — skipping midnight clear ({current_date})")
            last_seen_date = current_date

        # Outside active hours — skip unless in test mode.
        if not test_mode and state in ("closed", "after_hours"):
            if state == "closed":
                print(f"[MARKET] Market closed — idling until 8:00am ET.")
            else:
                print(f"[MARKET] After hours — dashboard static until midnight.")
            time.sleep(60)
            continue

        # 2x-volume sweep runs only at the :15/:45 cadence during open hours —
        # its 50-day + intraday history pulls are heavier than the 60s price
        # check, so it is NOT run every pass (turtle-volume-indicators.md).
        volume_slot = volume_check_slot(now_et) if state == "open" else None
        run_volume = volume_slot is not None and volume_slot != last_volume_slot

        # Hourly :30 re-stamp of live price onto cards that already exist.
        # Open hours only — matches the volume sweep's gate.
        price_slot = price_refresh_slot(now_et) if state == "open" else None
        run_price_refresh = price_slot is not None and price_slot != last_price_slot

        tickers = get_tickers()
        market_data = {}
        newly_triggered = {}

        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="5d", prepost=True)

                if len(hist) >= 2:
                    if test_mode:
                        # Test mode: always use the last two actual trading
                        # session closes — reproducible, no market-open dependency.
                        current_price = float(hist['Close'].iloc[-1])
                        prev_close    = float(hist['Close'].iloc[-2])
                        session_label = "test"
                    elif state == "pre_market":
                        # Current pre-market price = last close of a 1-minute
                        # intraday pull (prepost=True) — the same robust chart
                        # endpoint the regular-price path uses. NOT
                        # stock.info['preMarketPrice']: .info scrapes Yahoo's
                        # quoteSummary endpoint, which under a long-lived engine
                        # session throttles/times out (curl 28) or returns None
                        # during pre-market, silently dropping the ticker before
                        # the trigger is ever evaluated. The daily `hist` has no
                        # pre-market bar, so the live pre-market print lives only
                        # in the 1m series. See SESSIONS.md session 26 /
                        # CONTEXT.md pending_fixes (2026-07-14).
                        intraday = stock.history(period="1d", interval="1m", prepost=True)
                        if intraday.empty:
                            market_data[ticker] = {
                                "price": f"${float(hist['Close'].iloc[-1]):,.2f}",
                                "change": "pre-mkt",
                                "is_positive": None,
                                "session": state
                            }
                            continue
                        current_price = float(intraday['Close'].iloc[-1])
                        # Prev close (the 1σ anchor) stays on the 5-day clean
                        # regular-session daily pull — the multi-day window is
                        # needed to find the last regular close across weekends/
                        # holidays; prepost=True hist can carry a pre-market bar
                        # as iloc[-1]. UNCHANGED by the 2026-07-14 fix.
                        clean_hist = stock.history(period="5d", prepost=False)
                        # Last VALID regular-session close. In pre-market yfinance
                        # appends TODAY's (empty) regular-session daily bar with a NaN
                        # close, so a raw iloc[-1] is NaN -> pct_change NaN -> "nan%"
                        # on the card (hit ~2/3 of the watchlist 2026-07-15). dropna()
                        # takes yesterday's real close — the correct pre-market anchor.
                        clean_closes = clean_hist['Close'].dropna() if not clean_hist.empty else None
                        if clean_closes is None or clean_closes.empty:
                            market_data[ticker] = {
                                "price": f"${current_price:,.2f}",
                                "change": "pre-mkt",
                                "is_positive": None,
                                "session": state
                            }
                            continue
                        prev_close    = float(clean_closes.iloc[-1])
                        session_label = state
                    else:
                        current_price = float(hist['Close'].iloc[-1])
                        prev_close    = float(hist['Close'].iloc[-2])
                        session_label = state

                    pct_change = ((current_price - prev_close) / prev_close) * 100

                    market_data[ticker] = {
                        "price": f"${current_price:,.2f}",
                        "change": f"{pct_change:+.2f}%",
                        "is_positive": bool(pct_change >= 0),
                        "session": session_label
                    }

                    opt_data = analyze_options_structure(ticker, current_price)

                    # --- Additive trigger evaluation --------------------------
                    # Each independent trigger that fires appends its tag to
                    # `fired`; a ticker gets ONE card carrying the union of its
                    # conditions (turtle-volume-indicators.md). The 2x-volume
                    # sweep only runs at the :15/:45 cadence (run_volume).
                    fired = []
                    if opt_data and abs(pct_change) > opt_data['expected_move_pct'] and abs(pct_change) >= MIN_ABSOLUTE_TRIGGER_PCT:
                        fired.append("1-sigma")

                    volume_ratio_val = None
                    if run_volume:
                        vratio = compute_volume_ratio(stock, today=now_et.date())
                        if vratio is not None and vratio >= VOLUME_TRIGGER_MULTIPLE:
                            fired.append("2x-volume")
                            volume_ratio_val = round(vratio, 1)

                    # Turtle: 55-day channel breakout. Heavy levels/stats cached
                    # once/day; here it's a cheap live-price-vs-cached-level check.
                    turtle_meta = None
                    if state == "open" or test_mode:
                        snap = get_turtle_snapshot(ticker, stock, current_date)
                        if snap:
                            tdir = detect_breakout(current_price, snap["channel_high"], snap["channel_low"])
                            if tdir:
                                fired.append("turtle-trade")
                                turtle_meta = turtle_signal_metrics(snap, tdir)

                    # --- Hourly :30 price refresh (EXISTING cards only) --------
                    # A card's price/price_change otherwise FREEZE at the moment it
                    # first fired, because base_card is only built inside the
                    # `if fired:` branch below. This re-stamps live values once per
                    # hour at :30, whether or not the trigger still holds — a play
                    # deliberately stays up all day even after the move retraces
                    # (nothing but an explicit user dismiss removes a card).
                    # Costs ZERO extra API calls: current_price/pct_change were
                    # already computed for this pass.
                    # The existence check is load-bearing — patch_actionable_move
                    # CREATES an entry for an unknown ticker, so without it this
                    # would mint a bare price-only card for every ticker tracked.
                    if run_price_refresh:
                        with actionable_file_lock:
                            has_card = ticker in get_actionable_moves_local()
                        if has_card:
                            patch_actionable_move(ticker, {
                                "price": f"${current_price:,.2f}",
                                "price_change": round(pct_change, 2),
                            })

                    if fired:
                        with actionable_file_lock:
                            existing = dict(get_actionable_moves_local().get(ticker, {}))
                        existing_conditions = set(existing.get('conditions', []))
                        card_exists = bool(existing)

                        # Display name via .info only when minting a brand-new
                        # card — keeps that throttle-prone call rare.
                        if card_exists:
                            display_name = existing.get('name') or ticker
                        else:
                            info_name = stock.info.get('longName', ticker)
                            display_name = info_name if info_name else ticker

                        # Shared card body: live price + latest options snapshot,
                        # falling back to the existing card's values when this pass
                        # has no opt_data (e.g. a volume fire on a name whose chain
                        # didn't parse this pass).
                        base_card = {
                            "name": display_name,
                            "price": f"${current_price:,.2f}",
                            "price_change": round(pct_change, 2),
                            "expected_move": opt_data['expected_move_pct'] if opt_data else existing.get('expected_move'),
                            "atm_strike":    opt_data['atm_strike']     if opt_data else existing.get('atm_strike'),
                            "atm_put_price": opt_data['atm_put_price']  if opt_data else existing.get('atm_put_price'),
                            "atm_expiration":opt_data['atm_expiration'] if opt_data else existing.get('atm_expiration'),
                            "atm_iv":        opt_data['atm_iv']         if opt_data else existing.get('atm_iv'),
                            "put_wall":      opt_data['put_wall']       if opt_data else existing.get('put_wall'),
                            "call_wall":     opt_data['call_wall']      if opt_data else existing.get('call_wall'),
                        }

                        # --- 1-sigma: full card + synthesis on first sighting ---
                        # First-time gate matches the old `already_triggered`
                        # behavior (a card existed iff 1-sigma had fired).
                        if "1-sigma" in fired and "1-sigma" not in existing_conditions:
                            if test_mode:
                                trigger_status = "TRIGGERED - Test Mode"
                            elif state == "pre_market":
                                trigger_status = "TRIGGERED - Pre-Market"
                            else:
                                trigger_status = "TRIGGERED - Synthesis Pending"

                            print(f"[TRIGGER] {ticker} exceeded ATM Put Premium! ({session_label}) Posting card, synthesis running in background...")

                            newly_triggered[ticker] = {
                                **base_card,
                                "conditions": ["1-sigma"],
                                "status": trigger_status,
                                "why": "Scanning latest headlines...",
                                "structure": "Analyzing options chain...",
                                "impact": "Calculating optimal trade mechanics..."
                            }
                            patch_actionable_move(ticker, newly_triggered[ticker])

                            # News is no longer pulled on the spot. The cycle needs
                            # time to catch up -- an immediate pull reliably returned
                            # yesterday's articles. schedule_news_pull sets the card
                            # to "Awaiting news pull @ HH:MM"; news_loop does the work.
                            schedule_news_pull(ticker)

                        # --- 2x-volume: badge + live ratio -----------------------
                        # (The once/day updated synthesis is added in A3b.) The
                        # base_card refresh keeps price + the growing ratio current
                        # on each :15/:45 recheck without touching why/structure.
                        if "2x-volume" in fired:
                            vol_patch = {
                                **base_card,
                                "conditions": ["2x-volume"],
                                "condition_meta": {"2x-volume": {"ratio": volume_ratio_val}},
                            }
                            # A volume fire with no 1-sigma card needs its own
                            # status + placeholder text so it renders standalone.
                            if not card_exists and "1-sigma" not in fired:
                                vol_patch["status"] = "TRIGGERED - Volume Spike"
                                vol_patch["why"] = f"Volume {volume_ratio_val}x the 50-day average."
                                vol_patch["structure"] = "Elevated participation — see chart."
                                vol_patch["impact"] = "Volume-driven; catalyst scan pending."
                            if "2x-volume" not in existing_conditions:
                                print(f"[TRIGGER] {ticker} volume {volume_ratio_val}x 50-day avg ({session_label}).")
                            patch_actionable_move(ticker, vol_patch)

                            # A volume fire ALWAYS earns a fresh look, once per ticker per
                            # day — it is not folded into whatever the 1-sigma card already
                            # pulled. Volume usually arrives with definitive news, so the
                            # spike is evidence something printed after the morning attempt.
                            # schedule_news_pull() would have no-opped here; its guard is
                            # right for a repeat price trigger and wrong for this one.
                            schedule_volume_news_pull(ticker)

                        # --- Turtle: 55-day breakout, gated for the day ----------
                        # Fires ONCE and persists via existing_conditions — re-entering
                        # the channel intraday does NOT clear it; the midnight clear
                        # resets it. No news synthesis: the breakout metrics (in
                        # condition_meta) ARE the content.
                        if "turtle-trade" in fired and "turtle-trade" not in existing_conditions:
                            tdir = turtle_meta["direction"]
                            turtle_patch = {
                                **base_card,
                                "conditions": ["turtle-trade"],
                                "condition_meta": {"turtle-trade": turtle_meta},
                            }
                            # Standalone Turtle card (no 1-sigma / volume) needs its
                            # own status + text so it renders on its own.
                            if not card_exists and "1-sigma" not in fired and "2x-volume" not in fired:
                                arrow = "↑" if tdir == "long" else "↓"
                                turtle_patch["status"] = f"TRIGGERED - Turtle {tdir.capitalize()} Breakout"
                                turtle_patch["why"] = f"55-day {tdir} breakout {arrow} (Turtle System 2)."
                                turtle_patch["structure"] = (
                                    f"Breakout {turtle_meta['breakout_level']:.2f} · N={turtle_meta['atr']:.2f} · "
                                    f"stop {turtle_meta['suggested_stop']:.2f}."
                                )
                                turtle_patch["impact"] = "Trend-follow entry — see Trade Data for pyramid + historical stats."
                            print(f"[TRIGGER] {ticker} Turtle {tdir} breakout @ {turtle_meta['breakout_level']:.2f} ({session_label}).")
                            patch_actionable_move(ticker, turtle_patch)
                else:
                    market_data[ticker] = {"price": "--", "change": "--", "is_positive": None, "session": state}
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                market_data[ticker] = {"price": "--", "change": "--", "is_positive": None, "session": state}

        with open(DATA_FILE, 'w') as f:
            json.dump(market_data, f)

        # Mark this :15/:45 window done so the volume sweep fires once per window.
        if run_volume:
            last_volume_slot = volume_slot

        # Same, for the :30 price-refresh window.
        if run_price_refresh:
            last_price_slot = price_slot

        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market Data Engine (Alpha Vantage)")
    parser.add_argument("--test", action="store_true", help="Run in test mode: bypass market hours, use last two trading session closes")
    parser.add_argument("--as-of-date", dest="as_of_date", metavar="YYMMDD",
                        help="Turtle test-injection: evaluate --ticker as of this past date and write a real card (e.g. --as-of-date 260530 --ticker QQQ)")
    parser.add_argument("--ticker", help="Ticker symbol for --as-of-date injection")
    args = parser.parse_args()

    if args.as_of_date:
        if not args.ticker:
            parser.error("--as-of-date requires --ticker (e.g. --as-of-date 260530 --ticker QQQ)")
        try:
            as_of = datetime.strptime(args.as_of_date, "%y%m%d").date()
        except ValueError:
            parser.error(f"--as-of-date must be YYMMDD (got {args.as_of_date!r})")
        print(f"[AS-OF TEST] Evaluating {args.ticker.upper()} as of {as_of} using real history through that date...")
        startup_actionable_reconcile()      # preserve any live cards; inject alongside
        run_turtle_asof(args.ticker.upper(), as_of)
        print("[AS-OF TEST] Engine serving on :5001 — open the dashboard and click the card to inspect. Ctrl+C to stop.")
        start_macro_loop()
        start_news_loop()
        app.run(port=5001)
    else:
        if args.test:
            print("[TEST MODE] Starting in test mode — market hours guard disabled.")
        startup_actionable_reconcile()
        threading.Thread(target=fetch_loop, args=(args.test,), daemon=True).start()
        start_macro_loop()
        start_news_loop()
        start_stoplight_scheduler()
        app.run(port=5001)