# Stock Dashboard — Claude Code Instructions

## Project Overview

A real-time stock watchlist dashboard with two parallel engines for A/B comparison:
- **AV Engine** (`market_data_engine.py`) — Alpha Vantage news + Claude synthesis, port 5000
- **Claude Engine** (`market_data_engine_claude.py`) — Claude web search + synthesis, port 5001

Both engines share `tickers.json` and write to separate JSON data files. Two HTML dashboards (`trader_dashboard.html`, `trader_dashboard_claude.html`) poll their respective engines every 10 seconds.

---

## Before Making Any Code Changes

1. **Always read the file before editing it** — never edit from memory or a prior session's view
2. **Always verify Python syntax** after editing either engine:
   ```bash
   python3 -c "import ast; ast.parse(open('market_data_engine.py').read())" && echo "OK"
   python3 -c "import ast; ast.parse(open('market_data_engine_claude.py').read())" && echo "OK"
   ```
3. **Changes to dashboard logic apply to both HTML files** — `trader_dashboard_claude.html` mirrors `trader_dashboard.html` except for port (5001 vs 5000) and the CLAUDE SEARCH header badge
4. **Never hardcode API keys** — placeholders only:
   - `ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"`
   - `ALPHA_VANTAGE_KEY = "YOUR_ALPHA_VANTAGE_KEY_HERE"`

---

## Running the Project

```bash
# Terminal 1 — serve dashboards
python3 -m http.server 8000

# Terminal 2 — AV engine
python3 market_data_engine.py

# Terminal 3 — Claude engine
python3 market_data_engine_claude.py

# Test mode (bypasses market hours, uses last two trading session closes)
python3 market_data_engine.py --test
python3 market_data_engine_claude.py --test
```

---

## Architecture — Critical Design Decisions

### Thread Safety
All writes to `actionable_moves.json` (and `_claude` variant) go through `patch_actionable_move()` — a lock-protected read-modify-write. **Never do a whole-file blind overwrite** from the main loop or background threads. This fixed a race condition where the main loop's end-of-pass write clobbered background thread patches.

### Cache Prefill Pattern (Claude Engine)
Before writing a placeholder card, `fetch_loop` checks the cache first. If a valid cached synthesis exists, it writes the real fields directly — no background thread needed. This prevents a race where a fast cache-hit background thread patches the file, then a subsequent ticker's `patch_actionable_move` overwrites it during its own read-modify-write.

### Cache Lifecycle
- **AV engine cache** (`news_cache.json`) — stores raw news text, cleared at midnight weekday rollovers only (NOT on restart)
- **Claude engine cache** (`news_cache_claude.json`) — stores full `{why, structure, impact}` synthesis output, same clear schedule
- **Never cache failed synthesis** — check `why` field against failure phrases before writing to cache
- **Restart intentionally preserves today's cache** — only midnight rollover clears it

### Token Architecture (Claude Engine)
- Turn 1: web search, expensive (5,000-47,000 tokens depending on ticker/ETF)
- Turn 2: synthesis only — **strip raw search blocks** before passing Turn 1 context forward, keeping only `type: "text"` blocks. This dropped per-ticker usage from ~50,000 to ~5,000-15,000 tokens
- `synthesis_semaphore = threading.Semaphore(2)` — caps concurrent calls to prevent TPM bursts
- Rate limiter tracks both RPM (45/min) and TPM (45,000/min) in rolling windows
- Oversized single calls (> TPM ceiling) bypass the limiter rather than loop forever

### ETF Detection
`stock.info['quoteType'] == 'ETF'` determines prompt branching. ETFs get a macro/sector-focused search prompt; individual stocks get company-specific catalyst prompts. Detected at trigger time in `fetch_loop`, passed through to `run_synthesis_in_background` and `search_and_synthesize`.

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
├── market_data_engine.py          # AV engine (port 5000)
├── market_data_engine_claude.py   # Claude engine (port 5001)
├── trader_dashboard.html          # AV dashboard
├── trader_dashboard_claude.html   # Claude dashboard (port 5001, violet badge)
├── inspect_news_cache.py          # Debug: view cache entries for a ticker
├── inspect_alpha_vantage.py       # Debug: raw AV news response
├── tickers.json                   # Shared watchlist (both engines read this)
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

## Common Debug Tasks

### Clear a specific cache entry
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

### Clear all bad cache entries in bulk
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
2. No other ticker in the same article scores ≥ 0.4 (prevents sector/comparison articles like "AMD vs INTC" from being treated as single-company news)

---

## Known Pitfalls

- **Similar ticker symbols** (e.g. SPCX vs SPCK) can still cause cross-ticker contamination despite the co-mention filter — Alpha Vantage's relevance scoring isn't perfect
- **ETFs generate large search results** — XLK consumed 47,564 tokens in a single Turn 1 call; the oversized call bypass handles this but it's worth monitoring token logs
- **`[SYNTHESIS COMPLETE]` in the log does not guarantee the card updated** — if the completion message appears but the card shows placeholder text, check whether a subsequent `patch_actionable_move` from the main loop overwrote the synthesis (this was fixed but worth knowing)
- **Alpha Vantage free tier: 25 calls/day** — the cache is specifically designed to protect this quota across restarts; do not clear the news cache on engine restart
