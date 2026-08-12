"""
Per-ticker news archive — the history behind the "Why" box.

Engine-split pattern (engine/newsletter.py, engine/macro.py, ...): a self-contained
Flask Blueprint importing nothing from watchtower_engine. Registered with:

    from engine.news_archive import bp as news_archive_bp
    app.register_blueprint(news_archive_bp)

Serves GET /get_news_archive/<ticker>.

WHY THIS EXISTS
---------------
Actionable cards are patched IN PLACE, so a later trigger overwrites the narrative a
previous one wrote. Observed on ENB: a 2026-08-04 synthesis correctly identified the
Michigan Supreme Court vacating the Line 5 tunnel permit, and two turtle-only fires on
08-06 and 08-09 replaced it with "55-day short breakout". The analysis was not
missing — it was erased from the live card. It survives only because archive/ keeps an
end-of-day copy.

Reading the series back is worth more than any single entry. ENB's run flags "decline
contradicts positive news" on three separate days across six weeks before the Line 5
ruling lands — a pattern no individual card shows.

NO NEW CAPTURE. This reads what the engine already writes:
  archive/YYYY-MM-DD.json   end-of-day snapshot of the whole card set
  actionable_moves.json     today, which has not been archived yet

KNOWN LIMITS (surface these rather than papering over them)
  * History begins 2026-06-21 and has gaps — days with no triggers, or the engine down.
  * Only END-OF-DAY state is archived. Intraday re-patches are already lost.
  * A turtle-only day archives the one-liner, so it appears as a thin entry rather
    than a narrative. Flagged via has_news so the UI can dim it instead of pretending.
"""
import glob
import json
import os
import threading
import time

from flask import Blueprint, jsonify

bp = Blueprint('news_archive', __name__)

ARCHIVE_DIR = 'archive'
LIVE_FILE = 'actionable_moves.json'
META_FILE = 'actionable_moves_meta.json'

# A real synthesis vs the turtle one-liner ("55-day short breakout (Turtle System 2).").
# Length is a crude test but a robust one: every generated narrative runs to a few
# sentences, and every mechanical one-liner is well under this.
NEWS_MIN_CHARS = 120

CACHE_TTL_SECONDS = 300      # archive files change once a day; the live card intraday
_lock = threading.Lock()
_cache = {}                  # ticker -> (payload, at)


def _entry(day, card):
    why = (card.get('why') or '').strip()
    return {
        "date": day,
        "status": card.get('status'),
        "price": card.get('price'),
        "price_change": card.get('price_change'),
        "why": why,
        "structure": (card.get('structure') or '').strip() or None,
        "impact": (card.get('impact') or '').strip() or None,
        "news_source": card.get('news_source'),
        "conditions": card.get('conditions'),
        "has_news": len(why) >= NEWS_MIN_CHARS,
    }


def build_archive(ticker):
    """Newest-first history for one ticker. Today's live card first (it has not been
    archived yet), then every archived day it appears in."""
    out = []

    # Today, from the live card. Dated off the meta file rather than the clock, so it
    # matches whatever trading date the engine believes it is on.
    try:
        with open(LIVE_FILE, encoding='utf-8') as f:
            live = json.load(f)
        card = live.get(ticker)
        if card:
            day = None
            try:
                with open(META_FILE, encoding='utf-8') as f:
                    day = json.load(f).get('trading_date')
            except Exception:
                pass
            out.append(dict(_entry(day or 'today', card), live=True))
    except Exception as e:
        print(f"[NEWS] live card read failed: {type(e).__name__}: {e}")

    seen = {e["date"] for e in out}
    for path in sorted(glob.glob(os.path.join(ARCHIVE_DIR, '*.json')), reverse=True):
        day = os.path.basename(path)[:-5]
        if day in seen:
            continue                     # already have it from the live card
        try:
            with open(path, encoding='utf-8') as f:
                card = json.load(f).get(ticker)
        except Exception:
            continue                     # one unreadable day must not sink the history
        if isinstance(card, dict):
            out.append(dict(_entry(day, card), live=False))

    return {
        "ok": True,
        "ticker": ticker,
        "entries": out,
        "n_news": sum(1 for e in out if e["has_news"]),
        "n_total": len(out),
    }


@bp.route('/get_news_archive/<ticker>', methods=['GET'])
def get_news_archive(ticker):
    ticker = ticker.upper()
    with _lock:
        hit = _cache.get(ticker)
        if hit and time.time() - hit[1] < CACHE_TTL_SECONDS:
            return jsonify(hit[0])
    try:
        payload = build_archive(ticker)
    except Exception as e:
        print(f"[NEWS] archive build failed for {ticker}: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "ticker": ticker, "entries": [],
                        "error": f"{type(e).__name__}: {e}"})
    with _lock:
        _cache[ticker] = (payload, time.time())
    return jsonify(payload)
