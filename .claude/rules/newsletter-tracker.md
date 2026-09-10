---
paths:
  - "newsletter*.py"
  - "watchtower.html"
  - "watchtower_engine.py"
---
<!-- 2026-07-13: removed retired market_data_engine.py / trader_dashboard.html
     entries (retired 2026-07-12) — watchtower_engine.py/watchtower.html already
     covered this file, those two were stale dead weight, not functional. -->


# Newsletter Tracker — Schema Mapped to Dashboard (updated 2026-07-07)

**2026-07-13 — `watchtower.html` JS split into `static/js/` modules (no logic change).**
The single ~1,900-line inline `<script>` was extracted into nine files under
`static/js/`; **eleven as of session 42** (`strategy.js`, `news-archive.js` added), **thirteen
as of 2026-08-15** (`strategy-dive.js` added; the count line itself had gone stale, which is
why it now carries a date); `watchtower.html` dropped 2,410 → ~520 lines (markup + CSS + the
`<script src>` tags). **These are CLASSIC scripts, NOT ES modules** — every function
stays global, so the `onclick="fn(...)"` handlers in the markup keep working with zero
changes. **Do not add `import`/`export` or `type="module"`** (that would scope the
functions and break every `onclick`). The split was purely mechanical (a build script
asserted the slices reconstruct the original JS byte-for-byte). Load order is
load-bearing only at the ends: **`core.js` first, `main.js` (the bootstrap) LAST**; the
middle files are just definitions and their order is free. Shared globals live
where noted below.

| File | Concern | Notable globals it declares |
|------|---------|------------------------------|
| `core.js` | shared helpers (`esc`, `initHorizontalScrollStrip`), `API_BASE`, **the detail-panel switch** | `API_BASE`, **`DETAIL_PANELS`/`showOnlyPanel`** |
| `watchlist.js` | left panel / market-data sidebar (`renderDashboard`, `addStock`, …) | `categories`, `openStates` |
| `macro.js` | macro panel + self-waking poll clock | `MACRO_*` consts |
| `stoplight.js` | AI Bubble sidebar section + its detail panel — incl. the PER-FACTOR view (`openBubbleDetail(factorId)`, `renderBubbleHead`, `renderBubbleSubhead`) | `_abFactor` (live since 2026-08-21, was reserved) |
| `actionable.js` | Actionable Moves strip + ticker deep-dive triggers | `dynamicContextData`, `TRIGGER_DEFS` |
| `newsletter-cards.js` | plays strip + all card/trade rendering | **`NEWSLETTER_TRADES`/`NEWSLETTER_ISSUE`/`newsletterEditions`** |
| `charts.js` | tab control + chart tab + `updateContext` (ticker dive) | `viewState` |
| `strategy.js` | Rocket Strategy sidebar section (Fed dial + selected holding) | `STR_POLL_MS`, `strSel`, `strLast`, `strFindHolding` |
| `strategy-dive.js` | Rocket Strategy DETAIL panel — Strategy/Chart/Dial tabs, the chart's strategy levels, and the Strategy tab. **THREE parts as of 2026-09-02:** a full-width NOTIONAL PHASE DIAGRAM on top, then the ruleset and the last-10 LEDGER (a table) side by side, with the whole tab scrolling as ONE container. **All five strategies serve it** — QQQ, XLE, GLD, MO, PM. `rules`, `phase_diagram` and `trades` are SERVED from `strategy_config` (they carry the parameters) and never authored in this repo; the renderer learns no strategy vocabulary, which is what lets one picture draw five systems (`opens`, `band_names`, `sleeve_names`, `silent_entry`, `dark_note`). THE LEDGER IS ONE BOOK, not one sleeve — QQQ merges the VIX flush, XLE the overlay RUNS, tobacco is built from RUNS because a tier handover is not a transaction. | `_sdSeq` |
| `news-archive.js` | per-ticker news history inside the "Why" box | `_naEntries`, `_naSel` |
| `newsletter-dive.js` | thesis deep-dive panel | `_ndDiveSeq` |
| `newsletter-digest.js` | weekly digest + import + Past Editions | `digestOpen`, `openDropdownEl`, `viewingPastStem` |
| `main.js` | bootstrap wiring (loads LAST) | — |

