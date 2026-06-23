# Stock Dashboard — Architecture & Design Reference

## What This Is

A real-time stock watchlist dashboard that monitors a user-defined list of tickers, identifies outsized price moves relative to each stock's nearest-term ATM put premium (the "expected move"), and triggers AI-powered news synthesis to explain the catalyst. Built in Python (Flask backend) with a vanilla HTML/JS frontend.

---

## System Overview

- **Engine** (`market_data_engine.py`) — Alpha Vantage news + Claude synthesis, with Claude web search as a fallback when Alpha Vantage has no relevant articles. Port 5000.
- **Dashboard** (`trader_dashboard.html`) — polls the engine every 10 seconds.
- **Macro panel** — powered by Gemini 2.5 Flash + Google Search grounding; updates on startup and hourly during market hours.

---

## How to Run

```bash
# Serve dashboard (one terminal)
python3 -m http.server 8000

# Engine (second terminal)
python3 market_data_engine.py

# Test mode — bypasses market hours, uses last two trading session closes
python3 market_data_engine.py --test
```

Open `http://localhost:8000/trader_dashboard.html` in a browser.

---

## API Keys Required

Keys are stored in a `.env` file in the project root (never committed to source control). Copy `.env.example` to `.env` and fill in your values:

```
ANTHROPIC_API_KEY=your-key-here
ALPHA_VANTAGE_KEY=your-key-here
GEMINI_API_KEY=your-key-here
```

- **`ANTHROPIC_API_KEY`** — AI synthesis and Claude web search fallback (Haiku 4.5). Get from platform.anthropic.com. Requires $5 minimum deposit (Tier 1) for 50 RPM.
- **`ALPHA_VANTAGE_KEY`** — primary news source. Free tier: 25 calls/day. Get from alphavantage.co.
- **`GEMINI_API_KEY`** — macro regime panel (Gemini 2.5 Flash + Google Search grounding). Get from aistudio.google.com.

---

## Trigger Logic

Each 60-second loop fetches price history for every ticker via yfinance. A ticker **triggers** when:

```
abs(pct_change) > ATM put premium percentage
```

Where `pct_change` is calculated against the previous trading session's close (holiday-safe via yfinance's trading-day-only history), and the ATM put premium is the last price of the nearest-expiration put closest to the current price, expressed as a percentage of the stock price.

When triggered:
1. A card is immediately written to the dashboard with placeholder text
2. A background thread runs news fetch + AI synthesis
3. If Alpha Vantage has no relevant articles, a two-turn Claude web search + synthesis call runs as fallback
4. The card is patched in place when synthesis completes
5. The dashboard polls every 10 seconds and re-renders automatically

---

## Market Hours (ET)

| State | Hours | Behavior |
|---|---|---|
| `closed` | Midnight → 8:00am | Loop idles, no fetches |
| `pre_market` | 8:00am → 9:30am | Uses `fast_info.pre_market_price`, status: "TRIGGERED - Pre-Market" |
| `open` | 9:30am → 4:00pm | Normal live prices |
| `after_hours` | 4:00pm → midnight | Loop idles, dashboard static for review |

Weekend behavior: dashboard stays static all weekend. Midnight clear only fires on weekday rollovers (Mon-Fri) and Sunday→Monday. Friday→Saturday and Saturday→Sunday midnight are skipped so Friday's moves are preserved for weekend review.

---

## Caching

