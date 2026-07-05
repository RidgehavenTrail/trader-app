# Stock Dashboard — Claude Code Instructions
# Last updated: 2026-07-04 — see CONTEXT.md (repository copy) for the fast-load session
# brief and current 3D heatmap status; this file covers engine/dashboard architecture only.

## Project Overview

A real-time stock watchlist dashboard that monitors a user-defined ticker list, identifies outsized price moves relative to the nearest-term ATM put premium, and triggers AI-powered news synthesis to explain the catalyst.

- **Engine** (`market_data_engine.py`) — Alpha Vantage news + Claude synthesis, with Claude web search fallback. Port 5000. Also now serves `/get_price_history/<ticker>` (OHLC + SMA-ready candles, cached) for the chart tab — see `.claude/rules/newsletter-tracker.md`.
- **Dashboard** (`trader_dashboard.html`) — polls the engine every 10 seconds.
- **Newsletter tracker UI** (`watchtower.html`) — standalone prototype, not yet merged into the dashboard above. Renamed from `newsletter_mockup.html` 2026-07-05. See `.claude/rules/newsletter-tracker.md`.

**Note:** the previous parallel Claude engine (port 5001) is deprecated as of
2026-07-04 — AV engine only now.

---

## Before Making Any Code Changes

1. **Always read the file before editing it** — never edit from memory or a prior session's view
2. **Always verify Python syntax** after editing the engine:
   ```bash
   python3 -c "import ast; ast.parse(open('market_data_engine.py').read())" && echo "OK"
   ```
3. **Never hardcode API keys** — placeholders only:
   - `ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"`
   - `ALPHA_VANTAGE_KEY = "YOUR_ALPHA_VANTAGE_KEY_HERE"`
   - `GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"`

---

## Running the Project

```bash
# Terminal 1 — serve dashboard
python3 -m http.server 8000

# Terminal 2 — engine
python3 market_data_engine.py

# Test mode (bypasses market hours, uses last two trading session closes)
python3 market_data_engine.py --test
```

---

## Architecture — Critical Design Decisions

### Trigger Logic
```
abs(pct_change_vs_prev_close) > ATM_put_premium_pct
AND
abs(pct_change_vs_prev_close) >= MIN_ABSOLUTE_TRIGGER_PCT   (2.0, set 2026-07-02)
```
ATM put premium uses mark price `(bid+ask)/2` (see Known Pitfalls — lastPrice is stale).
`MIN_ABSOLUTE_TRIGGER_PCT` is a hard floor added on top of the 1σ breach because the
1σ condition alone let low-IV mega-caps and ETFs (tight ATM put premium, e.g. XLK at
~1.36%) trigger on moves too small to be tradeable-sized. Both conditions must be true.
The 1σ bound (`±X%`) is still computed and still shown on every card — the floor only
gates whether a card gets posted, it doesn't change what's displayed. Constant lives
near the top of `market_data_engine.py`.

### Thread Safety
All writes to `actionable_moves.json` go through `patch_actionable_move()` — a lock-protected read-modify-write. **Never do a whole-file blind overwrite** from the main loop or background threads. This fixed a race condition where the main loop's end-of-pass write clobbered background thread patches.

### Cache Prefill Pattern
Before writing a placeholder card, `fetch_loop` checks the cache first. If a valid cached synthesis exists, it writes the real fields directly — no background thread needed. This prevents a race where a fast cache-hit background thread patches the file, then a subsequent ticker's `patch_actionable_move` overwrites it during its own read-modify-write.

### Cache Lifecycle
- **News cache** (`news_cache.json`) — stores raw news text, cleared at midnight weekday rollovers only (NOT on restart)
- **Never cache failed synthesis** — check `why` field against failure phrases before writing to cache
- **Restart intentionally preserves today's cache** — only midnight rollover clears it

