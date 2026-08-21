---
paths:
  - "AI Stoplight/**"
  - "watchtower.html"
  - "watchtower_engine.py"
  - "stoplight_*.py"
---
# AI Bubble Stoplight — BUILD SEQUENCE (start-here for the coding session)

**Status (2026-07-20, session 33): COMPLETE — ALL 16 ranked lights + Silicon E module LIVE.** The board is a
self-contained `stoplight/` package (blueprint like `engine/newsletter.py`, wired into
`watchtower_engine.py`; `GET /get_stoplight`; sidebar render in `watchtower.html` + `static/js/stoplight.js`).
All 4 EXTRACTION factors now hardened on real per-source data (locked to `stoplight_state.json` /
`extracted_inputs.json`): **silicon_payback (yellow 0.21)**, **capex_spigot (red +87%)**, **infra_backlog
(#11 YELLOW 2.9x — RED capped by the non-disclosure rule, session 38-41)**, **regulatory (#9 RED 3 states)**. Session 33 built the last two with the same per-source
machinery + a hard adversarial-hardening pass: VRT method-guard (rejects backlog-delta); GEV emits a
verbatim GW STOCK or a management-stated direction and Python derives the +/- glyph from the period delta;
regulatory's statute count is a **Python-maintained ROSTER** (model proves add/repeal deltas, Python
unions/dedupes/counts — fixed an absolute-count bug); DCW is null-safe + quote-required. STAGE1 restored to
`openrouter/auto-beta` (do NOT re-pin); STAGE2 = `claude-sonnet-5` low. Templates for any future extraction
factor: `stoplight/extractors/run.py` `run_silicon_multi` / `run_capex_spigot_multi` / `run_infra_backlog_multi`
/ `run_regulatory_multi` (focused per-source search, Python-derive, sample-and-median, pin/roster facts). Extraction
DOCTRINE + full arc: SESSIONS.md session 32 + memory [[stoplight-inference-openrouter]] +
[[stoplight-build-next-action]]. Source-oriented scheduling design: `AI Stoplight\STOPLIGHT_SCHEDULING.md`.
Billed extractor runs need explicit user go + cost estimate ([[prompt-before-billed-runs]]). Full per-factor
specs live in `Trader App\AI Stoplight\SESSION_DELTA_2026-07-18.md`; source/cadence reference =
`STOPLIGHT_SOURCES.md`. Visual = `stoplight_mockup.html` + `STOPLIGHT_DESIGN.md`.
The Tier 0-4 build plan below is HISTORICAL (executed session 32) — kept for reference on the free factors.

**Sessions 34-37 (2026-07-20→23) added, on top of the 16 lights (all $0 to build; master `b248486`..`dd897ff`,
NOT pushed):** a self-sustaining event CALENDAR (`stoplight/events.py`; weekly free yfinance earnings-date
refresh + report-session pull_date guard; seed git-tracked / live gitignored), a compact-view `D`/date rail,
and an event-driven per-source UPDATE BUTTON — earnings refresh ONLY the reporting company's leg (GOOGL never
re-pulls NVDA/MSFT), fired by a button in the AI-bubble DETAIL PANEL via `POST /run_stoplight_updates`.
`STOPLIGHT_BILLED_AUTOFIRE` stays DISARMED (the button is the sole spend path; the scheduler only flags
`pending_billed`). Verified live ($0.0333 GOOGL/gemini click). See SESSIONS.md 34-37 + memory
[[stoplight-build-next-action]]; design in `AI Stoplight\STOPLIGHT_{SCHEDULING,DESIGN}.md`.

