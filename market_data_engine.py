import time
import json
import os
import argparse
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

# --- Claude Rate Limiter (conservative default for Tier 1: 50 RPM) ---
class RateLimiter:
    def __init__(self, max_calls, period_seconds):
        self.max_calls = max_calls
        self.period = period_seconds
        self.call_times = deque()
        self.lock = threading.Lock()

    def wait_for_slot(self):
        """Blocks only as long as needed to stay under the limit, then records the call."""
        with self.lock:
            now = time.time()

            # Drop timestamps older than the rolling window
            while self.call_times and now - self.call_times[0] >= self.period:
                self.call_times.popleft()

            if len(self.call_times) >= self.max_calls:
                # Wait only until the oldest call in the window expires
                sleep_time = self.period - (now - self.call_times[0]) + 0.1  # small buffer
                if sleep_time > 0:
                    print(f"[RATE LIMITER] At capacity ({self.max_calls}/{self.period}s). Waiting {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                now = time.time()
                while self.call_times and now - self.call_times[0] >= self.period:
                    self.call_times.popleft()

            self.call_times.append(time.time())

claude_limiter = RateLimiter(max_calls=45, period_seconds=60)
actionable_file_lock = threading.Lock()
news_cache_lock = threading.Lock()

# ==========================================
# PASTE YOUR ANTHROPIC (CLAUDE) API KEY HERE - platform.claude.com
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"
# PASTE YOUR ALPHA VANTAGE API KEY HERE (free at alphavantage.co)
ALPHA_VANTAGE_KEY = "L5CDTQYL6SG2P4VR"
# ==========================================

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
                print(f"[NEWS FALLBACK] {ticker}: Alpha Vantage had nothing, asking Claude to search...")
                news_text = fetch_news_via_claude_search(ticker, round(pct_change, 2))
                news_source = "Claude Search"

            # Cache whatever we got (including fallback text) so a re-trigger
            # today - e.g. from a restart during testing - doesn't call out again
            set_cached_news(ticker, news_text, news_source)

        ai_synthesis = generate_ai_synthesis(ticker, opt_data, news_text, round(pct_change, 2))
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
                if t.get("ticker") != ticker_symbol and float(t.get("relevance_score", 0)) >= 0.4
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

def fetch_news_via_claude_search(ticker_symbol, pct_change):
    """
    Fallback for when Alpha Vantage has no news (quota exhausted or empty feed).
    Uses Claude's native web search tool to research the move directly.
    Note: web search and forced-JSON-only prompting don't mix well in one call,
    so this returns plain text to be fed into generate_ai_synthesis() as news_text.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return "News unavailable: no fallback possible (missing Claude API key)."

    claude_limiter.wait_for_slot()

    prompt = f"""The stock {ticker_symbol} moved {pct_change}% today. Use the web_search tool right now to find out why - search for something like "{ticker_symbol} stock news today" or "why did {ticker_symbol} stock move today".

Do not answer from memory. You must call the search tool before responding.

After searching, summarize the 2-3 most relevant, recent headlines and a brief summary of each in plain text. Focus on company-specific news, earnings, analyst actions, or sector-wide catalysts."""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=45)

        if response.status_code == 429:
            print(f"[RATE LIMIT] Hit limit during search fallback for {ticker_symbol}. Waiting 30s...")
            time.sleep(30)
            response = requests.post(url, headers=headers, json=payload, timeout=45)

        result = response.json()

        if 'error' in result:
            print(f"[SEARCH FALLBACK ERROR] {ticker_symbol}: {result['error'].get('message', 'Unknown Error')}")
            return "News unavailable: search fallback failed."

        content_blocks = result.get('content', [])

        # Debug: log what block types actually came back, so we can see
        # whether the model searched at all or just answered directly.
        block_types = [b.get('type') for b in content_blocks]
        print(f"[SEARCH DEBUG] {ticker_symbol} response blocks: {block_types}")

        searched = any(t in ('server_tool_use', 'web_search_tool_result') for t in block_types)
        if not searched:
            print(f"[SEARCH DEBUG] {ticker_symbol}: model did not invoke web_search at all.")

        text = "\n".join(
            block.get('text', '') for block in content_blocks if block.get('type') == 'text'
        )
        if text.strip():
            return text.strip()

        return "News unavailable: search fallback returned no content."

    except Exception as e:
        print(f"[SEARCH FALLBACK EXCEPTION] {ticker_symbol}: {e}")
        return "News unavailable: search fallback failed."

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
                        current_price = float(pre_price) if pre_price else float(hist['Close'].iloc[-1])
                        prev_close    = float(hist['Close'].iloc[-2])
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
    app.run(port=5000)