### Token Architecture (Claude Search Fallback)
- Turn 1: web search, expensive (5,000-47,000 tokens depending on ticker/ETF)
- Turn 2: synthesis only — **strip raw search blocks** before passing Turn 1 context forward, keeping only `type: "text"` blocks. This dropped per-ticker usage from ~50,000 to ~5,000-15,000 tokens
- `fallback_semaphore = threading.Semaphore(2)` — caps concurrent fallback calls to prevent TPM bursts
- Rate limiter tracks both RPM (45/min) and TPM (45,000/min) in rolling windows
- Oversized single calls (> TPM ceiling) bypass the limiter rather than loop forever

### ETF Detection
`stock.info['quoteType'] == 'ETF'` determines prompt branching. ETFs get a macro/sector-focused search prompt; individual stocks get company-specific catalyst prompts.

### Macro Regime Panel
`generate_macro_regime()` fetches ^TNX and ^VIX via yfinance, calls Gemini 2.5 Flash with Google Search grounding, and writes `macro_regime.json`. `macro_loop()` fires once at startup then hourly during pre-market/open hours. The dashboard polls `/get_macro_regime` every 10 minutes.

**Important:** yfinance history calls use `period="1mo"` (not `"5d"`) for ^TNX and ^VIX. The `"5d"` period can return fewer than 2 rows after a system restart or crash, causing a silent bail-out. If the macro panel shows stale data after a restart, check the log for `[MACRO] Insufficient yfinance history`.

### Market Hours (ET)
```
closed:      midnight → 8:00am  (loop idles)
pre_market:  8:00am → 9:30am    (uses fast_info.pre_market_price)
open:        9:30am → 4:00pm    (normal live prices)
after_hours: 4:00pm → midnight  (loop idles, dashboard static for review)
```
Midnight clear fires Mon-Fri rollovers and Sun→Mon. Skips Fri→Sat and Sat→Sun so Friday's moves survive the weekend.

---

## Planned: Schwab Data Source Integration

**NOT YET BUILT.** Design settled 2026-07-03, no code written. Full spec — data
source table, fast-loop/slow-refresh decoupling, active-trader/situational-awareness
mode design, OAuth token lifecycle, chain-parsing rationale, 5-item build order —
lives in `.claude/rules/schwab-integration.md` (path-scoped, auto-loads when Claude
touches `market_data_engine.py` or any `schwab*.py` file). Do not duplicate that
content back into this file.

## Planned: Newsletter Tracker

**UI mockup + chart infrastructure built 2026-07-04** (`watchtower.html`,
plus the new `/get_price_history` endpoint in `market_data_engine.py`). Schema,
ingestion, and lifecycle storage are still just a brainstorm — confirm with the
user before writing that part. Condenses a weekly market newsletter (stocks,
options, futures, heavy on pairs trading via composite charts) into structured
trade cards with lifecycle tracking and a composite ratio/spread chart pipeline.
Full detail — what's built and settled vs. still brainstorm — lives in
`.claude/rules/newsletter-tracker.md` (path-scoped, auto-loads when Claude
touches `market_data_engine.py`, `newsletter*.py`, `trader_dashboard.html`, or
`watchtower.html`). Do not duplicate that content back into this file.

---

## File Structure

```
project/
├── market_data_engine.py      # Engine (port 5000)
├── trader_dashboard.html      # Dashboard
├── watchtower.html      # Newsletter tracker UI (renamed from newsletter_mockup.html) — standalone, not merged in yet
├── price_history_cache.json    # Cache for /get_price_history (TTL 300s, never caches failures)
├── heatmap_3d.py               # 3D options OI blanket heatmap — LOCKED (see CONTEXT.md)
├── ridgeline.py                 # Catenary ridgeline module — LOCKED, never modify
├── save_oi_snapshot.py         # Save OI data before midnight rollover
├── test_heatmap.py             # 2D options heatmap (standalone, run: python3 test_heatmap.py TICKER)
├── test_heatmap_3d_v1.py       # v1 terrain model — locked reference baseline
├── test_heatmap_3d.py          # v1 alias / earlier iteration — locked reference
├── test_heatmap_3d_blanket.py  # blanket terrain dev iteration
├── test_heatmap_3d_impulse.py  # impulse terrain dev iteration
├── test_heatmap_3d_v2.py       # v2 terrain dev iteration
├── debug_avex.py                # scratch: one-off AVEX mark-price debug script
├── tickers.json                # Watchlist
├── market_data.json            # Live prices
├── actionable_moves.json       # Triggered cards
├── news_cache.json             # News cache
├── macro_regime.json           # Latest macro briefing
├── archive/                     # Daily archives
└── scratch/                     # Retired/experimental files
```