**Sessions 38-41 (2026-07-28→08-01) hardened the BILLED PATH and added the CHARTS tab (master
`ef5a5c0`..`e4fa83d`, NOT pushed; $0.137 spend, all human-triggered).** Four rules now govern billed pulls
and should not be re-litigated: (1) `pending_billed` is a **PERSISTENT per-(factor,event) queue**
(`events.reconcile_billed_queue`) draining on per-SOURCE fulfilment — the weekly calendar roll used to
ERASE an unfired pull; (2) a row clears **ONLY on a SUCCESSFUL pull** — a failure stays queued and ALERTS
with cumulative sunk cost (user: "it's already gated by my action"), with **Check tomorrow** (snooze) and
**Clear** (dismiss, scoped to that one event) as the manual outs; (3) a quarterly leg is **PERIOD-PINNED**
to ONE named period as a DATE, and **"not published yet" is a first-class answer** — this closed a guard
evasion where a CLAIMED-but-unsourced `orders_over_revenue` slipped a wrong-quarter number past a guard
that only checks the claimed METHOD, never its inputs; (4) `_today()` is **per-call**, never module-level
(it froze at engine boot and broke same-day fulfilment). **infra_backlog is now YELLOW** — VRT stopped
disclosing book-to-bill (2 straight quarters, verified), and non-disclosure **CAPS** the light rather than
downgrading it (never reaches green). Its primary leg has NO refresh path — an OPEN item. Also: heavy_haul
rebuilt to **XTN methodology** (equal weight, quarterly rebalance, fixed base — cap weight was tested and
rejected: 3 rails are 71.4% of basket cap and would have read RED into a 13-of-16 rollover). See
SESSIONS.md 38-41 + memory [[stoplight-build-next-action]].

**Session 46 (2026-08-21) — the PER-FACTOR DETAIL PANEL started (`c6fbdd1`..`f9cb005` on master, NOT
pushed).** A BUILT factor row in the sidebar is now clickable and opens the shared AI-bubble panel with
its own header, plus a SUB-HEADER BAND (between the title header and the tabs, outside the scrolling
pane) holding an About box (measures / why) on the left and the LIGHT-SCALE LEGEND on the right — every
band a segment, the current one lifted carrying the live metric, glyph pair beneath when the factor has
one. The renderer is GENERIC: `bands` is a LIST, not a fixed trio (verified against heavy_haul's four,
incl. orange), and a factor with no definition renders a zero-height band.
**THE ONE SHORTCUT, AND THE NEXT TASK:** the definitions are hand-written in `static/js/stoplight.js`'s
`AB_WHY` with ONLY `premium_share` filled. Every factor's thresholds live as docstring prose plus loose
constants (`GREEN_BELOW`, `RED_AT_OR_ABOVE`, `GREEN_BPS`...) and `stoplight_state.json` carries none at
all. Promote a structured `definition` (measures / why / bands / glyph) into the 16 factor modules and
the legend renders for all of them — the source changes, the render does not. Settle the glyph
vocabulary in the same pass: `capex_pressure` emits `down`, `silicon_e`/`regulatory` emit `up`,
`premium_share` emits `plus`; `slGlyph` normalizes for display but a definition block should pick one
pair (plus/minus — the glyph means AGREEMENT, not direction).
A prototype of the full four-band shell (both Ledger and Two-lenses evidence views, 10 days of real
OpenRouter data) is published at claude.ai/code/artifact/0d4c13d9-266e-4953-adcc-7b7fc49b5d7c.

## READ BEFORE BUILDING (in this order)
1. `AI Stoplight/STOPLIGHT_SOURCES.md` — every factor's exact URL/method + the 3-axis taxonomy
   (cadence / catalyst / highlight). This is the "where do I get everything" authority.
2. `AI Stoplight/SESSION_DELTA_2026-07-18.md` — the 16 factor specs (measure/thresholds/caveats/events)
   + conviction ranking + update mechanics + Silicon E. The CADENCE/CATALYST/HIGHLIGHT authority pointer
   at the top of its factor-specs section supersedes any older "event/continuous" wording in a spec line.
3. `AI Stoplight/STOPLIGHT_DESIGN.md` + open `stoplight_mockup.html` in a browser — the locked visual.

## BUILD ORDER (sequenced by dependency — do NOT start with a factor builder)

