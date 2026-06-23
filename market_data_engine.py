import time
import json
import os
import argparse
from dotenv import load_dotenv
load_dotenv()
import yfinance as yf
import threading
import requests
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

TICKERS_FILE = 'tickers.json'
DATA_FILE = 'market_data.json'
ACTIONABLE_FILE = 'actionable_moves.json'
ARCHIVE_DIR = 'archive'
NEWS_CACHE_FILE = 'news_cache.json'
MACRO_FILE = 'macro_regime.json'

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
fallback_semaphore = threading.Semaphore(2)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def generate_macro_regime():
    """
    Fetches live ^TNX and ^VIX data via yfinance, then calls Gemini with
    Google Search grounding to generate a market briefing headline and
    2-3 sentence summary. Writes result to macro_regime.json.
    Only runs during market hours (8am-4pm ET weekdays).
    """
    if not GEMINI_API_KEY:
        print("[MACRO] Gemini API key missing — skipping macro regime update.")
        return
    try:
        tnx = yf.Ticker("^TNX")
        vix = yf.Ticker("^VIX")

        tnx_hist = tnx.history(period="2d")
        vix_hist = vix.history(period="2d")

        if len(tnx_hist) < 2 or len(vix_hist) < 2:
            return

        tnx_price = round(float(tnx_hist['Close'].iloc[-1]), 2)
        tnx_change = round(float(tnx_hist['Close'].iloc[-1]) - float(tnx_hist['Close'].iloc[-2]), 2)
        vix_price = round(float(vix_hist['Close'].iloc[-1]), 2)
        vix_change = round(float(vix_hist['Close'].iloc[-1]) - float(vix_hist['Close'].iloc[-2]), 2)

        prompt = f"""Search for today's market news and provide a concise market briefing.

Current market data:
- 10-Year Treasury Yield: {tnx_price}% ({'+' if tnx_change >= 0 else ''}{tnx_change} today)
- VIX: {vix_price} ({'+' if vix_change >= 0 else ''}{vix_change} today)

Search for what's driving broad market movement today, any major scheduled
catalysts (Fed speakers, economic data releases, large earnings announcements),
and the current risk tone across markets.

Return ONLY a valid JSON object with exactly these two keys, no preamble,
no markdown fences:
"headline": A single punchy sentence capturing the dominant market theme today
"summary": 2-3 sentences covering what's moving markets, major catalysts on
deck today, and the current risk tone. Keep it concise and actionable for
an active trader."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}]
        }

        response = requests.post(url, json=payload, timeout=30)
        result = response.json()

        if 'error' in result:
            print(f"[MACRO] Gemini error: {result['error'].get('message', 'Unknown')}")
            return

        if 'candidates' not in result or not result['candidates']:
            print("[MACRO] Gemini returned no candidates.")
            return

        text = result['candidates'][0].get('content', {}).get('parts', [{}])[0].get('text', '')
        if not text:
            return

        text = text.replace('```json', '').replace('```', '').strip()
        macro_data = json.loads(text)

        macro_data['tnx'] = tnx_price
        macro_data['tnx_change'] = tnx_change
        macro_data['vix'] = vix_price
        macro_data['vix_change'] = vix_change
        macro_data['updated_at'] = datetime.now(ET).strftime('%I:%M %p ET')

        with open(MACRO_FILE, 'w') as f:
            json.dump(macro_data, f)

        print(f"[MACRO] Updated macro regime: {macro_data['headline'][:60]}...")

    except Exception as e:
        print(f"[MACRO] Failed to generate macro regime: {e}")

def macro_loop():
    """Runs generate_macro_regime() once at startup and then every
    hour during market hours (8am-4pm ET weekdays)."""
    generate_macro_regime()
    while True:
        time.sleep(3600)
        state = market_state()
        if state in ('pre_market', 'open'):
            generate_macro_regime()

def get_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            with open(TICKERS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return list(set(data))
        except:
            pass
    return ["AAPL", "QQQ", "SPY"]

def save_tickers(tickers):
    with open(TICKERS_FILE, 'w') as f:
        json.dump(list(set(tickers)), f)

def get_actionable_moves_local():
    if os.path.exists(ACTIONABLE_FILE):
        try:
            with open(ACTIONABLE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

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
    """Archives, then wipes ACTIONABLE_FILE clean. Called on startup and at midnight rollover.
    News cache is only cleared when clear_news_too=True (i.e. an actual day change),
    since a restart shouldn't throw away still-valid cached news."""
    if archive_date is None:
        archive_date = datetime.today().date()
    with actionable_file_lock:
        archive_actionable_moves(archive_date)
        with open(ACTIONABLE_FILE, 'w') as f:
            json.dump({}, f)
    with last_clear_lock:
        global last_clear_time
        last_clear_time = time.time()
    print(f"[CLEANUP] actionable_moves.json cleared ({reason}).")
    if clear_news_too:
        clear_news_cache(reason=reason)