**Note:** `inspect_news_cache.py` and `inspect_alpha_vantage.py` (referenced in older
versions of this file) no longer exist in the project — removed at some point, not
replaced with equivalents. Use direct file reads or the inline Python snippets below
for cache debugging instead.

---

## Common Debug Tasks

### Clear a specific cache entry
```bash
python3 -c "
import json
from datetime import date
with open('news_cache.json') as f:
    cache = json.load(f)
key = f'{date.today().isoformat()}:TICKER'
if key in cache:
    del cache[key]
    print(f'Removed {key}')
with open('news_cache.json', 'w') as f:
    json.dump(cache, f)
"
```

### Clear all bad cache entries in bulk
```bash
python3 -c "
import json
with open('news_cache.json') as f:
    cache = json.load(f)
before = len(cache)
cache = {k: v for k, v in cache.items() if 'unavailable' not in v.get('why', '').lower()}
with open('news_cache.json', 'w') as f:
    json.dump(cache, f, indent=2)
print(f'Removed {before - len(cache)} bad entries.')
"
```

### Inspect what Claude received for a ticker
No dedicated script exists for this anymore (`inspect_news_cache.py` was removed).
Read the cache entry directly instead:
```bash
python3 -c "
import json
from datetime import date
with open('news_cache.json') as f:
    cache = json.load(f)
key = f'{date.today().isoformat()}:INTC'
print(json.dumps(cache.get(key, 'Not cached'), indent=2))
"
```

### Check raw Alpha Vantage feed for a ticker
No dedicated script exists for this anymore (`inspect_alpha_vantage.py` was removed).
`debug_avex.py` is a one-off scratch script (hardcoded to AVEX, checks options chain
mark price, not Alpha Vantage) — copy its pattern for a new ticker if needed, or call
`fetch_latest_news(ticker)` directly from a Python REPL with the engine's functions
imported.

---

## Alpha Vantage News Filtering Rules

Two conditions must both pass for an article to be included:
1. Relevance score ≥ 0.5 for the specific ticker
2. No other ticker in the same article scores within 0.05 of the primary ticker's relevance score (prevents sector/comparison articles like "AMD vs INTC" from being treated as single-company news)

---

## Options Heatmap (test_heatmap.py)

Standalone script that fetches real yfinance options chain data and renders
a self-contained HTML heatmap. Run with:
```bash
python3 test_heatmap.py AMD
python3 test_heatmap.py AAPL
```

### Data Pipeline
- Fetches all expirations within 90 days via yfinance
- Strike keys stored as `str(float(strike))` — e.g. `"520.0"` — throughout Python and JS to avoid float/int key mismatch
- Uses `.values` arrays directly (not `iterrows()`) to avoid DataFrame index leaking into strike keys
- Strike filter: OI threshold-based (min_oi=100 at any expiration) + ±30% price range cap, with progressive fallback to 50/10/1 if fewer than 20 strikes survive
- Smoothing: Gaussian kernel (sigma=14) across strikes before rendering

### 2D Heatmap Design (current implementation)
- Butterfly layout: puts left, calls right, 0 DTE at center
- X axis: compressed time scale — 0-14 DTE = 42% of half-width, 14-42 DTE = 33%, 42-90 DTE = 25%
- Y axis: strike prices (shared, continuous, highest strike at top)
- Color: dark background → bright lime green (calls peak) / bright orange-red (puts peak), log scale
- Amber horizontal line = current price
- Dashed vertical lines at 14 DTE and 42 DTE zone boundaries
- Column boundaries pre-computed via `computeColBounds()` — no overlap, no gaps
- Cells use strike array INDEX for Y positioning (not dollar value) for pixel-perfect tiling
- 95th percentile OI as color scale ceiling to prevent outlier domination

