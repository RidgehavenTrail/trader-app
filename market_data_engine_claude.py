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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

TICKERS_FILE = 'tickers.json'                        # shared - both engines read the same watchlist
DATA_FILE = 'market_data_claude.json'                # separate from the AV engine
ACTIONABLE_FILE = 'actionable_moves_claude.json'     # separate from the AV engine
ARCHIVE_DIR = 'archive_claude'                       # separate archive folder
NEWS_CACHE_FILE = 'news_cache_claude.json'           # separate cache

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
                    # Reserve the slot
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
                    # Wait until enough tokens roll off the window
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

# Cap concurrent synthesis calls to avoid TPM bursts when many tickers
# trigger simultaneously. Each search-and-synthesize call can consume
# 5,000-15,000 input tokens; at 2 concurrent max we stay well under 50k TPM
# even in a worst-case burst of simultaneous triggers.
synthesis_semaphore = threading.Semaphore(2)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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
    """Returns cached synthesis dict {why, structure, impact, source} for this
    ticker today, or None if not cached."""
    if label_date is None:
        label_date = datetime.today().date()
    with news_cache_lock:
        cache = _load_news_cache()
        entry = cache.get(_cache_key(ticker_symbol, label_date))
        return entry if entry else None

def set_cached_news(ticker_symbol, synthesis, source, label_date=None):
    """Stores the full synthesis output {why, structure, impact} for this
    ticker/day so a re-trigger today skips the API call entirely."""
    if label_date is None:
        label_date = datetime.today().date()
    with news_cache_lock:
        cache = _load_news_cache()
        cache[_cache_key(ticker_symbol, label_date)] = {
            "why": synthesis.get("why", ""),
            "structure": synthesis.get("structure", ""),
            "impact": synthesis.get("impact", ""),
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

def run_synthesis_in_background(ticker, opt_data, pct_change, is_etf=False):
    """Runs Claude search + synthesis off the main loop, then patches the card in place.
    On a cache hit, patches directly from stored synthesis with zero API calls.
    Uses a semaphore to cap concurrency at 2 simultaneous calls, preventing TPM
    bursts when many tickers trigger in the same loop pass."""
    cached = get_cached_news(ticker)
    if cached is not None:
        print(f"[NEWS CACHE HIT] {ticker}: patching card from cache — no API call.")
        patch_actionable_move(ticker, {
            "status": "TRIGGERED - Exceeded Premium",
            "news_source": cached.get("source", "Cached"),
            "why": cached.get("why", ""),
            "structure": cached.get("structure", ""),
            "impact": cached.get("impact", "")
        })
        print(f"[SYNTHESIS COMPLETE] {ticker} (via cache, no API call)")
        return

    with synthesis_semaphore:
        try:
            label = "ETF" if is_etf else "stock"
            print(f"[SEARCH] {ticker} ({label}): asking Claude to search and synthesize...")
            ai_synthesis = search_and_synthesize(ticker, opt_data, round(pct_change, 2), is_etf)
            news_source = "Claude Search"

            # Only cache if synthesis actually succeeded — don't persist
            # failure/timeout messages so a re-trigger gets a fresh attempt.
            failed_phrases = ("synthesis failed", "timed out", "api error", "n/a")
            why = ai_synthesis.get('why', '').lower()
            if not any(p in why for p in failed_phrases):
                set_cached_news(ticker, ai_synthesis, news_source)
            else:
                print(f"[CACHE SKIP] {ticker}: synthesis result looks like a failure, not caching.")

            patch_actionable_move(ticker, {
                "status": "TRIGGERED - Exceeded Premium",
                "news_source": news_source,
                "why": ai_synthesis.get('why', ''),
                "structure": ai_synthesis.get('structure', ''),
                "impact": ai_synthesis.get('impact', '')
            })
            print(f"[SYNTHESIS COMPLETE] {ticker} (via {news_source})")
        except Exception as e:
            print(f"[SYNTHESIS THREAD ERROR] {ticker}: {e}")
            patch_actionable_move(ticker, {
                "status": "TRIGGERED - Synthesis Failed",
                "why": "AI synthesis failed to complete.",
                "structure": "N/A",
                "impact": "N/A"
            })

# --- AI Synthesis Logic ---
def search_and_synthesize(ticker, opt_data, pct_change, is_etf=False):
    """
    Single-call replacement for fetch_latest_news + generate_ai_synthesis.
    Claude searches the web for the move's catalyst, then synthesizes news
    and options data into the structured why/structure/impact JSON in one shot.
    Uses a two-turn conversation: first turn triggers the search, second turn
    forces the structured JSON output from the search results.
    ETFs get a macro/sector-focused prompt to avoid flooding search results
    with constituent stock coverage.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return {"why": "API Key Missing.", "structure": "N/A", "impact": "N/A"}

    claude_limiter.wait_for_slot(estimated_tokens=8000)  # Turn 1: prompt only, pre-search

    if is_etf:
        search_prompt = f"""What macro or sector catalyst is driving the {pct_change}% move in {ticker} during the most recent trading session?

Do not answer from memory — search for today's news before responding. Focus on broad market themes, sector rotation, economic data, Fed commentary, or geopolitical events rather than individual stock stories. Summarize your findings in 3-5 sentences."""
    else:
        search_prompt = f"""What's driving the {pct_change}% move in {ticker} during the most recent trading session?

Do not answer from memory — search for today's news before responding. Focus on company-specific catalysts: earnings, guidance, analyst actions, product news, regulatory decisions, executive commentary, or any other single-company event. Summarize your findings in 3-5 sentences."""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    # Turn 1: search for the catalyst
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

        # Log Turn 1 token usage — this is the expensive one since it includes
        # the raw web search results injected into context by Anthropic's infra.
        t1_usage = result.get('usage', {})
        t1_in = t1_usage.get('input_tokens', 0)
        t1_out = t1_usage.get('output_tokens', 0)
        print(f"[TOKENS] {ticker} Turn 1 (search):    in={t1_in:,}  out={t1_out:,}")

        # Update the limiter with the real token count from Turn 1
        claude_limiter.record_usage(t1_in + t1_out)

        # Log what block types came back so we can verify search was invoked
        block_types = [b.get('type') for b in result.get('content', [])]
        print(f"[SEARCH DEBUG] {ticker} response blocks: {block_types}")

        if not any(t in ('server_tool_use', 'web_search_tool_result') for t in block_types):
            print(f"[SEARCH DEBUG] {ticker}: model did not invoke web_search.")

        # Extract the text summary from turn 1
        search_summary = "\n".join(
            b.get('text', '') for b in result.get('content', []) if b.get('type') == 'text'
        ).strip() or "No relevant news found via search."

        # Turn 2 carries the full Turn 1 context forward, so its input tokens
        # will be at least as large as Turn 1's. Use Turn 1 actual as the estimate.
        claude_limiter.wait_for_slot(estimated_tokens=t1_in + t1_out)

        why_instruction = (
            "A 2-3 sentence macro or sector-driven reason for the ETF move based on what you found. Focus on the broad market theme, not individual constituent stocks. If search results were insufficient, say so plainly rather than speculating."
            if is_etf else
            "A 2-3 sentence company-specific reason for the move based on what you found. If search results were insufficient, say so plainly rather than speculating."
        )

        synthesis_prompt = f"""Based on your search findings above, now synthesize the news with the following options structure data and return ONLY a valid JSON object with EXACTLY these three keys — no preamble, no markdown fences:

Options Structure Data for {ticker}:
- Put Wall (Highest OI): {opt_data['put_wall']}
- Call Wall (Highest OI): {opt_data['call_wall']}
- ATM Put Premium Implied Volatility: {opt_data['atm_iv']}%

"why": {why_instruction}
"structure": A 1-2 sentence explanation of the options mechanics.
"impact": A strict 1-2 sentence actionable trading rule or portfolio impact warning."""

        # Strip raw search result blocks before passing Turn 1 context into Turn 2.
        # The full content array includes server_tool_use and web_search_tool_result
        # blocks that can each run 8,000+ tokens of raw page content — redundant
        # since Claude already distilled them into its text summary. Keeping only
        # the text block drops Turn 2 input from ~17,000 tokens to ~400-600.
        summary_only = [
            b for b in result.get('content', []) if b.get('type') == 'text'
        ]

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

        # Log Turn 2 token usage and combined total for this ticker
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
                            info = stock.info
                            name = info.get('longName', ticker)
                            is_etf = info.get('quoteType', '').upper() == 'ETF'

                            # Check cache before writing placeholder — if we already
                            # have today's synthesis, write the real fields immediately
                            # so the background thread's patch doesn't race with or
                            # get overwritten by a placeholder write.
                            cached = get_cached_news(ticker)
                            failed_phrases = ("synthesis failed", "timed out", "api error", "n/a")
                            cached_why = (cached.get("why", "") if cached else "").lower()
                            cache_is_valid = cached is not None and not any(p in cached_why for p in failed_phrases)

                            if cache_is_valid:
                                card = {
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
                                    "status": "TRIGGERED - Exceeded Premium",
                                    "news_source": cached.get("source", "Cached"),
                                    "why": cached.get("why", ""),
                                    "structure": cached.get("structure", ""),
                                    "impact": cached.get("impact", "")
                                }
                                patch_actionable_move(ticker, card)
                                print(f"[CACHE PREFILL] {ticker}: wrote real synthesis directly, no background thread needed.")
                            else:
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
                                    args=(ticker, opt_data, pct_change, is_etf),
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
    parser = argparse.ArgumentParser(description="Market Data Engine (Claude Search)")
    parser.add_argument("--test", action="store_true", help="Run in test mode: bypass market hours, use last two trading session closes")
    args = parser.parse_args()

    if args.test:
        print("[TEST MODE] Starting in test mode — market hours guard disabled.")

    clear_actionable_moves(reason="startup")
    threading.Thread(target=fetch_loop, args=(args.test,), daemon=True).start()
    app.run(port=5001)  # Port 5001 to run alongside the AV engine on 5000