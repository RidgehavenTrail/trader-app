# Stock Dashboard — Architecture & Design Reference

## What This Is

A real-time stock watchlist dashboard that monitors a user-defined list of tickers, identifies outsized price moves relative to each stock's nearest-term ATM put premium (the "expected move"), and triggers AI-powered news synthesis to explain the catalyst. Built in Python (Flask backend) with a vanilla HTML/JS frontend.

---

## System Overview

Two parallel engines serve two separate dashboards for A/B comparison:

| | AV Engine | Claude Engine |
|---|---|---|
| **File** | `market_data_engine.py` | `market_data_engine_claude.py` |
| **Port** | 5000 | 5001 |
| **Dashboard** | `trader_dashboard.html` | `trader_dashboard_claude.html` |
| **News source** | Alpha Vantage (Claude search fallback) | Claude web search only |
| **Data files** | `market_data.json`, `actionable_moves.json` | `market_data_claude.json`, `actionable_moves_claude.json` |
| **Cache file** | `news_cache.json` | `news_cache_claude.json` |
| **Archive** | `archive/` | `archive_claude/` |
| **Shared** | `tickers.json` (watchlist shared between both engines) | |

---

## How to Run

```bash
# Serve dashboards (one terminal)
python3 -m http.server 8000

# AV engine (second terminal)
python3 market_data_engine.py

# Claude engine (third terminal)
python3 market_data_engine_claude.py

# Test mode — bypasses market hours, uses last two trading session closes
python3 market_data_engine.py --test
python3 market_data_engine_claude.py --test
```

Open `http://localhost:8000/trader_dashboard.html` and `http://localhost:8000/trader_dashboard_claude.html` in separate browser tabs.

---

## API Keys Required

Keys are stored in a `.env` file in the project root (never committed to source control). Copy `.env.example` to `.env` and fill in your values:

```
ANTHROPIC_API_KEY=your-key-here
ALPHA_VANTAGE_KEY=your-key-here
```

- **`ANTHROPIC_API_KEY`** — both engines use this for AI synthesis (Haiku 4.5). Get from platform.anthropic.com. Requires $5 minimum deposit (Tier 1) for 50 RPM.
- **`ALPHA_VANTAGE_KEY`** — AV engine only, for news sentiment. Free tier: 25 calls/day. Get from alphavantage.co.

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
3. The card is patched in place when synthesis completes
4. The dashboard polls every 10 seconds and re-renders automatically

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

### AV Engine (`news_cache.json`)
- Caches raw Alpha Vantage headline text (pre-synthesis) keyed by `YYYY-MM-DD:TICKER`
- Cache hit → reuses stored text, still runs a Claude synthesis call
- Cleared on weekday midnight rollovers; **not** cleared on engine restart (intentional — preserves today's fetched news across restarts)

### Claude Engine (`news_cache_claude.json`)
- Caches the **full synthesis output** `{why, structure, impact}` keyed by `YYYY-MM-DD:TICKER`
- Cache hit → patches card directly, **zero API calls**
- Failed synthesis results are never cached (checked against failure phrases before writing)
- Cleared on weekday midnight rollovers; not cleared on engine restart

### Clearing a specific cache entry manually
```bash
python3 -c "
import json
from datetime import date
with open('news_cache_claude.json') as f:
    cache = json.load(f)
key = f'{date.today().isoformat()}:TICKER'
if key in cache:
    del cache[key]
    print(f'Removed {key}')
with open('news_cache_claude.json', 'w') as f:
    json.dump(cache, f)
"
```

### Clearing bad entries in bulk
```bash
python3 -c "
import json
with open('news_cache_claude.json') as f:
    cache = json.load(f)
before = len(cache)
cache = {k: v for k, v in cache.items() if 'unavailable' not in v.get('why', '').lower()}
with open('news_cache_claude.json', 'w') as f:
    json.dump(cache, f, indent=2)
print(f'Removed {before - len(cache)} bad entries.')
"
```

---

## Alpha Vantage News Filtering (AV Engine)

Articles are filtered by two conditions before being sent to Claude:

1. **Relevance score ≥ 0.5** for the specific ticker (not just any mention)
2. **No other ticker scoring ≥ 0.4 in the same article** — prevents sector/comparison pieces (e.g. "AMD vs INTC") from being treated as single-company news

This addresses a real issue where Alpha Vantage's relevance scoring can assign high scores to articles primarily about a different company in the same sector.

---

## Claude Engine — Search & Synthesis Architecture

Two-turn conversation per trigger:

- **Turn 1:** Claude searches the web with a natural-language question ("What's driving the X% move in TICKER during the most recent trading session?") using the `web_search_20250305` tool with `max_uses: 3`
- **Turn 2:** The **text summary only** from Turn 1 is passed forward (raw search result blocks are stripped before Turn 2 to avoid token bloat — this was critical; leaving them in caused single-ticker calls to exceed 45,000 tokens)
- **ETF detection:** `stock.info['quoteType'] == 'ETF'` branches to a macro/sector-focused prompt instead of a company-specific one, keeping search results targeted

Model: `claude-haiku-4-5-20251001` for both turns.

---

## Rate Limiting (Claude Engine)

A token-aware `RateLimiter` class tracks both RPM and TPM in a rolling 60-second window. Key behaviors:

- `wait_for_slot(estimated_tokens)` blocks until both RPM and TPM limits allow the call
- After Turn 1 completes, `record_usage(actual_tokens)` updates the reservation with real token counts — Turn 2 uses Turn 1's actual count as its estimate (since Turn 2 context includes Turn 1's output)
- **Oversized call bypass:** if a single call's estimated tokens exceed the TPM ceiling (e.g. a high-coverage ETF consuming 47k tokens), the limiter lets it through rather than looping forever, relying on the API's 429 retry handler
- **`synthesis_semaphore = threading.Semaphore(2)`** caps concurrent synthesis calls at 2 to prevent TPM bursts when multiple tickers trigger in the same loop pass