### TIER 0 — architecture first (blocks everything; DESIGN AGAINST THE LIVE CODEBASE)
These are the gaps NOT specced this session, deliberately left for Claude Code because they depend on
watchtower_engine.py's existing structure:
1. **Data structure + persistence** for the 16 lights + module: how each factor's {light, metric,
   prev_metric, updated_at} is stored; whether there's a composite score or 16 independent lights + the
   module. Every builder writes into this shape.
2. **Daily snapshot-log** design (store/schema/retention). THREE things depend on it: Memory canary (#9),
   Silicon E (both need a 63-bar / last-5 history that yfinance does NOT provide), and the state-change
   detection the whole update-model uses. SQLite vs JSON — your call against the codebase.
   → Building any factor before Tier 0 exists = guaranteed rework.

### TIER 1 — fast, high-confidence builders (momentum)
3. **FRED factors** (1 Yield curve, 7 Market credit, 15 Inflation, 16 Net liquidity; #3 Rate path already
   built). One shared `fred_csv(series)` helper w/ retry/fallback, then each is a short compute. All
   live-verified this session; unit traps documented (esp. net-liq millions-vs-billions).
4. **Clean yfinance factors** (14 Copper, 11 Heavy haul, 12 Capex pressure) — verified pulling clean,
   tickers/baskets enumerated. Then **9 Memory canary + Silicon E** — but only AFTER Tier-0 #2 (they
   need the snapshot log).

### TIER 2 — key-gated + header-dependent
5. **Provision OPENROUTER_API_KEY into `.env`** (per no-hardcoded-keys rule), THEN build **4 Premium
   share** (public pull = Top-12 = insufficient; key is required, not optional).
6. **2 Concentration** — iShares `.ajax` endpoint returns HTML on naive GET; needs headers or
   Claude-in-Chrome. Fallback chain specced (yfinance market_cap → Slickcharts → ^GSPC).

### TIER 3 — extraction / earnings (Claude news-synthesis pipeline, not clean pulls)
7. **5 Silicon payback, 8 Infra backlog, 10 Regulatory, 13 Capex spigot.** Read-and-extract from
   earnings materials / trackers. Current anchors are VERIFIED (8 = 2.9× reported by VRT; 13 = +73% YoY
   reported-capex basket) — no dangling numbers to relitigate.

### TIER 4 — assembly (consumes everything above)
8. **Scheduler/invocation** — run each builder on its cadence (hourly copper, daily batch, weekly/monthly/
   quarterly catalysts). Needs all builders to exist.
9. **watchtower.html integration** — Flask endpoint (JSON shape), render fn, three `<details>` sections,
   odometer roll. `stoplight_mockup.html` is the pixel-exact visual contract; the endpoint/render WIRING
   is undesigned (design it here). Multi-file, live-in-browser → this is the real Claude Code work.

## PARALLEL / NON-BLOCKING HOUSEKEEPING
- Finish `stoplight_events.json` — it is flagged INCOMPLETE (`_INCOMPLETE` key lists the ~12 missing rows);
  authoritative source = each factor's `Events:` line in SESSION_DELTA.
- MERGE `SESSION_DELTA` → canonical `Documents\Macro Newsletters\AI_BUBBLE_STOPLIGHT_BOARD.md` — CAREFULLY:
  Rate path (#3) REPLACES the old "Fed/real rates" section; conviction ranking replaces GICS bins.
- MIRROR `Trader App\AI Stoplight\` → Repository rollback tree.
- RECONCILE: CRWV / "Debt-funded edge" is referenced by #7's credit-pair logic but is NOT in the ranked 16
  — decide: add it, fold it, or drop the reference.

## SINGLE STRONGEST RECOMMENDATION
Do Tier 0 first. The factor builders feel concrete and tempting, but the data-structure + snapshot-log
decisions are upstream of all 16 and of the update-model. Build one factor before them and you refactor it.
Tier 0 is exactly the part that needs the live codebase — which is why it belongs in the coding session,
not the chat spec work.
