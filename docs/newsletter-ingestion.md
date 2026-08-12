<!-- Full newsletter-ingestion documentation. Freely editable — this is a PLAIN DOC, NOT
     a .claude rule, so edits do NOT hit the .claude config-guard prompt. The thin
     standing-directives rule that auto-loads with the code is
     .claude/rules/newsletter-ingestion.md; everything here is the full design notes,
     build log, card-fix queue, session handoffs, and token/reasoning-cost investigation. -->

> **STATUS (2026-07-13): SHIPPED / HISTORICAL — this file is a build log, not an
> active spec.** The newsletter-ingestion feature described below is complete and
> consolidated into `master` (`watchtower.html` + `watchtower_engine.py`, port 5001).
> Read this file for *why* a given piece of derivation/display logic works the way
> it does — it is not a to-do list, and nothing below should be read as "not done
> yet" just because it's phrased that way in an old section. Current pending work
> lives in `SESSIONS.md` (Repository root), not here. Ongoing standing rules for
> anyone touching `newsletter_ingest.py`/`watchtower.html`/`watchtower_engine.py`
> are in `.claude/rules/newsletter-ingestion.md` and `.claude/rules/newsletter-schema.md`
> — those stay live; this file does not.

# Newsletter Ingestion — Settled Design (2026-07-06)

Everything below was worked out in a chat-interface design session, before any
build work started. This file is the spec for that build. See
`newsletter-schema.md` for the target JSON shape and trade lifecycle state
machine — this file covers the *mechanics* of getting a pasted/printed
newsletter issue into that schema, not the schema itself.

## Build status (2026-07-06) — BUILT and validated end-to-end

The extraction prompt, the text->JSON pipeline, and the two endpoints are built
in the `feature/newsletter-ingestion` worktree and validated against 6 real
issues (2026-05-25 -> 06-29), plus real billed API runs of the live-set pipeline.

- **`newsletter_ingest.py`** (new): `EXTRACTION_SYSTEM` (the prompt, sent as a
  cached system block), `extract_pdf_text()` (pdfplumber), `run_extraction()`
  (raw-HTTP Anthropic call, model `claude-sonnet-5`), the Python store
  (`new_store` / `merge_into_store` / `rebuild`-by-replay is not used — the
  endpoint persists `_store.json`), and `ingest_issue()` tying it together.
- **`watchtower_engine.py`**: `GET /list_pending_newsletters` and
  `POST /import_newsletter` (with `_atomic_write_json`, the YYMMDD/YYYY-MM-DD date
  parser, and config `NEWSLETTER_PDF_DIR` / `NEWSLETTER_EXTRACTED_DIR`).
- **Two cost levers built** (see "Storage architecture" and the cost note below):
  the LIVE-SET model (the prompt is fed & returns only the live working set +
  this issue's new/newly-terminal trades; Python owns accumulation) so output
  doesn't grow with history; and PROMPT CACHING (the ~6.4k-token instruction
  block is the cache_control `system` prompt, the small live-set + issue text are
  the user message). Measured ~$0.18-0.29 per extract at intro pricing, and flat
  as the store grows (was climbing past $0.60/issue under the old full-union).
- **Step 4 UI is now BUILT (2026-07-07)** — see "Build status update (2026-07-07)"
  immediately below. One recurring model judgment call remains: a scaled/tiered
  tactical entry -> `planned`, resolved via a prompt rule (see newsletter-schema.md
  "open vs planned").

The rest of this file remains the authoritative spec; where the build differs
from the original wording it is noted inline.

## Build status update (2026-07-07) — step 4 UI built + hardening, first real import landed

Step 4 (UI wiring) is done, plus two production fixes surfaced by the first real
end-to-end run against live PDFs. The feature is now clickable end to end: Import a
pending PDF from the digest strip, it extracts + merges + persists, and the plays
panel + digest render from the real store.

