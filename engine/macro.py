"""
Macro regime layer — engine split phase 3 (2026-07-21), extracted verbatim from
watchtower_engine.py following the engine/newsletter.py + engine/price_history.py
pattern: self-contained, imports NOTHING from watchtower_engine (no circular
import) — only stdlib, flask, yfinance, requests, and engine.common.

FIRST phase to move a BACKGROUND THREAD, so unlike price_history this module
exports a starter as well as a blueprint (same shape as stoplight's
start_scheduler). The engine registers and starts it with:

    from engine.macro import bp as macro_bp, start_macro_loop
    app.register_blueprint(macro_bp)        # module level
    start_macro_loop()                      # __main__, next to the other loops

Serves GET /get_macro_regime (reads the persisted file only — the thread does all
the work), and macro_loop() keeps macro_regime.json fresh during market hours.

market_state() and ET live in engine.common because fetch_loop (still in the
engine) needs them too — they cannot live here without recreating the cycle.
"""
import json
import os
import threading
import time
from datetime import datetime

import requests
import yfinance as yf
from flask import Blueprint, jsonify

from engine.common import ET, market_state

bp = Blueprint('macro', __name__)

MACRO_FILE = 'macro_regime.json'

# --- Scheduled-release anchors (ET) -------------------------------------------
# The hourly staleness rule alone is phase-blind: it refreshes an hour after the
# last SUCCESS, which has no relationship to when data actually prints. A briefing
# generated at 08:29 would not refresh until 09:29, leaving an 08:30 release stale
# for 59 minutes — and the summary reads as though the number is still upcoming.
# These force a refresh once each anchor has passed, on top of the hourly rule.
# A few minutes AFTER the release, deliberately: at 08:30:00 the wires have printed
# but search has not indexed the result copy, so an instant pull still retrieves
# preview articles.
#   08:35  CPI, PPI, PCE, payrolls, jobless claims, retail sales, GDP
#   10:05  ISM, consumer sentiment, JOLTS
#   14:05  FOMC statement / minutes
RELEASE_ANCHORS_ET = [(8, 35), (10, 5), (14, 5)]

# Promoted out of macro_loop() so _existing_briefing_ts() can share the definition
# of "fresh" — a restart must inherit a briefing on exactly the terms the loop
# would have considered current.
CHECK_SECONDS = 300      # poll cadence
STALE_SECONDS = 3600     # a successful update stays fresh ~1 hour

# Read at import time, exactly as the engine did. The engine calls load_dotenv()
# at the top of its module, long before it imports this blueprint, so the value
# is populated by the time this line runs.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _existing_briefing_ts():
    """Epoch of the briefing already on disk, or 0.0 if there isn't a usable one.

    Lets a restart INHERIT a still-fresh briefing instead of regenerating it. The
    startup pull used to be unconditional, so every engine restart burned a Gemini
    call rewriting a file that was minutes old — and on a day with several restarts
    that is the dominant cost, well above anything the hourly loop spends.

    Keyed on file mtime rather than the `updated_at` field, which is formatted
    '%I:%M %p ET' and carries no date, so it cannot be turned back into an instant.
    Anything older than STALE_SECONDS reads as absent and the caller regenerates.
    """
    try:
        if not os.path.exists(MACRO_FILE):
            return 0.0
        with open(MACRO_FILE) as f:
            if not json.load(f).get('headline'):
                return 0.0          # present but empty/failed — treat as absent
        ts = os.path.getmtime(MACRO_FILE)
        return ts if (time.time() - ts) < STALE_SECONDS else 0.0
    except Exception:
        return 0.0


