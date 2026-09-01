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
**Session 47 (2026-08-21/27) — THE DETAIL PANEL IS BUILT OUT.** The Overview tab is now Euphemus'
prototype: a day RAIL (30 days, muted beyond the ledger's reach), a SUBSTRIP with the day's reading and
a band-edge sparkline, the evidence VIEW, and footnote columns. Two FREE endpoints feed it —
`/get_factor_history` (the snapshot log already held 34 days per factor and nothing served them) and
`/get_factor_ledger` (per-model evidence; `premium_share.ledger()` re-slices the SAME `rankings_daily()`
pull `compute()` was discarding). Capability is discovered by whether a builder exports `ledger()`, so
`has_ledger:false` is the normal answer for 15 of 16 and NOT an error.
**THE `ledgers` TABLE IS THE LOAD-BEARING PART.** A re-derived ledger is not the one that was live: old
volumes re-priced with today's list move models across a premium line that is a multiple of a fast-
deflating floor — 2026-08-13 recomputes 45.9% against a recorded 27.1%, a different BAND. The scheduler
captures each day at the prices its light was decided on, keyed on the DATA date (`asof`, not write-date),
and the upsert has a DIRECTION: `recorded` may replace `reconstructed`, nothing may replace `recorded`.
Days the ledger cannot reach are MUTED in the rail rather than silently clickable.

**ARCHITECTURE, SETTLED BY THE USER (2026-08-27) — read this before "generalising" anything here.**
The SHARED thing is the CHROME: header, About box, legend, rail, substrip, footnotes, all of which
already run for 16 factors with no per-factor code. The EVIDENCE is per-factor BY NATURE — a copper
ledger would be a price table and a regulatory one a case list, and nobody will write one renderer for
both. Euphemus' prototype said the same: *only the evidence block changes shape per factor.* So the
remaining work below is a VOCABULARY FILL, not a genericisation project, and per-factor content (the
sparkline's band-edge gridlines, for instance) does not have to wait for it.

**SESSION 50 (2026-08-31) — THE PANEL IS FILLED, AND THREE SOURCES STOP BEING TRUSTED ON
FAITH.** Read this with 48 and 49 below; those are the mechanism, this is what filling the last
twelve entries taught.

**A VENDOR WINDOW IS NOT A RECORD.** capex_pressure re-asked yfinance for its quarters every poll
and took whatever the rolling window held — 5-7 quarters a name, so its own DOCUMENTED primary
arrow basis (which needs 8) could never fire, and every stored reading used a fallback the
docstring calls occasional. New `sources/sec.py` takes them from SEC XBRL and the `financials`
table keeps them: 315 quarters, back to 2008, no key and no charge. Three traps, all measured:
most quarters are filed as discrete 3-month facts but **Q4 must be DIFFERENCED out of the
year-to-date ones** (no 10-Q reports it); **AMZN switched capex tags in 2017** and "first tag with
any facts" silently truncated nine years; restatements exist (14 of them) and the latest filing
wins with the superseded value kept.

**VALIDATE A REPLACEMENT AGAINST WHAT IT REPLACES, AS A FUNCTION.** `sec.cross_check` compares
against yfinance on the 30 overlapping quarters — 25 agree within 0.5%, 0 differ, 5 are vendor
NaNs. `leverage._ratio_frame` reproduces the factor's four pinned anchors (1.85 / 1.17 / 0.61 /
2.19) exactly, three of them on the far side of a column-format change. A claim like that belongs
in code that can be re-run, not in a commit message.

**A PINNED CONSTANT CAN BE THE WRONG KIND OF NUMBER.** capex_spigot's five priors were documented
as one basis and were five: two pure GAAP, one lease-inclusive, one neither, and **AMZN's was its
GUIDANCE rather than an actual** — $6.8B under its filed number, in the direction that inflates
the light. Now derived each pass. **The period follows the GUIDANCE, not the fiscal calendar**:
MSFT's year ends in June but it guides on the calendar year, and reading its fiscal year would
have been a silent 29% error.

**COLOUR MAY MEAN DIFFERENT THINGS IN TWO VIEWS OF ONE FACTOR — SAY SO ON THE VIEW.**
capex_pressure's Direction encodes the MOVE, not the band: a rising ratio travels toward the
pro-burst end and is drawn green while its level is still red. A one-line key names it, because
the same hues mean band position one tab away.

**AN ABSENCE MUST RENDER AS SOMETHING.** A blank cell reads as "not applicable" when the fact is
"we looked and found nothing" — capex_spigot's missing ORCL pull date, infra_backlog's dark glyph,
concentration's 2007 row. Each gets a marked state and a reason instead of white space.

**A DISPLAY OVERLAY IS ALLOWED TO BE APPROXIMATE — §7.4 IS THE TEST, NOT INSTINCT.** yield_curve's
crossover overlay was cut for being "a second rule that could disagree with the light" and the
user overruled, correctly: nothing DECIDES on it. Ask whether anything downstream consumes the
value before applying determinism doctrine to a picture.

**KEEP FOOTNOTES TO ~50 WORDS.** `.ab-foot` gives each topic a ~237px column, about 35 characters
a line against a readable 45-75. Drafts of 90-110 words ran 282-299px tall; trimmed they run 165.
The numbers are load-bearing; the justification belongs in the module header.

**A LONG HISTORY BEHIND A SMALL READING RIDES ONLY WHEN `days > 1`.** The scheduler captures with
`days=1` and whatever it gets is stored permanently; the panel asks for ten. rate_path's 387-point
cloud and leverage's 331-month series are therefore never written to disk, while the capture stays
~1KB. heavy_haul does the equivalent by reading the Charts tab's payload instead of re-storing 252
bars.

**PROTOTYPE WHEN THE SHAPE IS THE QUESTION.** rate_path's two candidates were published as an
artifact on real data and the user chose the scatter — rejecting the time series because the Fed
dial already answers that question one tab away. That duplication would have been very hard to
notice after the fact.

---

**SESSION 49 (2026-08-29) — FACTORS 3 AND 4, AND THE SHAPES A LEDGER CAN TAKE.** Read this
with the session-48 section below; that one is still the mechanism, this one is what two more
factors taught about it.

**THERE ARE NOW THREE LEDGER SHAPES, AND THE CHOICE IS NOT STYLISTIC — it decides whether the
pane can contradict the light.**
| shape | who | can it disagree with the light? |
|---|---|---|
| SNAPSHOT-DERIVED | memory_canary | **No.** It re-shapes the day's own recorded `extras`, so it is reading the numbers the light was decided on. Free — no source call, on the panel or in the scheduler's capture. |
| INPUT-DERIVED | silicon_payback, regulatory | No, but only one CURRENT record exists; history accumulates print by print as the scheduler records it. |
| RE-DERIVED | premium_share | **Yes** — it re-prices old volumes at today's list, which is why the `ledgers` table and the `recorded`/`reconstructed` distinction exist at all. |
Reach for snapshot-derived whenever the evidence already rides in the payload:
`backfill_ledger_from_snapshots.py <factor_id> [--apply]` seeds the history as `recorded`, and
its whitelist refuses any factor whose ledger re-derives from a live source.

**`AB_WHY.method` MAY BE A LIST of `{k, b}` topics**, rendering as headed footnote columns
(`.ab-foot` is already an auto-fit grid, so they flow and wrap unaided). A string still renders
as one column headed Method. Use it when a note covers several subjects — memory_canary's is
Basket / Horizon / Counting, regulatory's is What counts / What it costs / The arrow.
**Keep `measures` GLANCEABLE** (user, 2026-08-29): the About box must answer "what does this
measure" in a couple of seconds. Detail belongs in the footnotes, not the header.

**A PICTURE MAY BE TWO OBJECTS.** memory_canary's band is a pips svg pinned LEFT and a canary
svg pinned RIGHT with `space-between` giving the gap the slack. One drawing can only be pinned
to ONE edge: capped it leaves the slack on the right of a wide pane, uncapped it scales the
whole band with the row (a 900px row is a 225px-tall picture). Size such a pair by **WIDTH with
`height:auto`** — flex-shrink then distributes proportionally so both keep one scale. Sizing by
HEIGHT cannot shrink and overflows a narrow band.

**A MAP IS A BUILD ARTEFACT, NOT A RUNTIME ONE.** `gen_us_map.py` → `static/js/us-map.js` (36KB,
51 pre-projected paths); the runtime only fills them. The source TopoJSON is committed against
the `*.json` ignore rule so it rebuilds from a clean checkout. Two traps, both of which looked
plausible enough to ship: **Albers increases NORTHWARD while SVG increases downward** (the map
renders upside down), and **Alaska's Aleutians cross the antimeridian**, so its bounding box
spans the globe and the mainland fits to a speck until the positive lobe is brought round by
360. Choosing a real map over a tile grid is a DECISION with a cost: seven states including
Texas cover ~25% of the land and 14% of the count, so a map overstates coverage on a
count metric. The user made that call knowingly.

**A SECOND COLOUR LANGUAGE NEEDS ITS OWN VALIDATION.** regulatory's map colours by INSTRUMENT
(`#6366f1` statute · `#ec4899` executive order · `#0e9fbf` commission rule) because the band
colour is already spoken for. Run `scripts/validate_palette.js` from the `dataviz` skill against
this panel's surface (`#0f172a`), `--pairs all` for a map: the shipped set passes lightness
band, chroma floor, CVD (worst ΔE 8.2 deutan), normal-vision (18.5 vs a floor of 15) and
contrast. **Do not substitute by eye** — the blue/violet pairs that look obviously distinct
measure ΔE 0.5 apart under deuteranopia, and the first four candidate sets all failed. Keep the
new hues clear of red/yellow/green, which mean the light.

**PROSE IN A TABLE WEARS TEXT INK, NEVER A HUE** — and never the `.sl` subtitle style, which is
9px nowrap-with-ellipsis and built for a one-line citation. A reason column in `.sl` reads as
unreadable grey mush with the long entries clipped.

**AN EXCLUSION THAT LEAVES NO TRACE CANNOT BE TOLD FROM AN OVERSIGHT.** regulatory's second view
is what it REJECTED, with reasons, and it is arguably the more useful half. Same principle
inside the extractor: the classify validator RETURNS its rejections so the scheduler can log
them, because a gate that is too strict shrinks that count in the bubble-supportive direction.

**AND THE ONE THAT COST THE MOST THIS SESSION: A SWEEP'S USER MESSAGE IS ITS SEARCH QUERY.**
regulatory's read "Sweep now: every state action in force today" and returned an EMPTY national
list with six actions quoted in its own prompt. Survivable while the leg was a yes/no delta
detector; fatal once it had to enumerate. Give every web-search leg a real multi-angle query
constant the way `_DCW_QUERY` has one — the fix cost 2 cents and immediately found two states.

---

**SESSION 48 (2026-08-28) — SILICON PAYBACK IS THE SECOND FACTOR WITH AN EVIDENCE VIEW, AND
THE PATTERN FOR THE REST IS NOW SET.** Everything below is REUSABLE — it was decided while
building factor #5 but almost none of it is about factor #5. Read this before building the
third one. Live preview of the finished panel:
**https://claude.ai/code/artifact/28241b78-440f-4b45-a302-11548df2adcc**

**THE MECHANISM — `AB_VIEWS` in `static/js/stoplight.js`.** Adding a factor's evidence is
now FILLING ONE ENTRY, not touching the panel. The chrome (rail, substrip, sparkline,
header, footnotes) knows nothing factor-specific; it asks the vocabulary:

| key | what it supplies |
|---|---|
| `views` | the switcher's list, IN ORDER — **the first is the default view** |
| `value(day)` / `reading(day)` / `light(day)` | the day's number, its display string, its band |
| `tol` | how far a re-derived reading may sit from the recorded one before the pane says so. **Per-factor because the UNITS are** — 0.05 is a rounding error on a percentage and most of a band on a 0.2-0.5 ratio |
| `count(day)` | the "· 51 models" / "· 6 inputs" suffix in the evidence header |
| `figures(day)` | the substrip pairs |
| `render(key, day, all)` | the view itself |
| `method` (optional) | names a view that renders the Method prose ITSELF; the shared footnote then stands down |

Two latent bugs surfaced the moment a SECOND factor had a ledger, and both are fixed —
do not reintroduce them: `_abLedger` was cleared AFTER the first paint on a factor switch
(invisible while premium_share was alone, a crash the moment it wasn't), and `_abView` is
sticky across factors whose view KEYS are not shared vocabulary (`lenses` vs `sources`), so
the sticky choice is now validated against the incoming factor's own list.

**CHART RULES THAT GENERALISE (they cost a session to get right; inherit them).**
- **Validate a categorical palette against THIS panel's surface (`#0f172a`), all pairs,
  before shipping it** — `scripts/validate_palette.js` in the `dataviz` skill. Numbers, not
  taste: the shipped set clears normal-vision worst dE 17.3 against a floor of 15. A first
  cut of the same NAMED colours failed at 5.7 and had to be stepped apart on LIGHTNESS.
- **Past three or four hues nothing separates under all-pairs.** The answer is FACETING —
  two separate charts, separately captioned — not a fifth hue. Verified: no step in the
  palette clears the floor against four numerator hues (orange/yellow 10.6, violet/blue
  9.8, aqua/green 11.9).
- **Spend hue only where it does a JOB.** Identity (four different companies) earns
  categorical colour. A measured-vs-implied distinction is EPISTEMIC STATUS and earns
  TEXTURE — a hatch — because a second hue there invents a second entity.
- **Label ink per mark by MEASURED contrast**, not one ink for the chart: a bright green and
  a pale ice-blue both lose white text, a dark slate loses black. This survives a palette
  change, which is why it outlived one.
- **Label placement by measured arc, not a percentage threshold** — inside only when the arc
  at the label radius is wider than the text, so the same 10% slice reads inside the large
  pie and on a leader in the small one. Leaders that stack get pushed apart; assert **zero
  label overlaps** in the rendered SVG.
- **Give the panel a HERO FIGURE.** The one number a view exists to report goes at >=48px
  in the SANS (never mono, never a display face) with PROPORTIONAL digits -- tabular ones
  give every digit the width of a zero and read loose at display size. Exactly one per
  view; a stat-strip copy at 11px is not a competing hero. silicon_payback puts it
  top-LEFT of the pie band with its band label under it, so the answer is read before the
  arithmetic that produced it.
- **Draw a ratio to AREA when there is one.** Radius as sqrt(value) makes the small pie's
  area exactly the reading (0.2479 measured off the SVG), so the number is the picture. Area
  is a weak channel for magnitude, so keep the digits on screen beside it.

**THE `asof_keyed` REGISTRY FLAG — THE ONE CHANGE THAT TOUCHED DATA ON DISK.** A factor's
snapshot row is keyed on the ET WRITE date unless `asof_keyed=True`, and for anything whose
data date lags its write date that is wrong in three ways at once: two ET days file under
one data day, a third is ORPHANED (its ledger unreachable), and the rail's weekday label
runs a day ahead of its own data — which matters, premium_share reads red on Saturdays as a
calendar artifact. `store.record_snapshot(keep_first=)` also inverts for these factors:
**the first capture of a data day wins**, because a later run at moved prices is re-pricing
it, not observing it again (2026-08-25 recorded 71.5% RED and re-priced to 49.2% YELLOW the
next morning — a different band). Live on `premium_share` and `silicon_payback` only.
`silicon_payback` is QUARTERLY, and re-keying collapsed **38 near-identical rows to the 7
prints it has actually made** — the trend its own spec says to track. Migration:
`migrate_snapshots_to_asof.py <factor_id> [--apply]`, dry-run by default, refuses to
overwrite an existing backup. **Do NOT flag `concentration` or `silicon_e`** — other code
does arithmetic on their history.

**NEVER PUT THE EXPECTED ANSWER IN AN EXTRACTOR PROMPT (2026-08-28).** silicon_payback's
`nvda_share` prompt said the figure was *"~70-75% and DRIFTING DOWN as custom silicon grows
~3x faster"*. Asked to confirm a stated range, the model returned **0.73 on every pull across
all seven prints** while only NVDA's revenue moved — a pinned constant wearing the appearance
of a refreshed input, and the cost of a billed pull each quarter for an answer decided in
advance. Pin the DEFINITION (all-accelerator vs merchant-GPU are different questions ~20
points apart); never pin the VALUE or its DIRECTION. Same principle as the newsletter spec's
extract-vs-derive split, and the same one behind keeping a trend OUT of static display copy:
a direction that is asserted cannot be observed. Check the other extractors for this — the
guard bands must not smuggle the range back in either (`validate_nvda_share` stays 0.30-1.00
deliberately). **Know the sign of the error on any ratio input**: here the denominator is
`run_rate / share`, so holding the share too LOW overstates the denominator and reads the
light GREENER than truth.

**PROVEN, same day, for 2 cents.** With the anchor removed the very next pull returned
**0.80, not 0.73** — denominator 487.7 -> 445.0, reading 0.25 -> 0.27, still yellow, no band
change. Seven identical prints had not been a stable measurement; they were the model
agreeing with the sentence that told it the answer. The remaining watch item is SOURCE
QUALITY, not the anchor: the pull returned an aggregator (Celadon Research citing IDC's Q1
2026 tracker) published 2026-05-15 — 105 days before the reading — where the prompt only
PREFERS a primary house. If a future pull needs to be tighter, require the named primaries
rather than preferring them. User accepted 0.80 (2026-08-28) as close to his own reading, on
the basis that future pulls get scrutinised through the new Published column.

**`published_at` — THE SOURCE'S DATE IS NOT THE PULL DATE (2026-08-28).** `refreshed_at` says
when WE looked; it reads fresh while pointing at a years-old market-sizing press release. The
three SOFT sources (`openai`, `anthropic`, `nvda_share`) now ask for the source's own
publication date and the Sources view shows **Published** beside **Pulled**, ageing against the
reading's date. Earnings-fed legs don't need it — `nvda_dc` pins a named quarter — so a blank
there is muted, and red stays reserved for a missing PULL date. Shape-checked in
`schemas._pub_date`: a model asked for a date will return prose or today's date, and either
would defeat the point.

**SOURCES IS A VIEW SHAPE WORTH COPYING.** Every input with its value, **the date it was
pulled**, the publisher, and a link; ages measured against the READING's own date so an old
period does not look staler each time it is opened; a missing pull date rendered in the
error colour rather than left blank. It immediately earned itself — Gemini has no pull date
recorded at all, and Copilot's is 28 days behind the reading. Derivations (a x4, a division)
are NOT sources and get a footnote, never rows that imply a publisher.

**THE ONE SHORTCUT — STATUS, session 50:** `AB_WHY` is now **16 of 16 and DONE**; `AB_VIEWS` is
13 (nine factors with two views, four with one, and copper / market_credit / net_liquidity
legend-only on purpose). The definitions are still hand-written in `static/js/stoplight.js` rather
than promoted into the factor modules, and each entry quotes the thresholds FROM its module's own
constants, so the two can still drift — promoting a structured `definition` (measures / why / bands
/ glyph) into the 16 modules remains the clean end state, and the render would not change.

**THE GLYPH VOCABULARY WAS NEVER OPEN — corrected session 51.** The line that stood here called it
"the LAST structural item still open" and proposed collapsing to one pair because "the glyph means
AGREEMENT, not direction." Both halves are wrong against a spec locked six weeks earlier:
`STOPLIGHT_DESIGN.md:16-17` (**locked 2026-07-18**) defines TWO marks on purpose — `↑`/`↓` is
**physical-stoplight POSITION** (`↓` = toward burst) and `±` is the corroborator agreeing (`+`) or
contradicting (`−`). "**Glyph rides WITH the light, not the name**" is the whole rule: the arrow
tracks where the LIGHT is heading, never the direction of the underlying number. `slGlyph` and the
`AB_WHY.glyph` legend already implement exactly that, and each factor's About box lights its own
active side. There is nothing to pick and nothing to build.
The trap this note itself fell into: reading the four emitters as if the arrow described the metric
makes them look like two rival languages (`capex_pressure`'s ratios RISE while its glyph points
`down`), and a plausible-looking table of "conflicts" follows. It dissolves the moment the arrow is
read as light-position. **A status line that outlives its own resolution is this repo's recurring
failure** — it cost session 51 a re-litigation of settled ground before a single edit.
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
