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


# --- Deterministic context for the briefing (session 44) ----------------------
# Between 08:35 and this hour, a price reaction is worth measuring; after it, the
# 08:30 window is stale news and would just be noise on every hourly refresh.
REACTION_WINDOW_END_HOUR = 11
RELEASE_TIME_ET = (8, 30)


def _deterministic_context(now):
    """(figures_block, reaction_block, figures, reaction). NEVER raises.

    Both halves are a BONUS on top of the briefing, exactly as peer/macro context is a
    bonus on top of a news card -- and session 43 established what happens when a
    cosmetic context builder is allowed to throw into a paid call's error path: the
    paid pull is discarded and retried. Each half is wrapped separately so one failing
    cannot cost us the other, or the Gemini call.
    """
    figures_block = reaction_block = ""
    figures = reaction = None

    try:
        from engine.release_data import latest_releases
        from engine.release_data import format_for_prompt as fmt_figures
        figures = latest_releases(now=now)
        block = fmt_figures(figures)
        figures_block = f"\n{block}\n" if block else ""
    except Exception as e:
        print(f"[MACRO] release figures unavailable ({type(e).__name__}: {e}) "
              f"— continuing without them")

    try:
        if now.weekday() < 5 and (
                (now.hour, now.minute) >= RELEASE_TIME_ET
                and now.hour < REACTION_WINDOW_END_HOUR):
            from engine.release_reaction import measure_release_reaction
            from engine.release_reaction import format_for_prompt as fmt_reaction
            rel_dt = now.replace(hour=RELEASE_TIME_ET[0], minute=RELEASE_TIME_ET[1],
                                 second=0, microsecond=0)
            reaction = measure_release_reaction(rel_dt, now=now)
            block = fmt_reaction(reaction)
            reaction_block = f"\n{block}\n" if block else ""
    except Exception as e:
        print(f"[MACRO] release reaction unavailable ({type(e).__name__}: {e}) "
              f"— continuing without it")

    return figures_block, reaction_block, figures, reaction


def generate_macro_regime():
    """
    Fetches live ^TNX and ^VIX data via yfinance, pulls the day's released FIGURES
    from the publishing agency and measures the tape's REACTION to the 08:30 window,
    then calls Gemini with Google Search grounding to write the briefing around them.
    Writes result to macro_regime.json.
    Only runs during market hours (8am-4pm ET weekdays).

    THE MODEL NO LONGER LOOKS UP NUMBERS. It is handed the figures and the measured
    reaction and writes prose around them -- the same split the newsletter path uses
    (model turns prose into primitives; Python owns everything computable). It exists
    here because the reverse cost us a morning: on 2026-08-13 the model was asked to
    search for a PPI print seven minutes old, correctly reported it could not find the
    figure, and then wrote a headline saying markets awaited a release that had
    already happened.
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

        # THE MARKET'S OWN MOVE, so a card can say WITH or AGAINST it (user, 2026-08-17).
        # On a day with no macro print the briefing headline is model narrative with no
        # event under it -- on 2026-08-17 "reduced Fed rate hike bets" explained four
        # cards at 10:15 and had vanished from the 11:20 regeneration, with no speaker
        # and no release all day. A direction is a FACT and needs no narrative.
        #
        # Fetched here rather than in the news path: this job already runs hourly and
        # already pays for yfinance, so the news pull reads a number instead of adding a
        # call per ticker. SPY, not the watchlist median -- that list is tech-heavy and
        # would call its own concentration "the market". Failure is non-fatal: the field
        # goes absent and the news path simply omits the comparison.
        spy_price = spy_change_pct = None
        try:
            spy_hist = yf.Ticker("SPY").history(period="5d")
            if len(spy_hist) >= 2:
                _now = float(spy_hist['Close'].iloc[-1])
                _prev = float(spy_hist['Close'].iloc[-2])
                spy_price = round(_now, 2)
                spy_change_pct = round((_now / _prev - 1) * 100, 2)
        except Exception as e:
            print(f"[MACRO] SPY reference unavailable ({type(e).__name__}: {e}) — "
                  f"cards will omit the with/against-the-market line")

        now = datetime.now(ET)
        now_et = now.strftime('%A %Y-%m-%d %I:%M %p ET')
        figures_block, reaction_block, figures, reaction = _deterministic_context(now)

        prompt = f"""Search for today's market news and provide a concise market briefing.