The three cross-file newsletter globals (`NEWSLETTER_TRADES` etc.) are declared at the
top of `newsletter-cards.js`; `newsletter-dive.js`/`-digest.js` read them at runtime
(fine — classic scripts share one global scope, and nothing cross-calls at parse time).
`strategy-dive.js` reads `strLast`/`strFindHolding`/`strRow` from `strategy.js` and
`viewState`/`loadChart`/`switchTab` from `charts.js` the same way — note it loads BEFORE
`charts.js`, which is safe only because every one of those references is inside a function
body, evaluated on click rather than at parse time.

**ONE PANEL AT A TIME — `showOnlyPanel(id)` in `core.js` (2026-08-15).** The right-hand
column holds five mutually exclusive panels (`empty-state`, `populated-state`,
`newsletter-dive`, `ai-bubble-dive`, `strategy-dive`). Each opener used to hide its
siblings BY NAME, so a new panel had to be added to every existing opener and adding
`strategy-dive` was added to none of them — the AI Bubble detail rendered *beside* it
instead of replacing it. **Add a sixth panel to `DETAIL_PANELS` and nowhere else.**
`empty-state` is excepted from the `flex` toggle: it carries that class statically in
markup, so toggling it off breaks it on the next show.

**`switchTab(view, tabName)` reads its pane names off the tab strip's own `data-view`
attributes** (2026-08-15). It used to iterate a hardcoded
`['narrative','chart','options']` — the dd/nd vocabulary — so `sd`'s Strategy/Chart/Dial
panes would have been left untouched while the buttons restyled. A panel's tab strip is
the authority on its own panes. Charts stay LAZY (built on tab selection, never on open):
a chart built into a `display:none` pane measures zero and renders collapsed.
Served the same way as before (`python -m http.server` from the main dir serves the
whole tree, so `static/js/*` resolves with no config). This retires the session-10
"File size note" refactor item further down.

**Status (2026-07-07):** Fully wired end-to-end, not mock data. Left panel,
Actionable Moves, and the newsletter-specific side (Newsletter Plays strip, thesis
deep-dive, weekly digest) all render from real `newsletter-schema.md`-shaped data —
but as of this update, `NEWSLETTER_TRADES`/`NEWSLETTER_ISSUE` are `let`-populated
from the real backend store (`GET /get_newsletter_state`) via `loadNewsletterState()`,
not hand-authored JS. Step 4 (Import icon, Past Editions dropdown, plays panel wired
to the store) is BUILT and a first real import has landed successfully (`260608`
issue, 7 live/2 archive/1 discarded). See `.claude/rules/newsletter-ingestion.md`
"Build status update (2026-07-07)" for the full build log.

**2026-07-07 — card-design review session.** With real imported data finally on
screen, a full card-by-card review against all 9 real trades surfaced that several
of session 10's display choices below (status labels, title-building logic, the
conviction "n/a" fallback) don't hold up against real data, and that the extraction
prompt itself has real gaps (level fields holding prose instead of clean numbers).
**Full precise fix list, finalized target card specs per trade shape, and the new
risk-based P&L% calculation rule all live in `.claude/rules/newsletter-ingestion.md`
"Card-design review + fixes queued (2026-07-07)" — read that before touching
`watchtower.html`'s card-rendering functions or `newsletter_ingest.py`'s
`EXTRACTION_SYSTEM`.** Not duplicated here; the session-10 mapping below is
historical record of what was originally built, not the current target.

**2026-07-10 — status-display revision (SUPERSEDES the session-10 "Status labels" /
"Status colors" / "Per-play price line" / indicator-as-strip-card notes below).** The
card's **badge** and its **color** are now DECOUPLED (`getStatusMeta` returns `label` +
`tone`):
- **Badge (`label`) — "New" takes PRIORITY:** any trade on its first appearance
  (`first_seen === last_mentioned`) wears the **New** badge even when already ENTERED
  (`open`). So a new+entered trade shows a New badge on a violet card. Otherwise: `open`
  carried → Active, `planned` carried → Watching, `closed` → Closed.
- **Color / opacity / price-line (`tone`) — driven by actual lifecycle status:** `open`
  → violet (Active: Tgt/Stop line), `closed` → emerald + strikethrough (P&L/Exit line),
  `planned` → slate (Watching: Entry line). A New-badged *entered* trade therefore shows
  the **Tgt/Stop** line, not the Entry line.