### 3D Relief Model — `heatmap_3d.py`

**LOCKED.** Architecture, key constants, ridgeline/terrain algorithm, fixed bugs,
open priorities, and validated design decisions now live in
`.claude/rules/heatmap-3d.md` (path-scoped, auto-loads when Claude touches
`heatmap_3d.py`, `ridgeline.py`, `save_oi_snapshot.py`, or any `test_heatmap_3d*.py`
file). For broader project status and why v1 was superseded, see `CONTEXT.md`
(repository copy). Do not duplicate that content back into this file.

---

## Known Pitfalls

- **Similar ticker symbols** (e.g. SPCX vs SPCK) can still cause cross-ticker contamination despite the co-mention filter — Alpha Vantage's relevance scoring isn't perfect
- **ETFs generate large search results** — XLK consumed 47,564 tokens in a single Turn 1 call; the oversized call bypass handles this but it's worth monitoring token logs
- **`[SYNTHESIS COMPLETE]` in the log does not guarantee the card updated** — if the completion message appears but the card shows placeholder text, check whether a subsequent `patch_actionable_move` from the main loop overwrote the synthesis (this was fixed but worth knowing)
- **Alpha Vantage free tier: 25 calls/day** — the cache is specifically designed to protect this quota across restarts; do not clear the news cache on engine restart
- **Claude search coverage gaps:** Claude search fallback performs well on hard catalyst news (earnings, analyst actions, press releases) but may miss fundamental/valuation analysis pieces that Google surfaces more readily. "Insufficient information" results on declining stocks may reflect search coverage gaps rather than a true absence of relevant content. This is an accepted edge case — the honest "no catalyst found" response is preferable to hallucinating an explanation.
- **Stale midnight threads:** Background synthesis threads running at market close can still be alive at midnight when the daily clear fires. `last_clear_time` sentinel in `clear_actionable_moves()` and stale thread guard in `run_synthesis_in_background()` prevent them from resurrecting cleared cards. Never remove this guard.
- **Pre-market false re-triggers:** If `fast_info.pre_market_price` is None, skip trigger evaluation entirely — do NOT fall back to yesterday's close. Falling back causes yesterday's moves to re-trigger every morning before live data arrives. The pre-market branch writes `"change": "pre-mkt"` to market_data and calls `continue` to skip the ticker.
- **News cache failure phrases:** Failed synthesis results (`"synthesis failed"`, `"timed out"`, `"api error"`, `"n/a"`, `"unavailable"`) must never be cached. Check the `why` field before calling `set_cached_news()`. The cache prefill path in `fetch_loop` also validates cached entries before writing to the card.
- **ATM put premium uses mark price, not lastPrice** — `lastPrice` from yfinance is the last trade price, which can be stale by hours for illiquid options. `analyze_options_structure()` computes the mark as `(bid + ask) / 2` when both are available, falling back to `lastPrice` only if bid/ask are missing. This is critical for correctly sizing the expected move threshold — stale lastPrice was causing wide-premium tickers like AVEX to fail to trigger on legitimate moves.
- **yfinance strike key format:** Options chain strike values from yfinance must be stored as `str(float(strike))` throughout. Use `.values` arrays (not `iterrows()`) to extract strikes — `iterrows()` leaks the DataFrame row index into the keys.
- **Dashboard actionable card strip scroll:** The strip uses window-level capture phase pointer events for drag-to-scroll (`window.addEventListener('pointerdown', ..., {capture: true})`). Card inner elements have `pointer-events: none` permanently so clicks always land on the outer card div with the `onclick` handler. Do not add `pointer-events` to card children or change the event listener approach — this was hard-won after extensive debugging. The `pointerdown` event does not bubble correctly to the container from child elements in Chrome.
