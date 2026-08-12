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
    (4,  "earnings",      r"earnings|quarterly results|\bQ[1-4]\b|beats?\b|misses?\b|"
                          r"guidance|outlook|revenue|\bEPS\b"),
    (3,  "corp action",   r"acquisit|merger|to acquire|buyout|takeover|spin-?off|"
                          r"divest|tender offer|"
                          # a divestiture is often phrased as a sale of a business,
                          # not with the word "divest"
                          r"sells? .{0,30}?\b(division|unit|business|segment|assets)\b"),
    (3,  "regulatory",    r"\bFDA\b|approval|lawsuit|court|ruling|verdict|investigat|"
                          r"subpoena|recall|antitrust|settlement|probe"),
    (3,  "dilution",      r"public offering|shelf registration|convertible|"
                          r"at-the-market|dilut|secondary offering|prices? .*notes"),
    # business ABOVE analyst (user, 2026-08-10): a contract win or a product launch
    # is a real catalyst in a way a price-target tweak is not.
    (2,  "business",      r"contract|partnership|launch|unveil|collaborat|deal with"),
    (1,  "analyst",       r"upgrade|downgrade|price target|initiat\w+ coverage|reiterat"),
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
    (-3, "13F/stake",      r"\b13F\b|stake in|boosts? (its )?(stake|holdings|position)|"
                           r"trims? (its )?(stake|holdings|position)|"
                           r"(increases?|reduces?) (its )?(stake|position|holdings)"),
]
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

def set_cached_news(ticker_symbol, news_text, source, label_date=None):
    """Stores news_text for this ticker/day so repeated triggers (e.g. across
    engine restarts during testing) don't re-hit Alpha Vantage."""
    if label_date is None:
        label_date = datetime.today().date()
    with news_cache_lock:
        cache = _load_news_cache()
        cache[_cache_key(ticker_symbol, label_date)] = {
            "news_text": news_text,
            "source": source,
            "cached_at": datetime.now().isoformat()
        }
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
        patch_actionable_move(ticker, {
            "news_state": "retry", "news_due_at": sweep.timestamp(),
            "why": f"No news as of {now:%H:%M} ET — next pull @ {sweep:%H:%M} ET.",
        })
        print(f"[NEWS NONE] {ticker}: nothing fresh — retry at {sweep:%H:%M} ET")
    else:
        # Stable wording ON PURPOSE — this is the string to count when asking how
        # often a flagged move never got a story (user, 2026-08-11).
        patch_actionable_move(ticker, {
            "news_state": "none", "news_due_at": None,
            "why": "No news surfaced today.",
            "structure": "No catalyst found in two attempts.",
            "impact": "Move unexplained by available coverage.",
        })
        print(f"[NEWS NONE] {ticker}: no news surfaced today — closed out")


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
        try:
            _av_pace()
            news_text = fetch_latest_news(ticker)
            if news_text is None:
                _advance_after_empty(ticker, now)
                continue
            set_cached_news(ticker, news_text, "Alpha Vantage")
            print(f"[NEWS PULL] {ticker}: fresh news found ({state} attempt) — synthesising")
            ai = generate_ai_synthesis(ticker, _opt_from_card(card), news_text,
                                       round(float(card.get('price_change') or 0), 2))
            why = ai.get('why', '')
            if not why.strip():
                _advance_after_empty(ticker, now)
                continue
            patch_actionable_move(ticker, {
                "news_source": "Alpha Vantage", "why": why,
                "structure": ai.get('structure', ''), "impact": ai.get('impact', ''),
                "news_state": "done", "news_due_at": None,
            })
            print(f"[NEWS PULL] {ticker}: synthesis complete")
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
            news_text = fetch_latest_news(ticker)
            news_source = "Alpha Vantage"

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


def _materiality(title, summary):
    """(weight, label) for how much this story could plausibly MOVE a stock.

    Demotions are tested against the title alone and win outright, so an article
    whose subject is an insider sale is not promoted to the earnings tier merely
    for mentioning earnings in passing. Otherwise the strongest positive match
    across title+summary wins, defaulting to 0 for ordinary coverage.
    """
    for weight, label, pattern in MATERIALITY_DEMOTIONS:
        if re.search(pattern, title or "", re.I):
            return weight, label
    blob = f"{title or ''} {summary or ''}"
    best, best_label = 0, "general"
    for weight, label, pattern in MATERIALITY_RULES:
        if weight > best and re.search(pattern, blob, re.I):
            best, best_label = weight, label
    return best, best_label