def patch_actionable_move(ticker, updates):
    """Thread-safe read-modify-write for a single ticker's entry in ACTIONABLE_FILE."""
    with actionable_file_lock:
        current = get_actionable_moves_local()
        if ticker in current:
            current[ticker].update(updates)
        else:
            current[ticker] = updates
        with open(ACTIONABLE_FILE, 'w') as f:
            json.dump(current, f)

def run_synthesis_in_background(ticker, opt_data, pct_change):
    """Fetches news + runs Claude synthesis off the main loop, then patches the card in place."""
    triggered_at = time.time()
    try:
        cached = get_cached_news(ticker)
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
                failure_phrases = ("synthesis failed", "timed out", "api error", "n/a", "unavailable")
                if any(p in ai_synthesis.get('why', '').lower() for p in failure_phrases):
                    print(f"[CACHE SKIP] {ticker}: synthesis result looks like a failure, not caching.")
                else:
                    set_cached_news(ticker, ai_synthesis.get('why', ''), news_source)
                with last_clear_lock:
                    cleared_after_trigger = last_clear_time > triggered_at
                if cleared_after_trigger:
                    print(f"[STALE THREAD] {ticker}: midnight clear fired after this thread started — discarding synthesis.")
                    return
                patch_actionable_move(ticker, {
                    "status": "TRIGGERED - Exceeded Premium",
                    "news_source": news_source,
                    "why": ai_synthesis.get('why', ''),
                    "structure": ai_synthesis.get('structure', ''),
                    "impact": ai_synthesis.get('impact', '')
                })
                print(f"[SYNTHESIS COMPLETE] {ticker} (news via {news_source})")
                return

        ai_synthesis = generate_ai_synthesis(ticker, opt_data, news_text, round(pct_change, 2))
        failure_phrases = ("synthesis failed", "timed out", "api error", "n/a", "unavailable")
        why = ai_synthesis.get('why', '')
        if any(p in why.lower() for p in failure_phrases):
            print(f"[CACHE SKIP] {ticker}: synthesis result looks like a failure, not caching.")
        else:
            set_cached_news(ticker, news_text, news_source)
        with last_clear_lock:
            cleared_after_trigger = last_clear_time > triggered_at
        if cleared_after_trigger:
            print(f"[STALE THREAD] {ticker}: midnight clear fired after this thread started — discarding synthesis.")
            return
        patch_actionable_move(ticker, {
            "status": "TRIGGERED - Exceeded Premium",
            "news_source": news_source,
            "why": ai_synthesis.get('why', ''),
            "structure": ai_synthesis.get('structure', ''),
            "impact": ai_synthesis.get('impact', '')
        })
        print(f"[SYNTHESIS COMPLETE] {ticker} (news via {news_source})")
    except Exception as e:
        print(f"[SYNTHESIS THREAD ERROR] {ticker}: {e}")
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
def fetch_latest_news(ticker_symbol):
    """Returns a string of headlines on success, or None if Alpha Vantage has nothing usable."""
    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=NEWS_SENTIMENT"
            f"&tickers={ticker_symbol}"
            f"&limit=10"
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

        headlines = []
        for item in feed:
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
            other_high_scores = [
                float(t.get("relevance_score", 0)) for t in ticker_sentiments
                if t.get("ticker") != ticker_symbol and float(t.get("relevance_score", 0)) >= relevance - 0.05
            ]
            is_shared_coverage = len(other_high_scores) > 0

            if relevance >= 0.5 and not is_shared_coverage:
                headlines.append(
                    f"Headline: {title}\nSummary: {summary}\nRelevance: {relevance:.2f}"
                )
            elif relevance >= 0.5 and is_shared_coverage:
                print(f"[NEWS FILTER] {ticker_symbol}: skipped '{title[:60]}...' "
                      f"(relevance {relevance:.2f} OK, but shared coverage with other tickers scoring {[round(s,2) for s in other_high_scores]})")
            else:
                print(f"[NEWS FILTER] {ticker_symbol}: skipped '{title[:60]}...' (relevance {relevance:.2f} < 0.5)")

            if len(headlines) == 3:
                break

        if not headlines:
            return None

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

            synthesis_prompt = (
                f"Based on your search findings above, synthesize with the options data "
                f"and return ONLY a valid JSON object with exactly three keys — no preamble, no markdown fences:\n\n"
                f"Options Structure Data for {ticker}:\n"
                f"- Put Wall: {opt_data['put_wall']}\n"
                f"- Call Wall: {opt_data['call_wall']}\n"
                f"- ATM IV: {opt_data['atm_iv']}%\n\n"
                f'"why": 2-3 sentence company-specific reason. Say so plainly if insufficient.\n'
                f'"structure": 1-2 sentence options mechanics explanation.\n'
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

    prompt = f"""You are an elite quantitative market analyst.
The stock {ticker} has just moved {pct_change}%, exceeding its nearest-term ATM put premium of {opt_data['expected_move_pct']}%.

Options Structure Data:
- Put Wall (Highest OI): {opt_data['put_wall']}
- Call Wall (Highest OI): {opt_data['call_wall']}
- ATM Put Premium Implied Volatility: {opt_data['atm_iv']}%

Latest News:
{news_text}

Synthesize this data and return ONLY a valid JSON object with EXACTLY these three keys, and nothing else - no preamble, no markdown fences:
"why": A 2-3 sentence fundamental or news-driven reason for the move based on the headlines. If the news above does not contain enough information to explain the move, say so plainly rather than speculating.
"structure": A 1-2 sentence explanation of the options mechanics.
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

        # 1. Skip 0 DTE by filtering out today's date
        today_str = datetime.today().strftime('%Y-%m-%d')
        valid_exps = [exp for exp in expirations if exp > today_str]
        
        if not valid_exps:
            return None # Failsafe if there are no future expirations

        # 2. Get the nearest expiration > 0 DTE
        nearest_exp = valid_exps[0]
        opt_chain = stock.option_chain(nearest_exp)
        puts, calls = opt_chain.puts, opt_chain.calls

        # 3. Find the ATM Put and extract its premium price
        atm_put = puts.iloc[(puts['strike'] - current_price).abs().argsort()[:1]]
        if atm_put.empty: 
            return None

        atm_put_price = float(atm_put['lastPrice'].values[0])
        
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

# --- Endpoints ---
@app.route('/get_market_data', methods=['GET'])
def get_market_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

@app.route('/get_actionable_moves', methods=['GET'])
def get_actionable_moves():
    if os.path.exists(ACTIONABLE_FILE):
        try:
            with open(ACTIONABLE_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

@app.route('/add_ticker', methods=['POST'])
def add_ticker():
    data = request.json
    ticker = data.get('ticker', '').upper()
    tickers = get_tickers()
    if ticker and ticker not in tickers:
        tickers.append(ticker)
        save_tickers(tickers)
    return jsonify({"status": "success", "tickers": tickers})

@app.route('/delete_ticker', methods=['POST'])
def delete_ticker():
    data = request.json
    ticker_to_delete = data.get('ticker', '').upper()
    tickers = get_tickers()
    if ticker_to_delete in tickers:
        tickers.remove(ticker_to_delete)
        save_tickers(tickers)
    return jsonify({"status": "success"})

@app.route('/sync_tickers', methods=['POST'])
def sync_tickers():
    data = request.json
    frontend_tickers = data.get('tickers', [])
    if isinstance(frontend_tickers, list) and len(frontend_tickers) > 0:
        clean_tickers = list(set([str(t).upper() for t in frontend_tickers]))
        save_tickers(clean_tickers)
        print(f"[SYNC] Engine is now tracking: {clean_tickers}")
        return jsonify({"status": "success", "tickers": clean_tickers})
    return jsonify({"status": "no_change"})

@app.route('/get_macro_regime', methods=['GET'])
def get_macro_regime():
    if os.path.exists(MACRO_FILE):
        try:
            with open(MACRO_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

# --- Market Hours ---
ET = ZoneInfo("America/New_York")

def market_state():
    """
    Returns the current operating mode based on ET time and weekday:
      'closed'      — midnight→8am ET weekdays; all weekend except Sun→Mon midnight
      'pre_market'  — 8:00am→9:30am ET weekdays
      'open'        — 9:30am→4:00pm ET weekdays
      'after_hours' — 4:00pm→midnight ET weekdays (dashboard static, no triggers)
    Midnight Sunday→Monday is treated as 'closed' until 8am Monday ET.
    """
    now = datetime.now(ET)
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    t = now.time()

    from datetime import time as dtime
    MIDNIGHT     = dtime(0, 0)
    PRE_OPEN     = dtime(8, 0)
    MARKET_OPEN  = dtime(9, 30)
    MARKET_CLOSE = dtime(16, 0)

    # Full weekend days — always closed
    if weekday == 5:  # Saturday
        return "closed"
    if weekday == 6:  # Sunday
        return "closed"

    # Weekdays
    if MIDNIGHT <= t < PRE_OPEN:
        return "closed"
    elif PRE_OPEN <= t < MARKET_OPEN:
        return "pre_market"
    elif MARKET_OPEN <= t < MARKET_CLOSE:
        return "open"
    else:  # 4pm → midnight
        return "after_hours"

# --- Data Fetching Loop ---
def fetch_loop(test_mode=False):
    last_seen_date = datetime.now(ET).date()

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
                        pre_price = getattr(stock.fast_info, 'pre_market_price', None)
                        if pre_price is None:
                            market_data[ticker] = {
                                "price": f"${float(hist['Close'].iloc[-1]):,.2f}",
                                "change": "pre-mkt",
                                "is_positive": None,
                                "session": state
                            }
                            continue
                        current_price = float(pre_price)
                        prev_close    = float(hist['Close'].iloc[-1])
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

                    if opt_data and abs(pct_change) > opt_data['expected_move_pct']:
                        with actionable_file_lock:
                            current = get_actionable_moves_local()
                            already_triggered = ticker in current

                        if not already_triggered:
                            if test_mode:
                                trigger_status = "TRIGGERED - Test Mode"
                            elif state == "pre_market":
                                trigger_status = "TRIGGERED - Pre-Market"
                            else:
                                trigger_status = "TRIGGERED - Synthesis Pending"

                            print(f"[TRIGGER] {ticker} exceeded ATM Put Premium! ({session_label}) Posting card, synthesis running in background...")
                            name = stock.info.get('longName', ticker)

                            newly_triggered[ticker] = {
                                "name": name if name else ticker,
                                "price": f"${current_price:,.2f}",
                                "price_change": round(pct_change, 2),
                                "expected_move": opt_data['expected_move_pct'],
                                "atm_strike": opt_data['atm_strike'],
                                "atm_put_price": opt_data['atm_put_price'],
                                "atm_expiration": opt_data['atm_expiration'],
                                "atm_iv": opt_data['atm_iv'],
                                "put_wall": opt_data['put_wall'],
                                "call_wall": opt_data['call_wall'],
                                "status": trigger_status,
                                "why": "Scanning latest headlines...",
                                "structure": "Analyzing options chain...",
                                "impact": "Calculating optimal trade mechanics..."
                            }

                            patch_actionable_move(ticker, newly_triggered[ticker])

                            threading.Thread(
                                target=run_synthesis_in_background,
                                args=(ticker, opt_data, pct_change),
                                daemon=True
                            ).start()
                else:
                    market_data[ticker] = {"price": "--", "change": "--", "is_positive": None, "session": state}
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                market_data[ticker] = {"price": "--", "change": "--", "is_positive": None, "session": state}

        with open(DATA_FILE, 'w') as f:
            json.dump(market_data, f)

        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market Data Engine (Alpha Vantage)")
    parser.add_argument("--test", action="store_true", help="Run in test mode: bypass market hours, use last two trading session closes")
    args = parser.parse_args()

    if args.test:
        print("[TEST MODE] Starting in test mode — market hours guard disabled.")

    clear_actionable_moves(reason="startup")
    threading.Thread(target=fetch_loop, args=(args.test,), daemon=True).start()
    threading.Thread(target=macro_loop, daemon=True).start()
    app.run(port=5000)