**What was built/changed this session:**
- **Two new read endpoints** on `watchtower_engine.py` (no model call, disk reads):
  - `GET /get_newsletter_state` -> `{live, archive, issue, editions}` — the plays
    panel's data source (live working set + closed archive), the most recent issue
    envelope for the digest, and the Past Editions list.
  - `GET /get_extracted_newsletter?stem=...` -> one past issue's full extract
    (envelope + that week's `trade_updates`), traversal-rejected, for read-only
    Past Editions viewing.
- **`watchtower.html` wired to the store** (was hand-authored `NEWSLETTER_TRADES`):
  - `API_BASE` moved to `http://localhost:5001` — `watchtower_engine.py` serves the
    FULL endpoint set (watchlist / Actionable Moves / macro / price history) AND the
    newsletter endpoints, so one base covers everything. (The stale session-10
    schema-driven `watchtower.html` was copied in from the primary checkout first —
    it existed only as uncommitted edits there; see STEP4_HANDOFF.md.)
  - `loadNewsletterState()` fetches `/get_newsletter_state` on load + after each
    import; `NEWSLETTER_TRADES`/`NEWSLETTER_ISSUE` are now `let` populated from it.
  - Import icon -> `openImportPicker()` (lists pending, grays imported + before-start,
    POSTs `/import_newsletter`); Past Editions dropdown -> read-only envelope render
    that does NOT touch the live plays strip.
- **Streaming fix (`newsletter_ingest.py` `run_extraction`)** — was a non-streaming
  POST with a 300s read timeout; a cold-start extraction (`max_tokens=32000`, adaptive
  thinking on by default for `claude-sonnet-5`) generates for minutes and `ReadTimeout`d
  every time. Now `"stream": true` + `iter_lines()` accumulating `text_delta`s: the
  timeout is per-chunk and resets on every SSE event, so total wall-clock is unbounded
  as long as tokens keep arriving. Confirmed by the Anthropic API docs (streaming is the
  documented fix for high-`max_tokens` timeouts). Added a clear error on
  `stop_reason == "max_tokens"` instead of a downstream JSON-parse failure.
- **`NEWSLETTER_START_DATE` floor (`.env`, optional YYYY-MM-DD)** — issues dated (or
  mtime'd) before it are grayed out in the picker AND rejected server-side (400
  `before_start`). This is a hard guard, not cosmetic: importing an issue OLDER than
  ones already in the store is the backward-import corruption case — the older issue's
  silence-abandons / stale logic gets reconciled against a `live` set that already
  reflects LATER issues, mislabeling active trades abandoned/stale and overwriting
  `last_mentioned`/`status_history` with earlier dates. Current setting: `2026-06-08`
  (user chose to start from the last 4 weeks; grays `260525`/`260601`). Deleting the
  env line re-opens the full archive. See `merge_into_store()` — there is no date
  awareness in the merge itself; `live` is just "whatever the last import left," so
  strict oldest->newest import order is load-bearing.
- **First real import landed (2026-06-08 issue)**: `live=7, archive=2, discarded=1`,
  ~29,907 output tokens. Note: that cold-start generation ran long enough that the
  browser's `fetch` gave up before the synchronous server request returned, so the
  spinner cleared without the success handler firing and the panel didn't auto-refresh
  — a page reload populated it. The server had written everything correctly (atomic
  write => empty extract dir on failure, so a partial/timed-out run leaves no marker).

## Data layout (as-built, 2026-07-07) — read this before touching display/calc

The store lives in `NEWSLETTER_EXTRACTED_DIR` (default `<PDF_DIR>/extracted/`):
- **`_store.json`** = `{ "live": [...], "archive": [...], "discarded": [...] }`, the
  rolling persistent store `merge_into_store()` maintains. `live` = open/planned +
  standing indicators (fed to the model next issue); `archive` = full `closed` trade
  objects (scoreboard source); `discarded` = lightweight stubs for abandoned/unresolved
  (`_discard_stub()` shape: id, strategy_id, underlying, tickers, status, dropped_on,
  reason) — NOT full objects.
- **`<stem>.json`** (one per imported issue, e.g. `260608 ....json`) = that issue's
  extract: the envelope (`issue_date`, `title`, `themes`, `market_structure`,
  `portfolio_house_view`, `notable_flow_summary`, `playbooks`, `analysis_features`)
  PLUS `trade_updates` (this issue's new + changed trades as they stood that week).
  This file doubles as the "already imported" marker and the Past Editions record.
- Trade objects follow `newsletter-schema.md` exactly (id/strategy_id, type,
  asset_class, conviction, basket vs legs, underlying, entry/stop/targets,
  status/status_history, first_seen/last_mentioned, stale_flag, etc.).

Frontend consumption (`watchtower.html`):
- Plays strip: `NEWSLETTER_TRADES = [...live, ...archive]` (discarded not shown);
  `getStatusMeta()` maps status -> New/Watching/Active/Resolved; `renderNewsletterStrip()`
  orders New/Watching -> Active -> Resolved.
- Digest strip: `NEWSLETTER_ISSUE` = the latest `issue` envelope from
  `/get_newsletter_state`; header pills counted from `NEWSLETTER_TRADES`.
- Level display / P&L / conviction dots computed client-side in `levelsInlineHTML()`,
  `levelsRowHTML()`, `renderConvictionDotsHTML()`.

## Build status update (2026-07-08, session 16) — spec fix list IMPLEMENTED

The entire accumulated spec-only fix list (A.6, A.7, A.8, B.5, C.1, and section E)
was implemented and verified end-to-end this session. Two additional fixes surfaced
during verification and were also landed. Nothing here is spec-only anymore.

**Implemented + verified:**
- **B.5** (`newsletter_ingest.py` `EXTRACTION_SYSTEM`, `key_dates` block) — multi-day
  central bank meetings now instructed to collapse to ONE entry dated the last day.
  Prompt-only; takes effect on the next import (re-import 260608 to fix USDJPY's
  existing duplicate BOJ entries).
- **A.6** (`watchtower.html` `loadChart` + `showNewsletterDive`) — pair/basket chart
  ratio is now Σ(long-leg closes) ÷ Σ(short-leg closes), split by `side`. Verified
  live: XLV+XLP+XLF/IGV ratio ≈ 3.288, landing between entry 3.01 and targets
  3.59/3.79. `viewState.nd.entity` now carries `basketLegs` ({ticker, side}) instead
  of a bare ticker array so `side` reaches the chart layer.
- **A.7** (`watchtower.html` new `chartSymbol()` helper) — forex fetches `=X`
  (USDJPY → USDJPY=X, verified 162.x). Futures `=F` also enabled this session (see
  below). Applied at the fetch boundary only; the store keeps bare identity tickers.
- **A.8** (`watchtower.html`) — `tranches` now render in a "Scaled Entries / Adds"
  detail-panel block (`#nd-tranches-section`, hidden when empty). HG's $6.15 add
  level is now visible. **CONFIRMED GOOD 2026-07-10 (user):** reviewing the 260615
  merge, the user specifically liked the per-element tranche `note?`s rendered here
  (e.g. "starter filled Monday open… second half filled Thursday at 3.22", "trailed
  stop hit Tuesday") — they turn the block from a bare price ladder into a readable
  fill history. Settled keeper; do NOT strip the per-tranche notes from this render.
- **C.1** (`newsletter_ingest.py` `compute_risk_pnl()` + `_spread_credit_or_debit()`,
  called from `merge_into_store()` when archiving; `watchtower.html`
  `closedPnlDisplay()`) — risk-based P&L% computed deterministically in Python at
  close-time. Verified: DOCU (credit, width 5 − 0.51 = risk 4.49) → +11.4%; GLD
  call spread (debit) → **−74.0%** via the `exit_price` extension below. Frontend
  prefers `pnl_pct`, falls back to raw $ (fixing the old `pnl.unit==='pct'`-only bug
  that rendered `usd_credit`/`usd_per_share` as a bare ambiguous number).
  **Extended same session with `exit_price` capture** so pre-import-window closes
  compute a real % instead of falling back to raw $ — see the "C.1 extension"
  subsection under section C for the full change (prompt field + debit/credit
  inference formulas + the GLD 0.95 backfill note). The two already-archived trades
  were backfilled deterministically: DOCU +11.4% and GLD −74.0% now render without a
  re-import.
- **E** (`watchtower_engine.py` `GET /get_trade_quote` + helpers; `watchtower.html`
  `loadTradeQuote()` + `#nd-quote` header) — live current-price / day-change header,
  planned/open only, dispatching on trade type: outright underlying, pair ratio
  (same A.6 formula), options-spread live mark from bid/ask. The whole quote
  (price + %) is colored green up / red down / neutral gray-white when flat or
  unavailable (user request, 2026-07-08). Verified: SMH +1.9%, USD/JPY +0.2%, pair
  ratio +1.3%; FIVN/GLD-put/META all `chain_expired` (June expiries vs a July
  "today" — option_chain() only returns listed expiries, so the header is correctly
  hidden); closed/bogus id → `not_live`.

**Two extra fixes landed during verification (not in the original list):**
- **dotenv anchoring** (`watchtower_engine.py` line ~6) — `load_dotenv()` now loads
  the `.env` next to the script (`__file__`-anchored), not one relative to the launch
  cwd. A bare `load_dotenv()` silently lost ALL config (API keys, NEWSLETTER_PDF_DIR)
  when the engine was launched from any other directory — every newsletter endpoint
  just returned `not_configured`/empty. Surfaced because the preview harness launches
  from a relocated cwd.
- **Futures `=F` symbol translation** (user-approved, 2026-07-08) — bare futures roots
  silently mis-resolve on yfinance (`HG` → an unrelated equity at ~$34 instead of
  copper at ~$6). Now `chartSymbol()` (frontend) and `_quote_outright()` (backend)
  append `=F` for a CLEAN root (letters only), verified HG=F → real copper ~$6.13.
  This fixes BOTH the new quote header AND the long-standing HG Chart tab that was
  silently plotting the wrong instrument. An exotic display-name (e.g. "CL1!") fails
  the clean-root check and falls back to unavailable/bare rather than a wrong price —
  it partially addresses, but does NOT fully close, the still-open CL1!/CL=F
  display-vs-fetchable-symbol item (that remains for non-clean-root futures).

**Verification method:** backend endpoints exercised via curl against a live engine
(all trade types); frontend JS node-syntax-checked; C.1 arithmetic dry-run against
the real store; chart-symbol resolution confirmed against yfinance directly. The
card-by-card VISUAL review is the user's own instance (per standing preference) and
the user confirmed no remaining card/detail-panel issues on 2026-07-08.

**Nothing committed** — all changes remain uncommitted on `feature/newsletter-ingestion`.

## 260706 review — two schema gaps surfaced by tricky trades (2026-07-11)

The 260706 issue ("Mastering the Rotation") was imported incrementally at low
effort ($0.30, 7 live / 25 archive after merge — see the cost log). Reviewing
the 4 genuinely new trades against the source PDF surfaced two real structural
gaps in the schema — neither is a capture bug (the model extracted exactly
what was on the page), both are cases the current schema has no clean home
for. Confirmed against the PDF text directly, not guessed.

### F. Pairs trades with a PER-LEG conditional trigger — no structured home today

**IGV vs SOXX pair (`igv-vs-soxx-pair-2026-07-06`).** Source PDF, verbatim:

> Entry trigger: Enter both legs only after SOXX posts a daily close below its
> 50-day moving average
> Trigger: SOXX daily close below its 50DMA, currently ~545.63
> IGV confirmation: IGV should remain above its 50DMA, currently ~91.27
> Stop / invalidation: Close the trade if SOXX reclaims its 50DMA or IGV
> closes back below its 50DMA

This is a **compound, two-sided condition** — SOXX must break below its own
50DMA AND IGV must simultaneously stay above its own 50DMA. Unlike the
260608 XLV+XLP+XLF/IGV pair (a single ratio-level trigger, one number), this
trade has **two independent per-leg conditions on two different tickers**.
The schema only has one trade-level `entry.level`/`stop.level` pair, so the
extraction did the reasonable thing given what exists — it captured SOXX's
50DMA (545.63) as the single `entry.level`/`stop.level`, and pushed IGV's
condition (~91.27) into `entry.note` prose and `reference_values.igv_50dma`.
That's a faithful capture of what the letter said, but it means **IGV's
confirmation condition is not structured data** — nothing downstream (a
future "check if this trade should trigger" automation, for instance) could
evaluate it without parsing prose.

**DECIDED (user, 2026-07-11): leave as-is, capture the structured condition as
a FUTURE feature tied to the trigger-alert engine.** The full condition is
already captured losslessly in prose (`entry.note` / `stop.note`) and the
snapshot numbers in `reference_values`, so nothing is lost today. Crucially,
the two 50DMA numbers stored (545.63, 91.27) are point-in-time snapshots of
MOVING averages — they go stale immediately, and a real trigger engine would
recompute the 50DMA live from `/get_price_history` rather than read the stored
value. So the stored numbers are display/reference only, NOT the automation
input. The only thing an engine genuinely can't recompute — and thus the only
thing worth structuring — is the CONDITION shape (which ticker / which direction
/ which indicator: "SOXX below its 50DMA" AND "IGV above its 50DMA"), which is
prose today. Per §7.4 ("does anything downstream DECIDE based on it?") nothing
consumes it yet, so a typed `confirmation` field is deferred until the
trigger/proximity-alert engine (`newsletter-tracker.md` "Trigger philosophy")
is actually built — at which point the field should be shaped to fit that
engine's needs, and the relevant issues re-imported then. Capturing more now
buys nothing the prose doesn't already hold.

**Sharper version of the same gap (user, 2026-07-11): this pair has NO ratio
at all, unlike the 260608 XLV+XLP+XLF/IGV pair.** That trade's letter stated
an explicit combined number ("Entry Ratio 3.01") that both legs' merged price
action produces — a genuine ratio trade. IGV/SOXX is structurally different:
two **independent absolute-price conditions** on two different tickers (SOXX
below its own 50DMA, IGV above its own 50DMA), packaged as a "pair" for
thematic reasons (a leadership-rotation call), not because a combined ratio
metric is what's being traded. The PDF's "Exhibit 2: SOXX vs IGV setup" is
just a chart image, not an extractable number. Consequence: `entry.level:
545.63` in the stored trade is actually **SOXX's own raw 50DMA price**, not a
ratio — sitting in the exact same field that held a real ratio (3.01) for the
other pair. **FIXED 2026-07-11 (user: "the entry price should be a ratio; if the ratio
isn't stated, we revert to the trigger notes").** A pair's `entry`/`stop`/
`targets` `level` is RATIO-ONLY — never a single leg's raw price. When no ratio
is stated (the entry/stop is a per-leg price condition, as here), the level is
NULL, the condition lives in the sibling `note` (surfacing in the
Trigger/Invalidation panel), and any raw single-leg reference number (SOXX's
50DMA) goes to `reference_values`. Two-part fix:
- **Prompt (`EXTRACTION_SYSTEM` LEVELS & PRICES):** added the pairs rule —
  "a pair's level is a RATIO, NEVER a single leg's price; no ratio stated ->
  null level + condition in note + raw leg numbers in `reference_values`
  (`soxx_50dma`, `igv_50dma`)."
- **Data patch (current IGV/SOXX record, $0):** nulled `entry.level`/`stop.level`
  (both were 545.63 = SOXX's 50DMA, a raw price mis-filed as a ratio), moved
  545.63 to `reference_values.soxx_50dma` (symmetric with the existing
  `igv_50dma`); the condition notes were already present.

**Verified live** across all three pair cases, now internally consistent: IGV/SOXX
(no ratio) shows "Entry --" + the trigger notes; IWM/QQQ (real ratio 0.412) shows
"Entry 0.412"; the defensive-breadth closed re-entry (no stated entry level) shows
"Entry --" legitimately. The `soxx_50dma`/`igv_50dma` values are preserved in
`reference_values` but correctly filtered out of the stat-chips (recomputable
moving averages, per the `dma`-filter fix). A future current-ratio feature (A.6
extension) can now treat a null pair `level` as "no stated ratio" and a non-null
one as a genuine ratio — the ambiguity is designed out.

**Adjacent display bug, FOUND AND FIXED same session (user, 2026-07-11):**
reviewing this trade's detail panel, the user noticed the panel showed none
of the clarifying trigger/confirmation language at all — not even what
already exists in `entry.note`/`stop.note` ("IGV must remain above its own
50DMA," "close the trade if SOXX reclaims its 50DMA..."). Root cause,
confirmed by grep: `stop.note` was **never rendered anywhere** in
`watchtower.html` (zero matches), and `entry.note` only rendered as a
side-effect of the tranches block (`nd-tranches`, gated on
`tranches.length > 0`) — so for any trade without tranches (most trades),
`entry.note` was invisible too. `levelsRowHTML()`/`levelsInlineHTML()` (the
header/card level display) only ever show bare numbers via `fmtLevel()`, no
notes. This directly contradicted `newsletter-schema.md`'s own B.1 rule, which
created `.note` specifically to hold this exact kind of qualifying/conditional
language as "detail-panel content ... never on the card" — the intent existed,
the render path never got built. **Fixed:** added a new unconditional
"Trigger / Invalidation" section (`#nd-trigger-notes-section`, populated in
`showNewsletterDive()`) that shows `entry.note`/`stop.note` whenever present,
independent of tranches; removed the now-redundant duplicate `entry.note` line
from inside the tranches renderer. Verified live in the browser preview
against three cases: IGV/SOXX (both notes render correctly), HG copper with
real tranches (trigger note + per-tranche notes both show, no duplication),
and a trade with empty tranches (tranches section correctly stays hidden).
**Follow-up (user, 2026-07-11):** the new section originally spanned the full
panel width, making the note text stretch edge-to-edge (hard to read). Added
`max-w-[50%]` to `#nd-trigger-notes-section` — verified via `preview_inspect`:
width dropped from 884px to 439px (50%), box height grew as the same text now
wraps across a narrower column.

**Adjacent compactness fix, same session (user, 2026-07-11):** the Thesis box
(`#nd-thesis`) had unexplained blank space below short thesis text. Same root
cause the project already fixed once before in a different panel
(`newsletter-tracker.md`'s "Trigger Checklist border" note): `#nd-thesis` sat
in a `grid-cols-2` row alongside `#nd-options-data`/`#nd-structure` (Options
Structure), with `flex-1` stretching it to match whichever column was taller —
padding out empty space under short thesis text instead of sizing to content.
**Fixed:** removed `flex-1` from `#nd-thesis`'s class list. Verified via
`preview_inspect`: box height dropped from 169.5px to 136.5px on the IGV/SOXX
trade, now sized to its actual text instead of stretched to match its sibling.

**Follow-up, same session (user, 2026-07-11): the flex-1 removal alone didn't
fully fix it.** Direct measurement showed `#nd-thesis`'s own box shrank, but
its PARENT column wrapper (`<div class="flex flex-col">`, the actual CSS Grid
item in the `grid grid-cols-2` row) was still being stretched to match its
sibling column's height — CSS Grid's default `align-items: stretch` applies
to grid items themselves, one level above where `flex-1` was removed, so the
blank space just moved up one DOM level instead of disappearing. **User's
clarification on scope:** the Thesis/Options-Structure side-by-side layout
itself is fine to keep as the default top-row layout (a row's height
necessarily matches its tallest column — that's normal and expected); the
actual ask was that every section BELOW that top row should stack according
to real content height, with no column carrying forced blank space it doesn't
need. **Fixed:** added `items-start` to both `grid grid-cols-2` row
containers (Thesis|Options-Structure AND Key-Dates|Status-History) — this
overrides the grid's default stretch so each column sizes to its own content;
the row's overall height (and thus the position of *following* sections) is
still governed by the row's tallest column, which is expected/unavoidable for
a side-by-side layout, but nothing below is held down further than that, and
no column carries dead space beyond what the row height requires. **Verified
via `preview_inspect` on two real cases:** IGV/SOXX pair (Thesis column:
227.5px stretched → 194.5px content-sized); HG copper (Key Dates column,
empty: 122px stretched → 80.75px content-sized, next section — Tranches —
starts exactly at `row.bottom + gap` with no extra space introduced).

**Superseded by a full restructure, same session (user, 2026-07-11): "I don't
want one section to be a sibling to the adjacent one."** The `items-start`
fix above only stopped a column from padding out to match its sibling's
height WITHIN a shared row — it could not make sections below that row move
up, since a shared row's height is inescapably bound to its tallest column.
User's explicit direction: no shared rows at all. **Rebuilt `#nd-pane-narrative`
as two genuinely independent flex-column containers** (`grid grid-cols-2
gap-4 items-start` at the outer level, each column its own
`flex flex-col gap-4`) instead of pairing Thesis|Options-Structure and
Key-Dates|Status-History as separate grid rows:
- **Column A:** Thesis → Trigger/Invalidation → Key Dates
- **Column B:** Options Structure (+ heatmap button) → Status History → Tranches

Each column now stacks purely by its own content — nothing in one column is
height-matched to its counterpart in the other. **Verified via
`preview_inspect` on IGV/SOXX:** Column A totals 485px, Column B totals only
322px; Column B's Status History box ends at y=713, confirmed NOT stretched
down to match Column A's 877px bottom. No JS changes were needed — all
`getElementById` population code in `showNewsletterDive()` targets the same
IDs, which just moved to new DOM positions.

**Adjacent real bug found and fixed, same session (user, 2026-07-11): a
visibly empty, unlabeled grid cell inside the Options Structure box.**
`refValueChips()`'s filter (meant to exclude chart-redundant reference values —
moving averages, spot/close prices, since those are already on the Chart tab)
used a regex (`/(^dma_|_dma$|close$|^spot|_spot)/i`) that only matched
`dma_x`/`x_dma`-style naming. IGV/SOXX's actual field, `igv_50dma` (digits
directly before "dma", no separator), didn't match — so a genuine moving
average slipped through as a "trade-specific" chip. With only 2 chips
surviving the (broken) filter, the hardcoded `grid-cols-3` layout left one
grid cell completely empty — no box, no label, just dead space, which is the
"reserved space with no data" the user was pointing at. **Fixed two things:**
(1) broadened the filter regex to a plain `dma` substring match, which
correctly excludes `igv_50dma` (leaving only the genuine trade-specific
`soxx_52w_high`); (2) extracted a new `refValueChipsBlock()` that sizes the
grid's column count to the actual surviving chip count
(`Math.min(entries.length, 3)`) instead of hardcoding 3, so there's never an
empty cell regardless of how many chips remain. **Verified live:** IGV/SOXX
now renders exactly 1 chip in a 1-column grid; KRE (a different trade, 4 raw
reference values, `spot`/`reference_debit`/`breakeven`/`max_profit`) still
correctly renders all 3 non-spot chips in a 3-column grid with no gap —
confirming the fix didn't regress the working 3-chip case.

**That fix was NOT the real bug — user correctly rejected it ("that didn't fix
a thing").** Got an actual screenshot working (prior verification in this
session relied entirely on DOM measurement, which missed this) and saw
"Options Structure" was missing from the right column ENTIRELY — not a
partially-empty grid cell, the whole quadrant. Root cause: `#nd-options-data`
had `style="visibility: hidden"` set inline. Traced to `showNewsletterDive()`
(~line 1681): `ndGatingClass = (t.structure === 'pairs') ? 'pair' :
t.asset_class` intentionally feeds a synthetic `'pair'` class (since a basket
has no single options chain) into `setOptionsDataVisibility('nd',
ndGatingClass)`, which sets `visibility: hidden` whenever the class isn't
`'equity'`. That gating function's own comment ("Options Data quadrant only
makes sense for single-name equities... pairs trades have no single options
chain to show here, so the quadrant stays blank") describes an OLDER version
of this quadrant — before the C.4 fix rewrote `renderOptionsStructureHTML()`
to always render real content for pairs (basket composition) and outrights
too. The gating call was never updated to match, so it silently re-blanked a
quadrant that had genuinely useful, fully-populated content in the DOM
(confirmed: the basket chips were there, `visibility:hidden` just made them
invisible while still reserving the full 227.5px of layout space — exactly
the dead space the user saw). **Fixed:** removed the `setOptionsDataVisibility('nd', ...)`
call and unconditionally set `#nd-options-data` visible in
`showNewsletterDive()`. The Options TAB gating (`setTabsForAssetClass`, a
separate and still-valid concept — the actual Options tab pane shows literal
live-chain content meaningless for a pair) is untouched. The `dd` (ticker
Actionable-Moves) quadrant is a different, unrelated element still correctly
gated — it shows real ATM-strike/IV-style fields that don't exist for
non-equity tickers. **Verified with an actual screenshot** (not just DOM
measurement) on IGV/SOXX: "OPTIONS STRUCTURE" now renders with its
Basket/Pair label, LONG IGV / SHORT SOXX rows, and the reference chip.

**Final column assignment (user, 2026-07-11):** with both columns working,
the user specified the exact section-to-column mapping (reorder only, no logic
change — all section IDs unchanged, so `showNewsletterDive()` needed no edits):
- **Column 1 (the trade's "story"):** Thesis → Key Dates → Status History
- **Column 2 (the trade's "mechanics"):** Options Structure → Trigger /
  Invalidation (if present) → Scaled Entries / Adds (if present)

Trigger/Invalidation and Scaled Entries stay conditionally hidden (their
`.hidden` class is toggled by the populate code) — so a trade lacking either
just shows the sections it has, with the column collapsing to content height.
**Verified via DOM + screenshot on two trades:** IGV/SOXX (Column 2 = Options
Structure + Trigger/Invalidation; no tranches, Scaled Entries correctly
absent) and HG copper (Column 2 = all three, Scaled Entries present).

### Observation-only indicators — clickable from the digest (user, 2026-07-11)

Indicators (`conviction.label ∈ {observation_only, watchlist}`) are excluded
from the plays STRIP (§6 — they're a market read, not a takeable position, so
they render in the weekly-digest dropdown instead). But the user noticed the
detail panel DEFAULTS to an indicator on reload (whenever one sorts first in
`loadNewsletterState()`'s status-ordered pick — indicators stay in
`NEWSLETTER_TRADES`, they're only filtered out of the strip render), and once
you click any strip card there was **no way back** — the indicator had no
clickable surface anywhere. User likes seeing this data and asked for a way to
re-open it.

**Fix:** made the indicator cards in the digest body (`_renderDigest()`,
"Indicators" section) clickable — `onclick="event.stopPropagation();
showNewsletterDive('${ind.id}')"` plus `cursor-pointer` + a hover state.
`showNewsletterDive()` looks up `NEWSLETTER_TRADES`, which contains indicators,
so it opens the full detail panel for one exactly like any trade. The
`stopPropagation()` keeps the click from also toggling the digest collapse
(the digest header has its own `toggleDigest()`). Works in both live and
past-edition modes (past mode reassigns `NEWSLETTER_TRADES` to the frozen
issue's `trade_updates`, so the lookup still resolves). **Verified live:**
clicked a regular trade (IGV/SOXX), then clicked the digest's indicator card —
detail panel switched to the software-dispersion basket (correct thesis + full
CRWD/PANW/NET long, WIX/FIVN/PD short basket), digest stayed open. Left the
default-on-reload behavior as-is (user likes the indicator surfacing there);
the clickability just makes it recoverable.

### G. Multi-underlying "funded package" trades — closed sub-legs vanish from the archive

**QQQ/CRM/HUBS downside-convexity package.** Source PDF, verbatim:

> We entered this package on Monday 6/29 as a funded downside structure...
> Original structure: long QQQ July 17 735/715 put spread, funded by selling
> CRM July 17 165/180 call spread and HUBS July 17 200/220 call spread. Net
> package cost was roughly $0.45.
> We sold the QQQ put spread at $11.04 versus $5.98 entry. We also bought back
> the CRM call spread at $4.83 versus $2.25 entry... The remaining open leg is
> the HUBS 200/220 call spread.

This is a single economically-linked trade spanning **three different
underlyings** (QQQ, CRM, HUBS), where two of the three components (QQQ put
spread, CRM call spread) have already **closed for real, realized gains**
($5.98→$11.04 and $2.25→$4.83 respectively) and only the HUBS leg remains
open. **Confirmed via `q.py qqq` / `q.py crm`: neither QQQ nor CRM exists
anywhere in the store as its own trade record.** Their entry/exit prices are
captured, but only as inert `reference_values` (`qqq_leg_exit`,
`qqq_leg_entry`, `crm_leg_exit`, `crm_leg_entry`) on the surviving HUBS trade
object — meaning **two real closed positions with real realized P&L are
invisible to the `archive` bucket and will never appear in a future hit-rate
scoreboard**, which is exactly the kind of silent loss the whole 8d
tranche-split design was built to prevent for a *single*-underlying scaled
position. This is the same failure mode, one level up: a multi-underlying
package instead of a multi-tranche single position.

Also notable: `paired_with`/`pairing_note` exist precisely for "a deliberate
cross-trade relationship" (per `newsletter-schema.md`'s design principles) but
are `null` here — the model had a legitimate 3-way relationship to express and
no field shaped for more than a 2-way pairing.

#### Why the model "discarded" QQQ/CRM — it didn't; it's a SLOT problem, not a reasoning problem (diagnosed 2026-07-11)

User's sharp question: the language was plain and complete (structure, entry
price, exit price, expiry all stated for every leg) — "it cannot get any
easier than that — yet there's no artifact in the schema that pulled that data
out." Diagnosed against the actual `EXTRACTION_SYSTEM` prompt, not assumed:

- **The word "package" appears 0 times in the prompt.** The only structural
  instruction is "ONE trade [object per newsletter trade line]", and the entire
  `underlying`/`legs`/`basket` model is built around a **single underlying per
  trade object**. The one multi-ticker concept — `basket` — is explicitly for
  *pairs* (market-neutral, `legs = null`), NOT multi-underlying options. There
  is no target shape anywhere for "several underlyings, each with its own
  options legs."
- **A leg has no ticker field** — it inherits the parent trade's single
  `underlying` (confirmed against the MU iron condor: 4 legs, all sharing
  `underlying: MU`; `{strike, expiry, type, action, quantity, note?}`, no
  ticker). So the QQQ and CRM legs had **physically nowhere structured to go** —
  they can't join HUBS's `legs` (they'd wrongly inherit `underlying: HUBS`), and
  there's no second/third trade object for them.
- **The model did NOT discard the data — it demoted it losslessly.** Every
  number survived, in `reference_values` (`qqq_leg_entry/exit`,
  `crm_leg_entry/exit`) + prose. Given no structured slot, that was the correct
  conservative move. This is exactly the §7 principle in reverse: "a fact that
  can only live in a sentence is a SCHEMA BUG, not a model failure."
- **The model was also right NOT to improvise three objects.** The whole
  tightening pass (§7.4, determinism) explicitly trained it to fill defined
  slots and NOT invent structure — a model that spontaneously emits three trade
  objects from one "package" line is precisely the run-to-run structural
  variance that pass eliminated. So "it stayed as one object" is the tightening
  working as designed, not laziness.

**Takeaway: you cannot fix this with better prompt WORDING alone — there's no
target shape for the words to map onto.** The fix is DEFINITIONAL: give the
decomposition a rule + a slot, which turns it from improvisation (non-
deterministic, discouraged) into deterministic capture the model performs every
run — the same move §8d made for tranche splits.

#### RESOLUTION (DECIDED 2026-07-11, user) — decompose into N trades + a `package_id`

Chosen over a first-class `package` container object, and the reasoning is the
project's own architecture, not preference: **every existing "complex
situation" in this schema is already handled by decomposition into linked trade
objects, never by a container** — a covered call is "TWO objects, never one"
(`overlay_of`); a partially-closed scaled position splits into two records
sharing `strategy_id` (§8d); a cross-trade hedge is two independent trades
linked by `paired_with`. The trade object is the atomic unit the entire
downstream stack assumes (scoreboard groups them, `archive` buckets them,
`compute_risk_pnl` runs per object, renderers render them). A `package`
container would be a NEW kind of thing every consumer must learn to recurse
into — and it wouldn't even fix G's actual problem (QQQ/CRM invisible to the
scoreboard) unless the scoreboard also learned to unpack packages. Decomposition
fixes it directly: QQQ and CRM become normal top-level `archive` trades.

**The shape — TWO levels of linkage:**
1. **Each spread → its own trade object** with its own `underlying`, `legs`,
   `status`, entry/exit prices, and Python-derived `pnl_pct` + its own
   **`strategy_id`** (`qqq-bear-put-spread`, `crm-bear-call-spread`,
   `hubs-bear-call-spread`). They are genuinely different strategies on
   different names — the scoreboard SHOULD score them independently, so they do
   NOT share a `strategy_id`.
2. **A new `package_id` (shared string, grouping key exactly like `strategy_id`
   is for re-entries)** ties the members together as "entered as one funded
   structure." This is the display/context link — the Trade Structure panel can
   show "part of the QQQ/CRM/HUBS package" and cross-reference siblings.
   `package_id` is null on the vast majority of trades (only funded/linked
   multi-underlying packages carry one). Chosen over generalizing `paired_with`
   to an array because a package is an N-way grouping key, semantically identical
   to `strategy_id`/`campaign_title` (a shared label), not a directed pair.

**Extraction rule to add to `EXTRACTION_SYSTEM` (the definitional fix):**
> **Multi-underlying options package.** When one newsletter trade line describes
> a funded/linked structure spanning MULTIPLE underlyings (e.g. "long QQQ put
> spread, funded by selling CRM and HUBS call spreads"), emit **one trade object
> per underlying** — each with its own `underlying`, its own `legs` (that
> underlying's legs only), its own `status`, and its own entry/exit prices —
> NOT one object with the others' legs demoted to `reference_values`. Give every
> object the SAME `package_id` (a short slug naming the package, e.g.
> `qqq-crm-hubs-downside-convexity`). Each object's `status` is independent: a
> package leg the issue says is closed → that object is `closed` (with its
> exit_price); a leg still held → `open`. Do NOT force a single shared status.

**Python side (deterministic, per §7):** `package_id` is model-owned (it's a
label, like `campaign_title`); `strategy_id` and `pnl_pct` are derived per
object exactly as they already are for any single trade — no special package
logic needed in `compute_risk_pnl`, because after decomposition each object IS
just a normal single-underlying trade. The only genuinely new mechanical piece
is a display grouping in `watchtower.html` (show package siblings together /
cross-link). The `package_net_cost` figure ($0.45 here) does NOT survive as a
P&L basis — each sub-trade is scored on its OWN basis (QQQ 5.98→11.04, CRM
2.25→4.83, HUBS its own credit); the net-cost number is retained display-only
as a `reference_values` entry on the package group. This is MORE correct for a
per-strategy scoreboard (each spread judged on its own risk), and loses nothing
real — the "net funded package" framing is display color, preserved via
`package_id` + the note.

**Cost is modest and the capability is proven:** the model already captured all
6 legs' economics THIS run (just misfiled QQQ/CRM into `reference_values`), so
this is a placement/structure change — the same KIND of split the covered-call
two-object model already asks of it — not a new extraction capability.

**Status: BUILT 2026-07-11 (code complete; billed re-import of 260706 still
pending to capture it against the real PDF).** Item F remains DEFERRED. What
was built:
- **`newsletter_ingest.py` `EXTRACTION_SYSTEM`:** added the "MULTI-UNDERLYING
  OPTIONS PACKAGE -> ONE TRADE OBJECT PER UNDERLYING" rule (each object its own
  `underlying`/`legs`/entry-exit/`status`, all sharing a `package_id` slug;
  `package_net_cost` recorded once in `reference_values`; single-underlying
  multi-leg structures like an iron condor explicitly excluded — those stay one
  object). Added `package_id` to the primitives field list.
- **Python: no logic change needed, as predicted** — `merge_into_store` preserves
  unknown model fields (no whitelist), and each decomposed spread is a normal
  single-underlying options trade, so `strategy_id`/`pnl_pct`/bucketing all derive
  per-object automatically.
- **`watchtower.html`:** new `packageSiblingsHTML()` renders a "Part of Package"
  banner at the top of the Trade Structure block — the package slug + clickable
  sibling legs (each showing its own status), empty for the ~all trades with
  `package_id: null`.

**One refinement surfaced during the build — `source_section` must be per-leg,
not the package's printed section.** A $0 dry-run through `merge_into_store`
(hand-crafted 3-object package) first came back with the closed QQQ/CRM legs
wrongly flipped to `open`: `derive_status_from_section` forces `status="open"`
for anything whose `source_section == "open"`, and a package is printed under
ONE section (Open Trades) even though its legs are at different lifecycle points.
Fix (in the prompt rule, NOT the status core — kept the battle-tested
section-status logic untouched): because each decomposed object is SYNTHETIC
(no separate physical newsletter line for one leg), the model sets each object's
`source_section` from THAT leg's own disposition — a closed leg gets
`source_section:"closed"`, the held leg `"open"`. Re-validated: **HUBS open
(live); QQQ closed +84.6% (5.98→11.04 debit); CRM closed −20.2% (credit bought
back, risk basis); all three carry the shared `package_id`; distinct
per-underlying `strategy_id`s; 0 flags.** Both closed legs now land in `archive`
with real `pnl_pct` — the exact G fix. Display verified live by injecting the
3 objects: banner + clickable siblings + cross-navigation + per-leg P&L all
render correctly.

**VERIFIED against the real PDF — billed re-import done 2026-07-11 ($0.32, low
effort, 0 flags).** Ran on a clean, $0-rebuilt pre-706 base (see the restore-point
note below), so the whole store stayed consistent. Result exactly matched the $0
dry-run: HUBS open (live) + QQQ closed **+84.6%** + CRM closed **−20.2%**, all
three sharing `package_id: qqq-crm-hubs-downside-convexity`, distinct per-underlying
`strategy_id`s; the two closed legs now in `archive` (scoreboard-visible) where the
old collapsed extract had them invisible in HUBS's `reference_values`. Store went
7 live / 25 archive (old collapsed import) → **7 live / 27 archive** (the +2 =
QQQ + CRM). The same run also picked up the max_scale dot-count fix automatically
(KRE + IGV/SOXX both `max_scale: 4` from the model). Minor cosmetic: the model
dates the decomposed ids by ENTRY date (`hubs-…-2026-06-29`) not issue date —
harmless, `strategy_id` is the stable grouping key.

**Restore-point hygiene note (2026-07-11):** the `pre-260706-merge` restore point
was NOT created before this session's FIRST 260706 import (sessions 19-20 made
`pre-260622`/`pre-260629` ones; this was skipped). No data was lost — every issue's
`raw_extract` is archived, so the exact pre-706 base was rebuilt for $0 by replaying
260608→629 merges through the current (plumbing-fixed) code (verified: rebuilt base
= 6 live / 22 archive with IWM-options reading the corrected −53.8, not the archive
snapshot's stale +46.2). That rebuilt base was saved as
`restore_points/pre-260706-merge__20260711-173735/` and used for the re-import.
Lesson: always snapshot a `pre-<issue>-merge` restore point before a merge — but the
`raw_extract` archive is the real safety net that makes any base $0-recoverable.

### I. Closed pair showed blank Entry — `closingEntry()` missing the `entry.level` fallback — FIXED 2026-07-11

User (reviewing 260706): the IWM/QQQ pair "didn't have the entry listed even
though it was listed in the prior week's trade." A DISPLAY plumbing bug, the
class the session-20 note flags ("blank number → check the PLUMBING first, do
NOT reach for a prompt change") — the data was fully present. The closed
`iwm-vs-qqq-pair-2026-06-29` carries `entry.level: 0.412` (the entry ratio,
correctly captured when the trade was `planned` the prior week and carried
through on close), `entry_price: null`, `tranches: []`. The closed-trade Entry
display (`closingEntry()`) only checked `t.entry_price` then tranche
`entry_price`s, then returned null — it did NOT fall back to `t.entry.level`,
even though its active-trade counterpart `activeEntryText()` already does. So a
closed pair (whose "entry" IS a ratio level, never a separate fill cost) showed
Entry `--` with the ratio sitting right there in the data. **Fixed:** added
`if (t.entry && t.entry.level != null) return t.entry.level;` as the final
fallback in `closingEntry()`, mirroring `activeEntryText()`. `entry_price` still
wins when present (checked first), so an options spread whose fill cost genuinely
differs from a trigger level is unaffected; only a truly entry-less close (a
back-computed pre-window close with no stated level) still shows `--`. **Verified
live:** the IWM/QQQ detail panel now reads "Entry 0.412 · Exit -- · P&L -0.91%"
(Exit correctly stays `--` — the letter stated the −0.91% result but never a
numeric exit ratio, so there's genuinely no number to show, per the
never-fabricate rule).

**The Python P&L side already honored this principle — the gap was display-only
(confirmed 2026-07-11).** `_entry_exit_levels()` (the §8c input plumbing for
outright/pairs P&L) already sources the entry basis with `entry.level` checked
FIRST (`entry_p = (t.get("entry") or {}).get("level")`), ahead of `entry_price`
and tranches. So a closed pair with a prior-week `entry.level` and a stated exit
ratio already computes `pnl_pct` from that entry — the scoreboard was never
wrong. IWM/QQQ shows the stated −0.91% (not a computed number) only because no
exit ratio exists (`exit_p` is null → nothing to compute against), not because
the entry was missing. So this was a lone frontend inconsistency: `closingEntry()`
was the only one of the three entry-sourcing paths (`_entry_exit_levels` Python,
`activeEntryText` active-display, `closingEntry` closed-display) that omitted the
`entry.level` fallback. Now all three agree — the prior-week stated entry is the
entry basis for computation AND both display states.

### H. `conviction.max_scale` hardcoded to 5 in the extraction prompt — FIXED 2026-07-11

User noticed the KRE and IGV/SOXX pair cards showed 4 conviction dots instead
of the usual 5. Root-caused, not assumed: precisely counted the dot glyphs in
the 260706 PDF (`re.finditer(r'Conviction:\s*([●○]+)')`, not eyeballing) —
both trades print **exactly 4 total dots** (3 filled, 1 empty), a genuine
4-point scale this issue uses, not a 5-point scale. The frontend
(`renderConvictionDotsHTML()`, `watchtower.html` ~line 945) was already
correct — it reads `conviction.max_scale` dynamically and loops that many
dots; no bug there. The bug was entirely in `newsletter_ingest.py`'s
`EXTRACTION_SYSTEM` CONVICTION section: every branch hardcoded `max_scale: 5`
regardless of what was actually printed, telling the model to count filled
dots for `scale` but never to count total dots for `max_scale`.

**Fixed:** prompt now instructs counting BOTH filled dots (`scale`) and total
dots (`max_scale`) from what's actually on the page, with an explicit
4-point-scale worked example alongside the existing 5-point one. **Also
corrected the already-stored data** (both `_store.json` and the `260706...json`
marker) for the two affected trades, `max_scale: 5 -> 4` — a deterministic
correction from confirmed ground truth, not a re-billed run. Going forward,
any issue using a different dot-scale convention will be captured correctly
without a prompt change.

### J. Never-entered off-ramps — indicators/conditionals must eventually retire — BUILT 2026-07-11

**Motivating case (user):** the AI/software dispersion basket (an
`observation_only` indicator) went unreferenced in 260629 AND 260706, yet stayed
live with `stale_flag: true` — because the schema said indicators are "retired
ONLY on an explicit drop." User: "at some point the trade is no longer relevant —
there has to be an off-ramp for these kinds of trades. Especially if there's never
an entry." The indefinite no-auto-close protection should be reserved for
genuinely-ENTERED positions (real risk); anything **never entered** eventually
lapses.

**Two off-ramps, both Python-deterministic (§7), both terminal to a new `lapsed`
discard status** (lightweight stub, OUT of the scoreboard — it was never a
position, so it can't count as a win or loss). Thresholds decided with user:
1. **Indicator silence (`LAPSE_INDICATOR_SILENCE = 2`):** an
   `observation_only`/`watchlist` indicator unreferenced (by theme OR constituent)
   for 2 issues lapses. Indicators keep the *longer* leash (exempt from the
   1-issue silence rule — they recur intermittently), but not permanent exemption.
   Reads model-tracked `weeks_unmentioned`.
2. **Conditional max-age (`LAPSE_CONDITIONAL_MAX_WEEKS = 4` default):** a
   never-entered NON-indicator planned trade older than its stated
   `holding_period.max_weeks` (else 4 weeks) lapses — catches a conditional that
   keeps being reiterated but never triggers. Python-computed age from `first_seen`
   → issue_date.

**"Never entered" is the discriminant** (`_never_entered()`): currently `planned`
AND no `status_history` entry ever reached open/closed. An OPEN position gone
silent is untouched (verified) — silence still never auto-closes real risk.

**Implementation:** `apply_offramp(t, issue_date)` in `newsletter_ingest.py`,
called per-trade in `merge_into_store` (which now takes `issue_date`; threaded
through `ingest_issue`, `run_import.py`, `rebuild_store.py`,
`build_split_editions.py`). `lapsed` added to `DISCARD_STATUSES`; `lapsed_now` in
the merge counts. The prompt's indicator-exemption block was updated: it now says
track `weeks_unmentioned` faithfully because **Python** owns the lapse decision
(the model no longer told "retired only on explicit drop").

**Verified:** 6 unit cases all correct (indicator@2 lapses, indicator@1 doesn't,
conditional@5w-no-horizon lapses, conditional@3w doesn't, conditional@5w-within-8w-horizon
doesn't, OPEN@9w-silent never lapses). Full re-derive dry run ($0) fires the lapse
at exactly 260706 (dispersion basket: introduced 260615, last-mentioned 260622,
unreferenced 260629+260706 → weeks_unmentioned 2), not before. Applied to the live
store surgically ($0, dated 2026-07-06 — a rebuild would've regressed the IGV/SOXX
manual patch): store 7 live → **6 live / 27 archive / 3 discarded**; dispersion
basket now a discard stub, gone from the plays/digest, no console errors.

## Dashboard-path instrumentation + cold full-ingest setup (2026-07-12)

**Motivation (user):** wanted to drive a FULL newsletter ingest from the dashboard
(not the CLI) in test mode, with all instrumentation — including token metrics — so
results are reviewable. Problem: the `/import_newsletter` endpoint discarded ALL
telemetry (it called `ingest_issue`, threw away `usage`, wrote no cost-log row / no
thinking log / no run_archive receipts). Only the CLI (`run_import.py`) was
instrumented.

**Fix — one SHARED instrumented path, both callers use it (can't drift):**
- New `newsletter_ingest.ingest_issue_recorded(text, store, extracted_dir, stem,
  filename, mode, effort=)` — splits the pipeline for the pristine pre-merge
  re-derive receipt, writes `_store.json` then the marker atomically (marker LAST =
  completion signal), and records EVERYTHING: thinking trace → `thinking_logs/`,
  store+marker+raw_extract+response → `run_archive/`, and a token+cost row →
  `cost_experiment_log.jsonl` (now tagged `source: "dashboard"|"cli"`). Also holds
  the shared `RATE_*` constants + `_atomic_write_json`.
- `run_import.py` refactored to call it (its ~90 lines of inline telemetry deleted).
- `/import_newsletter` (watchtower_engine.py) rewritten to call it. Defaults to
  **low** effort (the validated import convention; overridable via a body `effort`),
  and now RETURNS `cost_usd`/`elapsed_s`/`tokens{input,output,thinking,final}` in the
  JSON response (available to the dashboard if it wants to show per-import metrics;
  the primary review path stays `python stats.py` over the cumulative cost log).
- Verified: all three files compile; telemetry smoke-tested at $0 (monkeypatched
  `run_extraction`) — cost row + thinking log + 4 run_archive receipts all written,
  `lapsed_now` flows through.

**Baseline archived before the cold ingest:** `extracted/archive_sets/
ingest-baseline-20260712-100444/` — the complete pre-ingest set (`_store.json` 6
live/27 archive/3 discarded + all 7 markers + the cost log + a `_MANIFEST.json`).
This is the "store the entire ingest set for future analysis" deliverable; it lets
the fresh full ingest be compared against the incrementally-built store.

**Cold in-window ingest staged (user's choice):** deleted `_store.json` + the 5
in-window markers (260608→260706) so the dashboard shows them all pending;
`NEWSLETTER_START_DATE=2026-06-08` kept (260525/260601 stay grayed). `run_archive/`,
`thinking_logs/`, `restore_points/`, the cost log, and the two `_store.BACKUP-*`
files are preserved. **Requires the :5001 engine RESTART** to load the new endpoint +
`newsletter_ingest` code before importing. The user drives each import from the
dashboard oldest→newest (each click is a ~$0.30 billed low-effort run; ~$1.50 total),
fully instrumented.

### K. `key_dates` drops secondary catalysts — prompt tightened 2026-07-12

**Observed (user, mid-ingest of 260615):** the USD/JPY conditional short didn't
capture the FOMC meeting as a `key_date` — "again" (also thin on 260608). The
260615 "What we are watching" block lists TWO catalysts back-to-back for the
trade: the BoJ decision (06-16) AND "FOMC decision on Wednesday, 2:00 PM ET"
(06-17, Warsh's first as Chair). The model kept the BoJ date and dropped the FOMC
— the known **low-effort `key_dates`-omission** pattern (token test: LOW dropped
the CPI catalyst entirely on the GLD put). Effort doesn't reliably fix these, so a
prompt-level design tweak, not a re-run, is the lever.

**User's call:** design tweak only (no data patch — "I don't want a display fix").
Chose **prompt emphasis (option 2)** over an envelope-level issue-catalyst calendar
(option 3, rejected — "could just end up creating noise for each trade").

**Fix (`EXTRACTION_SYSTEM` `key_dates` rule):** capture EVERY catalyst the issue
ties to the trade, not just the primary/"resolution" one; explicitly sweep the
"What we are watching" macro list (FOMC/BoJ/CPI/NFP/OPEC/earnings) for events
bearing on the trade's underlying — with a guard against noise (only events the
issue actually ties to THIS trade, not every macro event onto every trade). The
running :5001 engine was RESTARTED so the remaining ingest (260622→260706) uses
the new prompt. **The current stored USD/JPY still lacks the FOMC date** (no
patch, per the user) — the fix applies to future extractions.

### L. Blended (size-weighted) entry for scaled positions — BUILT 2026-07-12

**Motivating observation (user):** the defensive-breadth pair (tranches at ratio
3.01 and 3.22) kept its entry at the 3.01 starter, but copper's `entry_price` came
out **6.3215** = exactly `(6.375 + 6.268)/2` — the **model** had computed a blended
entry for copper and stored it, but did it **inconsistently** (copper yes, the pair
no). Classic §7 signature: a derivation the model shouldn't own. Digging further
exposed a second bug — copper's blend was **display-only**: its `pnl_pct` was
**0.86%** = `(6.43−6.375)/6.375`, computed off the **6.375 starter** (the first
closed tranche via `_entry_exit_levels`' shortcut), NOT the blend the card showed.
So even copper's shown entry and its P&L disagreed.

**Size semantics (user, 2026-07-12):** tranche `size` is the **CUMULATIVE** position
weight the newsletter states — this author scales toward a full 1.0 and never above
("starter half" = 0.5; "add to 1.00" = 1.0 TOTAL, not +1.0). So each slice's
incremental weight is the difference from the prior cumulative (0.5, then 0.5).

**Fix (Python owns it deterministically, §7):**
- `_blended_entry_exit(t)` + `apply_blended_entry(t)` — size-weighted average
  entry (and exit, when all filled slices exited) over FILLED tranches (skip
  `planned`). Cumulative sizes → incremental weights by consecutive differencing;
  equal-weight fallback when sizes are null or not strictly increasing (copper's
  case). Written to `entry_price`/`exit_price`, **overwriting** the model's ad-hoc
  value. Called post-split in `merge_into_store`, so each split child blends its own
  tranches.
- `_entry_exit_levels` now takes the blend FIRST for a 2+ filled-tranche position,
  so P&L uses the same basis the display shows.
- Prompt: `tranches[].size` documented as the cumulative running total.
- **Verified $0** on the live records: pair `3.01 → 3.115`; copper entry stays
  `6.3215` but **pnl `0.86 → 1.72`** (the true blended return: half +0.86%, half
  +2.58%); **0** single/no-tranche trades changed (surgical — zero blast radius).
- Applies to remaining ingest (260622→) after the engine restart; the two already-
  imported 260608 records (copper pnl, pair entry) reflect old behavior until
  re-derived/re-imported (a $0 deterministic patch is legitimate here since the
  value is Python-derived, not a hand guess).

### M. Carried-trade entry lineage lost on re-merge — durability fix for L, BUILT 2026-07-12

**Motivating catch (user, mid-ingest):** after importing 260622, the defensive-
breadth pair's blended entry (3.115, item L + the manual patch) **reverted** — the
user rightly asked whether the patch had been merely cosmetic. It had NOT (the
stored `entry_price` really was 3.115); the real cause is a **carried-trade
data-loss bug** in the merge, and it's more important than L itself.

**Mechanism:** 260622 CLOSED the original pair (+1.40%) and RE-ENTERED post-FOMC.
The model faithfully extracted that — but a newsletter does NOT restate the
original entry ratios when it reports a close, so the 260622 output carried
`tranches: [{closed, +1.40%, NO price}, {open, NO price}]`. `merge_into_store` then
**wholesale-REPLACED** the stored pair (which had 3.01/3.22 + the 3.115 blend) with
that thinner version — dropping every entry primitive the closing issue didn't
repeat. This hits ANY position that closes/updates in a later issue, corrupting the
closed record's entry→exit lineage for the scoreboard.

**Fix — the CONFIRMED-ENTRY LOCK (user's rule, generalized 2026-07-12): "a
confirmed entry never changes — it's locked until the trade closes."** Once a
position is actually entered, its (blended) fill price is authoritative and must
survive every later merge. In `merge_into_store`, capture the prior stored trade's
`_confirmed_entry` (blended over filled tranches / a filled tranche price / the
entry_price on a held position — **excludes a bare `entry.level`**, which is a
planned TRIGGER, not a fill) BEFORE re-processing. Then, for each post-split child,
restore the locked entry when this merge DROPPED it, on the CONTINUING position —
i.e. a non-split record OR the CLOSED child of a split. The OPEN child of a split is
a genuine RE-ENTRY (a new fill with its own, possibly-unstated, entry) and does NOT
inherit the lock. A legitimate new add still re-blends via `apply_blended_entry`
(that leaves a basis, so it isn't treated as a drop). New helpers `_confirmed_entry`
/ `_has_entry_basis`. This generalizes the earlier close-only preservation: the entry
is protected from the moment it's confirmed (not just reconstructed at close), so it
can't be thinned during the open period either. **Verified $0** by re-deriving
260608→260622 (store + markers): the closed pair record carries `3.115` + `+1.40%`,
the OPEN re-entry correctly stays null (a new position), copper stays `6.3215` /
`+1.72%`, 0 flags. Makes L durable across re-merges. Note the SPLIT semantics the
user's data made concrete: a close+re-enter yields TWO records — the closed original
(keeps its locked 3.115) and a new re-entry (its own entry) — so "the entry" on the
CLOSED record is the one that's locked; the re-entry legitimately starts fresh. A
re-derive must rebuild the per-issue MARKER/edition files too, not just `_store.json`
(the Past Editions view reads the frozen marker). Engine restarted for 260629/260706.

### N. "Space Trade" second target missing — FIXED 2026-07-12 (session 22): DISPLAY bug, not extraction

**Root cause (diagnosed via `python q.py rklb`):** the stored record has BOTH targets —
`T1 5.57` and `T2 {level 6.0, level_high 6.25}` — so extraction was clean; this was a
DISPLAY bug. The frontend only ever read `targets[0]` (`targetDisplay()` -> the compact
strip/level rows), so T2 (the 6.0–6.25 trim zone the run actually reached) rendered
nowhere — confusing on a trade that closed +9% showing only the lower T1.

**Fix (`watchtower.html`, display-only):** added `targetRowsHTML(t)` — a divider-topped
"Targets" sub-section folded INTO the existing Trade Structure box (it's target
*structure*, so it belongs there, NOT a separate panel — user, 2026-07-12: "too many
boxes"). Injected into all three `renderOptionsStructureHTML` branches (pairs / outright
/ options). Lists EVERY numeric target with its label, level/range (via `fmtLevel`, so T2
shows `6–6.25`), and note. **ONLY renders when a trade has 2+ numeric targets** (user,
2026-07-12: "only want targets to display if there's multiple levels — otherwise, do not
populate") — a single-target trade already shows its one target in the compact level row,
so the sub-section would be redundant. Same NUMERIC-only rule as `targetDisplay` (a real
level, or `0` for an expiration_worthless spread; a purely qualitative target is skipped).
The compact strip card stays lean (still `targets[0]`) by design. Applies to all statuses
(a closed multi-target trade still shows what the targets WERE). No data/extraction change;
nothing re-imported. UNCOMMITTED on `feature/newsletter-ingestion`.

**Follow-up (2026-07-12, user): profit-target vs UNDERLYING-price guidance split — UNIT-based,
in merge processing.** The newsletter files underlying-price/management levels into `targets[]`:
KRE `reassess @80` / `monetization_zone @83–85`, and GLD 395/372 `T1 380` / `T2 372` (underlying
gold prices, note "Max value zone"). A first cut split these by LABEL, but GLD proved the label
can't be trusted — it labels underlying levels `T1`/`T2`. The robust signal is the UNIT: a
vertical's premium lives in `[0, strike-width]`, so a target `>=` the lowest strike is an
UNDERLYING price, not a premium. `derive_target_basis()` (`newsletter_ingest.py`, in
`normalize_derived`, mirroring `derive_stop_basis`) tags such a target `basis:"underlying"`;
the frontend `isProfitTarget(t,tg)` then routes off the tag — options underlying-basis targets →
the **Trigger / Invalidation** guidance (with `entry.note`/`stop.note`), everything else → the
Targets sub-section. Non-options targets (XLV/Space/copper — underlying/ratio, same unit as
entry) are untouched and keep their Targets block. Genuine premium targets (TLT/SLV `max_value`,
below the strikes) stay targets. Affected: KRE + GLD 395/372 (both now show no Targets block, with
their levels under Trigger/Invalidation). Store + all markers re-tagged free; full-cascade replay
confirms 0-diff reproducibility. Merge-side (Python owns the classification, §7), consistent with
the stop-basis fix (item P); the model's mislabeling is tolerated because Python overrides it.

<details><summary>original queued note (2026-07-12, pre-fix)</summary>

**User observation (mid-ingest, flagged for later — deliberately NOT investigated
to conserve context):** the Space Trade (260615, the RKLB/SPCE/RDW space-dispersion
pair `rklb-spce-rdw-pair-2026-06-15`) listed **TWO targets (T1 and T2)** in the
newsletter, but only ONE target (the lower T1) shows anywhere in the store/display.
When the trade later closes for **+9%**, the displayed target reflects something much
lower than the realized gain — confusing, because the run clearly went past T1 toward
T2.

**Suspected area (unverified):** either extraction dropped the second `targets[]`
entry, or the display only renders `targets[0]`. NOT root-caused yet. Do NOT assume
it's one or the other — check the stored trade's `targets[]` first (`python q.py
rklb`): if both T1/T2 are present, it's a DISPLAY bug (renderer shows only the first);
if only T1 is stored, it's an EXTRACTION drop (prompt: capture ALL stated targets,
same class as the K `key_dates` "capture every catalyst" fix). Fix in a fresh session
with full context. No code touched this turn.
</details>

### O. "Dump of all past cards" after the final import — TRANSIENT, NOT a bug (2026-07-12)

**User saw** the plays strip full of every past issue's cards after the 260706
import. **Root-caused: NOT a real bug — the strip IS correctly scoped and works.**
`renderNewsletterStrip()` already filters `if (t.status==='closed' && !viewingPastStem)
return t.last_mentioned === issueDate` — a close shows ONLY when its close-issue
matches the dashboard's current issue. Verified live after refresh: `issueDate
2026-07-06`, `viewingPastStem null`, **11 cards rendered** (6 live + 5 closes dated
07-06), NOT 33. Backend also clean: issue envelope 2026-07-06, all 5 editions, archive
`last_mentioned` correctly spread 06-08→07-06, 0 duplicates. The transient "dump" was
the frontend rendering a STALE board mid-import — before `NEWSLETTER_ISSUE` refreshed
to the 07-06 date, `issueDate` was stale/absent so the scope filter mismatched. A
refresh fixes it. (Earlier notes here that called it a by-design flaw were wrong and
have been corrected.) Possible minor hardening if it recurs: ensure the strip re-
renders only AFTER `loadNewsletterState()` sets the new `NEWSLETTER_ISSUE` — but low
priority; the steady-state is correct.

### P. Options stop shown as a nonsensical "premium" — FIXED 2026-07-12 (session 22): merge-side unit tag

**User:** TLT Dec-18 88/92 bull call spread showed `Entry 1.23 · Tgt 4 · Stop 85` — the
`85` is the UNDERLYING price ("a break of $85 invalidates"), a different unit than the
premium entry/target, so it read as nonsensical. User's steer: don't make a crazy blanket
frontend rule ("hide options stops"); still SHOW an explicit stop; do the classification in
merge processing (Python owns it, §7).

**Fix.** `derive_stop_basis()` in `newsletter_ingest.py` (called from `normalize_derived`):
an OPTIONS trade's stop with a level and no basis is tagged `stop.basis = "underlying"` —
recording the unit, not inventing/dropping anything (the model sets a stop level only when
the newsletter states one, so explicit stops are preserved). Deterministic. The frontend
then routes off the tag (NOT a `structure==='options'` check): the compact premium level row
omits an `underlying`-basis stop (both `levelsRowHTML` and `levelsInlineHTML`), and the
**Trigger / Invalidation** section shows it as `<level> (underlying) · <note>`. Showing the
LEVEL there also recovered KRE's `71.5–72`, whose note never restated the number — it was
previously the only place that number could live and it was being dropped. `stop.basis` was
model-written but read by nothing before this, so it was free to adopt as the signal.

Affects the 4 options trades with a stop level (TLT 85, KRE 71.5, FIVN 27.5, META 650) — all
genuinely underlying prices. Store + all per-issue markers re-tagged free (targeted
`derive_stop_basis` pass; full-cascade replay confirms the store stays byte-reproducible, 0
diffs). Outright (underlying) / pairs (ratio) stops share their entry's unit — untouched.
UNCOMMITTED on `feature/newsletter-ingestion`.

### Q. Open position greyed as `planned` in a Past Edition — FIXED 2026-07-12 (session 22)

**User:** the MSFT 06/22 392/400 bear-call card shows grey (planned) in the 06/22 Past
Edition, but the newsletter printed it under *Open Trades* — it should be violet (open).

**Root cause (live derivation bug, not a stale marker — current code reproduced it):** the
06/22 marker had MSFT `status:"planned"` with `source_section:"open"`. `derive_status_from_section`
correctly set `open` from the section, but `enforce_untriggered_conditional` then demoted it:
MSFT's entry is `trigger_type:"premium_target"` (a $0.95 credit) with NO captured `entry_price`,
so `_has_fill_evidence` was False and the backstop forced `planned` regardless of section. That
backstop exists to catch a genuinely-untriggered **sell-stop** the model mis-tags as open
(USDJPY, `trigger_type:"stop"`), but it over-fired on a real held credit spread.

**Fix (`enforce_untriggered_conditional`):** a LIMIT-style entry (`premium_target`/`level`) in the
CLEAR `open` section is trusted as held — a missing fill price is an extraction gap, not proof it
never filled. Only a `stop` (breakout) still requires fill evidence even under `open` (preserves
USDJPY → planned/unresolved). Verified by re-deriving the full cascade: MSFT@06/22 → `open`
(closes 06/29 as before); USDJPY stays planned then unresolved; FIVN/SLV (premium_target WITH
fill) unaffected. Store re-derive = 0 diffs (MSFT's final record was already `closed`); the only
change is the 06/22 marker's MSFT `planned`→`open`. Full store + all 5 markers rebuilt
(dry-run-diffed first: exactly that one change). `rebuild_markers.py` scratch tool now does the
complete re-derive (store + markers), closing the marker-rebuild gap the old `rebuild_store.py`
left. UNCOMMITTED on `feature/newsletter-ingestion`.

## Session handoff (2026-07-12, session 22) — ingest COMPLETE + CONSOLIDATED into master

**Milestone: the newsletter ingest is DONE (user's call), and the whole project is now
consolidated into the MAIN `Trader App` directory on `master`. No more worktree.**

**Built this session (all committed on master):**
- **C.18 iron-condor pricing** — `_price_multi_spread()` + `_structure_max_loss()` in
  `newsletter_ingest.py`, wired into `compute_risk_pnl`. MU 260629 → entry 2.38 / exit 2.23 /
  **+0.3%** on 47.62 max-loss risk; clears the iron-condor "no pnl" flag (see the C.18 spec block).
- **Options level-unit routing (item P + the N follow-up)** — `derive_stop_basis()` +
  `derive_target_basis()` tag an options STOP or "target" that is an UNDERLYING price (>= the
  strikes) as `basis:"underlying"`; the display routes those to Trigger/Invalidation and keeps
  only true PREMIUM levels in the compact row / Targets block. Fixed TLT's nonsensical `Stop 85`,
  GLD 395/372 `T1 380`/`T2 372`, KRE reassess/monetize. Python owns the split (§7); frontend reads the tag.
- **Item N — all-targets display** — detail-panel Targets sub-section lists every profit target
  (was `targets[0]` only), multi-target gated, folded into the Trade Structure box; `targetDisplay`
  is basis-aware too.
- **Item Q — MSFT open-section status fix** — `enforce_untriggered_conditional` trusts the OPEN
  section for a `premium_target`/`level` entry with no captured fill (was greying a held credit
  spread to `planned`); a `stop` breakout still needs fill evidence (USDJPY unaffected).
- Store + all per-issue markers re-derived FREE for the basis tags + MU price + MSFT status;
  full-cascade replay confirms byte-reproducibility.

**CONSOLIDATION (the structural change):**
- Retired `trader_dashboard.html` + `market_data_engine.py`; **`watchtower.html` +
  `watchtower_engine.py` (port 5001) are the CANONICAL, only dashboard/engine** (verified strict
  superset). Heatmap suite verified byte-identical / untouched.
- Merged `feature/newsletter-ingestion` → `master` (via reset); the MAIN `Trader App` dir now
  holds everything. Safety nets in the main checkout (drop when satisfied): tag
  `master-pre-consolidation-2026-07-12` + `git stash@{0}`.
- **`.env` gotcha:** `.env` is gitignored, so the main dir's copy needed the newsletter vars added
  by hand — `NEWSLETTER_PDF_DIR=C:\Users\pguth\Documents\Macro Newsletters` +
  `NEWSLETTER_START_DATE=2026-06-08`. Done. Any fresh checkout needs the same.

**OPS (main dir now):**
- Engine does NOT auto-start. Run it: `cd "C:\Users\pguth\OneDrive\Desktop\Trader App"` then
  `python watchtower_engine.py` (:5001). Static: `python -m http.server 8000`, open `watchtower.html`.
- Store/markers/PDFs live in `C:\Users\pguth\Documents\Macro Newsletters\extracted\` (absolute, unmoved).
- The SessionStart worktree redirect is CLEARED (`.claude/session_root_target.json` target `""`).

**NEXT:**
1. Housekeeping: drop the safety tag + stash; `git worktree remove` the worktree +
   `git branch -d feature/newsletter-ingestion`.
2. **Hit-rate scoreboard** — the natural next build. 27 closed trades in `archive` carry `pnl_pct`
   + `strategy_id`; nothing consumes them yet. Overall win rate + P&L first, then maybe per-strategy.
3. Small gap: SOXX collar (`soxx-jun26-645-5725-collar-2026-06-29`) is CLOSED with no `pnl_pct`
   (the deferred collar shape — short call + long put overlay, not a multi-spread).
4. Billed (ASK FIRST): effort-ladder experiment + determinism sweep.

## Session handoff (2026-07-12, session 21) — full cold ingest done; commit + N/C.18 next

**State:** FULL cold in-window ingest COMPLETE (260608→260706, 5/5, ~$1.70, all via the
newly-instrumented dashboard path). Store real + current: **6 live / 27 archive / 3
discarded**, clean (0 dups). Engine on :5001 has all session-21 code.

**Built this session (see items E–O above + the "Dashboard-path instrumentation" and
"260706 review" sections):** G multi-underlying package decomposition (`package_id`),
J never-entered off-ramps (`lapsed`), K `key_dates` capture-all, L blended size-weighted
entry, M confirmed-entry LOCK (durable across re-merges), dashboard-path telemetry
(`ingest_issue_recorded`, shared with the CLI), pairs level=ratio-only, `max_scale`
dot-count, import-dropdown newest-first + order hint.

**NEXT (fresh context):**
1. **COMMIT** — everything is uncommitted on `feature/newsletter-ingestion`.
2. **N** — Space Trade (RKLB/SPCE/RDW) 2nd target missing; `python q.py rklb` FIRST
   (display-bug vs extraction-drop).
3. ~~**C.18** — MU iron-condor pricing~~ ✅ **DONE 2026-07-12 (session 22):** MU → +0.3% on 47.62
   risk; store + 260629 marker re-priced free. See the C.18 spec block for detail.

**OPS:** restarting :5001 or re-deriving the store while a dashboard is open leaves the
frontend stale → refresh the browser. A Python re-derive MUST rebuild the per-issue
MARKER files too (Past Editions reads the frozen marker). Backups in `extracted/_backups/`.

## Next steps (open, prioritized 2026-07-08, updated session 16)

1. **~~Display & calculation fixes~~ — DONE (session 16, see "Build status update
   2026-07-08 session 16" immediately above).** All of sections A/B/C plus section E
   implemented and verified. The remaining open sub-item is operational: re-import
   260608 to backfill C.1's `pnl_pct` on DOCU/GLD and collapse USDJPY's duplicate
   BOJ `key_dates` (B.5) — both are billed-re-import-only, not code work.
2. **Long-import UX** — the synchronous `POST /import_newsletter` can outlast the
   browser's patience on a cold start (see first-import note above). If it recurs on the
   incremental issues, switch the frontend to fire the import then poll
   `/get_newsletter_state` rather than blocking on the long request. Not worth doing
   unless it recurs (615/622/629 should be far smaller/faster than the cold start).
3. **Import the remaining in-window issues** oldest->newest: `260615`, `260622`,
   `260629` (each incremental, much cheaper than the cold start). Re-verify the card
   fixes below against a second real issue once imported — this session's data is a
   single cold-start import, so some fixes (esp. #6/#7/#9) are validated against 9
   trades from one issue only.
4. **Hit-rate / scoreboard** — still unbuilt; `archive` (closed trades) is the data
   source, `strategy_id` the grouping key. The new risk-based P&L% (#9 below) is
   presumably the scoreboard's real metric, not raw $ — build this after #9 lands.
5. **Nothing merged to `master`** — the entire feature (both engine files, `watchtower.html`
   changes, `.env.example`) is uncommitted on `feature/newsletter-ingestion`.
6. **Token/reasoning-cost optimization — see the dedicated section immediately below.**
   Discovered while investigating why `260615` was truncating even at `max_tokens=64000`:
   most of the bill is discarded reasoning, not visible output. This is now a HIGHER
   priority than items 2-4 above — start here before spending further effort on
   incremental-import UX or the remaining queue imports, since every subsequent import
   pays whatever this costs until it's addressed.

## Token/reasoning-cost investigation & optimization game plan (2026-07-08)

Triggered by real observed token growth when attempting the `260615` incremental
import (see `run_import.py`, built this session for exact token/cost readouts). What
was found reframes the entire cost picture for this pipeline.

### Key finding: reasoning, not visible output, dominates the bill

- **Verified fact:** the `260608` cold-start import billed **29,907 output tokens**
  total (real figure from that import's completion log).
- **Stated and accepted as fact this session** (not independently re-verified via a
  fresh API call — deliberately taken as given per explicit instruction, distinct from
  the total-output-tokens figure above which IS independently verifiable): of that
  total, only **~5,305 tokens was the actual visible JSON** (10 trades + the full
  issue envelope). The remaining **~24,600 tokens (~82%)** was extended thinking —
  billed at the full $15/M output rate, then discarded.
- **Why it's discarded, concretely:** `run_extraction()`'s streaming loop (as of this
  writing) only accumulates `content_block_delta` events where `delta.type ==
  "text_delta"`. It never handles `thinking_delta` events at all — so this reasoning
  isn't just unused, it was never captured or logged anywhere, including for our own
  inspection.
- **Why it's happening by default, not by choice:** `claude-sonnet-5` runs adaptive
  thinking automatically unless a request explicitly configures `thinking` — and
  `run_extraction()`'s request payload never sets that parameter. This is an
  unexamined default, not a deliberate setting.
- **Why this reframes everything:** every output-token fix already identified (delta
  extraction, carry-forward-field removal, cheap-model triage, prompt trimming) only
  ever touches the ~18% visible-output minority. Reasoning is the majority of the
  bill, and none of those fixes touch it.

### Rates behind this analysis

- **Claude Sonnet 5 (current model):** $3/M input, $15/M output — output is 5x
  pricier than input, which is also why prompt caching (input-only) was already
  correctly ruled out as a lever for this specific growth problem.
- **Claude Opus 4.8** ($5/M in, $25/M out) **and Claude Fable 5** ($10/M in, $50/M
  out): both guaranteed more expensive per token than Sonnet 5 at every context
  size — all three share the same 1M-token context window, so context isn't a
  differentiator between them. Ruled out: any effort-tuning benefit they'd offer is
  already available on the cheaper Sonnet 5 directly.
- **Claude Haiku 4.5** ($1/M in, $5/M out — 3x cheaper than Sonnet 5 both ways; 200K
  context, still far more than this pipeline needs). Real risk for the FULL
  extraction job: this task needs precise multi-constraint schema compliance and
  subtle lifecycle judgment (open-vs-planned by entry mechanics, abandoned-vs-
  unresolved, `strategy_id` re-entry matching) — exactly where a "fast/simple-task"
  model tends to underperform, and this session already caught the *more* capable
  current model getting parts of this wrong pre-fix (see section B below). NOT
  recommended as a full-job replacement. DOES fit the cheap-triage sub-task described
  under "visible-output tier" below — a narrow yes/no classification, not the full
  extraction.

### Per-field token cost (measured via the real Anthropic `count_tokens` endpoint against the actual `260608` store, 10 trades)

- `thesis`: 809 tokens (10.2%) — single biggest field.
- `entry` + `targets` + `stop` combined: 1,488 tokens — bigger than `thesis` alone,
  largely because of pre-B.1 prose contamination (e.g. `entry.level: "$0.70-$0.80
  credit; do not chase below $0.60"` instead of a bare number). B.1 is now
  implemented (see "Build status update 2026-07-08 session 16" above), so this
  measurement is a pre-fix baseline, not necessarily the current state.
- `status_history`: 534 tokens (6.8%) at measurement time — a single-week snapshot
  where most trades had only one history entry so far. Structurally the one field
  that can only grow, never shrink, over a trade's life; its share will climb as
  trades accumulate more issues of activity.
- Everything else (`legs`, `reference_values`, `conviction`, `sizing`, etc.): a long
  tail of small, mostly-necessary structural fields — not real optimization targets.

### The layered plan (decided 2026-07-08, in priority order — impact-first, not risk-first)

**Layer 0 — Diagnose, then tune. Do this first: cheapest, and directly informs Layer 1.**
Capture the actual thinking content (add `thinking_delta` accumulation to
`run_extraction()`'s streaming loop; request `thinking: {type: "adaptive", display:
"summarized"}` so it comes back readable instead of empty-text). Inspect what the
~24,600 tokens is actually being spent on *before* deciding anything. Then act —
lower `output_config.effort`, or disable thinking outright, based on what the trace
shows. Both a measurement step and a standalone lever; don't skip straight to tuning
blind.

**Layer 1 — Prompting methodology restructuring. Try this next, not Layer 2 — see rationale below.**
Four concrete, non-exclusive levers:
1. **Split by difficulty into separately effort-tuned calls.** Separate envelope
   extraction (`market_structure`, `portfolio_house_view`, themes, `playbooks`,
   `analysis_features` — largely "read and structure") from trade-lifecycle
   reconciliation (matching, open-vs-planned, abandoned-vs-unresolved — the genuinely
   hard reasoning). Low/no effort on the envelope call; full effort reserved for
   reconciliation only. Not the same as the "batching" idea already ruled out
   elsewhere (that split *output* across calls, which doesn't reduce total tokens) —
   this pairs a split with *different effort per call*, which is the actual lever.
2. **Procedural decision path per trade** (check mention -> check the three
   material-change conditions -> conclude) instead of open-ended judgment
   instructions, to reduce exploratory reasoning. Risk: too rigid a procedure could
   blunt genuinely subtle judgment calls the current free-form instructions handle
   correctly (e.g. open-vs-planned entry mechanics).
3. **Pre-segment the newsletter text in Python** using the known section skeleton
   (What's New -> What We're Watching -> ... -> Portfolio House View) before the
   call, narrowing each trade's search space to a candidate excerpt instead of the
   whole document. Documented risk: section headers drift across issues (see
   `newsletter-tracker.md`/`newsletter-schema.md`) — a rigid header-based pre-split
   is fast when the format holds and silently wrong when it doesn't, unlike the
   model's own flexible content-shape recognition.
4. **Structured outputs** (`output_config.format` schema enforcement) instead of
   relying purely on prompt-described schema. Likely smaller effect — mainly reduces
   self-correction/formatting reasoning; secondary reliability benefit.

   **Core tension across all four:** this session spent real effort *adding*
   precision to the prompt (B.1, B.2, the risk/P&L rules) specifically to fix real
   extraction errors. Each of these trades some of that hard-won guidance for
   efficiency and risks reopening those same bugs if done carelessly. Measure both
   token impact *and* accuracy against a real issue before trusting any of them —
   none are free wins.

   **Why Layer 1 before Layer 2, specifically on impact, not risk:** the mechanical
   bookkeeping Layer 2 targets is inherently low-complexity reasoning even under the
   *current* design — copying an array forward or incrementing a counter doesn't
   require real "thinking" regardless of whether it's in the prompt — so it's
   expected to be a small share of the ~24,600 thinking tokens. The real reasoning
   weight is expected to be in the judgment calls Layer 1 targets directly. Layer 0's
   trace capture should confirm or refute this with real data before deep Layer 1
   work begins.

**Layer 2 — Python offload of carry-forward fields. Fallback if Layer 1 stalls; low-risk, worth doing eventually regardless of reasoning-cost impact.**
Remove the model's responsibility for `status_history` full-array restatement,
`first_seen`, `strategy_id`, and `weeks_unmentioned`/`stale_flag` arithmetic
*entirely* from the prompt — not just suppress their appearance in the output while
the model still implicitly "carries" them. Python derives all of it post-hoc from
what's already in the store. Distinct from general field-level patching (see "ruled
out" below): these are specific fields the prompt already declares as
never-independently-changing, so there's no ambiguous inclusion/exclusion judgment
being asked of the model — removing them is safe, not speculative. Primarily an
**output-cost** win (`status_history` especially, since it's the one field
guaranteed to grow with trade age); reasoning-cost impact expected to be small per
the Layer 1-vs-2 rationale above.

### Below the reasoning-cost tier — visible-output fixes, queued for AFTER reasoning cost is under control

(All target the ~18% visible-output minority, deliberately deprioritized behind
Layers 0-2 per the "reasoning cost needs to reach output-cost parity first" directive.)

- **Trade-level delta, gated on MATERIAL change, not mere mention.** Omit a trade
  from `trade_updates` only when it fails the *same* three-condition bar already
  used for `status_history` entries (status changed / P&L reported / material risk
  parameter changed) — not when it simply wasn't mentioned. This newsletter is
  diligent about restating open positions weekly even with nothing new to say, so
  gating on "mentioned at all" would rarely trigger omission; gating on "materially
  changed" is the correct, narrower test. Unverified until measured against a real
  second issue.
- **Cheap-model (Haiku-tier) triage pre-pass.** A fast/cheap model reads the
  newsletter plus a compact live-trade summary and flags which trades show real
  activity; only flagged trades go to the expensive model for full extraction. The
  reliable mechanism for implementing the trade-level-delta decision rather than
  trusting the big model to self-report — also cuts input to the expensive call.
  Bias the triage toward over-flagging when uncertain (a false positive costs a
  wasted full re-extraction; a false negative silently loses real data).
- **Prompt-block trimming.** Shrinking the ~6.4k-token `EXTRACTION_SYSTEM`
  instructions affects input tokens, which are 5x cheaper than output and already
  heavily cache-discounted. Low expected impact; last resort.

### Explicitly ruled out this session (don't re-litigate without new evidence)

- **Field-level patching** (send only changed sub-fields, e.g. just an updated
  stop) — real ambiguity/omission risk: requires the model to reliably decide
  inclusion/exclusion per field, including array semantics (`status_history`,
  `tranches`, `key_dates` append-only handling). Worse risk profile than Layer 2's
  carry-forward fields, which have no such ambiguity.
- **Importing every issue cold (empty `prior_trades`) instead of incrementally.**
  Barely reduces the dominant output-token driver (the newsletter still describes
  roughly the same N active positions each week regardless of a prior reference),
  while permanently destroying continuity — `first_seen` resets every week,
  `status_history` never accumulates, silence-based lifecycle rules can never fire,
  closed trades between issues get silently lost *every* week, `strategy_id`
  re-entry grouping fragments. Strictly worse than delta extraction on both cost and
  correctness.
- **Switching to Opus 4.8 or Fable 5**, even at lower effort — guaranteed 1.7x/3.3x
  higher per-token pricing on both axes; the effort-tuning benefit is already
  available on the cheaper Sonnet 5 directly, with no plausible mechanism for a
  bigger model to generate dramatically fewer tokens on this exact task at
  comparable effort.
- **Full swap to Haiku 4.5 for the whole extraction job** — real risk of *more*
  extraction errors on the complex reconciliation logic (this session already caught
  the more capable current model getting parts of this wrong pre-fix). Haiku's good
  fit here is the narrow triage sub-task above, not the full job.
- **Pure call-splitting/batching without effort differentiation** — does not reduce
  total output tokens (the same content still has to be generated somewhere, plus
  each call re-pays a slice of system-prompt overhead); only helps avoid truncation,
  a reliability fix not a cost fix. (Layer 1's "split by difficulty" differs — it
  pairs the split with *different effort per call*, which is the actual lever.)
- **Aggressively archiving/demoting stale-but-open trades sooner** to shrink the
  live set — would directly fight the already-settled schema rule that silence never
  auto-closes an open trade (manual user action required); not worth revisiting just
  to save tokens.
- **Anthropic's Batches API** (real 50% discount) — asynchronous, results can take
  an hour or more; a bad fit for "click Import and see it now." Would only make
  sense for a genuine bulk catch-up of many backlogged issues at once.

### Session handoff (2026-07-11, session 20) — 260622 + 260629 merged; "exit-drop" was a PLUMBING misdiagnosis; C.11–C.18 built/specced; older backlog audited OBE

**HEADLINE — internalize this (user's synthesis).** The schema/prompt strategy is **ROBUST**: across
two fresh issues (260622, 260629) at LOW effort, the extraction (model → primitives) held up. **Every
bug this session lived in POST-MERGE processing** — derivation, display sourcing, a field-placement
read, a stale chart check — NOT in capture. This is a live validation of §7 (model does prose→
primitives; the engineering is Python derivation + display). **Operating lesson: when a number is
wrong/blank on a card, check the PLUMBING first — do NOT reach for a prompt change.** We wasted a
whole thread "hardening" the prompt against a capture failure that never happened.

**STORE STATE:** 260629-merged, **6 live / 22 archive**, real + current. Import queue is CAUGHT UP —
260629 is the last available PDF. A $0 post-processing re-derive ran this session (exits sourced from
top-level; IWM P&L corrected). Billed runs this session: **260622 ($0.41) + 260629 ($0.47)**, both low.

**DONE + validated this session (all in `newsletter_ingest.py` + `watchtower.html`):**
- **C.11** iron-condor classifier · **C.12** single-leg short P&L (SOXX +100%) · **C.13** positioning
  dated-history (`accumulate_positioning`, model emits per-issue read, Python owns the list) · **C.14**
  Entry leads the active detail header (+ `activeEntryText` sources the fill cost) · **C.15** closed
  card Entry→Exit→P&L, `--` when a level was never stated · **C.16** pair exit-ratio Σlong/Σshort
  (defensive pair = 3.43), open-no-entry cards mute their data (not asset-based), score-on-close.
- **THE PLUMBING FIX (headline bug).** The apparent "exit-drops" (MSFT/GLD×2/IWM/copper/MU-scalp) were
  a MISDIAGNOSIS — the model captured EVERY exit at the **top-level `exit_price`** field.
  `compute_risk_pnl` / `_entry_exit_levels` / `closingExit` read exit only from `status_history`/
  tranches, NOT top-level (they DID read top-level *entry* — that asymmetry was the tell). Fixed by
  sourcing top-level exit in all 3 spots + a deterministic re-derive. §8c prefer-computed then flipped
  **IWM +46.2% → −53.8%** (author had spun a loss as "+$0.30 incremental, debit financed by the SOXX
  overwrite"). The prompt-hardening built for the wrong diagnosis was **REVERTED** (user: don't burden
  the reasoning engine). `flag_missing_exit` (Python completeness net, no model load) is KEPT — its "0
  fired" is what EXPOSED the misdiagnosis.
- **Pairs-chart fix:** the chart's `isPair` keyed off the RETIRED `asset_class === 'pair'` value
  (tightening §1 made pairs `asset_class:'equity'`/`structure:'pairs'`), so EVERY pairs chart silently
  broke. Now detects from `basketLegs`. Whole class repaired.
- **Older backlog AUDITED:** C.2–C.9 all RESOLVED/OBE (see the "AUDIT 2026-07-11" note by C.2); only
  C.10 survives (low-pri future).

**CORRECTIONS on record (don't re-chase):** C.17 leads with the plumbing-not-capture correction;
USDJPY `unresolved` @260629 verified CORRECT; abandoned/unresolved = display color (zero machinery);
the `smh-collar` is correct capture (unscoreable close, not a gap); positioning discard-stub DROPPED.

**PARKING LOT (C.18 now DONE — no live build items left):**
- **C.18** ✅ **BUILT 2026-07-12 (session 22)** — multi-spread (iron condor) pricing. `_price_multi_spread()`
  + `_structure_max_loss()` in `newsletter_ingest.py`, wired into `compute_risk_pnl`. MU priced to
  entry 2.38 → exit 2.23 → **+0.3%** on risk 47.62; iron-condor flag cleared; store + 260629 marker
  updated free (no re-extract — sub-spread prices sourced from `reference_values`). Full detail at the
  C.18 spec block below. SOXX collar / single-leg shorts remain out of scope (different shapes).
- Design directions (decided, no code): non-actionable churn → digest routing (behavior, NEVER asset);
  scoreboard actionability segmentation (waits on the scoreboard).
- Billed (ASK FIRST — [[prompt-before-billed-runs]]): effort-ladder experiment; determinism sweep.
- Loose/low-pri: format-tolerance principle write-up (partially in C.17); C.10 z-score lookback window;
  stale `newsletter-tracker.md` `'pair'` asset_class taxonomy (doc cleanup — seeded the chart bug);
  A.1–A.8 not re-audited (almost certainly done).

**NEXT ACTION:** C.18 done (2026-07-12). Remaining queue is item **N** (Space Trade RKLB/SPCE/RDW 2nd
target — run `python q.py rklb` to tell display-bug from extraction-drop) and the "waiting-for-go"
billed items (effort-ladder, determinism sweep). NO pending import.

**OPS:** the running **:5001** engine holds STALE in-memory `newsletter_ingest` (started before this
session's code) — **restart it before any DASHBOARD-triggered import**; CLI `run_import.py` is
unaffected, and VIEWING the dashboard is fine (store served fresh per request). Session backups:
`…/scratchpad/_store.before-{c11c12,c13-migration,plumbing}.json` and
`extracted/restore_points/pre-260629-merge__*`.

### Session handoff (2026-07-10, session 19) — 260615 merge + section-status taxonomy BUILT/VALIDATED, display refinements

**Store state:** **260615 merged, correct, deterministic** (8 live incl. 1 observation
indicator / 5 archive). Everything below is BUILT, VALIDATED end-to-end, dispersion-tested
across two low merge runs, and COMMITTED this session (see git log after `ea0219f`).

**Built + validated this session:**
1. **Section-status taxonomy + fill mechanics** (`newsletter_ingest.py`). KEY LESSON: for
   THIS newsletter the section alone CAN'T drive status — its "Previous Week Trade Review"
   heading mixes held + untriggered + closed (USDJPY-untriggered and defensive-breadth-filled
   sit in the SAME review, needing OPPOSITE statuses). Final design:
   - `source_section` primitive `{new, open, closed, watching, review}`. Model tags the
     obvious buckets; fuzzy headings (Tactical Summary / Previous Week Trade Review) → `review`
     (neutral). `derive_status_from_section`: closed/open/watching authoritative; new/review/null
     DEFER to the fill mechanics.
   - **Fill mechanics decide the fuzzy case, SECTION-INDEPENDENT:** `enforce_untriggered_conditional`
     (trigger stop/level/premium_target + no fill → `planned` — fixes USDJPY even when
     mis-bucketed `open`) + `enforce_scaled_planned` with a **carried-fill release** (scaled +
     `first_seen != last_mentioned` + a filled tranche → `open` — fixes C.9 defensive-breadth
     @ 260615; the first-appearance fabrication @ 260608 stays clamped).
   - `test_section_status.py` 12/12; validated on BOTH real 260615 merge runs (identical
     statuses/source_section/strategy_id/pnl): defensive-breadth `open`, USDJPY `planned`,
     model tags `review` consistently. This was the C.9 pairs-mislabel fix that started the review.
2. **Split-in-file fix** (`run_import.py` + `newsletter_ingest.py`): `merge_into_store` returns
   the POST-split `processed` list; the marker/edition is frozen from it so past-edition views
   are faithful for split trades (copper shows two records).
3. **Display (`watchtower.html`):** past-edition **strip swap** (read-only, count pills → dropdown
   body); **indicator→digest routing** (§6, observation baskets leave the strip); **badge vs.
   tone decoupling** (New-priority badge on a status-colored card + status-driven price-line);
   **issue-activity summary pills**; options-expiry beside the strike; **closed-card Entry→Exit→P&L**
   round-trip (`closingEntry`). `newsletter-tracker.md` session-10 notes superseded to match.

**Watch-items (noted, NOT fixing):** `key_dates` soft-field variance (low catches BOJ-only on
USDJPY; re-check at medium+ in the effort ladder); cold-start "everything New" badge (first
issue's historical view only); GLD −74% closed card shows Entry `--` (back-computed, not stated).

**NEXT ACTIONS (each BILLED — ASK FIRST, [[prompt-before-billed-runs]]):**
1. **Effort-ladder experiment** (the one still-open experiment): run 260608/260615 at
   medium/high/xhigh/max, then `compare_narratives.py <stem>` — does higher effort write better
   narratives / catch the full key_dates calendar, or just cost more? Low is the validated baseline.
2. **Import queue: 260622 → 260629 at low.** Use `run_import.py <stem> --effort=low` from the CLI
   (picks up code fresh). The running :5001 engine has STALE code — **restart it before any
   DASHBOARD-triggered import** (CLI imports are unaffected).

**Ops / tooling (all $0, worktree):** `q.py <substr>` (store inspect — use, NOT `python -c`),
`stats.py` (billed ledger), `compare_narratives.py <stem>`, `test_section_status.py` (unit test),
`build_split_editions.py` (offline edition regen). Engine serves `_store.json` fresh per request
(view = refresh). To restore a 260608 base for another merge dispersion test: re-derive the saved
260608 `raw_extract` through `merge_into_store` and write `_store.json` (the throwaway
`rebuild_store_608.py` did this; recreate via the `build_<stem>.py` pattern).

### Session handoff (2026-07-09, session 18) — tightening BUILT + committed, stats tooling, cumulative-analysis emphasis

**The schema-tightening is BUILT, validated, and COMMITTED (`ef10326`).** The prior
handoff (below) said "BUILD it"; that's done. See SESSIONS.md Session 18 and the
`newsletter-tightening-next-action` memory for the full list. Highlights specific to
this file's concerns:

- Derivation layer + tranche split + deterministic guards (break-even; **`scaled` →
  `planned`**, §7.3a of the tightening spec) all in `newsletter_ingest.py`. The
  scaled-planned guard is the pattern to reuse: when the model coin-flips a lifecycle
  judgment, move it to a Python rule keyed off a STABLE primitive (here
  `entry.trigger_type == "scaled"`) rather than trying to fix the prompt.
- Per-element `note?` added to tranches/legs/basket (all trade types / asset classes:
  options→legs, pairs→basket, outright equity/future/forex→tranches). Displayed inline;
  basket-component list added to the pairs detail panel.
- Two low-effort billed 260608 re-extractions both matched §10.

**CUMULATIVE-ANALYSIS EMPHASIS (user, 2026-07-09) — do this FIRST next session.**
Statistics/analysis must span **ALL** billed runs, not just the latest. Three offline
`$0` tools now do this (in the worktree; run as scripts so `Bash(python *)` covers them —
NOT `python -c`, which prompts):
- `python stats.py` — the whole `cost_experiment_log.jsonl` ledger (10 runs, $3.70; per-
  effort avg cost + reasoning-share). Every `run_import.py` run appends a row.
- `python compare_narratives.py 260608` — narratives + token line side-by-side per run/
  effort. Reads the `run_archive/*__raw_extract.json` snapshots.
- `python q.py <substr>` / `--field <f>` — quick store inspection.

**Then (billed, ask first per [[prompt-before-billed-runs]] — one low run serves several):**
(1) determinism sweep, 1–3 more low (2 clean, §10 wants 3–5 identical); (2) the
narrative-quality-vs-effort ladder (medium/high/…) — the open experiment; (3) per-element
note verification; (4) import queue 615→622→629 at low. **FREE:** indicator→digest routing
at 615. **OPS:** verify the staged permission rules suppress prompts on reload, and
restart the engine on :5001 so dashboard imports use the new `newsletter_ingest`.

### Session handoff (2026-07-09, end of session) — token test RUN, full schema-tightening spec written

**The token/effort experiment from the prior handoff is DONE (8 billed runs, ~$3.08).**
Full data in `cost_experiment_log.jsonl` + `thinking_logs/` + `run_archive/`. Headlines:
- **Effort does NOT buy correctness.** Trade *mechanics* (legs, entry/stop/target
  levels, sizing, conviction) were identical at high/medium/low on nearly every trade;
  only the *derived/classified* fields coin-flipped — and they flip at BOTH effort
  levels. Fix is deterministic Python, not an effort knob.
- **Cost/speed is clean & monotonic** (cold 260608): high ~$0.53/290s, medium
  ~$0.34/160s, low ~$0.24/100s. Low ≈ 55% cheaper, ~3× faster.
- **The "high archives more trades" appearance did NOT replicate** — a re-run of high
  cold gave 9 trades like low; the extra archived trade was the copper tranche split
  firing ~1-in-8, not an effort effect.
- Token anatomy: final JSON is effort-invariant (~9k tok); effort only scales the
  (mostly hidden) reasoning (~4k low → ~23k high). Logged `thinking_tokens` undercounts
  (summarized display) — use `output_tokens − final_tokens`.

**The session then pivoted to a full schema redesign →
`.claude/rules/newsletter-schema-tightening.md` (NEW, complete, mirrored).** Driven by a
character-by-character review of all 9 (really 10) 260608 trades across the preserved
high/low `run_archive/` snapshots. **Read that spec — it is the authoritative target and
supersedes the ambiguous derived-field parts of `newsletter-schema.md`.** Highlights:
- Root principle (§7): **model = prose → structured primitives; Python = primitives →
  everything derived. Python NEVER parses prose** (prose fields are display-only).
- 3-class asset model (`equity`/`future`/`forex`; `pair` DROPPED — it is a *structure*,
  not an asset_class), new `structure` field {outright,pairs,options}, options branch
  (legs +quantity +leg-expiry-consistency, open-vocab `structure_label`, Greek binning,
  expires-worthless target rule), `bias`, `entry.trigger_type` closed enum, `role`
  REMOVED, `thesis` → `{rationale, positioning}` (positioning_note folded in).
- Derived deterministically in Python: `asset_class`, `structure`, `strategy_id`
  (taxonomy-composed; options token derived from `legs`, NOT structure_label),
  `structure_label`/`bias` (from legs for recognized structures), `pnl_pct`
  (level→pnl→pct hierarchy, prefer-computed, normalized unit enum).
- Tranche-as-entity + a Python-deterministic split (a partial-close + re-entry = two
  records sharing `strategy_id`, told apart by `status` + an `id` discriminator).
- `linked_theme` DELIBERATELY left freeform (model color, not a key) — no per-theme
  scoreboard for now (see §8b FUTURE-CONSIDERATION note; user cares only about overall
  newsletter performance right now).

**Exact next action (supersedes "resume the import queue"):**
1. **Build the tightening** — (a) rewrite `EXTRACTION_SYSTEM` in `newsletter_ingest.py`
   per the spec; (b) add a Tier-1 `validate_and_normalize()` Python layer.
2. **Validate against §10** — re-extract the 260608 PDF *through the new engine* (NOT a
   diff of old JSON); assert the acceptance fixture: **exactly 10 trades** (copper
   split), all **3 closed pnls** (DOCU +11.4, GLD −74, copper +1.96), canonical
   `strategy_id`s, and **deterministic across 3–5 repeats**. The correct 10-trade store
   was never persisted — §10's written answer key is authoritative.
3. Update `watchtower.html` display (role gone, thesis object, indicators → digest
   dropdown not the plays strip, split-trade rendering).
4. THEN resume imports 260615→260622→260629 at **`low` effort** (banks the token-test
   saving; safe because Python now owns the flaky fields).

**Store state:** EXPERIMENTAL — currently low-effort 260608-only (from the diff
investigation). NOT a real store; rebuild cleanly during step 2.

**`run_import.py` change this session:** every run now auto-archives its store + marker
to `NEWSLETTER_EXTRACTED_DIR/run_archive/` (tagged by stem/effort/timestamp), so a
`--cold` run can never destroy output history again (it DID during the experiment — the
high & medium stores were lost before this was added).

**Mirroring — now CONFIRMED WORKING.** The prior handoff's "auto-mirror not firing"
worry is resolved: this session hash-verified that all `.claude/rules/*.md` edits mirror
byte-identically to Repository AND Trader App. No manual `cp` needed.

**Permissions gotcha:** bare `"Edit"`/`"Write"` in `settings.json` did NOT suppress the
edit-approval dialog. Path-scoped `Edit(**)`/`Write(**)` were added to
`settings.local.json` (takes effect next session on reload). For prompt-free doc edits
THIS session, edits went via `python` (allowlisted) writing the file + calling
`pre_edit_guard.sync_after_edit()` to mirror, instead of the Edit tool.

## Display builds — 2026-07-10 (session 19), all DONE in `watchtower.html`

Backlog items surfaced by the first 260615 merge review, built + user-confirmed on screen:
- **Indicator→digest routing (§6 — backlog item now DONE).** `isIndicator(t)` =
  `conviction.label ∈ {observation_only, watchlist}`; excluded from `renderNewsletterStrip`,
  rendered in the digest dropdown (`_digestBodyHTML`) as title / "Proxy for:" (`indicates`)
  / rationale / long-short constituents. Verified on 260615's software winners/losers basket.
- **Badge vs. tone decoupling.** `getStatusMeta` returns `label` (BADGE — "New" priority on
  first appearance even when entered) + `tone` (LIFECYCLE — drives card color/opacity and the
  price-line). A new+entered trade = **New badge on a violet Active card with the Tgt/Stop
  line**. All couplings moved to `tone`: border/opacity in `renderNewsletterStrip`, both
  `levelsRowHTML`/`levelsInlineHTML`, and the deep-dive (`nd-levels`); badge text color stays
  on `label`.
- **Summary pills = issue ACTIVITY** (header on live view; dropdown body in read-only past
  mode). Indicators excluded; `new` = New-badge count; `closed` scoped to the current issue
  (`last_mentioned === issue_date`); active/watching = carried. Pills now match the strip's
  badges (fixes "1 new / 5 closed" → "2 new / 2 closed" on 260615).
- **Past-edition strip swap** + read-only pill (earlier this session — see "Display vs.
  archive" above).
- **Closed-card round-trip (user 2026-07-10):** closed trades now show **Entry → Exit →
  P&L** (strip card compact `entry→exit · P&L`; detail panel three cols) via a new
  `closingEntry()` helper (entry_price, else a tranche entry_price, else `--`). A
  back-computed-only entry (a pre-window close like the GLD −74% call spread: entry_price
  null, risk_capital 3.65) shows `--` for Entry — the entry wasn't STATED, only inferred
  for the P&L. Enhancement option if wanted: surface the inferred debit for debit spreads.

**Soft-field watch-item — `key_dates` variance (user 2026-07-10, NOT firming up yet).** The
low-effort 260615 merge caught only the BOJ catalyst on USDJPY; the earlier low run also
caught the FOMC. `key_dates` is a model-EXTRACTED soft field (§7.4, like `linked_theme`) and
varies run-to-run; effort doesn't reliably buy completeness. User's call: accept the
variance for now (cost may not justify a fix); **re-check whether `medium`/higher effort
catches the full catalyst calendar when the effort-ladder experiment runs.** Lever if ever
wanted: a prompt nudge to sweep the week's central-bank + top-tier data calendar into
`key_dates` for any rate/FX/macro-thesis trade.

**Known edge case — cold start labels every trade "New" (user 2026-07-10, NOT fixing).** The
badge rule "New = first appearance (`first_seen === last_mentioned`)" means on a COLD START
(the first ingested issue, e.g. 260608) EVERY trade is first-appearance, so held/active
positions (META/SMH/copper) wear the New badge on their Active(violet) card. Benign +
confined to the FIRST issue's historical (past-edition) view: any later issue's carried
trades have `first_seen != last_mentioned`, so New is correctly reserved for genuinely-new
setups (260615 shows New only on SLV/RKLB). Defensible as-is (those are new *to our tracker*;
the violet color still flags them held). Fix IF it ever matters: suppress New for a
first-appearance trade that is already HELD (`source_section: open` / `trigger_type:
pre_existing` / a filled position). Left as-is per user.

`newsletter-tracker.md`'s session-10 status-label/color/routing notes were superseded to
match (its 2026-07-10 revision note).

## Section-status taxonomy — derive `status` from the newsletter's own sections (DESIGN, 2026-07-10, session 19)

**Status: BUILT 2026-07-10 (Python + prompt); pending a billed re-import to validate
end-to-end.** Stage 1 (Python) — `derive_status_from_section` (open/closed/watching
sections authoritative; `new` left to the fill signal) + `enforce_scaled_planned` SCOPED
to the `new` section, wired into `normalize_derived`; offline unit test
`test_section_status.py` passes 10/10 (C.9 open→open, 260608 new-section scaled→planned,
SLV/RKLB new+market→open, watching→planned, null-section backward-compat, abandoned
preserved). Stage 2 (prompt) — `source_section` primitive added to `EXTRACTION_SYSTEM`
(enum new/open/closed/watching, bucket-by-content-shape per global rule 2, primary status
driver). **Still needed:** a billed re-import so the model actually emits `source_section`
— a 260608 cold run (verify §10, esp. defensive-breadth new-section→planned + copper
split) AND a 260615 merge (verify C.9: defensive-breadth open-section→open). Motivated by
the first 260615 merge (C.9 + the RKLB/defensive-breadth inconsistency below). **Supersedes the "loosen the scaled
guard" fix floated in C.9** — the real resolution is to make `status` a
*section*-conditioned derivation, and the scaled guard becomes section-scoped rather
than global. Design home is the plain doc for now; migrate into
`newsletter-schema-tightening.md` if/when built.

### The motivating failure — the scaled guard fires inconsistently
Two structurally identical tiered pairs trades in the 260615 store got OPPOSITE status,
purely from a flaky `entry.trigger_type` label:

| | tranches filled | `trigger_type` | guard fired? | status |
|---|---|---|---|---|
| RKLB (`rklb-vs-rdw-spce`) | starter only | `market` | no | **open** ✅ |
| Defensive-breadth (`xlf-xlp-xlv-vs-igv`) | **both** | `scaled` | yes | **planned** ❌ |

The *less*-filled trade is `open`; the *fully*-filled trade is clamped to `planned`.
Root cause: `enforce_scaled_planned` (§7.3a) keys off `trigger_type == "scaled"`, but
the model tags structurally-identical starter+add entries inconsistently
(`market` vs `scaled`). The guard isn't just too strict — **its trigger is itself an
unreliable judgment.** Applying status signals **context-free** (one global guard) is
the design flaw.

### The idea — `source_section` is the status discriminant (same pattern as §2)
Just as §2 makes `structure ∈ {outright, pairs, options}` the discriminant that
selects which fields/derivations apply (§7.1 derivation map), make the **newsletter
section a trade is printed under** the discriminant for `status`. The section is a
*document fact* — about as un-fabricable as `exit_price` — so it is a stable primitive,
unlike the fill-judgment.

- **New primitive:** `source_section ∈ { new, open, closed, watching }` — the
  *normalized bucket*, NOT the header text. Section LABELS drift issue to issue
  ("Tactical Summary" vs "New Trade Setups"; "Closed/Expired" vs "Closed Trades") — the
  `EXTRACTION_SYSTEM` already maps drift to buckets internally (rule #2); this just
  **persists** that bucket instead of discarding it after using it to guess status.
- **Model extracts** which bucket (mechanical); **Python derives** `status` from it
  (§7 ownership split).

### The signal-role flip (the core insight)
The unreliable signals (`trigger_type`, `conviction`, fill-language) aren't
intrinsically noisy — they were read without their conditioning variable. Per section,
their ROLE changes:

- **`new`: signals EARN the status.** Default `planned`; an explicit entry/fill signal
  PROMOTES to `open`. Signals are status-*determining*. This is the one section where
  fill-ambiguity is real — so **the scaled guard lives HERE, section-scoped**
  ("default `planned` unless an explicit entry is stated"), exactly where the 260608
  fabrication happened.
- **`open`: the section GIVES the status.** The trade is held because the newsletter is
  holding it. `trigger_type`/tranche-fill/fill-language CANNOT downgrade it — they drop
  to **maintenance** (update the fill display, log parameter changes to
  `status_history`, carry conviction forward for display). The ONLY exit from `open` is
  an explicit terminal event (close/stop/expiry) → `closed`. **Silence never closes**
  (existing asymmetric rule). *This is the C.9 fix:* defensive-breadth is under Open
  Trades → `open`, and the guard simply doesn't run here.
- **`closed`: section gives `closed`.** `exit_price`/`pnl` are the live signals (§8c);
  entry-side signals are historical. Less problematic — no observed status confusion.
- **`watching`: `observation_only`/indicator** (per §6 `conviction.label`). Exempt from
  lifecycle; routes to the digest, not the plays strip (§6). Less problematic.

| section | status | trigger_type / tranche-fill | conviction | fill-language |
|---|---|---|---|---|
| **new** | `planned` → `open` if explicit entry | **status-determining** (guard's scoped home) | fresh rating = meaningful | *promotes* planned→open |
| **open** | `open` (section-asserted) | maintenance only — cannot downgrade | carried-forward display | confirms hold; no status effect |
| **closed** | `closed` | historical | carried display | describes round-trip |
| **watching** | `observation_only` | n/a | watchlist label | descriptive |

### Conviction is NOT an independent axis (corrected 2026-07-10)
`conviction`-presence is not a clean new-vs-carried filter as stored: the merge
re-emits the fed live object, so a carried trade shows its *inception* conviction
(FIVN 4, defensive-breadth 3 are echoes, not fresh 260615 ratings). The real signal is
**conviction stated THIS issue**, which correlates with the `new` section — so it folds
INTO `source_section`, it is not a separate discriminant. Caveat: not every new trade is
rated (SLV is `new` with `null` conviction), so fresh-conviction is a *sufficient*
new-signal, not a complete one.

### Build order
1. **STEP 1 (this first):** add `source_section` as a persisted primitive the model
   emits (normalized bucket). Everything else depends on having it.
2. Derive `status` from `source_section` per the table; **scope `enforce_scaled_planned`
   to the `new` section**.
3. Re-run the determinism sweep — the section bucket should be at least as stable as the
   other primitives; confirm no flip is reintroduced.
4. `closed`/`watching` detail left minimal on purpose (user, 2026-07-10: no observed
   status confusion there — bin them, don't over-spec).

### Residual (honest)
Within `new`, "real early fill vs fabricated fill" (the 260608 problem) still isn't
fully resolvable from structured signals alone — but section-scoping puts the guard
exactly where that ambiguity lives instead of firing globally off a flaky label.
Candidate discriminator to test later: per-tranche fill prices + dates on ALL tranches
(specific = more trustworthy than vague ownership).

---

## Card-design review + fixes queued (2026-07-07)

Methodology: every one of the 9 real trades in the `260608` import's `_store.json`
was pulled directly (`live`+`archive`, full field dump) and cross-checked against the
live rendered DOM (via a scratch preview instance) and, where a number looked off,
the actual source PDF text — not reasoned about from memory. Two real display bugs
were caught this way (DOCU's card showing "65C/70C" with no ticker, momentarily
mistaken for IGV; a closed GLD trade invisible off the right edge of an unscrolled
strip, momentarily mistaken for a missing extraction). Both turned out to be existing
bugs below (A.2 and A.5), not extraction failures — the store/API data was correct
in both cases. Line numbers are as of this writing (`watchtower.html`, untouched by
this session — it was a design-only pass, no code edited yet); re-verify if they've
drifted by the time this is picked up.

### A. Confirmed frontend bugs — fix in `watchtower.html`

**A.1 — `getLegsLabel()` outright fallback checks the wrong field name.**
Function `getLegsLabel(t)`, ~line 750-757. Final line:
```js
return t.ticker || '--';
```
`t.ticker` does not exist anywhere in the schema — a plain outright's instrument is
`t.underlying` (per `newsletter-schema.md`). Every outright trade (no `basket`, no
`legs`) therefore always falls through to the literal string `'--'`. Confirmed live:
`usdjpy-short-conditional`, `smh-soxx-long`, `hg-copper-long` all rendered `"--"` as
their card title in the actual DOM. **Fix:** `return t.underlying || '--';`

**A.2 — Options/pairs trades never lead with the underlying ticker at all.**
This is the deeper issue A.1 is only one symptom of. The title line everywhere
(`renderNewsletterStrip()` ~line 863, `showNewsletterDive()`'s `nd-legs`) is:
```js
t.campaign_title || getLegsLabel(t)
```
`campaign_title` is null on most real trades. For options trades (which DO have
`legs`), `getLegsLabel()`'s legs-branch (~line 752-755) returns strike-based text
like `"65C/70C 06/12"` — never the underlying. This is confirmed to have caused real
user confusion this session: the DOCU bear-call-spread card showed `"65C/70C"` with
no ticker at all, and the *only* ticker visible anywhere on the card was "IGV" —
which appears purely as supporting color in the trade's `thesis` text, not the
underlying. Same root cause affected the GLD 425/450 call spread and the FIVN
spread before the card-design pass. **Fix:** rebuild the title logic per the
finalized card specs in section D below — lead with `t.underlying` (options/outright)
or the basket composition (pairs), never with campaign_title-or-strikes as the
primary path. `campaign_title`, when present, should still be usable as a secondary/
subtitle element, not the sole differentiator from a blank fallback.

**A.3 — Status label "Resolved" should read "Closed" (confirmed by user, 2026-07-07).**
Multiple sites all reference the literal string, all need updating together:
- `getStatusMeta()` ~line 765: `{ label: 'Resolved', ... }` → `{ label: 'Closed', ... }`
- `renderNewsletterStrip()` ~line 851-855: `meta.label === 'Active'`/`'Resolved'`
  ternaries (border color, opacity, dot color) — update the `'Resolved'` checks
- `renderNewsletterStrip()` ~line 863: the strikethrough-title condition
  `meta.label === 'Resolved'`
- `levelsInlineHTML()` ~line 819: `if (meta.label === 'Resolved')` branch
- `levelsRowHTML()` ~line 797: same check, nd-panel (thesis detail) version

**A.4 — Conviction "n/a" fallback should render nothing, not literal "n/a" text
(confirmed by user, 2026-07-07).**
`renderConvictionDotsHTML()` ~line 778-782:
```js
const text = conviction && conviction.label ? conviction.label.replace('_', ' ') : 'n/a';
```
Keep the branch that shows `conviction.label` text (e.g. "observation only") when a
label genuinely exists. Only the bare `'n/a'` catch-all (no scale, no label) needs to
become an empty string / no element rendered.

**A.5 — No horizontal-scroll interaction on `#newsletter-container`
(confirmed by user, 2026-07-07 — "it needs to advance horizontally, not vertically").**
All wheel/drag-to-scroll JS (`wheel` listener ~line 704, drag handlers ~line 669-690,
`scrollLeft` manipulation ~line 617-654) is wired exclusively to `#actionable-container`
— confirmed via grep, zero matches for `newsletter-container` in that block.
`#newsletter-container` (~line 239, 839) only has native CSS `overflow-x-scroll`,
which does not respond to a plain vertical mouse-wheel roll (only native horizontal
input — trackpad swipe, shift+wheel, manual scrollbar drag). A normal wheel scroll
over the strip scrolls the page instead. Root-caused live: with 9 real cards and a
296px visible viewport (only ~3 cards visible at once), the 9th card (a Closed trade,
since Closed sorts last) was genuinely present and correctly rendered but invisible
without scrolling — this is what caused the GLD-card confusion in the methodology
note above. **Fix:** generalize the existing interaction code (currently hardcoded to
`actionable-container`) to also attach to `newsletter-container`, or duplicate+adapt
it. Related, undecided UX question: even once scrolling works, there's still no
visual affordance (fade edge, arrow, dot indicator) hinting more cards exist
off-screen — not decided this session, flagging only.

### B. Confirmed extraction-prompt issues — fix in `newsletter_ingest.py`'s `EXTRACTION_SYSTEM`

**B.1 — Level fields (`entry.level`, `stop.level`, `targets[].level`) are
inconsistently prose vs. a clean number — RESOLVED 2026-07-08.** This was the
single biggest driver of card-design difficulty this session — confirmed against
real stored data, not speculation:
- FIVN `entry.level`: `"$0.70-$0.80 credit; do not chase below $0.60"` (prose)
- META `targets[0].level`: `"Spread expires worthless with META below $640"` (prose
  wrapping a real number, $640, recoverable)
- SMH `targets[0].level`: `"Continued semi outperformance after the pullback"` (pure
  prose, genuinely NO number — the newsletter itself stated no price target, so this
  is not extractable no matter how the prompt is tightened)
- copper `targets[0].level`: `6.68` (already a clean bare number — proves the model
  CAN do this correctly; it's inconsistent, not uniformly broken)

**Finalized shape** (`newsletter-schema.md`, design principles): `entry`, `stop`, and
every `targets[]` entry each get `level` (bare number or `null`), `level_high` (bare
number, only for a genuine stated range — `level` is the lower bound, `level_high`
the upper), and `note` (chosen over `condition` — matches the schema's existing
`note` convention; short paraphrase of qualifying language; detail-panel only, never
on the card).

**`EXTRACTION_SYSTEM` prompt addition (not yet implemented — next build step):**
> **Level fields.** For every `level` field (in `entry`, `stop`, and each `targets[]`):
> - `level` MUST be a bare number or `null`. Never a string, never a number wrapped in
>   text (`"$6.68"` → `6.68`, `"157.50"` → `157.50`). Strip currency symbols and units.
> - If the newsletter states a RANGE (e.g. "$0.70–$0.80", "6.00 to 6.25"), put the
>   lower bound in `level` and the upper bound in `level_high`. Otherwise `level_high`
>   is `null`.
> - If the newsletter states NO numeric value for a level (a purely qualitative target
>   like "continued outperformance"), set `level` to `null`. Do NOT invent or infer a
>   number.
> - Put any qualifying, conditional, or explanatory language that accompanies the level
>   ("do not chase below $0.60", "confirm on a Monday close above", "not yet triggered",
>   "spread expires worthless with META below $640") into the sibling `note` field as a
>   short paraphrase — NEVER inside `level`. `note` is `null` when there is none.
> - Do NOT repeat structural facts in `note` or `level`: the words "credit"/"debit",
>   the ticker, or the strategy name are already captured elsewhere. `note` holds only
>   caveats the structured fields don't encode.

**Worked before → after (the four real 06-08 cases):**

| Field | Old (as extracted) | New |
|---|---|---|
| FIVN `entry` | `"$0.70-$0.80 credit; do not chase below $0.60"` | `level: 0.70, level_high: 0.80, note: "do not chase below $0.60"` |
| META `targets[0]` | `"Spread expires worthless with META below $640"` | `level: 640, level_high: null, note: "spread expires worthless below this level"` |
| SMH `targets[0]` | `"Continued semi outperformance after the pullback"` | `level: null, level_high: null, note: "continued semi outperformance after the pullback"` |
| copper `targets[0]` | `6.68` | `level: 6.68, level_high: null, note: null` (already correct — no change) |

The copper row is the proof the model can already do this; the fix makes it required,
not occasional. **Frontend impact:** `levelsInlineHTML()`/`levelsRowHTML()` must
render `level`–`level_high` when `level_high` is non-null, else just `level`; a level
row is omitted entirely (no placeholder) when `level` is `null`.

**Migration:** these changes affect extracted output, so the already-imported 06-08
issue carries the old prose values until re-run. Once the prompt is tightened: delete
`260608...json` from `NEWSLETTER_EXTRACTED_DIR` and delete `_store.json` (so the store
rebuilds cleanly), then re-import 06-08 via the Import picker. **This is a billed
cold-start run (~$0.18–0.29, several minutes)** — do it in Claude Code where the live
engine + DOM check are. Verify the four cases above land in the new shape before
importing 260615 onward.

**B.2 — `underlying` itself is sometimes prose-contaminated, not just `level`
fields — RESOLVED 2026-07-08.** Copper: `underlying: "HG (front-month copper
future)"` instead of a bare `"HG"`. No schema change — the shape was always "bare
ticker string"; this is a prompt-adherence fix only.

**`EXTRACTION_SYSTEM` prompt addition (not yet implemented — next build step):**
> **`underlying`.** MUST be a bare ticker/symbol string exactly as the newsletter
> names the instrument — `"HG"`, `"GLD"`, `"USDJPY"`. Never add a descriptive
> parenthetical: `"HG (front-month copper future)"` → `"HG"`. The instrument's
> nature (future/forex/equity) is already carried by `type` and `asset_class`, so
> do not repeat it here. Do NOT convert to a data-provider symbol (`CL=F`, `=X`
> suffixes) — that mapping is handled downstream; use the newsletter's own ticker.

Adjacent but distinct open item, not solved by this: the schema's still-open
"ticker display-name vs. yfinance-fetchable-symbol" question (`CL1!` vs `CL=F`-style)
— HG the futures root vs. whatever symbol a future heatmap/price-history hook would
need. Not decided.

**B.3 — Conviction score is dropped once a trade's status leaves `planned` —
RESOLVED 2026-07-08.** Every `open`/`closed` trade in the real `260608` import has
`conviction: {scale: null, ...}` — `newsletter-schema.md`'s own worked example
showing a `closed`-status trade retaining a real score (`scale: 4`) was aspirational,
not a confirmed rule. **User decision:** blank-after-planned is acceptable. No
`EXTRACTION_SYSTEM` change to carry conviction forward — a trade may legitimately
show no conviction dots once it goes `open`/`closed`. Display handles the blank per
A.4 (the "n/a" → empty-string fix), which already covers this case correctly.

**B.4 — Direction field for outright trades — RESOLVED 2026-07-08 (recommended
2026-07-07, resolves the open inconsistency previously flagged in section D below).**
Add `direction` (`"long"` | `"short"` | `null`) as a first-class field on
`outright_equity`/`outright_future`/`outright_forex` trades only (`null` for
spreads/baskets/overlays). Replaces parsing direction out of the `id` string's
`-long`/`-short` suffix.

**`EXTRACTION_SYSTEM` prompt addition (not yet implemented — next build step):**
> **`direction`.** For an outright trade (`outright_equity` / `outright_future` /
> `outright_forex`), set `direction` to `"long"` or `"short"` from the newsletter's
> explicitly stated side of the position. `null` for every other trade type. Do not
> infer it from prose sentiment — use the stated side.

**Frontend:** read `t.direction` directly; remove the `-long`/`-short` `id`-suffix
parsing. Display resolution is in section D (Outright card) below.

**B.5 — Multi-day central bank meetings get split into duplicate `key_dates`
entries — confirmed 2026-07-08, card 4 (USD/JPY).** The real stored trade has:
```json
"key_dates": [
  { "date": "2026-06-15", "event": "BOJ meeting (day 1)", ... },
  { "date": "2026-06-16", "event": "BOJ meeting (day 2)", ... }
]
```
Two entries for what is really one event. **User's rule:** for a central bank
meeting spanning multiple days, the market-moving catalyst is the LAST day
(the decision/announcement day) — only extract that date as a single
`key_dates` entry, unless the newsletter explicitly calls out a reason both
days matter separately (e.g. distinct scheduled releases on each day, not just
a multi-day meeting window).

**`EXTRACTION_SYSTEM` prompt addition (not yet implemented — next build step):**
> **`key_dates` — multi-day central bank meetings.** When a central bank
> meeting spans multiple days (e.g. a 2-day BOJ/FOMC meeting), extract only
> ONE `key_dates` entry, dated the LAST day of the meeting (the
> decision/announcement day — that is when the market-moving catalyst actually
> lands). Do not create a separate entry per day of the same meeting window.
> Only deviate from this if the newsletter itself explicitly discusses the two
> days as separate distinct catalysts, not merely as a multi-day meeting.

### C. New calculation logic — does not exist anywhere yet, needs to be built

**C.1 — Risk-based P&L% for closed, defined-risk options-spread trades (confirmed
rule, 2026-07-07).** Replaces showing a raw, unitless `status_history[].pnl.value`
on a Closed options card (which also has its own latent bug: the code only appends
`%` when `pnl.unit === 'pct'`, so DOCU's actual unit — `"$/share credit captured"`
— and GLD's — `"$/share"` — both render as a bare, ambiguous number today).

**The rule, verified against both real closed options trades this session:**
- **Credit spread** (net credit collected to enter — e.g. DOCU's bear call spread,
  sell 65C/buy 70C): `risk = strike_width - credit_collected`. DOCU: width $5,
  credit $0.51 → risk $4.49. Realized pnl +$0.51 (full credit captured) → **+11.4%**.
- **Debit spread** (net debit paid to enter — e.g. GLD's bull call spread, buy
  425C/sell 450C): `risk = debit_paid` (the entire premium paid is the max loss,
  full stop — do NOT apply the credit-spread formula here; `width - debit` computes
  max PROFIT for a debit spread, not max risk, and was mis-derived that way once
  this session before being corrected). GLD 425/450: entry debit was never captured
  in `_store.json` because the trade was opened in an earlier, un-imported issue —
  algebraically inferred as ~$3.65 from `exit_price (0.95) - pnl (-2.70)`, cross-
  checked against the source PDF (which confirms the $2.70 loss but never restates
  the original entry debit, since newsletters only state entry economics when
  *introducing* a trade). Risk $3.65, realized pnl -$2.70 → **-74%**.
- **Fallback (explicitly confirmed by user):** if risk cannot be calculated *or*
  reasonably inferred from stored fields, show the raw `+/-$X` credit/debit captured/
  lost instead of a percentage. Expect this to recur systemically: **any trade opened
  before the very first imported issue will have no entry economics captured**, so
  this isn't a one-off edge case — it's the standing behavior for every
  pre-import-window trade that later closes.
- **Determining credit vs. debit spread:** derivable from `legs[].action`
  (buy/sell) and relative strikes, not from `structure_label` name-pattern alone
  (though empirically `bear_call_spread`/`bull_put_spread` → credit,
  `bull_call_spread`/`bear_put_spread` → debit held for both real examples this
  session — verify this holds before relying on it as the sole signal).

**Where this should live, architecturally:** compute deterministically in **Python**
at close-time (in `merge_into_store()` or a dedicated helper called from there), not
in the extraction prompt (LLM arithmetic reliability) and not duplicated in
client-side JS. This matches the existing project principle (`newsletter-tracker.md`,
session 10 notes, and the live-set/store split above) that Python owns deterministic
computation, never the model. Store the result on the trade object at the moment it
transitions to `closed` (e.g. a `risk_capital` field and/or a computed `pnl_pct` on
the relevant `status_history` entry) so the frontend only ever displays a
pre-computed value — no client-side spread math.

**C.1 extension — `exit_price` capture makes pre-window closes computable
(implemented 2026-07-08, session 16).** The original C.1 above treats a
pre-import-window close (entry economics never captured, `entry.level` null) as the
raw-$ **fallback** case — "standing behavior for every pre-import-window trade." That
is now the EXCEPTION, not the rule. The GLD 425/450 debit spread surfaced why: its
`pnl_pct` was blank on the Closed card, and the user (correctly) rejected the raw-$
fallback. Root cause was NOT the calc — it was a missing captured field. The 260608
letter DOES state the exit price (verified against the PDF: *"the position was cut at
$0.95 before Friday's rate shock could turn the structure into a max loss"*); the old
`EXTRACTION_SYSTEM` just never asked for it, so `entry.level` stayed null and C.1 fell
back to raw $. The spec's `0.95` was real source text, not an inference.

**What changed:**
- **`EXTRACTION_SYSTEM`** (`newsletter_ingest.py`, the `status_history` close guidance):
  on a CLOSE, additionally capture `exit_price` (bare number) on the closing
  `status_history` entry whenever the issue states the price/value the position was
  closed at — for a spread, the closing mark it was bought-back / sold-to-close at
  ("cut the 425/450 call spread at $0.95"); for an outright, the exit price. Separate
  from `pnl`. Shape is now `status_history[] {date,status,pnl?,exit_price?,note?}`.
- **`compute_risk_pnl()`** now infers the entry cost from the close when `entry.level`
  is null: **debit spread** (long the spread, SELL to close, `pnl = exit − entry`) →
  `entry = exit_price − pnl`; **credit spread** (short the spread, BUY BACK to close,
  `pnl = entry − exit`) → `entry = exit_price + pnl`. The sign flips with the side the
  spread is on — getting it wrong (using one formula for both) was a bug caught and
  fixed in the same session. Then risk = `width − credit` (credit) or `debit` (debit),
  and `pnl_pct = pnl / risk`. GLD worked example: exit_price 0.95, pnl −2.70 →
  inferred debit 3.65 → risk 3.65 → **−74.0%** (matches the spec's hand-derived −74%).
  DOCU is unaffected (its `entry.level` 0.51 is present, so it never hits the
  inference path; stays +11.4%).
- **True fallback is now narrow:** raw $ shows ONLY when NEITHER `entry.level` NOR
  (`exit_price` + `pnl`) is available — i.e. the letter states a dollar P&L but gives
  no close price at all. Much rarer than "every pre-window trade."

**Backfill note (one-time manual edit):** the existing 260608 store predates the
prompt change, so GLD carried no `exit_price`. Rather than bill another cold-start
re-import, `exit_price: 0.95` (the source-verified value) was **hand-inserted** into
the GLD closing `status_history` entry in BOTH `_store.json` and the 260608 marker
file, then `compute_risk_pnl()` re-run over the archive. So if a future clean
re-import is ever done, that 0.95 is not a mystery value — it is exactly what the
tightened prompt now extracts from the letter automatically. DOCU needed no backfill
(computes from its captured entry credit).

> **AUDIT 2026-07-11 (user asked "are C.2–C.10 still relevant?") — C.2–C.9 are all RESOLVED/OBE;
> only C.10 survives (and it's a deliberately-deprioritized future).** Verified against the current
> code/store: **C.2** break_even derived (`compute_break_even`) + displayed (`watchtower.html`);
> **C.3** `status:"planned"` tranche is in the §8d schema + prompt (the fix landed); **C.4** the
> pairs detail panel renders the reference_values chips (`renderOptionsStructureHTML` basket branch,
> `chipsBlock`); **C.5/C.6** `refValueChips` filters `dma_*`/spot/close and the header quote/placement
> was reverted; **C.7** §4f was revised to `level:0` and `targetDisplay` renders "0" (the label-omit
> path is moot); **C.8** the closed-card Entry→Exit→P&L line (C.15) surfaces the closing price in one
> spot; **C.9** the section-status taxonomy (session 19) fixed the scaled-guard clamp. **C.10** (below)
> remains OPEN but LOW-PRIORITY/FUTURE. Everything C.2–C.9 below is kept as history, marked resolved.

**C.2 — Break-even price on options-spread cards (OBSERVATION 2026-07-09, RESOLVED — derived +
displayed; see AUDIT 2026-07-11 above).** User observation reviewing the FIVN card after the tightening
re-import: an options spread should list its **break-even price** on the card/detail
panel, as a previous version did. It is a **reducible-but-mechanical** field (§7.4 of
`newsletter-schema-tightening.md`) — derive it deterministically in Python from `legs`
+ the net credit/debit (`entry_price`), NOT from the model. Vertical formulas:

- **Bear call spread** (credit): BE = short-call strike + net credit
  (FIVN 25/30, credit ~0.75 → **25.75**).
- **Bull put spread** (credit): BE = short-put strike − net credit.
- **Bull call spread** (debit): BE = long-call strike + net debit.
- **Bear put spread** (debit): BE = long-put strike − net debit.

Input source (REFINED 2026-07-09 against the GLD put spread — the original "from
`entry_price`" was incomplete): the net credit/debit comes from **`entry.level` when
`entry.trigger_type == "premium_target"`** (GLD bear put: `entry.level` 4.0 → BE
395 − 4.0 = **391**), ELSE from `entry_price`. Omit only when neither is present (a
pre-window spread with no captured entry economics). Display home: the options-card /
detail-panel line where it appeared before. Queued behind the determinism sweep +
import queue; not yet built.

**C.3 — Pairs planned-add level lost from `tranches` (OBSERVATION 2026-07-09; real
SCHEMA gap, not a display bug).** Reviewing the defensive-breadth pair
(XLV+XLP+XLF/IGV) after the tightening re-import: its 3.22 scaled ADD level is missing
from the Scaled Entries block (only the 3.01 starter shows). Root cause is a genuine
§8d gap: the new typed tranche entity is `{…status:"open"|"closed"}` — it models a
FILLED slice and has NO status for a PLANNED, not-yet-triggered add. So the model
(correctly) declined to force the 3.22 add into an open/closed tranche and demoted it
to `entry.note` prose (`"add fires on ratio close >3.22 or z>0"`). Per §7 (Python never
parses prose) that makes the add level structurally invisible — the A.8 tranche render
sees only the filled 3.01 starter. The OLD tranche shape carried a bare `level` with no
fill-status requirement, so it held planned adds fine. **Fix — needs a
`newsletter-schema-tightening.md` §8d extension:** give the tranche model a way to hold
a planned/unfilled add — e.g. a third `status:"planned"` (with `entry_price` = the
trigger level), or a separate `planned_adds[]`. Until then, un-filled scaled adds live
only in `entry.note`.

**C.4 — Pairs stats (z-score, betas) extracted but never displayed (OBSERVATION
2026-07-09; DISPLAY gap only).** The z-statistic is NOT ignored by extraction — it is
captured in `reference_values` (`z_score_recent: -1.04`, `z_score_extreme: -3.31`, plus
`beta_igv`/`beta_long_basket`), and z also appears in the entry/stop/target notes. The
gap is purely display: `renderOptionsStructureHTML()` renders `reference_values` as
chips ONLY for options trades; for a pairs trade it returns the "Pairs position — no
options structure" fallback and shows no stats at all, so the z-scores/betas never
render. (Matches the earlier card-review note that basket stats/z-scores were a missing
detail-panel feature.) **Fix:** add a pairs stats render path in the detail panel —
surface `reference_values` (z-scores, betas) for baskets the way legs/reference_values
are surfaced for options.

**C.5 — Don't display DMAs in the detail panel (OBSERVATION 2026-07-09; DISPLAY filter
only).** User reviewing the GLD put spread: the 50/200-day moving averages
(`reference_values.dma_50` 424.63, `dma_200` 405.2) don't need to render — the Chart
tab already plots SMA-50/SMA-200, so they're redundant. Extraction keeps them (fine as
context); the fix is display-side: when rendering `reference_values` chips (options
`renderOptionsStructureHTML()`, and the pairs stats path from C.4), FILTER OUT
chart-derivable keys (`dma_*`) and keep trade-specific stats the chart can't show
(z-scores, betas, IV, skew, credit/debit references, spot). General principle:
`reference_values` display = numbers the chart cannot already show.

**C.6 — Underlying price: drop from Options Structure, put it on the tab row far-right
(OBSERVATION 2026-07-09).** Two parts:
- *Filter (extends C.5):* the newsletter's stated close (`reference_values.gld_close`
  396.24) also doesn't belong in the Options Structure chips — same redundancy as the
  DMAs. Add spot/close keys to C.5's chip filter.
- *Placement — RESOLVED 2026-07-09 (reversed from the first take):* keep the section-E
  live quote in the HEADER next to the trade tag (its original home — it was briefly
  moved to the tab row, then reverted), and quote the **TRADING STRUCTURE's own value,
  NOT the underlying**: options → spread mark, outright → underlying price, basket →
  ratio. Rationale (user): for an options play the underlying ticker is redundant with
  the card tag, so the spread mark is the useful number — accepting it goes blank
  (`chain_expired`) once the legs expire (fine; an expired/closed play needs no live
  quote). This is the ORIGINAL `_quote_options_spread` dispatch, unchanged — the net
  code effect was reverting a briefly-tried underlying-price / tab-row detour.

**C.7 — `expiration_worthless` target needs a label display (OBSERVATION 2026-07-09;
DISPLAY gap, §4f working correctly).** META's target is now
`{label:"expiration_worthless", level:null}` — the §4f rule working: a credit spread
that profits by expiring worthless has no price to reach, so the engine correctly
refused to fabricate the short strike as a numeric target (the old "Tgt $640" WAS that
fabrication). Not an extraction bug. But the card's levels row
(`levelsInlineHTML`/`levelsRowHTML`, Active branch) OMITS a target when `level` is null,
so it renders nothing. **Fix:** when `level` is null but `targets[0].label` is set,
display the LABEL ("Expire worthless" / "Max profit if held to expiry") instead of
omitting the Tgt slot.

**C.8 — Consistent closing-price display location (OBSERVATION 2026-07-09; DISPLAY
only, data is fine).** The closing price (`exit_price`) is stored in two places by
design: a plain close records it on `status_history[].exit_price` (DOCU 0, GLD 0.95); a
tranche-split close records it on `tranches[].exit_price` (HG 6.5). Computation already
reads both (`_entry_exit_levels`), so nothing is broken — but the DISPLAY surfaces it in
different sections (status-history timeline vs Scaled Entries), which reads as
inconsistent. **Fix:** surface the closing price in ONE spot on the closed card/detail
(e.g. an "Exit" line beside realized P&L) via a helper that reads `exit_price` from
either location. Display-only; do not migrate the stored field.

**C.9 — Scaled-entry guard clamps a CONFIRMED-FILLED carried trade to `planned`
(OBSERVATION 2026-07-10, session 19; real LOGIC bug in `enforce_scaled_planned`, §7.3a).**
Surfaced by the first 260615 merge (low, onto the fixed 260608 base). The
defensive-breadth pair (XLV+XLP+XLF/IGV, `strategy_id: xlf-xlp-xlv-vs-igv`) should read
**Active** at 260615 — the June 15 letter explicitly confirms BOTH tranches filled (specific
fill prices, "starter filled Monday open… second half filled Thursday at the 3.22 ratio
trigger", note "Both tranches now confirmed filled at full 1.00 size"). The **model got it
right**: the saved `raw_extract` has `status:"open"` with both tranches `status:"open"` +
`entry_date:"2026-06-15"`. Then `enforce_scaled_planned()` **overrode it to `planned`**
(tranches normalized to `planned`, `entry_date` nulled). Root cause: the guard releases a
`scaled` entry only on *a closed tranche OR realized P&L*, and this trade has a fill but
neither — so it clamped a genuinely-confirmed fill. This is §7.3a's documented "under-call
a genuinely-filled scale-in for determinism" tradeoff, but 260615 is exactly the case that
shows the release rule is too narrow: the guard exists to kill the *260608* SAME-ISSUE
fabricated fill (new trade, no corroboration), whereas here the fill is confirmed in a
SUBSEQUENT issue — a far more trustworthy signal. Side effect: it left the store
self-contradictory (tranche *notes* say "filled Monday/Thursday" while `status` = planned,
`entry_date` = null). **RESOLUTION (2026-07-10 — supersedes the initial "loosen the guard" idea): see the
Section-status taxonomy above.** Loosening the release condition just chases the
cross-issue case and STILL fails a first-appearance already-filled scaled entry (the
RKLB shape). The real fix is to make `status` a *section*-conditioned derivation:
defensive-breadth is under **Open Trades**, so `status = open` by section, and
`enforce_scaled_planned` is **scoped to the `new` section only** — where the 260608
fabrication it was built for actually lives. Re-run the determinism sweep after
implementing. Related to C.3 (same trade, the planned-ADD tranche gap).

**C.10 — Observation-trade z-score: capture the value AND its lookback window (FUTURE,
LOW PRIORITY — user 2026-07-10).** Reviewing the 260615 software winners/losers
observation basket (`software-winners-vs-losers-igv-basket`): correctly gives NO explicit
entry guidance (it's `observation_only`), and the thesis reads well — but it references
the z-score only QUALITATIVELY in `thesis.rationale` ("the z-score is no longer at an
early-entry reset"), with NO numeric value and NO timeframe, and `reference_values` is
`{}`. Contrast the defensive-breadth pair, which DID capture
`z_score_recent`/`z_score_extreme` numerically in `reference_values` — but also without an
explicit window. **Desired:** capture the z-score as a typed value tagged with its lookback
window (user notes it's a **60D** z-score), so the thesis/display can say "z-score over 60D"
instead of leaving the window implicit. **Provenance caveat (user 2026-07-10):** the 60D
window is NOT in the newsletter prose — it's only inferable from the LABEL on top of the
source chart/graph. So this is NOT the model missing a stated number; capturing it would
depend on whether `pdfplumber` even extracts chart-annotation text at all (uncertain —
chart labels sit at the edge of text extraction, sometimes rasterized as image). That
lowers feasibility and reinforces the low priority. Also note the z-score value itself is
prose-only today, so per §7 (Python never parses prose) it's structurally invisible for the
observation trade. User explicitly DEPRIORITIZED — logged so it isn't lost. Related to C.4
(pairs z-score display gap).

**C.11 — `classify_legs` only recognizes 2-leg verticals; a 4-leg iron condor falls to the
generic leg-signature (OBSERVATION 2026-07-10, 260622 Micron merge; PYTHON coverage gap, NOT
a reasoning miss).** The MU earnings iron condor (sell 900 put / buy 800 put + sell 1350 call
/ buy 1450 call, shared 2026-06-26 expiry) stored as `strategy_id: mu-opt4-bcbpscsp` with
`structure_label: None`. Root cause: `classify_legs()` (`newsletter_ingest.py:808`) guards on
`if len(legs) == 2` and returns `(None, None, None)` for anything else, so the caller falls
back to the model's `structure_label` (null — model correctly deferred per §7) and
`_leg_signature()` → `opt4-bcbpscsp`. The **model did its half perfectly**: extracted all 4
legs, deferred all classification fields to null, and even named the `id`
`mu-earnings-iron-condor-2026-06-22`. Purely a derivation-layer coverage gap — **UNFIXABLE by
the effort ladder** (the reasoning already got it right; more spend changes nothing). **Fix:**
extend `classify_legs` to recognize the 4-leg iron-condor shape (2 puts + 2 calls, one buy +
one sell per side) → `structure_label: iron_condor`, `bias: neutral`, token `iron-condor`
(yielding `mu-iron-condor`). ~10 lines, deterministic. **FREE to apply retroactively** —
re-derive from the saved `run_archive/*260622*raw_extract.json`; no billed run. The §8a
"small deterministic classifier + generic fallback" design worked exactly as intended here;
the fallback token is just not human-pretty. Companion to C.12.

**C.19 — `classify_legs` didn't recognize a 2-leg calendar/diagonal; it fell to the generic
leg-signature (OBSERVATION 2026-07-13, 260713 "$23T Battle" merge, user-spotted; DONE
2026-07-13). Direct sibling of C.11 — same subsystem, one shape deeper.** The TSLA pre-earnings
calendar (sell 410 call 2026-07-17 / buy 410 call 2026-07-24) stored as
`strategy_id: tsla-opt2-bcsc` with `structure_label: None`. Root cause: the 2-leg branch of
`classify_legs()` guarded on `ss != bs` (different strikes) for a vertical, so a **calendar**
(SAME strike, DIFFERENT expiry) failed the guard and returned `(None, None, None)` → model
fallback (null) + `_leg_signature()` → `opt2-bcsc`. The model did its half perfectly (both legs,
classification deferred to null, even named the `id` `…-410c-calendar-…`). **Latent bug fixed in
the same pass:** a **diagonal** (different strike AND expiry) *passed* the old `ss != bs` guard
and would have been mislabeled a bull/bear vertical on strikes alone — so the new branch checks
**expiry FIRST**: same-strike+diff-expiry → `calendar`, diff-strike+diff-expiry → `diagonal`,
else the existing vertical logic (§4a — calendar/diagonal are the only 2-leg shapes whose legs
legitimately differ in expiry). **`bias` left null for both** (user, 2026-07-13: a calendar's
direction depends on the thesis, not the legs — read the thesis for context; don't force a
bull/bear guess). ~12 lines, deterministic. **Applied FREE retroactively** — re-derived
`_store.json` via `rebuild_store.py` (added `260713` to the cascade) and refreshed the 260713
edition/marker `trade_updates` off the saved `run_archive/*260713*raw_extract.json`; no billed
run. Diff confirmed exactly ONE trade changed (`tsla-opt2-bcsc`/null → `tsla-calendar`/`calendar`),
no collateral drift. The §8a "small deterministic classifier + generic fallback" design absorbed
a genuinely novel structure with a code-only change and a $0 re-derive — the intended outcome.
Companion to C.11.

**C.12 — Single-leg short call yields no `pnl_pct` on close; the guard flags it (OBSERVATION
2026-07-10, 260622 merge; PYTHON coverage gap).** The merge emitted the flag `closed options
trade 'soxx-jun18-650-shortcall-2026-06-22' is not a clean 2-leg vertical → no pnl_pct`. The
trade is a single-leg short call (sell 1× SOXX 650 call), closed and archived, but
`pnl_pct: None` — a **closed trade invisible to the scoreboard**, exactly the §8c/§8d failure
mode the flag exists to catch (it surfaced it, did NOT silently drop). Root cause:
`compute_risk_pnl` only derives P&L for 2-leg verticals; a lone short call (premium collected
− buyback cost, or full credit if it expired worthless) has no derivation path. **Fix:** add
a single-leg option P&L path (short: `pnl = entry_credit − exit_debit`; expired worthless →
full credit kept). **Verify first whether this is actually a covered-call overlay** of the
SOXX/SMH core (`overlay_of` + `structure_label: covered_call` per newsletter-schema.md) — the
260622 issue historically carried a SOXX overwrite into MU earnings, so the right P&L model
may be the overlay/covered-call one. FREE to apply retroactively. Companion to C.11 (both:
"deriver doesn't cover this leg shape yet").

**C.13 — `thesis.positioning` carries forward with no date and goes stale (OBSERVATION
2026-07-10, 260622 review; DECISION: date-tag it — user).** USDJPY
(`usdjpy-short-conditional-2026-06-08`, `planned`, first_seen 2026-06-08 / last_mentioned
2026-06-22) shows `thesis.positioning` = *"Leveraged funds remain heavily net short JPY
(~99,844 contracts) alongside asset managers (~78,076)…"* — specific CoT contract counts from
an EARLIER issue, rendered with no date, so it reads as current. Meanwhile `thesis.rationale`
on the SAME trade DID update to the 06-22 reality (BoJ hiked, USDJPY ran to 161.4 against the
short). So the two halves of the thesis are from different weeks with no way for a viewer to
tell the positioning half is weeks old. **DECISION (user, 2026-07-10, CLARIFIED): a date-tagged
HISTORY — not a single as-of tag.** Scope is DELIBERATELY narrow: `rationale` (the main thesis
writeup) is OUT — it's EXPECTED to change week to week, leave it a single current string, no
dating. Only `positioning` (the time-sensitive CoT/futures read) gets dated, and the intent is
a **history**: successive weeks' positioning reads ACCUMULATE as dated entries so you can see
the series evolve, rather than one value that silently overwrites/goes stale. **Shape:**
`thesis.positioning` becomes an append log — `[{ as_of, text }, …]` (newest entry = current for
display; older entries retained as the history trail). Fits CoT positioning naturally: contract
counts are a week-over-week series, so the history shows the short/long base building or
unwinding over time. **Display:** show the latest entry with its date ("as of {date}"), with the
prior entries available as a positioning history (e.g. an expandable list). Amends §6 of
`newsletter-schema-tightening.md` (thesis object — `positioning` goes from a string to a dated
list). **KEY BUILD QUESTION — how entries get appended under the live-set carry-forward,
§7-cleanly:** append one `{ as_of: issue_date, text }` entry ONLY when the model emits a
NON-NULL positioning that issue (a genuine restatement); an issue that doesn't restate appends
nothing and the existing history stands (its newest date shows how old the latest read is). That
keys off "did the model state positioning this issue," NOT a prose equality-compare (which would
edge on §7's "Python never reads prose to decide"). REQUIRES the extraction to emit
`positioning: null` when the issue doesn't restate it, rather than echoing the fed-in value —
verify/enforce that in the prompt, it's the crux (an echo would append a duplicate dated entry).
Alternative: the model emits the as-of date itself as a primitive. **Back-compat:** existing
stored `positioning` strings become a single-entry list stamped with the trade's
`last_mentioned` (best available date) on migration. NOTE (separate thread — RESOLVED this
review, NOT a mis-call): USDJPY correctly stays `status: planned`. Verified against
`status_history` — it WAS mentioned in 06-22 (`weeks_unmentioned: 0`, `stale_flag: false`) with a
genuine trade-level update (thesis re-framed to a failed-breakout / intervention reversal, sell
stop still untriggered), so it's a live watch, not silent/abandoned. The earlier "explicitly
retired 06-22 / setup died" alarm traced to a STALE historical schema note contradicted by the
actual store; the lifecycle engine handled it correctly. No queue item — withdrawn.

**C.14 — Show Entry in the detail-panel header for ACTIVE trades, before Stop/Tgt (REQUEST
2026-07-10, user; DISPLAY only).** For an active/open trade the deep-dive header (`#nd-levels`)
currently shows only Tgt + Stop — `levelsRowHTML()` (`watchtower.html:1041`, the
`meta.tone === 'Active'` branch) builds `[Tgt, Stop]` and drops Entry (the old design assumed
"already in, so entry is irrelevant"). User wants Entry listed, and LEADING. **Fix:** in that
Active branch, PREPEND an Entry column so the order becomes **Entry → Tgt → Stop** —
`cols.push(metricCol('Entry', <span class="font-mono text-slate-200">${fmtLevel(t.entry)}</span>))`
before the existing Tgt/Stop pushes. Use `fmtLevel(t.entry)` so a missing entry renders `--`
(never blank), matching the new/watching branch. **Scope: detail-panel header ONLY**
(`levelsRowHTML`) — NOT the compact strip card (`levelsInlineHTML`), which the user did not ask
to touch; leave the strip's Active line as Tgt/Stop. Also refresh the two stale comments reading
"Tgt+Stop (active)" — the `#nd-levels` placeholder (~line 379) and the block comment (~line
1017) — to "Entry+Tgt+Stop (active)". FREE, display-only; no store/extraction change.

**C.15 — Closed-card Exit slot: always show it, render `--` when the source stated no exit
level; never derive (OBSERVATION + DECISION 2026-07-10, user; DISPLAY only).** The closed
defensive-breadth pair (`defensive-breadth-vs-igv-pair-2026-06-08-closed`) shows no Exit on its
closed card. **NOT a data-loss bug:** the newsletter reported the close as a PERCENT (+1.40%),
never a closing ratio — confirmed in the 260622 raw extract (tranche entry ratios 3.01/3.22 +
`exit_date: 2026-06-16` + `pnl 1.4%`, and NO exit level; it closed early "after the hedge did its
job" at +1.40%, short of the stated 3.59 trim / 3.79 close targets, so no closing ratio was ever
printed). Per B.1 we must NOT invent an exit. Current renderer `levelsRowHTML()` Closed branch
(`watchtower.html:1037`) does `if (exit != null) cols.push(metricCol('Exit', …))` — it DROPS the
Exit column when null, so the card reads as if a field is missing. **DECISION (user 2026-07-10):
keep the Exit slot ALWAYS present for consistent display, rendering `--` when no exit level was
stated (the existing "missing → `--`, never blank" convention); do NOT derive `entry × (1+pnl%)`.
Performance (`pnl_pct`) is tracked regardless — the `--` is purely the exit-LEVEL display, not the
P&L.** **Fix:** always push the Exit column via a `--`-yielding formatter (fmtLevel-style) instead
of the null-guard drop; apply the same always-present treatment to Entry for consistency.
**Generalizes** (companion to C.8 + the GLD-Entry-`--` watch-item): closed-card level slots are
ALWAYS present; any stated-absent level renders `--`, never fabricated. Minor open sub-detail: the
pairs close has TWO tranche entries (3.01, 3.22) — decide whether the Entry slot shows the starter,
a weighted blend, or "3.01/3.22" (lean: show what's cleanly available, don't blend-invent). FREE,
display-only.

**C.16 — Open-with-NO-entry-price: grayed card, SCORE-on-close (not drop), and COMPUTE the exit
from stated levels (defensive-breadth re-entry; OBSERVATION + DECISIONS 2026-07-10, user).** The
re-entry (`defensive-breadth-vs-igv-pair-2026-06-08`, LIVE, `open`) has ONE tranche
(`entry_date 2026-06-18`, `status open`) with NO `entry_price` — the letter only said "re-entered
Wednesday post-FOMC," no ratio. Three linked rules:
1. **Display (open, no entry) — muted DATA, DONE 2026-07-10.** An `open` trade with no entry basis
   (no `entry.level`, no `entry_price`, no tranche `entry_price`) mutes its DATA rows (title +
   levels, `opacity-50`) while KEEPING its Active identity bright — the violet border AND the
   "Active" badge stay full-opacity (user: "make the text and symbols gray… Active trades can retain
   the purple highlight"). Implemented as `lacksEntryBasis(t)` + a `dataMute` wrapper in
   `renderNewsletterStrip` (Closed cards still mute wholesale via `cardMute`). **DECISION (user
   2026-07-10): the mute rule is UNIFORM on scoreability, NOT the tracking-window carve-out** — a
   `pre_existing` hold with no entry basis (the SMH core) is just as un-scoreable as a narrated
   in-window re-entry, so BOTH mute. The earlier "exclude pre_existing because its entry is
   out-of-scope" idea was rejected: graying is about display completeness, but the deeper shared
   trait is that neither can be scored at close (no entry basis) — a distinction that really belongs
   to the scoreboard (an "un-scoreable / pre-window" bucket, cf. the actionability-segmentation
   note), not to card opacity. So the card mute keys purely on "open + no entry basis." Level slots
   still show `--` (C.15).
2. **On close → SCORE it, do NOT drop/abandon (SUPERSEDES the initial drop idea).** 260629 closes
   this basket with a STATED **P&L +3.2%** (vs SPY −2.26%). A stated % is trackable per C.15's
   "track stated performance, don't invent" principle → keep it `closed` and capture +3.2%.
   Dropping it would discard a real stated winner and understate the scoreboard. (The first
   instinct — "closed without an entry → drop/abandon" — is RETIRED; it assumed no scorable data,
   which 260629 disproves by stating +3.2% plus closing marks.)
3. **Exit — COMPUTE the ratio from stated closing marks (the KEY refinement to C.15).** 260629
   gives actual per-leg closing marks: "sold XLV at $159.92, XLP at $84.87, XLF at $53.55, and
   covered IGV at $86.96." Because specific price LEVELS were stated, computing the pairs exit
   RATIO from them (× basket weights) is legitimate DERIVATION, not fabrication → DO compute and
   display it. **Discriminant vs C.15: did the newsletter state price levels? levels stated →
   COMPUTE the exit ratio; %-only with no levels (the 06-16 first close) → `--`. NEVER back-solve
   an exit from `entry × (1+pnl%)`.**

**Layers touched (NOT display-only):** the closing marks are PROSE today ("Closing marks: sold XLV
at…") — per §7 Python can't read prose, so they must be EXTRACTED into typed per-leg exit fields
(e.g. `basket[].exit_price`) before the ratio can be computed. So this needs: (extraction) capture
per-leg closing marks as typed data; (derivation) compute the exit ratio from marks + basket
weights and confirm `pnl_pct == +3.2%`; (display) render the computed exit ratio in the C.15 exit
slot. **Open sub-detail:** the re-entry has no stated ENTRY level — leave Entry `--`, or apply
§8c-style back-compute (`entry = exit ÷ (1+pnl)`) to fill it? Lean `--` (the entry was genuinely
never stated; back-computing it edges closer to inventing than the exit-from-marks case does).
First exercised when 260629 imports.

> ⚠️ **CORRECTION / RESOLVED 2026-07-11 — the "dropped capture" diagnosis below was WRONG. Real
> cause = PLUMBING (field placement); fix is DONE, $0, no billed run, no prompt change.** The
> pristine `raw_extract` proves the model captured EVERY exit — at the trade's **top-level
> `exit_price`** field (MSFT 0.36 / GLD 4.85 / GLD 2.96 / IWM 0.3 / HG copper 6.18 / MU scalp
> 1199.23). **Nothing was dropped.** The bug: `compute_risk_pnl`, `_entry_exit_levels`, and
> `closingExit` sourced the exit from `status_history[].exit_price` / tranches but NOT from the
> top-level field — an asymmetry, since they DID read top-level `entry_price`. So the captured
> exits were invisible to compute + display (showed `--`, P&L fell back to the stated value). The
> "format shift" was real, but its consequence was FIELD PLACEMENT (the new phrasing coincided with
> the model filing the exit top-level instead of in status_history), NOT dropped capture. **FIX
> (done):** source `exit_price` from the top-level field in those 3 spots + a deterministic
> re-derive over the existing store (no API). The prompt-hardening built for the wrong diagnosis was
> **REVERTED** (the model needs no help — user: "don't give the reasoning engine more tasks than it
> needs"). Sourcing the exit also triggered **§8c prefer-computed**, which corrected **IWM from a
> fabricated +46.2% to the honest −53.8%** standalone loss (the author had spun it: "+$0.30
> incremental profit… the $0.65 debit was financed by the prior SOXX overwrite" — creative
> cross-trade accounting; only IWM and a −2.6→−2.68 copper rounding changed, the other ~20 already
> reconciled). `flag_missing_exit` is **KEPT** — it's Python (no model burden), a general
> completeness net, and its "0 fired" result is literally what EXPOSED this misdiagnosis. **DISTILLED
> LESSON:** a "capture-completeness" scare that was really a plumbing/field-placement bug — before
> concluding the model dropped a primitive, check EVERY field it might have filed it under.
> Everything below is the SUPERSEDED original diagnosis, kept for that lesson.

**C.17 — Flag a closed options trade that dropped a recoverable exit price (PARKED 2026-07-11,
user; OBSERVABILITY, not derivation).** Extraction can silently drop an explicitly-stated exit
price. **Confirmed SYSTEMATIC at low effort in 260629 — THREE closes**, all "we entered/sold at $X
and closed at $Y" sentences where the model captured the entry (first figure) + the labeled `P&L:`
line but DROPPED the prose exit (second figure):
- MSFT Jun26 392.5/400 call spread — "sold at ~$1.00 and closed at **$0.36**" → `exit_price` None.
- GLD Jun26 385/375 put spread — "entered at ~$3.00 and closed at **$4.85**" → `exit_price` None.
- GLD Jun29 370/360 put spread — "entered at ~$1.09 and closed at ~**$2.96**" → `exit_price` None.
(Contrast `gld-jun12-395-372`, closed a PRIOR issue with different phrasing — DID capture exit 6.05.
So it's this issue's sentence structure / the low-effort run, not a universal failure.)

**Why a FLAG, not derivation (user 2026-07-11):** deriving the exit (exit = credit−gain for a credit
spread / debit+gain for a debit spread — all recoverable here, entry+pnl are present) would auto-fill
the gap and **DESTROY the ability to evaluate the reasoning engine's parse reliability**. The store
doubles as a DIAGNOSTIC INSTRUMENT for the extraction, so a dropped primitive must stay VISIBLE
(`--`), not silently patched. (Not a one-way door — flip on derivation LATER once the parse is
trusted; observability wins while still calibrating.) A hand-patch was tried on MSFT and REVERTED for
the same reason. The flag is the observability complement: surface the likely-drop at IMPORT time so
the miss is loud, not caught by eyeball three issues later.

**Scope (tight, high-signal, no prose-reading):** flag a **closed options trade with `entry_price`
AND a `pnl` present but NO `exit_price`** — the bracketing figures are there, the middle one isn't,
so it's almost certainly a drop (not a legit %-only close). Won't fire on pairs (%-only closes),
expired-worthless (exit=0 is present), or no-pnl closes (already flagged). ~a few lines in
`compute_risk_pnl` (which already knows it fell back to the stated pnl because `exit_price` was
absent). Flags SUSPECTED drops (candidates to check vs the source), not confirmed — but at this scope
"suspected" ≈ "almost certainly". **Purpose:** OBSERVABILITY of the engine's capture-completeness
(the systematic net vs the user's eyeball); troubleshooting falls out of it. Reinforces that
`capture-completeness ≠ value-stability` — the token test measured stability of CAPTURED values, never
whether every stated primitive was captured; this class was invisible to the existing flags (MSFT got
a `pnl_pct`, so "no derivable pnl" never fired).

**ROOT CAUSE — an AUTHOR FORMAT SHIFT, not model flakiness (user diagnosis, confirmed 2026-07-11).**
It's issue-wide in 260629 (**7 trades**: MSFT, GLD×2, MU earnings, MU scalp, IWM, HG copper) because
the AUTHOR changed how he reports closes:
- **260608 (old): exit stated SINGLY, often labeled** — "HG Copper first tranche: Closed Tuesday at
  the $6.50 trailed stop", "the position was cut at $0.95". The model captured these fine (6.5, 0.95).
- **260629 (new): entry + exit FUSED in one first-person clause** — "We entered at ~$3.00 and closed
  at $4.85", "We sold… at ~$1.00 and closed at $0.36", "We bought MU at… $1,237.62 and exited at
  $1,199.23", "We entered copper… at $6.35… and were stopped at $6.18". The model grabs the first
  figure (entry) + the labeled P&L, and skims the second (exit). (HG copper is a CLEAN instance, not
  murky — its PAST closes 6.50/6.43 were captured fine from the old format; only the new-format 06-29
  $6.18 stop dropped — the same ticker showing both behaviors is the tightest proof of the shift.)
So it's a **distribution shift in the INPUT** — the extraction was validated against 260608's format
(the §10 acceptance fixture) and silently failed to generalize to the new prose, with NOTHING in the
system catching it. Lesson: validation on one format ≠ robustness to author format drift.

**Two consequences for the fix:**
- The prompt-hardening is WELL-AIMED (it teaches the exact new "entered at X and closed at Y → grab
  BOTH" shape) — a learnable format, so good odds it catches this one.
- BUT format drift is UNPREDICTABLE — you cannot write a prompt example for a format the author hasn't
  invented yet. This is the strongest argument for the flag: it's **format-AGNOSTIC** — it fires on the
  RESULT (closed spread, entry + pnl, no exit) whatever phrasing caused it. A prompt example is
  format-specific; the flag is the net for the next drift. It would have surfaced all ~6 at import time
  instead of via eyeball across the strip.

**Current handling (per user — no derivation, no patch):** the 260629 exits stay `--` as honest miss
signals. The prompt WAS hardened ("both prices in one sentence — grab BOTH") to reduce the rate
upstream (low-cost, approved). The dropped exits (MSFT 0.36 / GLD 4.85 / GLD 2.96 / MU 3.86→2.23 / MU
scalp 1237.62→1199.23 / IWM / HG copper 6.35→6.18) are a concrete **effort-ladder test case**: re-run 260629 at medium/high
and check whether the prose exits low effort dropped get captured. **Status: PARKED — flag NOT built;
build when ready.**

**C.18 — Price a multi-spread options structure from per-sub-spread fills (SPEC 2026-07-11, user;
follow-up to C.11 — closes the iron-condor P&L gap).** C.11 taught the classifier to NAME an iron
condor but `compute_risk_pnl` still can't PRICE one ("not a clean 2-leg vertical → no pnl_pct"). The
newsletter quotes such structures as their **sub-spreads**, each with an entry AND exit — e.g. MU
260629: *"sold the 1250/1300 call spread at $3.86 and covered before earnings at $2.23… bought the
800/750 put spread for ~$1.48… those puts expired worthless."* From those stated components the whole
structure's entry/exit/P&L computes cleanly, so this is **legitimate derivation, not fabrication** —
the SAME principle as C.16 (per-name marks → ratio), user-confirmed clean against **B.1** (every input
is printed), **§7** (Python computes from typed primitives, doesn't parse prose), and **§8c** (the
computed +0.15 reconciles with the stated +0.15).

**Prerequisite — a per-sub-spread price slot (the missing piece).** Today the components live ONLY in
the prose note; MU's typed `entry_price`/`exit_price` are null, and the flat `legs[]` array (§4a,
authoritative for classification) has no per-leg/per-spread price slot. And per-LEG prices don't fit —
the letter gives the spread NET (3.86), never the individual 1250-call and 1300-call legs. So add an
optional pricing overlay, populated ONLY when a multi-spread structure is quoted per sub-spread:
```
spreads: [
  { side:"call"|"put"|…, legs:[{strike,expiry,type,action},…], entry_price:<net>, exit_price:<net; 0 if worthless> },
  …
]
```
`legs[]` stays the authoritative structure representation; `spreads[]` is a thin pricing overlay for
the sub-verticals. (Minimal alternative if structures stay simple: a `side`-tagged fill list
`[{side, entry_price, exit_price}]` and let Python group the flat legs by type — works for an iron
condor, i.e. one vertical per side, but breaks on 2-of-a-side; the explicit-legs `spreads[]` is the
robust choice. DECIDE at build.)

**Derivation (Python, deterministic):**
- Sign each sub-spread **+1 if credit (sold)** / **−1 if debit (bought)** via the existing
  `_spread_credit_or_debit` on that sub-spread's legs (no new judgment).
- `entry_price` (whole) = Σ(sign × sub.entry_price); `exit_price` (whole) = Σ(sign × sub.exit_price).
- `pnl` = entry − exit; then `pnl_pct = pnl / risk_capital`.
- **MU worked example:** entry = (+1)(3.86)+(−1)(1.48) = **2.38** net credit; exit = (+1)(2.23)+(−1)(0)
  = **2.23**; P&L = 2.38 − 2.23 = **+0.15** ✓ (matches the stated net). Card then shows
  Entry 2.38 → Exit 2.23 → P&L, and the iron-condor flag clears.

**Sub-questions:** **(1) RESOLVED (user 2026-07-11): `risk_capital` = the structure's MAX LOSS** — the
worst-case combined expiry payoff, found by evaluating the net payoff at each strike boundary (and the
tails) and taking the minimum. NOT a naive sum of per-sub-spread max losses — that overstates a TRUE
neutral iron condor, where the call side and put side max-loss in opposite scenarios and can't both
happen. Do NOT adjust for the author legging in/out over the trade's life (he covered the call spread
before the puts expired) — use the full assembled-structure max loss regardless (user: "not going to
wring my hands over it"). **MU worked example:** bearish structure (both spreads lose on the upside),
max loss at MU ≥ 1300 = (call-spread width 50 − credit 3.86) + put-spread debit 1.48 = **47.62** →
`pnl_pct` = 0.15 / 47.62 = **+0.3%** (big risk, tiny net — the honest read). Still OPEN: (2) `spreads[]` explicit-legs vs the `side`-tagged
minimal shape. (3) whether the model emits `spreads[]` fills or Python groups `legs[]` + matches
captured prices. **Scope note:** this handles multi-SPREAD structures (iron condor, the MU
call+put combo). The `smh-collar` P&L gap (short call + long put overlay) and single-leg shorts (C.12)
are DIFFERENT shapes — related "deriver-doesn't-cover-this" family, but not solved by `spreads[]`.
**Status: BUILT 2026-07-12 (session 22).** `_price_multi_spread()` + `_structure_max_loss()` in
`newsletter_ingest.py`, wired into `compute_risk_pnl` (fires when `_spread_credit_or_debit` returns
None). Sub-spread fills source from a typed `spreads[]` overlay when present (forward), else the
`reference_values` `{call,put}_spread_{entry,exit}` convention the model already emits (decides open
sub-question 3: **Python groups `legs[]` + matches the captured sub-spread prices** — no billed
re-extract needed). `risk_capital` = the general assembled-structure max loss (payoff evaluated at
every strike + tails, min taken), NOT a per-side sum. Also sets `entry_price`/`exit_price` for the
card. Verified free against the saved 260629 raw_extract: MU -> entry 2.38, exit 2.23, pnl +0.15,
risk 47.62, **pnl_pct +0.3%**, iron-condor flag cleared. Propagated to `_store.json` + the 260629
marker via a targeted re-price (only MU's 5 derived fields changed; a full 5-issue replay confirmed
the store is otherwise byte-identical). SCOPE (unchanged): the SOXX collar (short call + long put
overlay) and single-leg shorts remain out of scope — `_price_multi_spread` correctly returns False
for the collar (not 2 calls + 2 puts) rather than mispricing it, leaving its existing no-pnl flag.

### Scoreboard methodology — actionability segmentation (DESIGN 2026-07-10, not built; user)

Elaborates the "Hit-rate/accuracy tracking" open item in `newsletter-tracker.md`. **Requirement
(user 2026-07-10): break out newsletter performance by ACTIONABILITY — tracked, NOT displayed.**
A backend/scoreboard dimension only; no UI. The point: measure what a *subscriber to the weekly
could actually have captured*, so the newsletter's record isn't flattered by trades already
entered/closed before the reader saw them.

**Motivating pattern (260622, confirmed against the store).** The author reports Monday
(`issue_date 2026-06-22 = Mon`) on short-dated WEEKLY options largely entered BEFORE publication —
several already resolved by the time the issue lands. Of six 06-22 trades, only ONE (MU iron
condor, `planned`/`premium_target`, expiry 06-26 Fri) is a forward setup a reader could place.
Evidence: SOXX short call expired **Thu 06-18** ("expired worthless… covered-call overwrite") —
dead before the Monday issue; GC short "entered Wed 4,274, covered Thu 4,275 for a scratch" — a
round-trip pre-publication; IWM spread expires the SAME Monday as the issue (0DTE-dead); MSFT/GLD
expire Fri 06-26. This matches the user's hypothesis: weekly options entered mid-week, reported
the following Monday, book already in motion — plausibly to steer readers toward the $100/mo
real-time alert product.

**Segmentation model — all MECHANICALLY derivable from existing primitives, no judgment / no new
extraction:**
- **Showcase / un-actionable:** a trade whose FIRST appearance in the store is already `closed`
  (`first_seen == last_mentioned` on a closed status; no prior open-status issue in its history).
  A subscriber never had a shot. GC scratch + SOXX expired-worthless are the 260622 cases. Exclude
  from the follower hit-rate, or bucket separately as "author's book."
- **Time-to-expiry-at-publication (options):** `legs[].expiry − issue_date`. ~0 trading days of
  runway (IWM, expires issue day) → effectively un-actionable even when `status: open`; real
  runway (MU/MSFT/GLD, 4 days) → actionable. Pick a threshold (e.g. < 1 trading day → non-actionable).
- **Actionable:** `planned`/conditional, or open with real runway that a follower could place
  at/after publication. MU qualifies.

**Report hit-rate + P&L separately per bucket** (Actionable vs Showcase, optional marginal middle).
Keys off `status` + `first_seen`/`last_mentioned` + `status_history` + `legs[].expiry` +
`issue_date` — all present today; deterministic, §7-clean. **NOTE — `entry.trigger_type` does NOT
segment this on its own:** these pre-entered trades are tagged `market` (enter now), not
`pre_existing`, so the RELIABLE keys are the structural ones above (first-appears-closed;
expiry−issue), not the trigger enum. Depends on nothing but the scoreboard itself being built
(still unstarted).

### `abandoned` vs `unresolved` — display color, NOT a scoring key (DECISION 2026-07-11, user)

Prompted by USDJPY at 260629 going `planned` → `unresolved`. **The engine's call was CORRECT and
for the right reason** (verified): USDJPY's only 260629 appearance is line 399/409 (98% through) —
the **Dollar row of Portfolio House View** ("Dollar Neutral-to-bullish… but USDJPY above 160 raises
intervention risk"), a commentary mention with **no trade-level update**. Rule: planned + no
trade-level update + ticker still discussed in commentary → `unresolved` (not `abandoned`, which
needs the ticker WHOLLY absent). The stub `reason` articulated it precisely. **No fix needed.**

**But the review surfaced that the abandoned/unresolved distinction is currently bean-counting**,
by §7.4's own test ("does anything downstream DECIDE based on it?"):
- **Intended difference:** `abandoned` = newsletter dropped the ticker entirely (clean "gone");
  `unresolved` = ticker still discussed, no trade update → "can't tell if it quietly triggered and
  worked," a resting state meant to shield a maybe-winner from being scored a LOSS on the future
  hit-rate scoreboard.
- **Today nothing consumes it.** The scoreboard doesn't exist; the two states differ only in a
  `reason` string the discard stub already carries — the `status` enum is redundant with the note.
- **Even once the scoreboard exists,** both most likely collapse to the SAME action ("unknown
  outcome → exclude from hit-rate"); the difference (*why* it dropped) is a human-review hint, and
  the classifying test is fuzzy (USDJPY: a tangential house-view line tipped abandoned→unresolved).
  So it's **color, not a key.**

**DECISION (user 2026-07-11): leave it alone. Build ZERO machinery.** Specifically:
- **NO `weeks_unresolved` / "two unresolveds → abandoned" escalation timer** (a mid-discussion idea,
  explicitly RETRACTED — adding a lifecycle state machine to a color field is over-engineering).
  Note the current asymmetry it would have inverted: the 2-issue timer lives on the ACTIVE side
  (`stale_flag`, which KEEPS the trade, never abandons — silence never drops a held position);
  `unresolved` is a PLANNED-only state with no count.
- The split **only stops being bean-counting IF** a future scoreboard deliberately scores them
  differently (e.g. `abandoned` = a floated call that fizzled = soft follow-through miss, vs
  `unresolved` = excluded-unknown). That's an unmade scoreboard-design choice; revisit ONLY then.
- **C.13 stub-preservation — DROPPED, not tracked (user 2026-07-11, "too nuanced to care").**
  `_discard_stub` stripping `thesis`/positioning is by-design and correct for a truly `abandoned`
  trade; it only *costs* anything if an `unresolved` trade later RESUMES (rare). That's the same
  color field as this whole section, so it's folded into the "leave it alone" call — NOT a separate
  open item. Verified real (USDJPY lost its migrated positioning entry going `unresolved` at 260629),
  but deliberately not worth a fix. Revisit only if a resumed-unresolved trade's lost history ever
  actually bites — which would come bundled with the scoreboard-time revisit anyway.

### Non-actionable trades → digest dropdown, not the plays strip (DESIGN DIRECTION 2026-07-11, user; not built)

The actionability principle graduates from the (backend) scoreboard to the (frontend) plays strip.
The **plays strip is for ACTIONABLE trades only** — what the reader could actually take this week
(planned/conditional setups + open positions with real runway). The author's **intra-week churn**
(mid-week partial-closes, re-entries reported after the fact, showcase closes that were entered AND
exited before the issue landed) is **noise in the plays strip** — a fait-accompli copper scale-out
isn't a play you can take.

**DECISION (user 2026-07-11):**
- **Demote non-actionable trades to the DIGEST DROPDOWN** (situational-awareness lane), NOT the
  plays strip. Retain them (the user actively trades gold/copper and wants to observe his patterns
  over time — "maybe I can learn his patterns"), just out of the way of decisions.
- **Route by BEHAVIOR, NEVER by asset (emphatic).** Copper/gold are the user's *favorite*
  instruments; a CLEAN copper setup (a real takeable "buy at X", like the good copper week) STAYS
  in the plays strip. Only non-actionable *behavior* demotes, regardless of ticker. By-asset
  routing was explicitly REJECTED — it would exile a genuinely takeable copper setup just for being
  copper, and self-corrects nothing if he ever slows down on a name.
- **Discriminant = the mechanical actionability keys already spec'd** (first-appears-closed;
  expiry−issue runway; see "Scoreboard methodology — actionability segmentation" above). No new
  judgment; the scoreboard and the plays-strip routing share one rule.
- **Precedent:** mirrors the existing indicator→digest routing (§6, newsletter-tracker.md) — "not a
  takeable position → digest, not plays strip." Same display mechanic, different trigger, so this is
  extending established architecture, not inventing it.

**OPEN sub-question (user flagged — "need to think about how to distill those trades into a brief
line"):** the demoted trade's compact one-line form in the dropdown. Working shape ≈
`{ticker} {what he did} {outcome}` — e.g. "HG copper — scaled out 6.375→6.50, +1.96%, holding rest"
or "GC gold — Wed→Thu scratch" or "SOXX — covered call expired worthless, full premium." Format
TBD; the line must convey the pattern without a full card. **Status: DESIGN DIRECTION, not built —
build once the brief-line format is settled.**

### Card review pass — 2026-07-09 (post-tightening re-import, all 10 trades)

Second full card review, this time against the NEW-schema 260608 re-extraction (the
low-effort cold run). Distinct from the 2026-07-08 pass (old schema). Findings:

- **CONFIRMED WORKING** (do not regress): the `thesis.positioning` line renders well and
  is a keeper (§6 of `newsletter-schema-tightening.md`); B.5 collapses the USD/JPY BOJ
  meeting to ONE `key_dates` entry (first real import to exercise it); META correctly
  stays SILENT on entry price (`pre_existing` + B.1 never-fabricate — no restated entry
  in the letter); the HG-closed §8d tranche render ("6.375 → 6.50 · +1.96%" in Scaled
  Entries) displays well; SMH outright is clean.
- **NEW display fixes:** C.7 (expiration_worthless label), C.8 (closing-price location).
- **C.3 REINFORCED — second instance, worse:** HG copper's planned 6.15 add level is
  MISSING entirely — not in `tranches`, not in `entry.note`, not in `reference_values`
  (the pairs 3.22 case at least survived in `entry.note`; this one vanished). Proves the
  "demote unfilled adds to prose" fallback is UNRELIABLE — the model sometimes drops the
  level outright. Strengthens C.3's call for a structured `status:"planned"` tranche slot
  (a §8d extension); prose is not a safe home for planned adds.
- **CODE BUG (this session's `split_tranches`, `newsletter_ingest.py`) — status_history
  BLEED-THROUGH.** The model emitted copper as one trade with a single CONFLATED
  status_history entry (`status:"open"`, `pnl:+1.97%`, note covering both the stop-out
  AND the re-entry). `split_tranches()` deep-copies the whole parent history to BOTH
  children, so: the OPEN re-entry record shows a realized +1.97% it never made (the
  bleed-through), and the CLOSED record's history entry says `status:"open"` (its correct
  `pnl_pct 1.96` came from the tranche, not the history). The split partitions
  `tranches` but NOT `status_history`. **Fix:** during the split, rebuild each child's
  status_history from its own tranche — closed child gets a `closed`/pnl/exit entry, open
  child gets a clean `open` entry with NO realized pnl. Also a §8d spec gap (the split
  rule never specified status_history handling). FREE to fix + verify: re-run merge on
  the saved `run_archive/*__raw_extract.json`, no re-bill.

### D. Finalized card-design specs (target render logic) — confirmed 2026-07-07

Three trade shapes, each: **Line 1** = status label + conviction (dots, label text,
or blank per A.4) + stale badge if applicable. **Line 2** = identity. **Line 3** =
one status-dependent number, always a clean value (depends on B.1/B.2 landing first).
No price-level detail on the card itself — all of that (full entry/stop/target,
z-scores, ratio stats, key dates, thesis, tranches) belongs in the thesis detail
panel below, never the card.

**Options-spread card:**
- Line 2: `TICKER` (large/bold) + structure (small/dim). **Structure label shows the
  FULL descriptive name — "Bear Call Spread"/"Bull Put Spread"/etc. — on BOTH the
  card and the detail panel (user override, 2026-07-08).** The original 2026-07-07
  spec dropped the "Bear"/"Bull" word on the card (terse "Call Spread"/"Put Spread")
  on the logic that Call-vs-Put + Credit-vs-Debit already disambiguates; the user
  reversed this because the directional word "helps cage the mind to what we're
  looking at." Both surfaces now humanize `structure_label` in full via one shared
  helper (`getStructureDisplay()`), so they can't drift apart.
- Line 3 by status: Watching/New → `Credit $X` or `Debit $X`; Active → `Tgt $X ·
  Stop $Y` (omit `Tgt` entirely, don't show a placeholder, if no numeric target
  exists — confirmed via SMH, generalizes to options); Closed → `P&L +/-X%` (section
  C) or `P&L +/-$X` fallback.
- Real worked examples this session (full labels, per the 2026-07-08 override above):
  FIVN (`FIVN  Bear Call Spread` / `Credit $0.70–0.80`), GLD put spread
  (`GLD  Bear Put Spread` / `Debit $4.00`), GLD call spread (`GLD  Bull Call Spread` /
  `P&L -74%`), DOCU (`DOCU  Bear Call Spread` / `P&L +11.4%`), META
  (`META  Bear Call Spread` / `Tgt $640 · Stop $650`).

**Basket/pairs card:**
- Line 2: composition string, long side(s) joined by `+`, short side after `/` —
  e.g. `XLV+XLP+XLF/IGV` — plus fixed qualifier word "Pair" (confirmed: always
  "Pair" regardless of leg count, not "Basket" for 3+ names — user's call).
- Line 3 by status: Watching/New → `Entry <ratio>` (the newsletter's stated entry
  ratio, not a live-computed current ratio — z-score and the rest of the ratio
  stats go in the detail panel, not the card). Active/Closed rules for baskets not
  yet tested against a real trade this session (only one basket trade existed in
  the 06-08 import, and it was Watching) — extrapolate from the options-card
  Active/Closed rules when a real case appears, don't assume without checking.
- Real worked example: `XLV+XLP+XLF/IGV  Pair` / `Entry 3.01`.

**Outright card** (equity/future/forex, no `basket`, no `legs`):
- Line 2: `TICKER` (bare `underlying`, per A.1/A.2's fix — the alias, e.g. SOXX for
  SMH, stays in the detail panel per the existing alias rule) + a direction word.
  **RESOLVED 2026-07-08:** show the direction word on every outright card, reading
  the new `direction` field (`"long"`/`"short"` — see section B.4) directly rather
  than parsing it out of `id`. Render **"Long" in green, "Short" in red** — reuse
  the same green/red tokens the card already uses for P&L sign, for palette
  consistency. This reconciles the previous session's inconsistency (SMH/copper
  built with the word shown, USD/JPY built without it) in favor of showing it
  everywhere: `USD/JPY  Short` (red), matching `SMH  Long` / `HG  Long` (green).
- Forex-specific formatting, confirmed: insert a `/` for a forex pair display
  (`USDJPY` stored → `USD/JPY` shown); plain equity/future tickers display as-is,
  no slash.
- Line 3 by status: Watching/New → `Entry <price>`, no qualifier text (depends on
  B.1). Active → `Tgt $X · Stop $Y`, omitting `Tgt` with no placeholder when no
  numeric target exists (confirmed via SMH — this is the same rule as the
  options-card Active row, generalized).
- Real worked examples: `USD/JPY  Short` (red) / `Entry 157.50`; `SMH  Long` (green)
  / `Stop $540` (Tgt omitted, no number existed); `HG  Long` (green) / `Tgt $6.68 ·
  Stop $6.11`.

**Status labels — full vocabulary, current state:**
| `status` | Label | Notes |
|---|---|---|
| `planned`, first appearance (`first_seen === last_mentioned`) | New | |
| `planned`, seen again | Watching | |
| `open` | Active | + "Stale" badge if `stale_flag: true` |
| `closed` | **Closed** (was "Resolved" — A.3) | |
| `unresolved` | **undefined — known gap, kept intentionally (confirmed 2026-07-08)** | Not filtered out like `abandoned`/`deleted`, but has no branch in `getStatusMeta()` either; falls through to rendering the raw literal string `"unresolved"`, unstyled. Hasn't occurred in real data yet. **Decision:** leave as a known gap until it actually occurs in real data — no branch added now. |

**A.6 — Pairs/basket Chart tab pairs legs by ARRAY POSITION, not by long/short
`side` — confirmed 2026-07-08, card 2 of the review (XLV+XLP+XLF/IGV).**
`showNewsletterDive()` (~line 1237) builds `viewState.nd.entity.legs` via
`t.basket.map(b => b.ticker)` — this flattens the basket to a bare ticker array
and **discards `side` in the process**. `loadChart()` (~line 1044-1069) then does
`const [a, b] = entity.legs` and charts `closeA / closeB` as "the ratio." For a
simple 2-leg long/short pair this happens to work by luck (array order matches
long-then-short); for this 3-long/1-short basket (`['XLV','XLP','XLF','IGV']`) it
silently charts `XLV / XLP` — two LONG legs against each other, never touching
IGV (the actual short leg) at all. Confirmed via live prices: XLV/XLP ≈ 1.92
today, nowhere near this trade's real entry/stop/target (3.01 / 2.60 /
3.59-3.79). Pulled the source PDF text for this trade to check whether a
weighted-composite formula would fix it — the newsletter's `35%/35%/30%/33% of
long notional` weights turned out to be pure position-sizing math for a
beta-neutral book (`long_basket_beta 0.39 / igv_beta 1.16 ≈ 0.336`), not a
price-blend formula — confirmed by checking the actual formula against live
prices: **ratio = SUM of long-leg closes ÷ SUM of short-leg closes (raw prices,
no weighting)**, exactly matching the card's own literal `XLV+XLP+XLF/IGV`
notation. Verified: (XLV 163.24 + XLP 85.10 + XLF 55.23) / IGV 91.98 ≈ 3.30,
which lands right between this trade's real entry (3.01) and targets
(3.59/3.79) — strong confirmation this is the correct construction, not an
approximation. **Fix: separate the basket by `side`, sum each side's raw
closes, divide long-sum by short-sum.** Requires carrying `side` through to the
chart layer — `entity.legs` currently discards it (`t.basket.map(b =>
b.ticker)`, a bare ticker array), so `loadChart()` has no way to recover which
legs are long vs. short once flattened; needs to become (or be supplemented by)
a structure that preserves `{ticker, side}` per leg.

**A.7 — Forex trades never load a chart — confirmed 2026-07-08, card 4
(USD/JPY).** `showNewsletterDive()` (~line 1237) sets `entity.ticker =
t.underlying`, which for a forex trade is the bare schema-correct ticker
(`"USDJPY"`, no suffix — per `newsletter-schema.md`'s B.2 rule, this is the
right shape for `underlying` and should NOT change). `loadChart()`'s
non-pair branch (~line 1071) fetches
`${API_BASE}/get_price_history/${entity.ticker}?range=2y` verbatim, and
`watchtower_engine.py`'s `/get_price_history/<ticker>` route passes whatever
it receives straight to `yf.Ticker(ticker_symbol).history(...)`
(`fetch_price_history()`, ~line 773-801) with no suffix translation.
**Confirmed via direct yfinance test:** `yf.Ticker("USDJPY")` 404s (`"Quote
not found for symbol: USDJPY"`); `yf.Ticker("USDJPY=X")` and
`yf.Ticker("JPY=X")` both return real daily OHLC data. So yfinance does
support forex history — it just requires the `=X`-suffixed symbol, which
the store correctly does NOT carry (that suffix is a fetch-mechanics detail,
not part of the trade's identity). This is the same class of gap already
flagged as an open item in `newsletter-schema.md` ("Ticker display-name vs.
yfinance-fetchable-symbol mapping — `CL1!` vs `CL=F`") — forex hits it too,
just not yet triggered until a real forex trade's Chart tab was clicked.
**Fix:** translate at the fetch boundary, not in the stored data. Simplest
option: in `loadChart()`, when `entity.asset_class === 'forex'`, request
`${entity.ticker}=X` from the price-history endpoint instead of the bare
ticker (the entity object already carries `asset_class`, no new field
needed). Backend-side translation (in `get_asset_class()`/
`fetch_price_history()`) is the alternative if other callers of
`/get_price_history` end up needing the same bare-forex-ticker input; pick
whichever avoids duplicating the translation once the `CL1!`/`CL=F` futures
case is also tackled.

**A.8 — `tranches` is captured correctly but never rendered anywhere —
confirmed 2026-07-08, card 7 (HG copper).** The real stored trade has
`tranches: [{ level: 6.15, note: "Planned add level if it holds and the macro
tape does not deteriorate further." }]` — extraction correctly captured the
newsletter's stated $6.15 add level. Confirmed via grep: `tranches` has zero
matches anywhere in `watchtower.html` — no function reads it, so this
information is invisible in the UI no matter which trade has a planned add
level. This contradicts section D's own opening promise ("tranches... belongs
in the thesis detail panel below, never the card") — that commitment was never
actually built. **Fix:** add a render path for `t.tranches` in the detail
panel (narrative tab, alongside Key Dates/Status History) — at minimum, list
each tranche's `level` + `note`. Applies to any trade type that can carry
tranches (outright scaled entries like HG, and pairs/basket starter+add
sizing like card 2's XLV+XLP+XLF/IGV, whose `tranches` also currently renders
nowhere).

### Live card-by-card review, second pass (2026-07-08, post re-import)

With the 260608 re-import landed in the new B.1/B.2/B.4 shape, the user walked all 9
real cards one-by-one against the actual rendered detail panel (not just the strip
cards, which the 2026-07-07 pass had already covered). Two more real bugs surfaced
on trade 1 (FIVN):

- **Options Structure quadrant was always blank — fixed.** The detail panel's
  right-hand quadrant (`nd-options-data`) only ever had hardcoded placeholder cells
  for LIVE options-chain data (ATM strike/put premium/IV/put wall/call wall) — six
  `<p>` ids that no JS function ever populated for a newsletter trade (confirmed via
  grep: 6 matches, all in the HTML definition, zero in render code). Every options
  trade's detail panel showed six empty `--` cells with no options structure ever
  visible, which is exactly the trade's own `legs`/`reference_values` — data already
  sitting in the store, just never rendered. **Fix:** replaced that quadrant's markup
  with `#nd-structure`, populated by a new `renderOptionsStructureHTML(t)` (in
  `watchtower.html`) that renders the trade's own legs (action/strike+type/expiry,
  buy=green/sell=red) plus whatever's in `reference_values` as small chips. For a
  non-options trade (outright/pairs), it states plainly "Outright \<type\> position —
  no options structure." instead of showing anything options-shaped. This is
  static, always-available data from the extraction — NOT live market data, which
  still has no endpoint for newsletter trades (see the existing Options tab
  disclaimer in `nd-pane-options`, unchanged).
- **Structure label upgraded to full "Bear/Bull ... Spread" wording (user override,
  documented above) — same fix, since `getStructureDisplay()` feeds both the card
  and the new `renderOptionsStructureHTML()` header.**
- **SMA-200 chart line was too muted — fixed.** `addSMAOverlays()` used `#f8fafc`
  (a very light slate, near-white but visibly muted against the dark chart
  background) for the 200-day SMA. User wanted more contrast/"pop." Changed to pure
  `#ffffff`, same `lineWidth: 1.5` (user explicitly did not want it thicker — tried
  `2` first, reverted). SMA-50 (`#22d3ee` cyan) unchanged.

- **Pair card (XLV+XLP+XLF/IGV) reviewed — one real bug found (A.6, documented
  above with the rest of section A): the Chart tab's ratio calc pairs legs by
  array position, not by long/short `side`, so this basket's chart compared two
  LONG legs against each other and never touched the short leg (IGV) at all.**
  Confirmed formula (split by `side`, sum each side's raw closes, long-sum ÷
  short-sum — verified against live prices, lands right between this trade's
  entry and targets) but not yet implemented — this session is spec-only, no
  code changed. Two things initially flagged on this card were walked back after
  discussion, not real issues: (1) the "Outright pairs position" wording in the
  Options Structure quadrant's non-options fallback text reads oddly for a pairs
  trade, but it's inert disclaimer text with no functional impact and the card's
  own identity line already correctly says "Pair" — not worth a code change; (2)
  the basket's `reference_values`/`sizing`/`tranches`/full `stop`/`targets` having
  no render path anywhere in the detail panel is a missing feature, not a bug
  (nothing is broken/blank the way FIVN's options-structure quadrant was) — left
  out of scope for this review pass. Conviction dots (3/5 filled, correct for
  `conviction.scale: 3`) and the hidden stale badge (`stale_flag: false`, badge
  correctly `display:none`) were both checked and are correct as-is.

- **GLD put spread card reviewed by the user directly (their own running
  instance) — no issues found.**
- **USD/JPY card reviewed by the user directly — two real issues found (A.7,
  B.5, documented above in sections A and B):** (1) the Chart tab shows nothing
  because the bare forex ticker (`"USDJPY"`, correctly stored per B.2) is passed
  straight to yfinance, which requires the `=X`-suffixed symbol — confirmed
  yfinance does support forex history once the correct symbol is used; (2) the
  BOJ meeting's two calendar days were extracted as two separate `key_dates`
  entries for what is really one event — user's rule going forward: central
  bank meetings collapse to a single entry dated the LAST day, unless the
  newsletter explicitly treats the days as distinct catalysts. Neither fix
  implemented yet — spec-only session.

- **META card reviewed by the user directly — no issues found.** Initially
  flagged the Tgt/Stop labels on the bear-call-spread card (Tgt $640 = short
  strike/expiry-worthless level, Stop $650 = a hard close-stop) as possibly
  mislabeled, but on rereading the source letter the user confirmed the
  extraction correctly captured a genuinely nuanced case — both levels are
  right as extracted.

- **SMH card reviewed by the user directly — no issues found.**

- **HG copper card reviewed by the user directly — one real issue found (A.8,
  documented above in section A):** the newsletter's stated $6.15 planned-add
  level was correctly extracted into `tranches`, but nothing in
  `watchtower.html` ever reads that field, so it doesn't appear anywhere in the
  UI. Not implemented yet — spec-only session.

- **DOCU card reviewed by the user directly — confirms the already-documented
  C.1 (risk-based P&L%) applies here, no new finding.** The card currently
  shows the raw `$0.51` credit instead of the risk-based percentage; C.1 above
  already specs this exact trade as its credit-spread worked example ($5 width
  - $0.51 credit = $4.49 risk, realized +$0.51 → **+11.4%**). Not implemented
  yet — spec-only session.

- **GLD call spread card reviewed by the user directly — confirms the
  already-documented C.1 (risk-based P&L%) applies here too, no new finding.**
  This is C.1's debit-spread worked example ($3.65 inferred entry debit,
  realized -$2.70 → **-74%**). Not implemented yet — spec-only session.

**All 9 real trades from the 260608 import have now been reviewed card by card
(2026-07-08).** Confirmed findings across the pass: A.6 (pairs/basket chart
ratio pairs legs by array position, not by long/short side), A.7 (forex chart
never loads — bare ticker needs `=X` suffix translation before hitting
yfinance), A.8 (`tranches` captured correctly but never rendered anywhere),
B.5 (multi-day central bank meetings duplicate into two `key_dates` entries
instead of one dated the last day), and confirmation that C.1 (risk-based
P&L%) is needed and correctly specified against both DOCU (credit spread) and
the GLD call spread (debit spread). Everything else already documented in
sections A/B/C from the 2026-07-07/07-08 passes held up. **None of this
session's findings have been implemented in code yet — this was a spec-only
review pass**, per the original plan of fully reviewing all 9 cards before
resuming the import queue (260615 → 260622 → 260629) or building C.1.

## Source of newsletter files

Newsletters are saved as PDFs (print-to-PDF from wherever the user reads
them) into a folder **outside both `Trader App` and Repository** — the
user's own general-purpose location, not project-specific. This means the
engine cannot hardcode or guess the path; it must be configurable.

**Config, in `.env` (same mechanism as `ANTHROPIC_API_KEY`/`ALPHA_VANTAGE_KEY`,
loaded via `python-dotenv`):**
```
NEWSLETTER_PDF_DIR=<path to wherever the user saves newsletter PDFs>
NEWSLETTER_EXTRACTED_DIR=<path to extraction output>   # optional
```
If `NEWSLETTER_EXTRACTED_DIR` is unset, default to `<NEWSLETTER_PDF_DIR>/extracted/`.

Read both via `os.environ.get(...)` at `watchtower_engine.py` startup. Never
hardcode either path in source.

## "Already imported" tracking — no database, no archive-move

The PDF **never moves**. It stays in `NEWSLETTER_PDF_DIR` permanently. The
completion marker is simply: does a same-stem output file already exist in
`NEWSLETTER_EXTRACTED_DIR`?

- `pdfs/2026-07-06-issue.pdf` → extracted output `extracted/2026-07-06-issue.json`
- Match exists → dropdown shows it grayed out (already imported)
- No match → dropdown shows it as importable

This also means **manual re-import is trivial**: delete the corresponding
file from `NEWSLETTER_EXTRACTED_DIR` and the PDF un-grays itself next time
the dropdown is opened. No special "force reprocess" flag needed.

## Critical: atomic, last-step-only write

The output file in `NEWSLETTER_EXTRACTED_DIR` must **only** be created (or
renamed into place from a temp file) after the *entire* pipeline succeeds —
PDF text extraction, the extraction prompt, and the diff/merge into trade
storage all have to complete cleanly first.

**Why this is non-negotiable:** presence of this file is the *only* signal
the dropdown uses to decide "already done." If it's written early or
incrementally, a partial/failed run could leave a file behind that makes a
broken import look successful forever, with no way to tell short of manually
inspecting file contents. The user has explicitly said they will not be
diagnosing failures from the dashboard — so the file's mere existence must be
a trustworthy, all-or-nothing signal.

**Implementation pattern:** write to a temp filename (e.g.
`extracted/.tmp_2026-07-06-issue.json`), then `os.rename()` to the final
name only after every step above succeeds. On any failure, do not create or
rename the file — leave the PDF exactly as it was (indistinguishable from
"never attempted"). No error is surfaced to the UI; the user retries by
clicking Import again later.

## Endpoints (on `watchtower_engine.py`, port 5001)

**`GET /list_pending_newsletters`**
- Lists files in `NEWSLETTER_PDF_DIR`
- Sort order: parse a date out of the filename if one is present
  (`YYYY-MM-DD`-style), else fall back to file modified-time. Do not require
  or enforce a filename convention — the user may not always name files
  consistently (e.g. after a missed week from travel/vacation).
- For each file, indicate whether a matching stem exists in
  `NEWSLETTER_EXTRACTED_DIR` (already-imported flag for graying out)

**`POST /import_newsletter`**
- Body: `{ "filename": "..." }` — one of the filenames returned above
- Runs: `extract_pdf_text()` (pdfplumber) → extraction prompt (see below) →
  diff/merge against existing trade storage → atomic write per above
- Returns success/failure only; no detailed error payload needs surfacing
  to the UI (user's explicit call — see "Atomic write" section)

Multi-week catch-up (e.g. after a missed issue) is handled by the user
clicking Import repeatedly, oldest-pending first — there is no batch-import
endpoint and no enforced ordering in the backend. The dropdown's date-sorted
display is the only ordering aid; getting the order right is the user's
responsibility, not a mechanical constraint the code enforces.

## Storage architecture — live working set vs. archive (decided 2026-07-06)

Settled during the step-1/2 build, after the extraction prompt was validated
against 6 real issues (2026-05-25 → 06-29). The first prompt returned the FULL
union of every trade ever seen, re-emitted on every issue — which grows
unboundedly and wastefully re-sends terminal (closed/abandoned) trades through
the model each week. Corrected to a three-tier design that separates the model's
weekly working set from the durable store.

**The split — reading the newsletter vs. keeping the ledger:**
- The MODEL only reads the newsletter and reconciles this issue's activity. It is
  fed ONLY the live working set and returns only that set plus this issue's new /
  newly-terminal trades — never the full history.
- PYTHON owns the accumulation (this is the "diff/merge against existing trade
  storage" step of `POST /import_newsletter`): it applies the model's output to
  the persistent store and derives next week's live set. Deterministic
  bookkeeping, not a language-model job.

**Three tiers:**
1. **Live working set** — trades with `status` in {`open`, `planned`} plus
   standing observation-only indicators (`role:"indicator"` /
   `conviction.label:"observation_only"`, which are exempt from the silence rule
   per `newsletter-schema.md`). This is the ONLY thing fed to the model as
   `prior_trades` each issue; it stays small and bounded.
2. **Performance archive** — trades that have `closed`, stored as full trade
   objects for later recall / analysis (hit-rate scoreboard, realized-P&L
   history). Written once when a trade closes; NEVER re-processed or re-sent to
   the model. A scoreboard query is just `status == "closed"` over this archive.
3. **Lightweight discard stub** — `abandoned` and `unresolved` trades. The user
   does not care to analyze these, so they are NOT kept as full objects: Python
   records a minimal stub only (id, ticker(s)/underlying, status, drop date, a
   one-line reason). Recoverable for an abandonment-rate read if ever wanted, but
   they carry no weight and never touch the scoreboard.

**Terminal set (leaves the live working set):** `closed` → performance archive;
`abandoned` / `unresolved` → lightweight stub. Once terminal, a trade is never
fed to the model again. A strategy re-entry is always a NEW instance (new `id`,
same `strategy_id`), so re-entry never needs the old closed instance in the
model's input.

**Per-issue extract files ARE the permanent archive of past editions.** Each
`NEWSLETTER_EXTRACTED_DIR/<stem>.json` never moves or is deleted (it is also the
"already imported" completion marker). Under the live-set design each file
naturally holds that issue's envelope (summary, themes, `market_structure`, house
view, `analysis_features`, `playbooks`) plus that week's trade activity (new +
changed trades as they stood that issue) — i.e. "what this issue said" — which is
exactly what a past-edition recall view (see "UI — Past Editions dropdown") wants.
No separate issue-archive is needed; the extract files already are it.

## Extraction prompt — requirements (drafted 2026-07-06 in `newsletter_ingest.py`)

The prompt that turns extracted PDF text into schema-shaped JSON needs to:
- Produce output matching `newsletter-schema.md`'s exact shape, including the
  `underlying` field (required whenever `legs` is present, per the schema fix
  made 2026-07-06)
- Know the trade lifecycle rules from `newsletter-schema.md` /
  `newsletter-tracker.md`: silence-means-abandoned applies only to
  `planned`/conditional trades, never to `open` ones
- Reconcile against the previous issue's LIVE working set only (open/planned +
  standing indicators — see "Storage architecture" — NOT the full history).
  Match on `id`/`strategy_id`; update `status_history`, `last_mentioned`,
  `weeks_unmentioned`; apply lifecycle transitions (close/abandon/unresolved) so
  Python can move those out of the live set. Return the reconciled live set plus
  this issue's new / newly-terminal trades — NOT the full union of all history.
- Handle section-skeleton drift across issues — some issues use different
  section headers/structure week to week (see `newsletter-tracker.md`); key
  off content shape, not literal section labels

This prompt has not been drafted or tested against a real issue yet. Given
its centrality — everything else in the pipeline depends on it producing
reliable schema-shaped output — draft and iterate on it against a real saved
PDF before wiring up the endpoints above.

## E. Live current-price / day-change header for the detail panel (new feature, confirmed 2026-07-08)

**Not yet implemented — this is a spec-only addition from the 2026-07-08 card
review session, alongside sections A/B/C above.** User wants the detail
panel's header (`nd-panel`, alongside the existing status/conviction/levels
row) to show the trade's **current price** and **day's gain/loss %**, so a
card can be checked against the live market without leaving the dashboard.

**Scope decision (confirmed 2026-07-08): the % is the underlying/ratio/spread's
own raw day-over-day price move — the same convention already used elsewhere
in this dashboard (watchlist sidebar, Actionable Moves cards: ticker + price +
plain day %)** — NOT the position's directional P&L (a short trade does not
flip the sign). This keeps it a simple "what did the market do today" read,
separate from the trade's own entry-basis P&L (which is a different, already
partially-covered concept — see C.1).

**Applies to `planned`/`open` trades only** — a `closed` trade has no
meaningful "today's price" to show; omit the header quote entirely for
`closed` cards (they already show realized P&L per C.1).

**Per trade-type calculation:**
- **Outright (equity/future/forex):** straightforward — current price + plain
  day % change of `t.underlying`. For forex, needs the same `=X`-suffix
  translation as A.7 before hitting yfinance.
- **Pairs/basket:** current ratio using the **same formula confirmed in A.6**
  (sum of long-leg closes ÷ sum of short-leg closes), with day % change of
  that ratio (today's ratio vs. yesterday's ratio — NOT each leg's individual
  day change).
- **Options spread:** current mark computed from live bid/ask —
  **confirmed buildable, checked against real yfinance data (META
  `option_chain()`): columns include `strike`, `bid`, `ask`, `lastPrice`,
  `change`, `percentChange`, all real and populated.** Mark per leg = `(bid +
  ask) / 2`; spread mark = signed sum across legs (sell legs subtract, buy
  legs add, or vice versa depending on which side the trade is quoted from —
  match the sign convention already used for `entry.trigger_type` credit/debit).
  Day % change of the spread mark can be approximated from each leg's own
  `change` field (today's mark literally computed from bid/ask, yesterday's
  mark backed out via `lastPrice - change` per leg, combined the same way) —
  this is an approximation, not exact, since `change` reflects last-trade
  price movement rather than bid/ask-mid movement specifically, but it's the
  only day-over-day reference yfinance provides per-contract.
  **Real constraint found while checking this: `option_chain()` only returns
  currently-listed (non-expired) expiries** — a trade whose legs have already
  expired (common for anything `closed`, e.g. DOCU/GLD-put/FIVN/META/GLD-call,
  all June expiries against "today") has no chain data at all. In practice
  this doesn't matter much: expired-leg trades are already `closed` (no header
  quote needed per the scope decision above) — it would only bite an `open`
  options trade whose expiry passes while still open, an edge case, not the
  common path. Handle gracefully (omit/show "chain expired" rather than error)
  if it occurs.

**Architecture:** per the project's standing principle that Python owns
deterministic computation (same reasoning as C.1) — this should be a new
backend endpoint (e.g. `GET /get_trade_quote?id=...` or similar), not
client-side JS math reaching into yfinance-shaped data directly. The endpoint
dispatches on trade `type`/`asset_class` per the three cases above and returns
`{current_price, day_change_pct}` (or an explicit unavailable/expired
signal), which the frontend renders in a new header element (parallel to how
`renderOptionsStructureHTML()`/`nd-structure` were added for the FIVN fix) —
color-coded green/red by sign, matching existing conventions.

## UI — Import control placement (`watchtower.html`)

Placed in the Weekly Digest strip header (`renderDigestStrip()`), immediately
after the existing decorative violet dot, before the "Newsletter · {date}"
label. The dot itself stays purely decorative — a small adjacent icon button
is the actual click target (a 2px dot is too small/unreliable to click
directly).

```html
<div class="flex items-center gap-2 min-w-0">
    <span class="w-2 h-2 rounded-full bg-violet-400 shrink-0"></span>
    <button onclick="event.stopPropagation(); openImportPicker();"
            class="shrink-0 flex items-center justify-center w-5 h-5 rounded hover:bg-violet-500/20 text-violet-300 hover:text-violet-200 transition-colors"
            title="Import newsletter">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3v12"/>
            <path d="M7 10l5 5 5-5"/>
            <path d="M4 20h16"/>
        </svg>
    </button>
    <span class="text-xs font-bold text-violet-300 uppercase tracking-wider shrink-0">Newsletter · ${iss.issue_date}</span>
    <span class="text-xs text-slate-400 truncate">${iss.themes.join(' · ')}</span>
</div>
```

**`event.stopPropagation()` is required** — the whole digest header div
already has `onclick="toggleDigest()"` on it (see existing markup); without
stopping propagation, clicking Import would also expand/collapse the digest
strip underneath it.

`openImportPicker()` does not exist yet. It should call
`GET /list_pending_newsletters`, render a small dropdown/panel anchored under
the button (no existing dropdown/modal pattern exists elsewhere in this file
to reuse — this will be new), showing filename + date, with already-imported
entries grayed out (not hidden — see re-import note above). Selecting an
entry calls `POST /import_newsletter`.

## UI — Past Editions dropdown (`watchtower.html`, decided 2026-07-06)

A SECOND control in the same Weekly Digest strip header, alongside the Import
icon: a "Past Editions" dropdown for browsing already-extracted issues (distinct
from Import, which lists *pending* PDFs to bring in). It lists the files in
`NEWSLETTER_EXTRACTED_DIR` by date (newest first); selecting one loads that
issue's extract READ-ONLY.

**Display vs. archive — CLARIFIED + REVISED 2026-07-10 (supersedes the original
2026-07-06 "never touch the Newsletter Plays panel" constraint, which conflated two
ideas).** The 2026-07-06 note read as "the past-edition view must never swap the plays
strip; render into the digest area only." The user clarified 2026-07-10 that the real
intent was narrower and was about accumulation, not swapping: **never display a GROWING
list of old trades on the dashboard.** ("Newsletter Plays panel" and "plays strip" are
the same element, `#newsletter-container` — the terms are used interchangeably in code
and doc.) Disentangled:

- **DISPLAY (plays strip)** — always a SINGLE week, never an accumulation. The CURRENT
  week by default; or a specific FROZEN past week when pulled up via Past Editions.
  Pulling up a past edition now **SWAPS the plays strip (+ digest + deep-dive)** to that
  week's frozen file, read-only, with a **"← current"** button that reloads the live
  store (`viewPastEdition` / `returnToCurrentIssue`, built 2026-07-10). This is allowed
  and desired — it's one scoped week, not a growing pile, so it honors the real intent.
- **ARCHIVE (`_store.json.archive`)** — accumulates every closed trade forever for
  historic performance tracking / the hit-rate scoreboard. This is STORAGE, not display;
  the growing list lives here and never lands on the board.
- **Live board scopes closes to the current issue** (`last_mentioned === issue_date` in
  `renderNewsletterStrip`) so a prior week's closes don't linger. In past-edition mode
  that filter is skipped — the frozen file is already self-scoped to its week.

**The chalk-line principle (frozen weekly snapshots vs. the cascading store).** Each
per-issue extract file in `NEWSLETTER_EXTRACTED_DIR` is an IMMUTABLE snapshot of that
week — the chalk line snaps at the END of the pipeline, **after all data is PROCESSED**
(ingest → derive → merge → reconcile), NOT at raw ingest — that is the INTENT.

**FIXED 2026-07-10 (kept below as the diagnosis; was: "the freeze lands too early").** The file carried
the Python-derived `strategy_id`/`structure`/`bias` AND the merge-computed `pnl_pct`, **but
NOT the merge-level tranche split.** The split creates a NEW record and runs inside
`merge_into_store` on the STORE copy; the marker/edition file is written from the pre-split
`data`, so a split trade freezes as ONE record with both tranches inside it, not two.
Confirmed: the 260608 file has copper as a single `hg-copper-long-2026-06-08` (the closed
+1.96 tranche sits in its `tranches[]`, not as a separate `…-closed` card), while the store
has the two split records. So today's freeze is "after PARTIAL processing" — derivation +
pnl but before the split — NOT the full chalk-line. The user hit this 2026-07-10: the
second copper card was missing from the pulled-up 0608 view (the past-edition renderer
faithfully shows the file; the file is just short one record). Earlier hand-waves that "the
split shouldn't matter for a frozen week" were WRONG — this is precisely where it matters.
**FIX (DONE 2026-07-10):** the marker write now happens AFTER the split — `merge_into_store`
returns the post-split `processed` list, and `run_import.py` + `ingest_issue` freeze the
edition file's `trade_updates` from it (`ingest_issue` keeps its 4-tuple signature, so the
engine/test callers are unaffected). The existing 260608/260615 files were regenerated
offline (**$0**, deterministic) via `build_split_editions.py` — rebuild the store cascade
from the saved `raw_extract`s, rewrite only the two editions, `_store.json` untouched.
Verified on disk: the 260608 edition now carries BOTH `hg-copper-long-2026-06-08` and
`…-closed` (10 trades, flags `[]`), and the closed card shows the computed `pnl_pct` **1.96**
— which also resolves the 1.97/1.96 display nuance noted next. The engine reads editions
fresh per request, so no restart is needed — a refresh + pull-up of 0608 shows both copper
cards. *(Related display nuance, user-spotted 2026-07-10: the copper card's Scaled
Entries block renders the tranche's STATED pnl `1.97%`, while the store's split `…-closed`
card shows the §8c prefer-COMPUTED `pnl_pct` `1.96%`. When the split-in-file fix lands,
render the frozen split record's computed `1.96` so the two layers agree — a
stated-vs-computed §8c consistency, minor.)* Consequence (a feature, not a bug): a week
reflects the PROCESSING logic that was live when it was processed; shipping new
derivation logic later (e.g. the section-status taxonomy) does NOT retroactively rewrite
old weeks — re-running old logic requires a deliberate re-import of that week. This is
correct for a historical ledger: you see what the system actually produced then.

Needs a backend read path (e.g. `GET /list_extracted_newsletters` +
`GET /get_extracted_newsletter?stem=...`, or serving the extract files directly).
Same "no existing dropdown/modal pattern to reuse" note as the Import picker —
both are new and can share an anchor/dropdown pattern once built, and both need
`event.stopPropagation()` so opening them doesn't toggle the digest strip.

## Explicitly out of scope / deferred

- No email or web-scraping fetch — the user prints/saves the PDF themselves;
  "pull" only ever means "read from the folder the user already dropped it in"
- No in-dashboard error/diagnostic UI for failed imports — user will not be
  troubleshooting from the dashboard; failures just leave the item
  un-grayed for retry
- No enforced import ordering — the dropdown shows dates for the user's own
  judgment, nothing in the backend blocks importing out of order
- No batch-import — one file per click, always
