"""
Price-history HTTP layer — engine split phase 2 (2026-07-20), extracted verbatim
from watchtower_engine.py following the engine/newsletter.py blueprint pattern:
self-contained, imports NOTHING from watchtower_engine (no circular import) —
only stdlib, flask, and yfinance. Registered by the engine with
    from engine.price_history import bp as price_history_bp
    app.register_blueprint(price_history_bp)

Serves GET /get_price_history/<ticker> for the dashboard's Chart tab
(lightweight-charts candles), with a short-TTL JSON file cache.

Data source note: this always uses yfinance today. Per the settled Schwab
integration plan (.claude/rules/schwab-integration.md), equities may eventually
route through Schwab instead — but futures/forex stay on yfinance permanently
since Schwab doesn't cover them. fetch_price_history() stays its own function
so that swap is a one-function change, not a route rewrite.
"""
import json
import os
import threading
import time

import yfinance as yf
from flask import Blueprint, jsonify, request

bp = Blueprint('price_history', __name__)

# Relative to the engine's launch cwd (the project root), same as every other
# store file the engine writes (tickers.json, market_data.json, ...).
PRICE_HISTORY_CACHE_FILE = 'price_history_cache.json'

# How long a cached OHLC pull stays fresh before we hit yfinance again.
# Charts are opened on demand (not continuously polled like the trigger loop),
# so a short TTL is fine — this just prevents a burst of re-fetches if someone
# flips between tabs/tickers quickly.
PRICE_HISTORY_TTL_SECONDS = 300

price_history_lock = threading.Lock()


def get_asset_class(ticker_symbol):
    """
    Classifies a yfinance-style ticker into 'equity', 'future', or 'forex'.
    ETFs count as 'equity' — they have real listed options chains, same as
    single-name stocks, and share the same suffix-less ticker format.
    Only genuine futures (=F) and forex (=X) tickers get their own bucket,
    since those are the only asset classes without an options chain to trade.
    """
    t = ticker_symbol.upper()
    if t.endswith('=F'):
        return 'future'
    if t.endswith('=X'):
        return 'forex'
    return 'equity'


def load_price_history_cache():
    if os.path.exists(PRICE_HISTORY_CACHE_FILE):
        try:
            with open(PRICE_HISTORY_CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_price_history_cache(cache):
    with open(PRICE_HISTORY_CACHE_FILE, 'w') as f:
        json.dump(cache, f)


def fetch_price_history(ticker_symbol, range_key):
    """
    Pulls OHLC candles for a ticker via yfinance and shapes them for
    lightweight-charts (time/open/high/low/close, time as 'YYYY-MM-DD').

    Data source note: this always uses yfinance today. Per the settled
    Schwab integration plan, equities may eventually route through Schwab
    instead — but futures/forex stay on yfinance permanently since Schwab
    doesn't cover those asset classes. Keeping this as its own function
    (rather than inlining the yf call in the endpoint) is what makes that
    later swap a one-function change instead of a route rewrite.
    """
    period_map = {
        '1mo': '1mo', '3mo': '3mo', '6mo': '6mo', '1y': '1y', '2y': '2y', '5y': '5y',
    }
    period = period_map.get(range_key, '3mo')
    hist = yf.Ticker(ticker_symbol).history(period=period)
    if hist is None or hist.empty:
        return []
    candles = []
    for idx, row in hist.iterrows():
        candles.append({
            "time": idx.strftime('%Y-%m-%d'),
            "open": round(float(row['Open']), 4),
            "high": round(float(row['High']), 4),
            "low": round(float(row['Low']), 4),
            "close": round(float(row['Close']), 4),
        })
    return candles


@bp.route('/get_price_history/<ticker>', methods=['GET'])
def get_price_history(ticker):
    ticker_symbol = ticker.upper()
    range_key = request.args.get('range', '3mo')
    cache_key = f"{ticker_symbol}:{range_key}"
    asset_class = get_asset_class(ticker_symbol)

    with price_history_lock:
        cache = load_price_history_cache()
        entry = cache.get(cache_key)
        now = time.time()

        if entry and (now - entry.get('fetched_at', 0)) < PRICE_HISTORY_TTL_SECONDS:
            return jsonify({
                "ticker": ticker_symbol,
                "asset_class": asset_class,
                "range": range_key,
                "candles": entry['candles'],
                "cached": True,
            })

        try:
            candles = fetch_price_history(ticker_symbol, range_key)
        except Exception as e:
            print(f"[PRICE HISTORY] Fetch failed for {ticker_symbol}: {e}")
            # Never cache a failure — same principle as news_cache. Serve stale
            # data if we have it rather than an empty chart; otherwise empty.
            if entry:
                return jsonify({
                    "ticker": ticker_symbol,
                    "asset_class": asset_class,
                    "range": range_key,
                    "candles": entry['candles'],
                    "cached": True,
                    "stale": True,
                })
            return jsonify({
                "ticker": ticker_symbol,
                "asset_class": asset_class,
                "range": range_key,
                "candles": [],
                "error": "fetch_failed",
            })

        cache[cache_key] = {"candles": candles, "fetched_at": now}
        save_price_history_cache(cache)

        return jsonify({
            "ticker": ticker_symbol,
            "asset_class": asset_class,
            "range": range_key,
            "candles": candles,
            "cached": False,
        })