It is currently {now_et}. Anything scheduled for EARLIER today has already
happened — treat it as reported, not upcoming.
{figures_block}{reaction_block}
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

Any RELEASED FIGURES block above is AUTHORITATIVE — it was retrieved from the
publishing agency itself. Do not search for those numbers, do not replace them
with a figure you find elsewhere, and do not recompute them. Search is for
narrative, positioning and reaction commentary, not for the prints.

EVERY line of that block must appear in "data_releases" with its figure copied
exactly as supplied — all of them, whatever agency each came from, matching by
which release it is rather than by exact wording of the label. You already have
those numbers: never write that a supplied figure is unavailable, missing or
not in hand. (Observed failure: jobless claims were supplied as a figure and
still written up as "not yet in hand" while the PPI lines were copied
correctly.)

Only for a US release scheduled TODAY that is NOT in that block (ISM, consumer
sentiment, JOLTS, FOMC, GDP and anything else) decide which is true:
  RELEASED     - it has printed. Give the ACTUAL figure and what was expected.
  NOT RELEASED - its scheduled time has not arrived yet. Say so plainly.
"NOT RELEASED" is a correct and expected answer — never guess a figure, and
never present a preview as a result. If one of THOSE printed earlier today and
you cannot find its number, say the figure is not yet in hand. Never describe a
release that has already printed as upcoming, awaited or anticipated — that is
a statement about the market, and it would be false.

EXPECTATIONS are not supplied above. Where you give a consensus/expected figure
it must come from your own sources, and you must NOT mark it as such in the
text — see the formatting rule below.

FORMATTING — every field is read by a person on a dashboard. Output PLAIN PROSE
only: no citation markers, no bracketed source tags, no "[cite: ...]", no
footnote markup, no references to "provided data" or to these instructions. If
you cannot state something without a citation marker, state it without the
marker or leave it out.

Return ONLY a valid JSON object with exactly these three keys, no preamble,
no markdown fences:
"headline": A single punchy sentence capturing the dominant market theme today.
A release that has already printed must NEVER be described as awaited or
anticipated here, even when its figure is not in hand — if today's theme is a
print, the headline is what it DID, not that it is coming.
"summary": AT MOST 3 sentences covering what's moving markets, major catalysts
on deck today, and the current risk tone. Concise and actionable for an active
trader who is busy — every sentence must earn its place, and three short ones
beat five. A release that has already printed must be described in the past
tense: give its figure when one is supplied above, and otherwise say the figure
is not yet in hand. Report LEVELS, not intraday moves: a percentage change over
a time window is something the reader can see on a chart, so state where
something IS ("yield down to 4.63%"), not how far it travelled and over how
long. Mention an intraday move only when the price-action block above says it
was notable, and then in one clause.
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
        macro_data['spy'] = spy_price
        macro_data['spy_change_pct'] = spy_change_pct
        # PYTHON-AUTHORED, and persisted alongside the model's prose so downstream
        # consumers can read the FIGURE rather than re-reading a sentence about it.
        # macro_context() prefers these over the model's `data_releases` rows for
        # exactly that reason: `data_releases` is prose in a dict, and prose is not a
        # contract. Kept as separate keys rather than overwriting `data_releases`,
        # because merging the two would mean string-matching the model's row labels
        # against our release keys -- i.e. parsing prose to decide something, which is
        # the one thing Python is never allowed to do here.
        macro_data['released_figures'] = figures
        macro_data['market_reaction'] = reaction
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