- **Indicators route to the DIGEST, not the strip (§6, built 2026-07-10):** trades with
  `conviction.label ∈ {observation_only, watchlist}` are excluded from the plays strip
  and rendered in the digest dropdown (title/proxy/thesis/constituents). They are NOT
  shown as strip cards with a text label (the old session-10 behavior at line ~84).
- **Digest summary pills = issue ACTIVITY** (not the raw store): indicators excluded;
  `new` = New-badge count; `active`/`watching` = carried-forward; `closed` scoped to the
  CURRENT issue (`last_mentioned === issue_date`) so prior weeks' closes don't inflate it.
- **Past Editions SWAP the plays strip** to that week's frozen file (read-only, "← current"
  to restore); the summary pills move into the dropdown body in that mode. This reverses
  the old "never touch the plays panel" constraint — see `newsletter-ingestion.md`
  "Display vs. archive" for why (the real intent was "no growing pile," not "no swap").

Full detail + rationale live in `.claude/rules/newsletter-ingestion.md` (do not duplicate).

**Schema update (2026-07-05):** the extraction schema brainstorm at the bottom of
this file is now superseded by `.claude/rules/newsletter-schema.md`, drafted and
confirmed against 5 real newsletter issues (2026-05-04, 05-25, 06-09, 06-22, 06-29)
across a dedicated multi-session design pass. Read that file before writing any
ingestion/parsing code — it has the current target JSON shape, the confirmed
trade-lifecycle state machine (silence-means-abandoned only for `planned`/
conditional trades, never for `open` ones), the basket-vs-options `legs`
distinction, and the newer `campaign_title`/`key_dates`/`positioning_note`/
`holding_period`/`paired_with`/`analysis_features` fields. The brainstorm below is
left for historical context only.

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

## Schema-to-dashboard mapping (session 10, 2026-07-05)

Everything below was built this session. No backend changes — all frontend-only
in `watchtower.html`. The old `NEWSLETTER_MOCK` object (flat, ad-hoc fields) is
gone, replaced by `NEWSLETTER_TRADES` (array of real schema-shaped trade objects)
and `NEWSLETTER_ISSUE` (the issue envelope with `playbooks[]` and
`analysis_features[]`). Data is still hand-authored JS, not fetched from a backend.

**What changed in the Newsletter Plays strip:**
- Cards rendered by `renderNewsletterStrip()` from `NEWSLETTER_TRADES`, not hardcoded HTML
- Conviction: 5-dot scale (`renderConvictionDotsHTML()`) replaces momentum-word pills
  (New/Reiterated/Increasing/Fading are gone). `role: "indicator"` trades show a text
  label (observation_only/watchlist) instead of dots.
- Status labels: **New** = `planned` trade on its first appearance (`first_seen ===
  last_mentioned`); **Watching** = `planned` but seen in 2+ issues; **Active** = `open`;
  **Resolved** = `closed`. `abandoned`/`deleted` trades filtered out before render.
- Stale badge: amber "Stale" tag on Active cards when `stale_flag: true`
- Card titles: derived from `basket` (pairs → "XLE / XLF"), `legs` (options → strike
  labels), or plain `ticker` via `getLegsLabel()`. `campaign_title` used when present.
- Entry/Tgt-Stop/P&L row: simplified by status via `levelsInlineHTML()` — New/Watching
  → Entry only; Active → Tgt+Stop; Resolved → realized P&L with sign-based color
  (fixes the old hardcoded-green bug flagged in item 4 of the original open items list).

**What changed in the thesis deep-dive (nd panel):**
- `showNewsletterDive(id)` looks up by `id` in `NEWSLETTER_TRADES` instead of key
  in `NEWSLETTER_MOCK`
- Header levels box: Entry/Tgt-Stop/P&L (was "Support/Resistance" from old brainstorm
  schema — that field never existed in the real schema)
- Conviction dots in header (was a momentum-word pill)
- Stale badge next to status label
- Key Dates: real list from `trade.key_dates[]` with passed/pending indicators (was
  one hardcoded line)
- Status History: real timeline from `trade.status_history[]` with dated entries and
  P&L where present (was "Conviction History" prose paragraph)

