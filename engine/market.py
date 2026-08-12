"""
Market-data + ticker-management HTTP layer — engine split phase 4 (2026-07-22),
extracted verbatim from watchtower_engine.py following the phase 1-3 pattern:
self-contained, imports NOTHING from watchtower_engine (no circular import) —
only stdlib, flask, and engine.common.

    from engine.market import bp as market_bp
    app.register_blueprint(market_bp)

Routes:
  GET  /get_market_data  — serve the snapshot fetch_loop writes each pass
  POST /add_ticker       — append one symbol to the tracked list
  POST /delete_ticker    — remove one symbol
  POST /sync_tickers     — replace the whole list from the frontend's localStorage

Routes only, no background thread (unlike phase 3's macro) — fetch_loop, which
produces the data these serve, stays in the engine until the final phase.

TICKERS_FILE / DATA_FILE / get_tickers / save_tickers live in engine.common
because fetch_loop needs them too; they cannot live here without recreating the
cycle the split exists to avoid.
"""
import json
import os

from flask import Blueprint, jsonify, request

from engine.common import DATA_FILE, get_tickers, save_tickers

bp = Blueprint('market', __name__)


@bp.route('/get_market_data', methods=['GET'])
def get_market_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})


@bp.route('/add_ticker', methods=['POST'])
def add_ticker():
    data = request.json
    ticker = data.get('ticker', '').upper()
    tickers = get_tickers()
    if ticker and ticker not in tickers:
        tickers.append(ticker)
        save_tickers(tickers)
    return jsonify({"status": "success", "tickers": tickers})


@bp.route('/delete_ticker', methods=['POST'])
def delete_ticker():
    data = request.json
    ticker_to_delete = data.get('ticker', '').upper()
    tickers = get_tickers()
    if ticker_to_delete in tickers:
        tickers.remove(ticker_to_delete)
        save_tickers(tickers)
    return jsonify({"status": "success"})


@bp.route('/sync_tickers', methods=['POST'])
def sync_tickers():
    data = request.json
    frontend_tickers = data.get('tickers', [])
    if isinstance(frontend_tickers, list) and len(frontend_tickers) > 0:
        clean_tickers = list(set([str(t).upper() for t in frontend_tickers]))
        save_tickers(clean_tickers)
        print(f"[SYNC] Engine is now tracking: {clean_tickers}")
        return jsonify({"status": "success", "tickers": clean_tickers})
    return jsonify({"status": "no_change"})
