# Stock Dashboard — Claude Code Instructions

## Project Overview

A real-time stock watchlist dashboard that monitors a user-defined ticker list, identifies outsized price moves relative to the nearest-term ATM put premium, and triggers AI-powered news synthesis to explain the catalyst.

- **Engine** (`market_data_engine.py`) — Alpha Vantage news + Claude synthesis, with Claude web search fallback. Port 5000.
- **Dashboard** (`trader_dashboard.html`) — polls the engine every 10 seconds.

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

### Market Hours (ET)
```
closed:      midnight → 8:00am  (loop idles)
pre_market:  8:00am → 9:30am    (uses fast_info.pre_market_price)
open:        9:30am → 4:00pm    (normal live prices)
after_hours: 4:00pm → midnight  (loop idles, dashboard static for review)
```
Midnight clear fires Mon-Fri rollovers and Sun→Mon. Skips Fri→Sat and Sat→Sun so Friday's moves survive the weekend.

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
```bash
python3 inspect_news_cache.py INTC
python3 inspect_news_cache.py INTC 2026-06-21  # specific date
```

### Check raw Alpha Vantage feed for a ticker
```bash
python3 inspect_alpha_vantage.py INTC
```

---

## Alpha Vantage News Filtering Rules

Two conditions must both pass for an article to be included:
1. Relevance score ≥ 0.5 for the specific ticker
2. No other ticker in the same article scores within 0.05 of the primary ticker's relevance score (prevents sector/comparison articles like "AMD vs INTC" from being treated as single-company news)

---

## Known Pitfalls

- **Similar ticker symbols** (e.g. SPCX vs SPCK) can still cause cross-ticker contamination despite the co-mention filter — Alpha Vantage's relevance scoring isn't perfect
- **ETFs generate large search results** — XLK consumed 47,564 tokens in a single Turn 1 call; the oversized call bypass handles this but it's worth monitoring token logs
- **`[SYNTHESIS COMPLETE]` in the log does not guarantee the card updated** — if the completion message appears but the card shows placeholder text, check whether a subsequent `patch_actionable_move` from the main loop overwrote the synthesis (this was fixed but worth knowing)
- **Alpha Vantage free tier: 25 calls/day** — the cache is specifically designed to protect this quota across restarts; do not clear the news cache on engine restart
- **Claude search coverage gaps:** Claude search fallback performs well on hard catalyst news (earnings, analyst actions, press releases) but may miss fundamental/valuation analysis pieces that Google surfaces more readily. "Insufficient information" results on declining stocks may reflect search coverage gaps rather than a true absence of relevant content. This is an accepted edge case — the honest "no catalyst found" response is preferable to hallucinating an explanation.
