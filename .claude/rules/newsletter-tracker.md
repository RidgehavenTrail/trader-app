---
paths:
  - "market_data_engine.py"
  - "newsletter*.py"
  - "trader_dashboard.html"
  - "watchtower.html"
  - "watchtower_engine.py"
---

# Newsletter Tracker — Left Panel + Actionable Moves Wired to Live Data (2026-07-05)

**Status:** Left panel (categorized watchlist, macro panel) and Actionable Moves
(strip + dd-dive, including the full Options Data quadrant) are now wired to real
`market_data_engine.py` endpoints — see "Live wiring" section below. Newsletter-side
schema/ingestion/lifecycle-storage are still just a brainstorm (see bottom half of
this file) — none of that backend logic exists yet, and a git worktree +
`feature/newsletter-ingestion` branch with a sandboxed engine copy
(`watchtower_engine.py`, port 5001) now exist specifically for building that out
without touching the live, stable `market_data_engine.py`/`trader_dashboard.html`.
Read this top section first before touching `watchtower.html`, `watchtower_engine.py`,
or adding to `market_data_engine.py`.

## Live wiring (2026-07-05)

`watchtower.html`'s left panel and Actionable Moves are now real, not mock, mirroring
`trader_dashboard.html`'s existing implementation exactly:

- **Left panel** — ticker input/category dropdown → `addStock()`/`/add_ticker`;
  sidebar accordion (Watchlist/Portfolio/Dividends, sorted by day's % change) →
  `renderDashboard()` off `/get_market_data`, polled 10s; macro panel →
  `fetchMacroRegime()` off `/get_macro_regime`, polled 10min. Category grouping is a
  client-side `localStorage('userStocks')` construct layered on top of the flat
  `tickers.json` list server-side — same as `trader_dashboard.html`, not a separate
  backend concept. `syncTickersWithBackend()` pushes the list to `/sync_tickers` on load.
- **Actionable Moves strip + dd-dive** — `fetchActionableMoves()` off
  `/get_actionable_moves`, same empty-state message and scroll-position preservation
  as `trader_dashboard.html`. `updateContext(ticker)` now populates every dd-dive field
  including `dd-sigma` and the full Options Data quadrant (ATM strike/put
  premium/expiration/IV/put+call wall) — previously dead markup under `TICKER_MOCK`.
  **Known simplifications, not yet resolved:** `asset_class` is hardcoded to
  `'equity'` for every Actionable Moves card (safe today since only equities/ETFs
  trigger these — see "Futures/forex Actionable-Moves triggering" below — but revisit
  if that ever changes); the Trigger Checklist always shows only `1-sigma` as hit,
  since `actionable_moves.json` doesn't tag which specific trigger(s) fired.
- **Drag-to-scroll + wheel-to-horizontal** — `watchtower.html`'s Actionable Moves strip
  had no interaction layer at all before this (only `overflow-x: scroll` with nothing
  converting a mouse wheel gesture into horizontal movement). Ported verbatim from
  `trader_dashboard.html` — see CLAUDE.md's Known Pitfalls entry, now updated to
  reflect both files share this pattern.

## Layout — settled, don't re-litigate without reason (updated 2026-07-05)

- **dd-pane-narrative row 2 swapped**: was Options Structure & Impact (left) / Trigger
  Checklist (right); now **Trigger Checklist (left) / Options Structure & Impact
  (right)**. Reason: the left column was stacking two dense-text blocks (Why → 
  Structure & Impact) while the right column stacked two compact-stat blocks (Options
  Data → Triggers) — swapping row 2 makes each column alternate text/compact instead
  of one column reading as a wall of narrative. IDs unchanged (`dd-triggers`,
  `dd-structure`, `dd-impact`), so `updateContext()` needed no JS changes for this.
- **Trigger Checklist border no longer stretches to match its sibling column** —
  `#dd-triggers` previously had `flex-1`, which grew the bordered box to match
  "Options Structure & Impact"'s taller paragraph stack, leaving empty bordered space
  below the actual checklist items. `flex-1` removed so the border sizes to content
  (verified: box height dropped from matching a ~282px sibling to ~109px for 3 items).
  Do not re-add `flex-1` here without re-checking this specific visual complaint.

**File:** `watchtower.html` (renamed from `newsletter_mockup.html` on 2026-07-05
once the UI was solid enough to get its own identity, distinct from
`trader_dashboard.html`. Trader App only — NOT regularly mirrored to Repository,
same as `trader_dashboard.html`; only `.claude/rules/*.md` files get mirrored
as a matter of course. A manual rollback snapshot of the pre-rename file does
exist in Repository under the old name for historical reference.)
Standalone static page, served via the existing `python -m http.server 8000`.
Hardcoded example data for everything EXCEPT the chart tab, which hits the real
live backend endpoint below.

### Layout — settled, don't re-litigate without reason

- **Weekly digest strip** — top of right column, above Actionable Moves. Click
  to expand a short recap. Violet accent throughout for anything newsletter-related.
- **Newsletter Plays strip** — its own horizontal row, directly below the
  Actionable Moves strip. **Not mixed into Actionable Moves** — tried that first,
  user rejected it in favor of a separate strip.
- **Sidebar "Newsletter Theses" section — REJECTED.** First attempt put newsletter
  plays in a sidebar `<details>` group grouped by status. User didn't like it there.
  Don't re-add; the strip is the answer.
- Newsletter Plays ordering: **Watching → Active → Resolved/Closed**, left to right.
- Status colors (kept from the rejected sidebar attempt, still correct): slate =
  watching, violet = active, emerald = resolved.
- **Per-play price line — simplified by status** (this is the *second* iteration;
  first iteration showed Entry/Tgt/Stop always, all three, which user found
  cluttered):
  - `watching` → show only **Entry**
  - `active` → show only **Tgt** (green) and **Stop** (red)
  - `resolved` → show only **Exit** (currently hardcoded green — doesn't yet
    branch red for a stopped-out/loss case; fix before this goes further)
  - Missing value → `--` in neutral gray, never blank.

### Tab control — Narrative/Thesis · Chart · Options

Added to both the ticker deep-dive (Actionable Moves entities) and the newsletter
thesis deep-dive. Shared logic: `switchTab(view, tabName)` where `view` is `'dd'`
(ticker) or `'nd'` (newsletter). Segmented pill buttons, not a dropdown.

**Options tab visibility is conditional on `asset_class`, not on which strip the
card came from.** This matters because a newsletter play can itself be a single
ticker (NVDA outright) or a pair (XLE/XLF) — the axis that decides the Options
tab is asset class, not entity origin.

### `asset_class` taxonomy — settled

Four values: `'equity' | 'future' | 'forex' | 'pair'`.

- **ETFs count as `'equity'`** — real listed options chain, same suffix-less
  ticker format as single-name stocks. Confirmed explicitly with the user.
- **Options tab shows ONLY for `asset_class === 'equity'`.** User confirmed no
  options trading planned on futures/forex — direct buys/sells only — so those
  (and pairs, which have no options chain at all) get Narrative/Chart only.
- Detection is suffix-based: `=F` → future, `=X` → forex, else → equity.
  Implemented server-side as `get_asset_class()` in `market_data_engine.py`
  (search for it — it's placed right before the `/get_price_history` endpoint).

**Open item:** display ticker (e.g. `"CL1!"`) vs. the actual yfinance-fetchable
symbol (e.g. `"CL=F"`) has no real schema field yet — it's hardcoded per-mock-entity
in the JS (`ticker` vs `legsLabel`). Needs a real home once tickers.json or a
newsletter storage schema exists.

### Futures/forex Actionable-Moves triggering — explicitly deferred, not walled off

User confirmed (2026-07-04): futures/forex should **only** appear via Newsletter
Plays for now, NOT trigger their own Actionable Moves card. But this is a
deliberate "not yet" — user said they may add new Actionable-Moves criteria for
futures/forex later. **Do not treat this as a permanent architectural rule.** If/when
it happens, it needs its own non-options expected-move definition (e.g. historical
volatility over some lookback), since the existing 1σ trigger is built entirely
around ATM put premium, which doesn't exist for non-optionable instruments.

## New backend endpoint — `/get_price_history/<ticker>` — built and tested working

Added to `market_data_engine.py` this session. Tested live against the running
engine (`--test` mode) — confirmed working for equities (AAPL, AMD), futures
(`CL=F`), cache-hit behavior, and 2y-lookback SMA seeding.

**New constants:** `PRICE_HISTORY_CACHE_FILE = 'price_history_cache.json'`,
`PRICE_HISTORY_TTL_SECONDS = 300`, `price_history_lock`.

**New functions** (all placed just before the `# --- Endpoints ---` section):
`get_asset_class()`, `load_price_history_cache()`, `save_price_history_cache()`,
`fetch_price_history(ticker_symbol, range_key)`.

**Cache pattern mirrors `news_cache.json`'s existing rules:** never cache a
failure; if a fresh yfinance pull throws and stale cache exists, serve the stale
data with a `"stale": true` flag rather than an empty chart; TTL check (300s)
before deciding to refetch vs. serve cached.

**Data source note (ties into the settled Schwab plan):** this endpoint always
uses yfinance today, for every asset class. Per `.claude/rules/schwab-integration.md`,
equities may eventually route through Schwab instead — but futures/forex stay on
yfinance permanently since Schwab doesn't cover them. `fetch_price_history()` is
deliberately its own function (not inlined in the route) so that swap is a
one-function change later, not a route rewrite.

**`period_map` supports:** `1mo, 3mo, 6mo, 1y, 2y, 5y`. `2y` was added specifically
so the frontend can fetch a long buffer for SMA-200 seeding while only displaying
6 months (see Chart behavior below).

**New live data file, not in the repo:** `price_history_cache.json` — add this to
CONTEXT.md's "Live data files (not in repo)" list if it isn't there already.

## Chart tab — TradingView Lightweight Charts

**Library:** `lightweight-charts@4.1.3` via unpkg CDN. **Confirmed free** — Apache
2.0 licensed, open-source, no TradingView account or paid tier needed (checked
2026-07-04, since licensing terms can change). Apache 2.0 technically requires an
attribution notice + link to tradingview.com — trivial for a local personal
dashboard, **not yet added anywhere in the mockup.**

**Display behavior (settled):**
- Shows the **last 6 months of daily candles**.
- Fetches **2 years** of data behind the scenes purely to seed the SMAs — a
  200-day SMA needs 200 days of data *before* the display window starts, or the
  line has a gap/ramp-up artifact at the left edge. Confirmed via direct testing
  that both SMA lines have full coverage across the entire 6-month window (124
  trading days) with no gap.
- **SMA 50** — cyan (`#22d3ee`). **SMA 200** — white (`#f8fafc`). Computed
  client-side (`calcSMA()`, trailing-window sum) — not server-side.
- Applied to **both** single-instrument candlestick charts AND the pair ratio
  line chart. This was a judgment call, not an explicit request — a 200-day SMA
  on a ratio series is a real pairs-trading mean-reversion tool, but flag to the
  user if they'd rather pairs stay SMA-free.
- Pair ratio computed client-side: `closeA / closeB` per matching date, rendered
  as a violet (`#a78bfa`) line series instead of candlesticks.
- Charts load lazily (only fetched on Chart-tab click) and cache per-entity
  client-side (`viewState.dd/nd.loadedFor`) so re-clicking tabs doesn't refetch.
- **No range-toggle UI yet** (1mo/3mo/1y etc.) — fixed 6-month display only.

## Not yet done — real open items for next session

1. Ticker display-name vs. yfinance-symbol mapping (`CL1!` vs `CL=F`) — no schema field.
2. Newsletter ingestion — confirmed manual paste each week, but no actual paste/parse
   UI or Claude-extraction prompt exists. This session only built the display/tracking
   UI and chart infra, assuming the data already exists in the right shape.
3. Hit-rate/accuracy tracking — confirmed as a wanted goal, but no diffing/scoreboard
   logic exists yet.
4. Resolved-card exit color is hardcoded green (assumes a win) — doesn't branch red
   for a stopped-out/loss outcome.
5. Lightweight Charts attribution notice not added anywhere.
6. **None of this is wired into the real `trader_dashboard.html` yet.** Everything
   lives in the standalone `watchtower.html`. Merging into production is
   unstarted — will need the real Actionable Moves card markup/JS merged with the
   tab-control + chart logic built here.
7. The original brainstorm below (schema draft, lifecycle enum, ingestion/hit-rate
   open questions) is still just a brainstorm — today's backend work was ONLY the
   price-history endpoint, unrelated to actual newsletter data storage/lifecycle.

---

# Original brainstorm (2026-07-03) — schema, lifecycle, ingestion — still unresolved

**Status:** Brainstormed in a planning conversation, before the Schwab integration
discussion. No schema finalized, no storage/lifecycle code written. Confirm schema
and open questions with the user before writing code against this section.

## What this is for

The user receives a weekly market newsletter covering stocks, options, and futures,
heavy on pairs trading via composite charts (e.g. stock1/stock2 ratio). Currently
Gemini summarizes content, key dates, and support/resistance levels from each issue.
Goal: condense and track this the same way the dashboard already condenses options
signals — structured cards, not prose, with state that persists across issues.

## Structured extraction schema (rough draft, not finalized)

Get the newsletter summarizer (Gemini or Claude) to return structured JSON per issue
instead of prose, so it can be stored/diffed/queried like `actionable_moves.json`:

```json
{
  "issue_date": "2026-07-01",
  "themes": ["Fed pause reversal", "Energy vs Financials rotation"],
  "trades": [
    {
      "id": "xle-xlf-ratio-2026-07-01",
      "type": "pairs",
      "legs": ["XLE", "XLF"],
      "direction": "long_ratio",
      "thesis": "condensed 1-2 sentence summary",
      "key_levels": {"support": 1.42, "resistance": 1.58, "basis": "ratio"},
      "key_dates": [{"date": "2026-07-15", "event": "OPEC meeting"}],
      "conviction": "new" | "reiterated" | "increasing" | "fading",
      "status": "watching"
    }
  ]
}
```

`type` matters (pairs / outright / options / futures) — each needs different display
math. A pairs trade's "price" is a ratio or spread, not a quote. Note: this session's
`asset_class` taxonomy (`equity`/`future`/`forex`/`pair`) is a related-but-different
axis — `type` here is about trade structure, `asset_class` is about the underlying
instrument. Reconcile these before building real storage.

## Trade lifecycle tracking

Same `patch_actionable_move()`-style read-modify-write pattern the engine already
uses for triggered cards, but on a weekly cadence instead of 60-second:

- `watching` → thesis just introduced
- `active` → user has taken it, or it's crossed a level worth acting on
- `hit target` / `stopped` / `expired` → resolved, archived

The real value: since the newsletter repeats itself week to week, diff this week's
`trades[]` against last week's by `legs` + `direction` to build a **conviction
tracker** (is the same trade reiterated? did the level get breached or fade?) and
eventually a **hit-rate scoreboard** for the newsletter itself — how many "watching"
calls actually played out, to calibrate how much weight to give future issues.

## Pairs/composite chart data pipeline

**Built this session** (see above) — client-side ratio computation + Lightweight
Charts line series. What's still missing from the original brainstorm: overlaying
the newsletter's stated support/resistance as horizontal lines on the chart, same
visual language as the 3D heatmap's amber current-price line.

## Trigger philosophy — different from the existing engine's

Existing engine triggers on 1σ expected-move breach, checked every 60s. Newsletter
trades are level-based and lower-frequency, so the natural trigger is: *today's
ratio/price is within X% of a newsletter-flagged support/resistance level.* Could
bolt onto the existing `fetch_loop` for any ticker/pair with an active newsletter
thesis — proximity check alongside (or instead of) the ATM-put-premium trigger.

## Open questions (still not decided)

- **Ingestion**: confirmed manual paste-and-parse (not email/PDF automation) —
  but no UI or extraction prompt built yet.
- **Is newsletter accuracy tracking itself a goal**: confirmed yes, eventually —
  but no diffing/scoreboard code exists.
- Composite/pairs chart rendering: **built** this session (see above) — this bullet
  from the original brainstorm is resolved.