Limits set at: 45 RPM (buffer under Tier 1's 50 RPM), 45,000 TPM (buffer under 50,000 TPM).

---

## Known Issues & Design Decisions

**Race condition (fixed):** The original `fetch_loop` read `actionable_moves.json` once at the top of each pass and wrote it all back at the end — this caused background thread patches to be overwritten by the main loop's stale snapshot. Fixed by routing all writes through `patch_actionable_move()` (lock-protected read-modify-write) and never doing a whole-file blind overwrite.

**Cache prefill (fixed):** On engine restart with existing cache, background threads completing near-instantly on cache hits could race with the main loop's placeholder write for subsequent tickers. Fixed by checking cache before writing placeholder — if cache exists and is valid, write real synthesis directly from `fetch_loop` itself with no background thread.

**Alpha Vantage ticker confusion:** Similar ticker symbols (e.g. SPCX vs SPCK) can cause cross-ticker contamination in Alpha Vantage's news feed even with relevance filtering. The co-mention filter catches most cases but not all.

**Token bloat (fixed):** Passing Turn 1's full `content` array into Turn 2 included raw `web_search_tool_result` blocks (up to 8,000 tokens each × 3 searches). Stripping to `text` blocks only dropped per-ticker token usage from ~50,000 to ~5,000-15,000.

---

## Archive

On each weekday midnight rollover (and Sunday→Monday), `actionable_moves.json` is archived to `archive/YYYY-MM-DD.json` before being cleared. Archives contain trimmed entries: `ticker`, `status`, `price`, `price_change`, `why`, `structure`, `impact`. The full options data (put wall, call wall, etc.) is not archived.

---

## File Structure

```
project/
├── market_data_engine.py          # AV engine (port 5000)
├── market_data_engine_claude.py   # Claude engine (port 5001)
├── trader_dashboard.html          # AV dashboard
├── trader_dashboard_claude.html   # Claude dashboard
├── tickers.json                   # Shared watchlist
├── market_data.json               # AV engine live prices
├── market_data_claude.json        # Claude engine live prices
├── actionable_moves.json          # AV engine triggered cards
├── actionable_moves_claude.json   # Claude engine triggered cards
├── news_cache.json                # AV engine news cache
├── news_cache_claude.json         # Claude engine synthesis cache
├── archive/                       # AV engine daily archives
└── archive_claude/                # Claude engine daily archives
```

---

## What Works Well

- Pre-market detection and separate badge status
- Weekend-aware midnight reset preserving Friday's moves through the weekend
- Claude search catching social media catalysts Alpha Vantage misses (e.g. Trump tweet driving INTC +10%)
- Alpha Vantage producing higher-quality, more succinct synthesis on well-covered stocks
- Token-aware rate limiting preventing 429 errors on burst triggers
- Test mode (`--test` flag) for after-hours debugging using last two trading session closes
- Options data panel in detail view showing exact ATM strike, put premium, expiration, IV, put wall, and call wall at time of trigger

## What to Watch

- Alpha Vantage 25 calls/day free tier — adequate for ~15 triggers/day with caching, may constrain larger watchlists
- Claude search token costs — ETFs and high-coverage names can consume 30,000+ tokens per call; XLK was the worst observed case
- Anthropic Tier 1 TPM ceiling (50,000) — single large calls can approach this; semaphore at 2 concurrent calls provides a reasonable buffer