def fetch_latest_news(ticker_symbol):
    """Returns a string of headlines on success, or None if Alpha Vantage has nothing usable."""
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
        resp = requests.get(url, timeout=10)
        data = resp.json()

        # Catch missing/invalid API key or quota exhaustion
        if "Information" in data or "Note" in data:
            msg = data.get("Information") or data.get("Note")
            print(f"[NEWS WARNING] Alpha Vantage API issue: {msg}")
            return None

        feed = data.get("feed", [])
        if not feed:
            return None

        # Collect every candidate that clears the relevance bar, THEN rank. The old
        # loop broke at the first 3 that passed, which -- because the feed arrives
        # newest-first -- meant selection by recency. On a day of filing-aggregator
        # posts all three slots filled before a real catalyst was ever examined.
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
            weight, label = _materiality(title, summary)
            candidates.append({
                "title": title, "summary": summary, "relevance": relevance,
                "tier": weight, "label": label, "co_tagged": co_tagged,
                "weight": weight - (SHARED_COVERAGE_PENALTY if co_tagged else 0),
            })

        if stale or undated:
            print(f"[NEWS FRESH] {ticker_symbol}: dropped {stale} published before "
                  f"{cutoff:%Y-%m-%d %H:%M} ET"
                  + (f" and {undated} undated" if undated else "")
                  + f" (of {len(feed)}).")

        if not candidates:
            # Not a failure -- the honest answer is that nothing recent exists. The
            # caller falls through to a LIVE search, which is better placed to explain
            # a same-day move than anything Alpha Vantage still had on file.
            print(f"[NEWS FRESH] {ticker_symbol}: nothing published since the prior "
                  f"close — falling through to live search.")
            return None

        # Materiality first, relevance as the tiebreak. Nothing is dropped for being
        # low-materiality -- a routine filing still surfaces when it is all there is.
        candidates.sort(key=lambda c: (c["weight"], c["relevance"]), reverse=True)

        # DEDUPE. Aggregators reprint the same story, and with only three slots a
        # duplicate is a slot spent saying nothing new. Observed 2026-08-11: DDOG's
        # feed gave the SAME CEO-share-sale piece twice, taking two of three slots.
        # Compared on a normalised title prefix -- reprints share a headline even
        # when the summary is reworded.
        seen_titles, deduped = set(), []
        for c in candidates:
            key = re.sub(r"[^a-z0-9 ]", "", (c["title"] or "").lower())
            key = " ".join(key.split())[:60]
            if key and key in seen_titles:
                print(f"[NEWS RANK] {ticker_symbol}: duplicate '{c['title'][:55]}...' — skipped")
                continue
            seen_titles.add(key)
            deduped.append(c)
        candidates = deduped

        chosen, dropped = candidates[:3], candidates[3:]

        def _why(c):
            """tier + modifier = total, so an effective weight is always traceable
            back to an authored number rather than appearing from nowhere."""
            share = f" shared(-{SHARED_COVERAGE_PENALTY})" if c["co_tagged"] else ""
            return (f"{c['label']}({c['tier']}){share} = {c['weight']}, "
                    f"rel={c['relevance']:.2f}")

        for c in dropped:
            print(f"[NEWS RANK] {ticker_symbol}: below the cut '{c['title'][:55]}...' [{_why(c)}]")

        headlines = []
        for c in chosen:
            print(f"[NEWS RANK] {ticker_symbol}: chose '{c['title'][:55]}...' [{_why(c)}]")
            notes = []
            if c["co_tagged"]:
                peers = ", ".join(tk for tk, _ in c["co_tagged"][:5] if tk)
                notes.append(f"SECTOR/SHARED COVERAGE — also covers {peers}. This may "
                             f"explain a sector-wide move rather than a company-specific one.")
            # Flag a demoted item so the synthesis does not present a routine filing
            # as a catalyst. This is the DDOG failure in one line: an 18.7% earnings
            # gap explained as "insider selling ... triggered the selloff".
            if c["tier"] < 0:
                notes.append("Routine filing/position disclosure — background only, "
                             "not a plausible cause of a large move.")
            note = ("\nNOTE: " + " ".join(notes)) if notes else ""
            headlines.append(
                f"Headline: {c['title']}\nSummary: {c['summary']}\n"
                f"Relevance: {c['relevance']:.2f}{note}"
            )

        return "\n---\n".join(headlines)

    except Exception as e:
        print(f"[NEWS ERROR] Alpha Vantage fetch failed for {ticker_symbol}: {e}")
        return None

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
    if opt_data:
        move_line = f"The stock {ticker} has just moved {pct_change}%, exceeding its nearest-term ATM put premium of {opt_data['expected_move_pct']}%."
        options_block = (
            "\nOptions Structure Data:\n"
            f"- Put Wall (Highest OI): {opt_data['put_wall']}\n"
            f"- Call Wall (Highest OI): {opt_data['call_wall']}\n"
            f"- ATM Put Premium Implied Volatility: {opt_data['atm_iv']}%\n"
        )
        structure_key = '"structure": A 1-2 sentence explanation of the options mechanics.'
    else:
        move_line = f"The stock {ticker} has just moved {pct_change}% on a volume spike and has no listed options chain."
        options_block = ""
        structure_key = '"structure": A 1-2 sentence explanation of what the volume/price action implies (no options data available).'

    prompt = f"""You are an elite quantitative market analyst.
{move_line}
{options_block}
Latest News:
{news_text}

Synthesize this data and return ONLY a valid JSON object with EXACTLY these three keys, and nothing else - no preamble, no markdown fences:
"why": A 2-3 sentence fundamental or news-driven reason for the move based on the headlines. If the news above does not contain enough information to explain the move, say so plainly rather than speculating.
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
                        vratio = compute_volume_ratio(stock)
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

                            # Volume confirms AFTER news prints as often as before it, so a
                            # volume fire just schedules the same T+30 pull. schedule_news_pull
                            # is idempotent -- if 1-sigma already scheduled this ticker today,
                            # the clock is NOT reset. The old volume_synth_ran budget flag went
                            # with the retired weak-synthesis re-scan (2026-08-11).
                            schedule_news_pull(ticker)

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