### News cache (`news_cache.json`)
- Caches raw Alpha Vantage headline text (pre-synthesis) keyed by `YYYY-MM-DD:TICKER`
- Cache hit → reuses stored text, still runs a Claude synthesis call
- Failed synthesis results are never cached (checked against failure phrases on `why` field before writing)
- Cleared on weekday midnight rollovers; **not** cleared on engine restart (intentional — preserves today's fetched news across restarts)

### Clearing a specific cache entry manually
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

### Clearing bad entries in bulk
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

---

## Alpha Vantage News Filtering

Articles are filtered by two conditions before being sent to Claude:

1. **Relevance score ≥ 0.5** for the specific ticker
2. **No other ticker scoring within 0.05 of the primary ticker's relevance score** — prevents sector/comparison pieces (e.g. "AMD vs INTC") from being treated as single-company news

---

## Claude Search Fallback — Architecture

When Alpha Vantage returns no qualifying articles, a two-turn Claude search runs:

- **Turn 1:** Claude searches the web ("What's driving the X% move in TICKER?") using `web_search_20250305` with `max_uses: 3`
- **Turn 2:** Text summary only from Turn 1 is passed forward (raw search result blocks stripped to avoid token bloat)
- **ETF detection:** `stock.info['quoteType'] == 'ETF'` branches to a macro/sector-focused prompt
- **Semaphore:** `fallback_semaphore = threading.Semaphore(2)` caps concurrent fallback calls

Model: `claude-haiku-4-5-20251001` for both turns.

---

## Rate Limiting

A token-aware `RateLimiter` class tracks both RPM and TPM in a rolling 60-second window:

- `wait_for_slot(estimated_tokens)` blocks until both RPM and TPM limits allow the call
- `record_usage(actual_tokens)` updates with real counts after each call
- **Oversized call bypass:** single calls exceeding the TPM ceiling are let through rather than looping forever
- Limits: 45 RPM, 45,000 TPM (buffer under Tier 1's 50 RPM / 50,000 TPM)

---

## Known Issues & Design Decisions

**Race condition (fixed):** The original `fetch_loop` read `actionable_moves.json` once at the top of each pass and wrote it all back at the end — this caused background thread patches to be overwritten. Fixed by routing all writes through `patch_actionable_move()` (lock-protected read-modify-write).

**Stale thread guard (fixed):** Background synthesis threads triggered near 4pm could still be alive at midnight when the daily clear fires. Fixed by recording `last_clear_time` on each clear and checking it before any `patch_actionable_move` call — stale threads log `[STALE THREAD]` and discard their result.

**Token bloat (fixed):** Passing Turn 1's full `content` array into Turn 2 included raw search result blocks. Stripping to `text` blocks only dropped per-ticker usage from ~50,000 to ~5,000-15,000.

**Alpha Vantage ticker confusion:** Similar ticker symbols (e.g. SPCX vs SPCK) can cause cross-ticker contamination even with relevance filtering.

**Claude search coverage gaps:** Claude search fallback performs well on hard catalyst news (earnings, analyst actions, press releases) but may miss fundamental/valuation analysis pieces. "Insufficient information" on declining stocks may reflect search coverage gaps rather than a true absence of content. Honest over hallucinated.

---

## Archive

On each weekday midnight rollover, `actionable_moves.json` is archived to `archive/YYYY-MM-DD.json` before being cleared. Archives contain trimmed entries: `ticker`, `status`, `price`, `price_change`, `why`, `structure`, `impact`.

---

## File Structure

```
project/
├── market_data_engine.py      # Engine (port 5000)
├── trader_dashboard.html      # Dashboard
├── inspect_news_cache.py      # Debug: view cache entries for a ticker
├── inspect_alpha_vantage.py   # Debug: raw AV news response
├── tickers.json               # Watchlist
├── market_data.json           # Live prices
├── actionable_moves.json      # Triggered cards
├── news_cache.json            # News cache
├── macro_regime.json          # Latest macro briefing
├── archive/                   # Daily archives
└── scratch/                   # Retired/experimental files
```

---

## What Works Well

- Pre-market detection and separate badge status
- Weekend-aware midnight reset preserving Friday's moves through the weekend
- Claude search fallback catching catalysts Alpha Vantage misses
- Token-aware rate limiting preventing 429 errors on burst triggers
- Test mode (`--test` flag) for after-hours debugging
- Live macro regime panel (Gemini + Google Search) updating on startup and hourly
- Options data panel in detail view showing ATM strike, put premium, expiration, IV, put wall, and call wall at time of trigger

## What to Watch

- Alpha Vantage 25 calls/day free tier — adequate for ~15 triggers/day with caching, may constrain larger watchlists
- Claude search token costs — ETFs and high-coverage names can consume 30,000+ tokens per call
- Anthropic Tier 1 TPM ceiling (50,000) — single large calls can approach this; semaphore at 2 concurrent fallback calls provides a reasonable buffer