**What changed in the weekly digest strip:**
- Header: JS-rendered from `NEWSLETTER_ISSUE` — date, themes, and status-count pills
  (new/watching/active/closed) derived from `NEWSLETTER_TRADES`
- Expanded body order: 1) Newsletter summary (issue title), 2) Analysis features
  (sector_model with ▲/▼ tickers, deep_dive with linked_theme tag), 3) Playbooks
  (conditional rules with per-candidate status). Trade summary line removed per user
  request — redundant with the Newsletter Plays strip.
- `toggleDigest()` uses `scrollHeight` instead of fixed 120px so content isn't clipped.

**Options tab / Options Data quadrant changes:**
- `dd-pane-options`: was hardcoded `$142.50/$3.15/42.8%`; now wired to real
  `actionable_moves.json` fields via `updateContext()`
- `nd-pane-options`: was hardcoded `$115.00/$4.20/51.2%`; now shows an honest message
  that no live options-chain endpoint exists for newsletter trades yet
- "🗻 3D Heatmap — Coming Soon" placeholder button (dashed border, disabled,
  equity/ETF-gated) added in **four** places, not just the quadrant: `dd-options-data`
  and `nd-options-data` (the Options Data quadrant on the Narrative tab), AND
  `dd-pane-options` and `nd-pane-options` (the actual Options tab pane itself).
  **Bug fixed same session (caught by user):** the placeholder was originally only
  added to the Narrative-tab quadrant — clicking the actual "Options" tab button
  showed nothing about the heatmap at all. Both locations now have it for
  consistency. This is the future launch point for `heatmap_3d.py` — see
  `.claude/rules/heatmap-dashboard-hook.md`.

**New CSS classes added:** `.conviction-dots`, `.conviction-dot`, `.conviction-dot.filled`,
`.conviction-label-only`, `.status-dot-new`, `.stale-badge`, `.heatmap-hook-placeholder`

**New rule file created this session:** `.claude/rules/heatmap-dashboard-hook.md` —
documents the previously-undocumented decision that the Options Data quadrant is the
future launch point for the 3D heatmap. Placeholder only, not wired. Equity/ETF only,
daily-snapshot-based once built, does not touch locked heatmap code.

**File size note:** `watchtower.html` is now ~1300 lines. Discussed refactoring JS into
separate files by concern (watchlist, newsletter, charts) — natural moment to do this
is when ingestion code is added, not before. The JS functions already have clean
boundaries for splitting.

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

## Not yet done — real open items (updated session 10)

1. Ticker display-name vs. yfinance-symbol mapping (`CL1!` vs `CL=F`) — no schema field.
2. ~~Newsletter ingestion — backend + step-4 UI~~ — **DONE 2026-07-07.** Backend
   (`newsletter_ingest.py` + `watchtower_engine.py` endpoints) built 2026-07-06;
   step-4 UI (Import icon, Past Editions dropdown, plays panel wired to the real
   store) built and a first real import landed 2026-07-07. What's open now is a
   card-design/display-and-calculation fix list surfaced by that first real
   import — see `.claude/rules/newsletter-ingestion.md` "Card-design review +
   fixes queued (2026-07-07)", not a rebuild of anything in this item.
3. Hit-rate/accuracy tracking — confirmed as a wanted goal, but no diffing/scoreboard
   logic exists yet.
4. ~~Resolved-card exit color is hardcoded green~~ — **FIXED session 10.** P&L color
   now branches by `pnl.value` sign (green positive, red negative) via `levelsInlineHTML()`
   and `levelsRowHTML()`.
5. Lightweight Charts attribution notice not added anywhere.
6. **None of this is wired into the real `trader_dashboard.html` yet.** Everything
   lives in the standalone `watchtower.html`. Merging into production is
   unstarted — will need the real Actionable Moves card markup/JS merged with the
   tab-control + chart logic built here.
7. ~~The original brainstorm schema was speculative~~ — **RESOLVED sessions 9-10.**
   Real schema in `newsletter-schema.md`, display layer mapped in session 10.
8. **Refactoring `watchtower.html`** (~1300 lines) into separate JS modules — discussed
   end of session 10, deferred to when ingestion code is added (natural growth point).

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