def _release_anchor_passed(last_ok, now=None):
    """True when a scheduled-release anchor has fallen between the last successful
    briefing and now — i.e. data has printed that the current briefing predates.

    Returns False when last_ok is 0 (no good briefing yet): the caller is already
    going to refresh in that case, and treating it as due would be meaningless.
    """
    if not last_ok:
        return False
    now = now or datetime.now(ET)
    last = datetime.fromtimestamp(last_ok, ET)
    for hh, mm in RELEASE_ANCHORS_ET:
        anchor = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if last < anchor <= now:
            return True
    return False


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

        tnx_hist = tnx.history(period="1mo")
        vix_hist = vix.history(period="1mo")

        if len(tnx_hist) < 2 or len(vix_hist) < 2:
            print(f"[MACRO] Insufficient yfinance history — TNX rows: {len(tnx_hist)}, VIX rows: {len(vix_hist)}. Skipping.")
            return

        tnx_price = round(float(tnx_hist['Close'].iloc[-1]), 2)
        tnx_change = round(float(tnx_hist['Close'].iloc[-1]) - float(tnx_hist['Close'].iloc[-2]), 2)
        vix_price = round(float(vix_hist['Close'].iloc[-1]), 2)
        vix_change = round(float(vix_hist['Close'].iloc[-1]) - float(vix_hist['Close'].iloc[-2]), 2)

        now_et = datetime.now(ET).strftime('%A %Y-%m-%d %I:%M %p ET')
        prompt = f"""Search for today's market news and provide a concise market briefing.

It is currently {now_et}. Anything scheduled for EARLIER today has already
happened — treat it as reported, not upcoming.

Current market data:
- 10-Year Treasury Yield: {tnx_price}% ({'+' if tnx_change >= 0 else ''}{tnx_change} today)
- VIX: {vix_price} ({'+' if vix_change >= 0 else ''}{vix_change} today)

Search for what's driving broad market movement today, any major scheduled
catalysts (Fed speakers, economic data releases, large earnings announcements),
and the current risk tone across markets.

DATA RELEASES — this is the part that is most often got wrong. Most search
results about a scheduled release are PREVIEW articles written before it, so
they outnumber the coverage of the actual print and will dominate the results.
Do not let that make you describe a number that has already come out as though
it is still expected.

For every US economic release scheduled TODAY (CPI, PPI, PCE, payrolls, jobless
claims, retail sales, GDP, ISM, consumer sentiment, JOLTS, FOMC), decide
explicitly which of these is true:
  RELEASED     - it has printed. Give the ACTUAL figure and what was expected.
  NOT RELEASED - its scheduled time has not arrived yet. Say so plainly.
"NOT RELEASED" is a correct and expected answer — never guess a figure, and
never present a preview as a result. If a release was scheduled for earlier
today and you cannot find the actual number, say the figure was not found
rather than describing it as upcoming.

Return ONLY a valid JSON object with exactly these three keys, no preamble,
no markdown fences:
"headline": A single punchy sentence capturing the dominant market theme today
"summary": 2-3 sentences covering what's moving markets, major catalysts on
deck today, and the current risk tone. Keep it concise and actionable for
an active trader. A release that has already printed must be described in the
past tense with its actual figure, never as awaited.
"data_releases": One short line per US release scheduled today, each tagged
RELEASED or NOT RELEASED, e.g. "Core PCE (8:30 ET): RELEASED +0.3% m/m vs
+0.2% expected" or "CPI (8:30 ET Wed): NOT RELEASED". Use the exact string
"none scheduled" if there are no US releases today."""

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
        return True

    except Exception as e:
        print(f"[MACRO] Failed to generate macro regime: {e}")
    return False


def macro_loop():
    """Keep the macro regime FRESH during market hours (8am-4pm ET weekdays).

    Polls every few minutes and regenerates when it's market hours AND the last
    GOOD update is ~1h+ old — anchored to the MARKET SCHEDULE, not the engine start
    time. The old version slept a fixed 3600s from startup, so its hourly tick landed
    at an arbitrary minute (an engine started at 7:45pm only refreshed at :45 past the
    hour); at 8:00am premarket open the panel still showed the prior evening's briefing
    until 8:45am. Now it refreshes within a few minutes of premarket open and hourly
    through the close, and a failed attempt retries on the next poll rather than waiting
    a full hour. generate_macro_regime() returns True on success."""
    # Inherit a still-fresh briefing rather than regenerating it. A restart only
    # costs a call when the file is genuinely stale, missing, or empty.
    last_ok = _existing_briefing_ts()
    if last_ok:
        age = int((time.time() - last_ok) / 60)
        print(f"[MACRO] existing briefing is {age}m old — skipping the startup pull.")
    else:
        try:
            last_ok = time.time() if generate_macro_regime() else 0.0
        except Exception as e:
            print(f"[MACRO] startup refresh failed: {type(e).__name__}: {e}")
            last_ok = 0.0
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            # Two independent reasons to refresh: the briefing is simply old, OR a
            # scheduled release has printed since it was written. The second is what
            # stops an 08:30 number sitting undescribed until the hourly tick
            # happens to come round.
            due = (time.time() - last_ok >= STALE_SECONDS) or _release_anchor_passed(last_ok)
            if market_state() in ('pre_market', 'open') and due:
                if generate_macro_regime():
                    last_ok = time.time()
        except Exception as e:
            # Belt-and-braces: the loop must survive ANYTHING (mirrors stoplight's
            # scheduler_loop). generate_macro_regime() already swallows its own
            # errors, but anything it doesn't — or a raise from market_state() —
            # would otherwise kill this daemon thread SILENTLY. A dead macro thread
            # doesn't look like a crash: the panel just freezes, which reads as
            # "no news" and can go unnoticed for days. sleep() stays OUTSIDE this
            # try so a persistent failure still backs off instead of hot-spinning.
            print(f"[MACRO] loop error: {type(e).__name__}: {e}")


def start_macro_loop():
    """Start macro_loop on a daemon thread. Mirrors stoplight's start_scheduler —
    the engine calls this from __main__ instead of building the Thread itself."""
    t = threading.Thread(target=macro_loop, daemon=True, name="macro_loop")
    t.start()
    return t


@bp.route('/get_macro_regime', methods=['GET'])
def get_macro_regime():
    if os.path.exists(MACRO_FILE):
        try:
            with open(MACRO_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})
