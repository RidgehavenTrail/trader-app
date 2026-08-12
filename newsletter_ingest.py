"""
newsletter_ingest.py — Newsletter PDF -> schema-shaped JSON ingestion.

Pipeline: PDF -> pdfplumber text -> extraction prompt (Claude) -> schema JSON,
then a deterministic Python merge into a persistent store. Not yet wired into
watchtower_engine.py (that's the step-3 endpoints).

Design docs:
  - target JSON shape + trade lifecycle: .claude/rules/newsletter-schema.md
  - storage architecture (live/archive/discarded), live-set model, caching:
    .claude/rules/newsletter-ingestion.md ("Storage architecture")

Two cost levers are built in (see newsletter-ingestion.md):
  1. LIVE-SET MODEL — the model is fed and returns only the live working set
     (open/planned + standing indicators) plus this issue's new/newly-terminal
     trades. Python owns accumulation into the store. Output no longer grows with
     history, so per-extract cost stays flat as the store accumulates.
  2. PROMPT CACHING — the large, byte-stable instruction block is the `system`
     prompt with cache_control; only the small user message (issue text + live
     set) varies. Cache TTL is minutes, so this pays off during multi-issue
     backfills, not the weekly single-import cadence.

The prompt is CONTENT-SHAPE driven, never issue-specific: no ticker, strategy, or
section-label is hard-coded into it.
"""

# Extraction is a heavy structured task -> Sonnet 5 (stronger than the engine's
# Haiku synthesis model). Runs adaptive thinking by default.
EXTRACTION_MODEL = "claude-sonnet-5"

# ---------------------------------------------------------------------------
# EXTRACTION SYSTEM PROMPT (static -> cached)
# ---------------------------------------------------------------------------
# This block is byte-stable across every call and is sent as the cache_control
# `system` prompt. The two runtime inputs (issue text + live working set) are in
# the user message, AFTER the cache breakpoint, so they don't invalidate the cache.
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = r"""You convert one weekly issue of a markets newsletter (The Crown Macro Letter)
into a single strict-JSON object. The user message gives you two things: the
LIVE_WORKING_SET (the trades still live from the previous issue) and the
ISSUE_TEXT (this week's issue, as raw PDF text). Extract this issue into the
target schema and reconcile the live trades against it.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

============================================================================
GLOBAL RULES
============================================================================
1. PARAPHRASE, never reproduce verbatim. Every `thesis.rationale`,
   `thesis.positioning`, `summary`, `notable_flow_summary`, and `note` is your own
   condensed wording, not copied sentences.
2. KEY OFF CONTENT SHAPE, NOT SECTION LABELS. Section headers drift issue to
   issue ("Tactical Summary" vs "New Trade Setups"; "Previous Week Trade Review"
   vs "Open Trades"; "Closed/Expired this week" vs "Closed Trades"). Identify
   content by what it IS — a trade row table, per-trade prose updates, a levels
   table, a house-view table — not by the heading above it.
3. The lead "Tactical Summary" table (when present) is the SPINE. pdfplumber
   interleaves table columns, so a single logical row often arrives as scrambled
   fragments across several lines. Reconstruct each row by grouping fragments that
   belong to the same instrument (Market View / Entry-Trigger / Stop-Risk /
   Target / Sizing). When the prose sections give fuller detail for the same
   trade, MERGE them — do not emit two trades for one instrument. Match the table
   row to its prose writeup by instrument + strikes.
4. SKIP boilerplate: legal/disclaimer/"Performance Disclosure" paragraphs, the
   author bio, marketing lines ("Desk access now available"). Extract nothing
   from them.
5. If a value is genuinely absent, use null. Never invent numbers, dates,
   tickers, expiries, or conviction scores. For entry/stop/targets level fields
   specifically, see LEVEL FIELDS below — a stated range is split into two
   numeric bounds there, never left as raw text.

============================================================================
OUTPUT OBJECT — issue envelope
============================================================================
{
  "issue_date": "YYYY-MM-DD",           // from the issue's own dateline, not the PDF print/footer timestamp
  "title": "...",                        // the issue headline, own wording only if paraphrasing a subtitle
  "themes": ["...", "..."],              // 2-4 short paraphrased theme tags for the week
  "market_structure": { ... },           // see below
  "portfolio_house_view": [ ... ],       // see below
  "notable_flow_summary": "...",         // paraphrased condensation of the Notable Flow section, or null
  "analysis_features": [ ... ],          // see below; [] if none
  "playbooks": [ ... ],                  // see below; [] if none
  "trade_updates": [ ... ]               // see LIFECYCLE below; the reconciled live set + new/newly-terminal
}

--- market_structure ---
{
  "index_close": { "spx": <num|null>, "spy": <num|null> },
  "levels": [ { "spx": <num|null>, "spy": <num|null>, "label": "<normalized>", "note": "<paraphrase>" } ]
}
Normalize each level's label to ONE of:
  call_wall | hedge_wall | put_wall | gamma_flip | desk_pivot | deep_support
Map by concept, not wording: "call wall/upside ceiling" -> call_wall;
"vol trigger / regime line / reclaim improves tape" -> hedge_wall;
"zero gamma / gamma flip" -> gamma_flip; "put wall" -> put_wall;
"absolute gamma strike / dealer concentration / magnet / pivot / spec re-short" -> desk_pivot;
"downside magnet / deep support" -> deep_support. If a level truly fits none,
pick the closest and say why in `note`. A pure "Friday close reference" row that
is not itself a wall may be dropped.

--- portfolio_house_view ---
Array of { "asset_class": "...", "view": "...", "key_driver": "<paraphrase>" }.
Typically the same fixed rows every issue (equities, gold, oil, short-end rates,
long-end rates, credit, dollar). `view` is short and directly diffable
("bullish"/"neutral"/"bearish, with tactical long"). Emit exactly the rows the
issue lists — do not pad to a fixed count if some are absent.

--- analysis_features --- ([] if none)
Two variants, same bucket:
  ranking:  { "id":"...", "type":"sector_model", "title":"...", "summary":"<paraphrase>",
              "top_ranked":[...], "bottom_ranked":[...], "linked_theme": <theme|null> }
  deep_dive:{ "id":"...", "type":"deep_dive", "title":"...", "summary":"<paraphrase>",
              "top_ranked": null, "bottom_ranked": null, "linked_theme": <theme|null> }
Capture only the useful ends of a ranking (top/bottom names), not the full table.
`linked_theme` must be one of this issue's `themes[]` or null.

--- playbooks --- ([] if none)
A standing conditional rule that can fire against a BRACKET of candidates (not a
single trade), e.g. "short a country's home index the session after elimination".
{ "id":"...", "role":"indicator", "trigger_rule":"<paraphrase>",
   "candidates":[ { "entity":"...", "index":"...", "next_event_date":"YYYY-MM-DD|null", "status":"pending|..." } ],
   "sizing_per_trigger": <num|null>, "hold_sessions": "<text|null>" }

============================================================================
TRADE OBJECTS (trade_updates)
============================================================================
Each is a persistent entity. You emit PRIMITIVES ONLY — the raw facts read from
the prose. A deterministic Python layer DERIVES everything computable from them
(`structure`, `asset_class` for baskets/options, `structure_label`, `bias`,
`strategy_id`, `pnl_pct`, `risk_capital`) and OVERWRITES whatever you put in
those, so don't agonize over them — get the primitives right. Field list:
  id, conviction {scale,max_scale,label}, indicates, linked_theme,
  underlying, underlying_alias, asset_class, direction, beta_neutral,
  basket, legs, greeks, sizing {risk_unit,note}, tranches[],
  entry {trigger_type,level,level_high,note}, entry_price, exit_price,
  stop {level,level_high,basis,note}, targets[] {label,level,level_high,note},
  reference_values{}, thesis {rationale,positioning}, campaign_title,
  key_dates[], holding_period {stated_text,min_weeks,max_weeks},
  is_core_position, overlay_of, paired_with, pairing_note, package_id,
  first_seen, last_mentioned, source_section, status, stale_flag, weeks_unmentioned,
  status_history[] {date,status,pnl?,exit_price?,note?}
(No `type`, `role`, `structure`, `structure_label`(non-options), `strategy_id`,
`positioning_note`, or `pnl_pct` — those are dropped or Python-owned.)

PICK EXACTLY ONE CONTAINER — this is how Python derives the trade's structure:
- OPTIONS structure (spread/condor/collar/overlay/single) -> populate `legs`,
  set `underlying` = the single ticker the options are written on (REQUIRED),
  `basket` = null. Per-leg shape:
    {strike, expiry, type:"call"|"put", action:"buy"|"sell", quantity, note?}
  * `quantity` = number of contracts for that leg (1 for a plain vertical; 2 vs 1
    for a ratio spread). Default 1 when the letter implies an even spread.
  * `note` (optional) = any per-leg context the letter gives (why a strike, a leg's
    role). Omit when none.
  * LEG-EXPIRY CONSISTENCY: every leg of a SAME-EXPIRY structure (any vertical,
    condor, strangle, straddle, collar) MUST carry ONE shared expiry. If one leg
    is quoted more precisely than another ("short Jun 18, long June"), propagate
    the PRECISE date ("2026-06-18") to ALL legs. Only a calendar/diagonal
    legitimately has legs at different expiries. If only a month is stated and no
    day, use "YYYY-MM" and do not invent the day.
- PAIRS / multi-ticker basket -> populate `basket`
  [{ticker, side:"long"|"short", weight, entry_price?, exit_price?, note?}],
  `underlying` = null, `legs` = null.
  Same-direction multi-ticker holdings (all long) are still a basket. Per-component
  `note` (optional) = any context on that ticker (its role/rationale in the basket).
  `entry_price` / `exit_price` (optional, per component) = that ticker's stated
  ENTRY or CLOSING mark when the issue prints per-name prices — e.g. a close reading
  "sold XLV at 159.92, XLP at 84.87, XLF at 53.55, covered IGV at 86.96" fills each
  component's `exit_price`. Bare number, native price. `weight` is beta-neutral
  SIZING only — never fold it into the price; the composite ratio is computed straight
  up from the raw prices (Σ long prices / Σ short prices), so leave the marks raw.
- PLAIN SINGLE-NAME OUTRIGHT (one equity/ETF/future/forex, no options) -> put the
  one instrument in `underlying`; `basket` = null, `legs` = null.

MULTI-UNDERLYING OPTIONS PACKAGE -> ONE TRADE OBJECT PER UNDERLYING (never one
combined). When a SINGLE newsletter trade line describes a funded/linked options
structure spanning MULTIPLE DIFFERENT underlyings — e.g. "long QQQ Jul17 735/715
put spread, funded by selling CRM Jul17 165/180 call spread and HUBS Jul17 200/220
call spread" — do NOT collapse it into one object with the other names' legs stuffed
into `reference_values`. Emit a SEPARATE trade object for EACH underlying (a QQQ
object, a CRM object, a HUBS object), each with its own `underlying`, its own `legs`
(that underlying's legs only), its own entry/exit prices, and its own `status`.
- Give every object from the same package the SAME `package_id` — a short slug naming
  the package (e.g. "qqq-crm-hubs-downside-convexity"). `package_id` is null on every
  ordinary trade; only a multi-underlying package fills it.
- Each object's `status` is INDEPENDENT, and so is its `source_section`. A package is
  usually printed under ONE section (e.g. Open Trades), but its legs can be at different
  lifecycle points. Because each object is SYNTHETIC (there is no separate physical
  newsletter line for one leg), set each object's `source_section` from THAT LEG's own
  reported disposition, NOT the package's printed section: a leg the issue reports as
  closed -> `source_section:"closed"` + `status:"closed"` + fill its `exit_price`; a leg
  still held -> `source_section:"open"` + `status:"open"`. Do NOT force one shared
  status/section across the package (that would flip a closed leg back to open).
- The package's NET cost (e.g. "net package cost $0.45") is a package-level figure, not
  a per-object P&L basis — record it once in `reference_values.package_net_cost` on any
  one member; each object's own entry/exit prices drive its own P&L.
This is the SAME two-object discipline as a covered call (core + overlay), one level up.
A single-underlying multi-leg structure (an iron condor, a collar — all legs on ONE
name) is NOT a package: keep it as ONE object with all legs in `legs`.

EQUIVALENT VEHICLES ARE ONE OUTRIGHT, NOT A BASKET. An index + its tradeable ETF
proxy for the SAME exposure (SOXX/SMH, SPX/SPY) is a single outright: put the
tradeable vehicle in `underlying` (SMH, SPY) and the index in `underlying_alias`.
A `basket` is only for genuinely distinct holdings (a long/short pair, a
dispersion basket). `underlying_alias` MAY cross asset classes: a GLD call spread
quoted with a "GC (gold future) reference" -> `underlying:"GLD"`,
`underlying_alias:"GC"`, commodity-price levels in `reference_values`.

`underlying` MUST be a BARE ticker exactly as the newsletter names it — "HG",
"GLD", "USDJPY". Never a parenthetical ("HG (front-month copper future)" -> "HG"),
never a data-provider symbol (no "=F"/"=X" — that suffix is derived downstream
from asset_class, not stored here).

`asset_class`: emit it ONLY for a single-name OUTRIGHT, as one of
{equity, future, forex}, read from the prose (a "copper future" -> future, a forex
pair -> forex, a stock/ETF -> equity). For baskets and options Python forces
`equity`, so you may omit it there.

`direction`: "long" | "short" for an OUTRIGHT (the stated side, never inferred
from sentiment). null for options and baskets (their side is per-leg `action` /
basket `side`).

`bias` (OPTIONS only, optional): "bullish" | "bearish" | "neutral" when the issue
states or clearly implies a directional lean on the options structure; null for a
pure-vol/ambiguous play. Omit for outright/pairs — Python fills those.

`structure_label` (OPTIONS only): your best canonical snake_case name
(bear_call_spread / bull_put_spread / iron_condor / calendar / collar /
covered_call / cash_secured_put / strangle / ...). Python re-derives it for
structures it recognizes and only keeps yours for an exotic it can't name, so
close-enough is fine. Null/omit on outright and pairs.

`greeks` (OPTIONS only, optional): record a trade-level Greek exposure the issue
STATES ("short vega", "30-delta call", "long gamma on the trade") — do NOT compute
one. Shape [{greek, exposure?, value?, note?}], e.g. {greek:"delta", value:30},
{greek:"vega", exposure:"short"}. Omit when none stated. (Dealer/positioning gamma
or an index gamma-flip level is market_structure, not a trade greek; beta belongs
to the equity/pairs side, never here.)

COVERED CALL = TWO OBJECTS: (1) the persistent equity-core outright (continues
untouched); (2) the short call written against it — a one-leg options trade with
`overlay_of` = the core's id and `structure_label:"covered_call"`. When the call
expires the overlay goes `closed` (premium is its P&L) and the core continues. A
roll = close the old overlay, open a new one `overlay_of` the same core.

CONVICTION:
- Dot rating "●●●●○" -> {scale:4, max_scale:5, label:null}. Count FILLED dots
  for `scale` AND count the TOTAL dots (filled + empty) for `max_scale` — do
  NOT assume a fixed 5-dot scale. Some issues use a 4-point scale ("●●●○" ->
  {scale:3, max_scale:4, label:null}); read whatever is actually printed.
- An OBSERVATION/INDICATOR-ONLY trade -> {scale:null, max_scale:<total dots
  the issue uses elsewhere, or 5 if no dot rating appears anywhere in this
  issue>, label:"observation_only"|"watchlist"} and set `indicates` (what
  broader question it proxies) + `linked_theme`. This label is the ONLY
  indicator marker (there is no `role` field); it exempts the trade from the
  silence rule and routes it to the weekly digest instead of the plays strip.
- No rating given -> {scale:null, max_scale:<same fallback as above>,
  label:null}.

LEVELS & PRICES:
- entry/stop/targets hold ACTIONABLE levels only. Informational anchors ("spot
  reference", "reference credit", "200-DMA value", COT counts) go in
  `reference_values`, never in entry/stop/targets.
- PAIRS: a pair's entry/stop/target `level` is a RATIO (the composite spread level,
  e.g. "enter at ratio 3.01"), NEVER a single leg's own price. If the issue does NOT
  state a ratio — the entry/stop is a per-leg price CONDITION instead ("enter after
  SOXX closes below its 50DMA while IGV holds above its own") — leave that `level`
  NULL, put the condition in the sibling `note` (it surfaces in the trigger display),
  and put any raw single-leg reference numbers (a leg's 50DMA, spot) in
  `reference_values` (e.g. `soxx_50dma`, `igv_50dma`). NEVER put a leg's raw price
  (545.63) into a pair's `entry.level`/`stop.level` — that field is ratio-only.
- Every `level` field (in `entry`, `stop`, each `targets[]`) MUST be a bare number
  ("$6.68" -> 6.68; strip currency/units). A stated RANGE ("$0.70-$0.80") puts the
  lower bound in `level`, the upper in `level_high` (else `level_high` null).
- TARGETS ARE NUMERIC ONLY — never prose, never null. Each `targets[]` entry is a
  real price `level` (or 0 for an expires-worthless credit spread, per below). A
  purely QUALITATIVE "target" with NO stated number (e.g. SMH "continued
  outperformance after the pullback") is NOT a target — do NOT emit a `targets[]`
  entry for it. The guidance is still useful: put it in a `status_history` note
  (`{date, status, note:"<the guidance>"}`) instead. Do not carry qualifying prose
  in a `targets[].note`.
- For `entry`/`stop` only: a `level` may be null when no number is stated (never
  invent one), and qualifying language ("do not chase below $0.60", "confirm on a
  Monday close above") goes in that field's sibling `note`, NEVER in `level`; don't
  repeat the ticker/"credit"/"debit"/strategy name in `note`.
- `entry.trigger_type` — CLOSED ENUM, pick exactly one:
    market         = enter now, no condition
    level          = enter when price/ratio REACHES entry.level (a limit — a dip
                     buy, a pullback-to-X, a ratio level)
    stop           = enter on a breakout THROUGH entry.level in the momentum
                     direction (a buy-stop / sell-stop)
    premium_target = options: open when the spread hits entry.level credit/debit
    scaled         = multi-tranche entry; the tiers live in `tranches[]`
    pre_existing   = carried from before the tracking window; no entry action now
  Nuance ("on a pullback", "do not chase") goes in entry.note.
- `entry_price` / `exit_price` — the RAW transaction levels in native unit (dollars
  for options/outrights, a ratio for pairs). For an options CREDIT spread,
  `entry_price` is the CREDIT collected; for a DEBIT spread, the DEBIT paid.
  `exit_price` is the closing mark (0 for a spread left to expire worthless).
  Capture when stated — they are the primary input Python uses to compute pnl_pct.
  Omit when the issue states neither.
- EXPIRES-WORTHLESS TARGET: a credit / defined-risk spread's max profit is the
  spread expiring worthless = going to ZERO, so emit its target `level` as 0 (a real
  number, never a prose label): {label:"expiration_worthless", level:0}. Do NOT emit
  the short strike as the target (it is already in `legs`; repeating it fabricates a
  price to hit). A genuine directional structure with a real price target keeps its
  numeric `targets[]`.
- `tranches` — one record per scaled slice, a TYPED ENTITY (not an event log):
    {size?, entry_price?, entry_date?, status:"open"|"closed"|"planned",
     exit_price?, exit_date?, pnl?:{value,unit}, note?}
  `size` = the CUMULATIVE position weight the newsletter states AFTER this slice —
  this source scales toward a full 1.0 and never above it, so a "starter half" is
  size 0.5 and an "add to 1.00" is size 1.0 (the running TOTAL, not the increment
  added). Python differences consecutive sizes to get each slice's incremental
  weight for the blended cost basis. Leave null only if the issue states no size.
  `note` (optional) = per-slice context: the trigger CONDITION for a `planned` add
  ("add on a ratio close >3.22 or z>0"), or the close reasoning for a `closed` slice
  ("trailed-stopped at ATH resistance"). This is the per-tranche home for context
  that would otherwise be stranded in trade-level `entry.note`.
  status: `open` = a FILLED slice still held; `closed` = a filled slice exited
  (carries exit/pnl); `planned` = a scaled ADD level the issue NAMES but that has
  NOT yet triggered — set `entry_price` = the stated trigger/add level and leave
  entry_date/exit_price/exit_date/pnl null.
  ALWAYS capture a stated planned add as a `planned` tranche (e.g. copper "add at
  $6.15", the pair "add on a ratio close above 3.22") — do NOT drop it and do NOT
  bury it in `entry.note`; the tranche is its structured home.
  entry_price absent = the slice predates tracking / held-from-prior with no
  stated fill; exit_price absent = still open. A `closed` slice needs enough to
  derive its P&L (entry+exit, OR exit+pnl, OR a stated pnl %); if it has none,
  still emit it (Python flags it) — never drop a realized slice. When a position
  has BOTH a closed slice AND an open slice (partial close + re-entry), keep it as
  ONE trade carrying ALL its tranches — Python deterministically splits it into a
  closed record + an open record (planned adds ride with the open record) sharing
  one lineage. Do NOT pre-split it, and do NOT bury a close in a note.
- `pnl` (in status_history or a tranche) = {value, unit}, unit in
  {pct, usd_per_share, usd_total, points}. Single-instrument (options/outright)
  use usd_per_share/usd_total/points/pct; pairs/ratios use pct (or points for a
  raw ratio-point move), NEVER usd_*. Use the issue's own sign. `pnl_pct` is NEVER
  yours — Python computes it.
- `thesis` = {rationale, positioning}:
    rationale   = the trade's FULL reasoning in your words — why it's on, what
                  confirms/invalidates it. Justify it; do not compress to a
                  one-liner.
    positioning = THIS issue's CoT / futures-positioning read tied to THIS trade
                  (raw numbers fine), as a plain string; null when THIS issue states
                  no positioning for it. Report ONLY what this issue says — do NOT
                  carry over or restate a prior week's positioning. Python keeps the
                  dated history across issues, so a week with no new read is just null.
  (No separate positioning_note field — it folds in here.)
- `holding_period` only when an explicit duration is stated ("2-4 Week Hold").
- `campaign_title` only when the issue names one; never invented.
- `key_dates`: [{date, event, significance:"<paraphrase>", passed:false}] from a
  catalyst calendar tied to THIS trade. Always emit `passed:false` (display
  computes it live; do NOT compute it from the issue date). Collapse a multi-day
  central-bank meeting to ONE entry dated the LAST (decision/announcement) day,
  unless the issue treats the days as separate distinct catalysts.
  * Capture EVERY catalyst the issue ties to the trade — NOT just the single
    "resolution"/primary one. A trade watched into MULTIPLE events (e.g. a USDJPY
    short watched into BOTH the BoJ decision AND the FOMC decision the same week)
    gets an entry for EACH; do not keep one and drop the others. In particular,
    sweep the issue's "What we are watching" (or equivalent) macro-catalyst list
    for any event bearing on this trade's underlying (FOMC/BoJ/CPI/NFP/OPEC/
    earnings): if the issue links it to the trade's thesis or instrument, it is a
    key_date. (Guard against noise: only events the issue actually ties to THIS
    trade — do not attach every macro event in the issue to every trade.)
- `overlay_of` / `paired_with`+`pairing_note` — populate ONLY on the issue's
  EXPLICIT statement of the relationship; never infer from theme or proximity.
- `is_core_position`: true ONLY when the letter explicitly excludes the position
  from tactical-book P&L ("not including this in our performance illustration").
  Descriptive "core position" wording alone is flavor, not the exclusion.

============================================================================
LIFECYCLE — reconcile against the LIVE_WORKING_SET
============================================================================
You are given the LIVE_WORKING_SET ONLY: the previous issue's `open` + `planned`
trades plus any standing observation-only indicators. You are NOT given closed,
abandoned, or unresolved trades from earlier issues — those are archived
downstream and never come back to you. Therefore:

`trade_updates` MUST contain exactly:
  (1) every trade in the LIVE_WORKING_SET, reconciled with this issue (status and
      fields updated; return it UNCHANGED if nothing changed) — do not drop one;
  (2) any NEW trade this issue introduces;
  (3) any live trade that became TERMINAL this issue (closed / abandoned /
      unresolved) — emit it ONCE with its terminal status so the store records the
      transition. Downstream code moves it out of the live set; you never carry a
      terminal trade forward again.
Do NOT invent or re-emit terminal trades from earlier issues (you weren't given
them). Do NOT emit the full history.

MATCHING: match a live trade to this issue's mentions by `id`; if ids differ but
it is clearly the same live instrument+structure, match on the live set's
`strategy_id` (Python-derived, present on the trades you are given). Carry
`first_seen` and the existing `status_history` FORWARD unchanged; never reset
them. (You do not emit `strategy_id` — Python re-derives it.)

FOR A TRADE MENTIONED THIS ISSUE:
- set `last_mentioned` = this issue_date, `weeks_unmentioned` = 0.
- append a `status_history` entry {date:issue_date, status, pnl?, exit_price?, note?}
  when ANY of these is true this issue: (a) the status changed, (b) the issue reports
  a P&L, or (c) a MATERIAL risk parameter changed (stop, target, or sizing — e.g. a
  stop tightened/added, a target revised). For (c), keep `status` unchanged and
  add a short `note` describing the change (the audit trail). `pnl` = {value:<num>,
  unit} with unit in {pct, usd_per_share, usd_total, points} (pairs/ratios use pct/
  points, never usd_*), using the issue's own sign. Do NOT log an entry for pure
  wording/thesis rephrasing — only genuine parameter or status/P&L changes.
- ON A CLOSE, additionally capture `exit_price` (a bare number) on that closing
  entry whenever the issue states the price/value the position was CLOSED at — for
  an options spread this is the spread's closing mark (the debit/credit it was
  bought-back or sold-to-close at, e.g. "cut the 425/450 call spread at $0.95"); for
  an outright it is the exit price. This is SEPARATE from
  `pnl` (the realized gain/
  loss) — capture both when both are stated. `exit_price` is what lets risk% be
  computed for a defined-risk spread whose ENTRY economics predate the imported
  window (entry debit/credit never restated): the entry cost is then inferred
  downstream as exit_price − pnl. Omit `exit_price` only when the issue gives no
  closing price at all.
- update status per the state machine below.

OBSERVATION-ONLY INDICATORS GET A LONGER SILENCE LEASH, NOT PERMANENT EXEMPTION.
A trade whose `conviction.label` is "observation_only"/"watchlist" is a STANDING
watchlist read, not a position. It is NOT abandoned or marked unresolved by a
SINGLE issue of silence (it recurs intermittently). A reference to its theme OR
any of its constituent tickers anywhere in the issue counts as a mention — set
`last_mentioned` = issue_date, `weeks_unmentioned` = 0, and carry it forward at
its existing status. When it is NOT referenced, INCREMENT `weeks_unmentioned`
(carry the trade forward at its status) — this is load-bearing: Python lapses the
indicator to a discard stub once it goes unreferenced for a couple of issues (an
off-ramp so a stale read doesn't linger forever). So track `weeks_unmentioned`
faithfully; Python owns the actual retirement decision. It is also retired
immediately if the issue explicitly drops it ("no longer watching / removing this
basket"). (This handles the software winners/losers dispersion basket, whose theme
and constituents recur without the basket itself being restated each week.)

FOR ANY OTHER LIVE TRADE NOT GIVEN A TRADE-LEVEL UPDATE THIS ISSUE (asymmetric
silence rule). A "trade-level update" = a status/entry/exit/stop line in the
tactical table, the closed list, or a per-trade review — NOT the ticker merely
appearing in market commentary (Notable Flow, What's New, another trade's
rationale):
- if its status was `planned`/conditional-not-triggered, look at whether its
  underlying/ticker appears ANYWHERE in this issue's commentary:
    * ticker NOT present anywhere -> truly silent -> status `abandoned`. Append
      {date:issue_date, status:"abandoned"}.
    * ticker present in commentary (its thesis is discussed, e.g. "the software
      crack we forecast arrived") but the TRADE is not tracked -> status
      `unresolved`, NOT abandoned. Append {date:issue_date, status:"unresolved",
      note:"<why: ticker discussed as thesis playing out, but no trade-level
      trigger/entry/status given — could be abandoned OR triggered-but-untracked;
      preserved for manual judgment>"}. This protects a trade that may have
      quietly triggered/worked from being erased as abandoned.
- if its status was `open`/active -> DO NOT close it. Increment
  `weeks_unmentioned`; if >= 2, set `stale_flag`:true. Keep tracking, leave
  `last_mentioned` at its prior value, and still emit it (it stays live).

`source_section` — which SECTION BUCKET this trade sits under in THIS issue. Be
CONSERVATIVE: only use `open`/`closed` when the section UNAMBIGUOUSLY implies that status;
otherwise use `review` and let the fill mechanics decide. ONE of:
  new      = a NEW trade setup / idea introduced this issue
  closed   = an explicit Closed / Expired / stopped-out trade
  open     = a section that UNAMBIGUOUSLY states these are currently-HELD positions
             (explicit ownership) — NOT merely "reviewed"
  watching = an observation-only / watchlist read (What We're Watching)
  review   = a FUZZY / mixed heading (Tactical Summary, Previous Week Trade Review) that
             spans held + closed + never-triggered trades, so it implies NO status; also for
             any carried trade whose status is not obvious from its section
  null     = under NO section this issue (terminal by silence — abandoned/unresolved)
Identify the BUCKET by CONTENT SHAPE per GLOBAL RULE 2, never the literal header. Python
derives `status`: closed->closed, open->open, watching->observation; new/review/null -> from
your `status` + the fill mechanics (a NOT-YET-TRIGGERED conditional is `planned` regardless
of section). KEY: a trade a review explicitly says did NOT trigger is `review`, never `open`.
You STILL set `status` per the ENTRY MECHANICS below (used for new/review/null).

STATUS `open` vs `planned` — ENTRY MECHANICS DECIDE, NOT PROSE ENTHUSIASM. A
trade is `open` only when the issue confirms it is actually held: explicit
ownership ("own at $X", "we entered / we are long/short", "hold" an existing
position, a reported P&L, or a tranche stated as filled or stopped). A trade
whose entry is still described as levels to ACT ON — a sell-stop, "enter on a
close above / a pullback to X", or a SCALED / TWO-TIER entry (e.g. "$6.45 half,
$6.30 add") with no confirmed fill — is `planned`, EVEN IF the surrounding prose
is bullish about the setup ("breakout confirmed three weeks ago, held through
pullbacks"). A tiered entry in the tactical table is a plan to scale in, not
evidence the position is on; the entry column outranks the narrative. Put the
tiers in `tranches` with `entry.trigger_type:"scaled"` and keep status `planned`
until a later issue reports ownership or P&L — at which point transition
planned -> open (same `strategy_id`).

STATE MACHINE:
  planned -> abandoned (silent AND ticker absent) | unresolved (trade-silent but
             ticker discussed) | triggered->open (entry hit)
  open    -> open (stale_flag if unmentioned >=2 issues) | closed (EXPLICIT
             "closed/covered/stopped/expired" only) | deleted (manual only)
Silence NEVER closes an `open` trade. For a `planned` trade, silence yields
`abandoned` only when the ticker is wholly absent; otherwise `unresolved`.

COLD START (LIVE_WORKING_SET == []): every trade this issue is new. Set
`first_seen` = issue_date, `last_mentioned` = issue_date, `weeks_unmentioned` = 0,
and seed `status_history` with a single {date:issue_date, status} entry (include
this-issue P&L if reported). Do not fabricate earlier history even when the prose
implies the trade predates our tracking — note the stated original entry inside
`thesis`/`reference_values` instead.

IDs: emit only `id` — a stable per-instance slug from underlying/structure/date,
e.g. "meta-jun640-670-bearcall-2026-05-25", "tlt-long-2026-05-25". Do NOT emit
`strategy_id` (the cross-time lineage key) — Python derives it from the taxonomy
fields so re-entries/rolls group deterministically.

Return the single JSON object now."""

# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------
import os
import io
import re
import copy
import json
import contextlib
import warnings
import datetime

# A trade leaves the live working set when it reaches one of these. `closed` is
# archived as a full object (the performance scoreboard); `abandoned`/`unresolved`
# are kept as lightweight stubs only. See newsletter-ingestion.md.
ARCHIVE_STATUSES = ("closed",)
DISCARD_STATUSES = ("abandoned", "unresolved", "lapsed")
TERMINAL_STATUSES = ARCHIVE_STATUSES + DISCARD_STATUSES

# Off-ramps for NEVER-ENTERED live trades (user, 2026-07-11) — "at some point the
# trade is no longer relevant; there has to be an off-ramp, especially if there's
# never an entry." The indefinite no-auto-close protection is reserved for
# genuinely-ENTERED positions (real risk); anything never entered eventually lapses.
LAPSE_INDICATOR_SILENCE = 2        # an observation_only/watchlist indicator lapses after
                                   # this many issues with no theme/constituent reference
LAPSE_CONDITIONAL_MAX_WEEKS = 4    # default max age for a never-triggered conditional
                                   # (used only when the trade states no holding_period)


def extract_pdf_text(pdf_path):
    """Extract text from a newsletter PDF via pdfplumber.

    Page-delimited (matching what the prompt was validated against). pdfplumber's
    FontBBox warnings on this publisher's PDFs are noise — suppressed here so the
    text (which extracts fine) isn't drowned out.
    """
    import pdfplumber
    parts = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stderr(io.StringIO()):
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    parts.append(f"\n===== PAGE {i + 1} =====\n{page.extract_text() or ''}")
    return "".join(parts)


def _build_user_message(issue_text, live_working_set):
    """The volatile per-call content: live set + issue text. Kept OUT of the
    cached system prompt so it never invalidates the cache."""
    # C.13: strip each live trade's positioning HISTORY before the model sees it —
    # the model emits only THIS issue's positioning read (fresh from the issue text)
    # and can't echo the prior list, since it never sees it. Python owns the history.
    ls = copy.deepcopy(live_working_set) if live_working_set else []
    for _tr in ls:
        _th = _tr.get("thesis") if isinstance(_tr, dict) else None
        if isinstance(_th, dict) and "positioning" in _th:
            _th["positioning"] = None
    live_json = json.dumps(ls, indent=2, ensure_ascii=False)
    return (
        "LIVE_WORKING_SET (the trades still live from the previous issue — open/"
        "planned + standing observation-only indicators; [] on a cold start):\n"
        f"{live_json}\n\n"
        "ISSUE_TEXT (raw pdfplumber text; page headers/footers and the recurring "
        "URL line are noise — ignore them):\n"
        "<<<ISSUE_TEXT\n"
        f"{issue_text}\n"
        "ISSUE_TEXT\n"
    )


def _extract_json(text):
    """Pull the JSON object out of a model response, tolerating fences/prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t[:4].lower() == "json":
            t = t[4:]
        t = t.strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            t = t[i:j + 1]
    return json.loads(t)


def _count_tokens(text, model=EXTRACTION_MODEL):
    """Real Anthropic token count for a piece of text via /v1/messages/count_tokens
    (tokenization only, no generation — not a billed model call). Used to split a
    streamed response's combined output_tokens into thinking vs. final-text, since
    the Messages API only reports the combined total, never the breakdown."""
    if not text or not text.strip():
        return 0
    api_key = os.getenv("ANTHROPIC_API_KEY")
    import requests
    r = requests.post(
        "https://api.anthropic.com/v1/messages/count_tokens",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": model, "messages": [{"role": "user", "content": text}]},
    )
    return r.json().get("input_tokens", 0)


def run_extraction(issue_text, live_working_set=None, model=EXTRACTION_MODEL,
                   max_tokens=64000, timeout=300, effort=None):
    """Run the extraction prompt against the Anthropic API; return (data, usage).

    Raw-HTTP pattern matching watchtower_engine.py (no anthropic SDK dependency).
    The static instruction block is the `system` prompt with cache_control; the
    small user message (live set + issue text) is the only per-call variable
    content. `data` is the parsed schema dict; `usage` includes cache-hit counts.
    Raises on a missing key / API error / JSON error — the caller decides what to
    do (per the atomic-write rule, a failure must leave no output file behind).

    max_tokens is a CEILING, not a cost — only actual output tokens bill. The
    live-set model shrinks *actual* output on later issues (live set + this
    issue's activity, not the full union), which is the cost win; but a cold
    start or a busy week still emits many trades plus ~8k thinking, so keep 64k
    of headroom to avoid truncation (raised from 32k after the 260615 incremental
    import — 7-trade live set re-emitted + new trades + thinking — truncated at 32k).

    STREAMED (not a single blocking POST): with max_tokens this high, a cold-start
    extraction can take longer than any fixed read timeout to generate, and a
    non-streaming request would ReadTimeout mid-generation (the original bug). With
    stream=True the `timeout` becomes a PER-CHUNK read timeout that resets on every
    SSE event, so total wall-clock can far exceed it as long as tokens keep
    arriving — which is exactly the behavior a long extraction needs.

    effort: None (omit -> claude-sonnet-5's API default, "high") or one of
    "low"/"medium"/"high"/"xhigh"/"max" — passed through as `output_config.effort`.
    Built for the Layer-0 cost experiment; see newsletter-ingestion.md "Token/
    reasoning-cost investigation & optimization game plan (2026-07-08)".

    Thinking is now explicitly requested with display:"summarized" (previously
    omitted entirely — the API defaults to display:"omitted" on Sonnet 5, meaning
    thinking blocks streamed with EMPTY text even though they were generated and
    billed). `usage` now additionally carries `thinking_tokens`, `final_tokens`
    (the real output split, via `_count_tokens` above — the Messages API only
    reports a combined total) and `thinking_text` (the actual captured reasoning,
    for qualitative review — previously 100% discarded, never logged anywhere).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        raise RuntimeError("ANTHROPIC_API_KEY missing — copy .env into the worktree or export the key.")
    import requests
    text_parts = []
    thinking_parts = []
    usage = {"input_tokens": None, "output_tokens": None,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    stop_reason = None
    api_error = None

    request_body = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "system": [{
            "type": "text",
            "text": EXTRACTION_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{"role": "user", "content": _build_user_message(issue_text, live_working_set)}],
    }
    if effort is not None:
        request_body["output_config"] = {"effort": effort}

    with requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=request_body,
        timeout=timeout,
        stream=True,
    ) as resp:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload:
                continue
            try:
                evt = json.loads(payload)
            except ValueError:
                continue
            etype = evt.get("type")
            if etype == "message_start":
                u = evt.get("message", {}).get("usage", {})
                usage["input_tokens"] = u.get("input_tokens")
                usage["cache_creation_input_tokens"] = u.get("cache_creation_input_tokens", 0)
                usage["cache_read_input_tokens"] = u.get("cache_read_input_tokens", 0)
            elif etype == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    thinking_parts.append(delta.get("thinking", ""))
            elif etype == "message_delta":
                stop_reason = evt.get("delta", {}).get("stop_reason", stop_reason)
                if evt.get("usage", {}).get("output_tokens") is not None:
                    usage["output_tokens"] = evt["usage"]["output_tokens"]
            elif etype == "error":
                api_error = evt.get("error", {})
    if api_error:
        raise RuntimeError(f"Anthropic API error: {api_error.get('message', 'unknown')}")
    if stop_reason == "max_tokens":
        raise RuntimeError(f"Output truncated at max_tokens={max_tokens} — raise the ceiling and retry.")
    text = "".join(text_parts)
    if not text:
        raise RuntimeError(f"Empty response (stop_reason={stop_reason}).")
    data = _extract_json(text)

    thinking_text = "".join(thinking_parts)
    usage["thinking_text"] = thinking_text
    usage["final_text"] = text  # the raw JSON the model returned — the true "receipt"
                                # for a billed run, so a successful extract can be
                                # replayed/re-derived later without re-paying.
    usage["final_tokens"] = _count_tokens(text, model)
    usage["thinking_tokens"] = _count_tokens(thinking_text, model) if thinking_text else 0

    return data, usage


# ---------------------------------------------------------------------------
# STORE — Python owns accumulation (the "diff/merge against existing storage")
# ---------------------------------------------------------------------------

def new_store():
    """An empty persistent store. `live` feeds the next issue's model call;
    `archive` holds full closed trades (scoreboard); `discarded` holds lightweight
    stubs for abandoned/unresolved."""
    return {"live": [], "archive": [], "discarded": []}


def _discard_stub(t):
    """Minimal record for an abandoned/unresolved trade — enough to recall it
    existed and why it was dropped, nothing more (per the user's 'keep it
    lightweight' call)."""
    hist = t.get("status_history") or []
    last = hist[-1] if hist else {}
    return {
        "id": t.get("id"),
        "strategy_id": t.get("strategy_id"),
        "underlying": t.get("underlying"),
        "tickers": [b.get("ticker") for b in t["basket"]] if t.get("basket") else None,
        "status": t.get("status"),
        "dropped_on": last.get("date"),
        "reason": last.get("note"),
    }


def _spread_credit_or_debit(t):
    """Classify a two-leg vertical options spread as 'credit' or 'debit' and
    return (kind, strike_width) — or (None, None) if it isn't a clean same-type
    two-leg vertical. Derived from the legs' actions + relative strikes (per
    newsletter-ingestion.md C.1), NOT the structure_label name alone: a vertical
    is a CREDIT spread when the SOLD leg is the more valuable / closer-to-the-money
    strike (for calls the lower strike, for puts the higher strike), else debit."""
    legs = t.get("legs") or []
    if len(legs) != 2:
        return None, None
    types = {l.get("type") for l in legs}
    if len(types) != 1:  # must be call/call or put/put to be a vertical
        return None, None
    opt_type = next(iter(types))
    sold = next((l for l in legs if l.get("action") == "sell"), None)
    bought = next((l for l in legs if l.get("action") == "buy"), None)
    if not sold or not bought:
        return None, None
    ss, bs = sold.get("strike"), bought.get("strike")
    if ss is None or bs is None:
        return None, None
    width = abs(ss - bs)
    if width == 0:
        return None, None
    if opt_type == "call":
        kind = "credit" if ss < bs else "debit"
    elif opt_type == "put":
        kind = "credit" if ss > bs else "debit"
    else:
        return None, None
    return kind, width


# ===========================================================================
# DERIVATION / VALIDATION LAYER  (newsletter-schema-tightening.md, "Tier-1")
# ===========================================================================
# Python owns everything COMPUTABLE from the model's primitives (§7). The model
# emits prose->primitives; this layer derives+overwrites the rest and validates
# the enums, the generalized `compute_risk_pnl()` pattern applied to every
# derived field.
#
# INPUT CONTRACT — the primitive shape the extraction model MUST emit for this
# layer to run (this is the target the prompt rewrite, task 3, has to satisfy):
#   underlying   : bare ticker string (outright/options) | null (pairs)
#   asset_class  : model primitive for a single-name OUTRIGHT only
#                  (equity|future|forex, read from prose); IGNORED/overwritten
#                  for basket(->equity) and options(->equity). (§3 rule 1,
#                  corrected 2026-07-09.)
#   direction    : long|short for outright; null otherwise (per-leg side encodes it)
#   basket[]     : {ticker, side:long|short, weight, entry_price?, exit_price?, note?} — pairs
#                  (weight = beta-neutral sizing ONLY; the composite ratio is Σlong/Σshort
#                   of the RAW per-name prices — display-computed, C.16)
#   legs[]       : {strike, expiry, type:call|put, action:buy|sell, quantity, note?} — options
#   tranches[]   : {size?, entry_price?, entry_date?, status:open|closed|planned,
#                   exit_price?, exit_date?, pnl?:{value,unit}, note?}  (§8d, typed entity)
#   (note? on every sub-element = optional per-element context, rendered inline)
#   entry        : {trigger_type (closed enum §5), level, level_high, note}
#   entry_price / exit_price : raw transaction LEVELS in native unit ($ or ratio).
#                  For an options credit spread kept to expiry, entry_price is the
#                  CREDIT collected and exit_price the buyback (0 if worthless).
#   status_history[] : {date, status, pnl?:{value,unit}, exit_price?, note?}
#   thesis       : {rationale, positioning}  (§6)
# Python DERIVES (and overwrites any model value): structure, asset_class
# (basket/options), structure_label, bias, strategy_id, pnl_pct, risk_capital.

ASSET_CLASSES = ("equity", "future", "forex")
OPTIONABLE_ASSET_CLASSES = {"equity"}          # §4c — extend here for futures options
STRUCTURES = ("outright", "pairs", "options", "unclassified")
TRIGGER_TYPES = ("market", "level", "stop", "premium_target", "scaled", "pre_existing")
PNL_UNITS = ("pct", "usd_per_share", "usd_total", "points")


def fetch_symbol(underlying, asset_class):
    """The yfinance-fetchable symbol, derived FROM asset_class (§3, corrected
    2026-07-09) — the ONE source of truth so the stored class and the data pull
    can't drift. equity -> bare; future -> +=F (clean root only); forex -> +=X.
    Mirror of watchtower.html chartSymbol(); kept here so any Python-side fetch
    uses the identical mapping."""
    if not underlying:
        return underlying
    if asset_class == "forex":
        return f"{underlying}=X"
    if asset_class == "future" and re.fullmatch(r"[A-Za-z]{1,4}", underlying):
        return f"{underlying}=F"
    return underlying


def classify_structure(t):
    """§3 rule 3 — exactly one container: legs (options) XOR basket (pairs) XOR
    bare-underlying-only (outright). Returns (structure, flags). An unfittable
    trade -> 'unclassified' + a flag for manual review (the escape hatch), never
    force-fit."""
    legs = t.get("legs")
    basket = t.get("basket")
    underlying = t.get("underlying")
    has_legs, has_basket, has_underlying = bool(legs), bool(basket), bool(underlying)
    flags = []
    if has_legs and has_basket:
        flags.append("both legs and basket populated")
    if has_basket and has_underlying:
        flags.append("basket (pairs) trade should have null underlying")
    if has_legs:
        structure = "options"
        if not has_underlying:
            flags.append("options trade missing underlying")
    elif has_basket:
        structure = "pairs"
    elif has_underlying:
        structure = "outright"
    else:
        structure = "unclassified"
        flags.append("no container populated (legs/basket/underlying all empty)")
    return structure, flags


def derive_asset_class(t, structure):
    """§3 rule 1 (corrected). basket/options -> equity (derived). outright ->
    validated model primitive. Returns (asset_class, flags)."""
    if structure in ("pairs", "options"):
        return "equity", []
    if structure == "outright":
        ac = t.get("asset_class")
        if ac in ASSET_CLASSES:
            return ac, []
        return ac, [f"outright asset_class {ac!r} not in {ASSET_CLASSES}"]
    return t.get("asset_class"), []  # unclassified: leave as-is


def classify_legs(legs):
    """Deterministic legs -> (structure_label, bias, strategy_token) for a
    RECOGNIZED options structure (§7.2/§8a). Verticals are fully covered (the
    only shapes in the 260608 fixture); an unrecognized structure returns
    (None, None, None) so the caller falls back to the model's structure_label
    and a generic leg-signature token. bull-vs-bear comes from which strike
    carries the sell vs buy — capturing direction WITHOUT the absolute strikes,
    so a rolled spread at new strikes keeps the same token (§8a)."""
    legs = legs or []
    if len(legs) == 2:
        types = {l.get("type") for l in legs}
        actions = {l.get("action") for l in legs}
        if len(types) == 1 and actions == {"buy", "sell"}:
            opt = next(iter(types))
            sold = next(l for l in legs if l.get("action") == "sell")
            bought = next(l for l in legs if l.get("action") == "buy")
            ss, bs = sold.get("strike"), bought.get("strike")
            se, be = sold.get("expiry"), bought.get("expiry")
            diff_strike = ss is not None and bs is not None and ss != bs
            diff_expiry = se is not None and be is not None and se != be
            # Calendar/diagonal (§4a — the only 2-leg shapes whose legs legitimately
            # differ in expiry). Check expiry FIRST so a diagonal (different strike
            # AND expiry) isn't mistaken for a vertical on its strikes alone. bias
            # left null: a calendar's direction depends on the thesis, not the legs
            # (user, 2026-07-13) — read the thesis for context.
            if diff_expiry:
                if not diff_strike:
                    return "calendar", None, "calendar"
                return "diagonal", None, "diagonal"
            if diff_strike:
                if opt == "call":
                    if ss < bs:
                        return "bear_call_spread", "bearish", "bear-call-spread"
                    return "bull_call_spread", "bullish", "bull-call-spread"
                if opt == "put":
                    if ss > bs:
                        return "bull_put_spread", "bullish", "bull-put-spread"
                    return "bear_put_spread", "bearish", "bear-put-spread"
    if len(legs) == 4:
        # Iron condor / iron butterfly (§8a, C.11): 2 puts + 2 calls, one buy +
        # one sell on EACH side (a put vertical + a call vertical). Both are
        # neutral structures; the butterfly is the special case where the two
        # SHORT strikes coincide. The model nails the 4 legs but defers the
        # classification (null structure_label) — Python names it here so it
        # stops falling to the generic `opt4-…` leg signature.
        calls = [l for l in legs if l.get("type") == "call"]
        puts = [l for l in legs if l.get("type") == "put"]
        both_sides_one_each = (
            len(calls) == 2 and len(puts) == 2
            and {l.get("action") for l in calls} == {"buy", "sell"}
            and {l.get("action") for l in puts} == {"buy", "sell"})
        if both_sides_one_each:
            short_call = next((l for l in calls if l.get("action") == "sell"), None)
            short_put = next((l for l in puts if l.get("action") == "sell"), None)
            scs, sps = short_call.get("strike"), short_put.get("strike")
            if scs is not None and sps is not None and scs == sps:
                return "iron_butterfly", "neutral", "iron-butterfly"
            return "iron_condor", "neutral", "iron-condor"
    return None, None, None


def _leg_signature(legs):
    """Generic deterministic token for an options structure classify_legs can't
    name (§8a fallback) — strike-relative, expiry/absolute-strike free so it
    stays stable across rolls. Sorted (type, action) multiset + leg count."""
    legs = legs or []
    parts = sorted(f"{l.get('action', '?')[0]}{l.get('type', '?')[0]}" for l in legs)
    return f"opt{len(legs)}-" + "".join(parts) if legs else "opt"


def derive_strategy_id(t, structure, strategy_token):
    """§8a — strategy-level lineage key, strikes/expiries/aliases excluded, from
    taxonomy fields only. Groups rolls/re-entries of one idea."""
    if structure == "outright":
        u = (t.get("underlying") or "").lower()
        d = t.get("direction")
        return f"{u}-{d}" if d else u
    if structure == "options":
        u = (t.get("underlying") or "").lower()
        return f"{u}-{strategy_token or 'options'}"
    if structure == "pairs":
        basket = t.get("basket") or []
        longs = sorted((b.get("ticker") or "").lower() for b in basket if b.get("side") == "long")
        shorts = sorted((b.get("ticker") or "").lower() for b in basket if b.get("side") == "short")
        return f"{'-'.join(longs)}-vs-{'-'.join(shorts)}"
    return t.get("strategy_id")


def compute_break_even(t):
    """§7.4/C.2 mechanical field: break-even price of a 2-leg vertical, derived from
    the legs + net credit/debit. Stored as `break_even`; left absent when it isn't a
    clean vertical or the credit/debit isn't known (a pre-window spread with no captured
    entry economics — e.g. GLD 425/450, META). Credit/debit is sourced from
    `entry.level` when `entry.trigger_type == 'premium_target'`, else `entry_price`
    (C.2 input refinement, 2026-07-09). Vertical break-evens:
      bear_call (credit): short-call strike + credit
      bull_put  (credit): short-put  strike − credit
      bull_call (debit):  long-call  strike + debit
      bear_put  (debit):  long-put   strike − debit"""
    if t.get("structure") != "options":
        return
    kind, _width = _spread_credit_or_debit(t)
    if kind is None:
        return
    legs = t.get("legs") or []
    sold = next((l for l in legs if l.get("action") == "sell"), None)
    bought = next((l for l in legs if l.get("action") == "buy"), None)
    if not sold or not bought or sold.get("strike") is None or bought.get("strike") is None:
        return
    entry = t.get("entry") or {}
    prem = entry.get("level") if entry.get("trigger_type") == "premium_target" else None
    if prem is None:
        prem = t.get("entry_price")
    if prem is None:
        return
    opt = sold.get("type")
    if kind == "credit":
        be = sold["strike"] + prem if opt == "call" else sold["strike"] - prem
    else:
        be = bought["strike"] + prem if opt == "call" else bought["strike"] - prem
    t["break_even"] = round(be, 4)


def derive_stop_basis(t):
    """Tag an OPTIONS trade's stop as an UNDERLYING-price invalidation (user,
    2026-07-12). Such a stop ("a break of $85 invalidates") is quoted on the
    underlying — a DIFFERENT unit than the premium entry/target — so the display must
    not render it in the premium Entry/Tgt row (TLT's $85 read as nonsensical next to
    a $1.23 debit / $4 max value). Records `stop.basis = "underlying"` when a stop
    LEVEL is present (the model sets one only when the newsletter explicitly states a
    stop, so an explicit stop is preserved — just unit-tagged) and basis isn't already
    set, letting the frontend route it to the Trigger/Invalidation detail instead of
    the premium row. Non-options stops (outright underlying, pairs ratio) share the
    entry's unit and are left untouched. Deterministic; Python owns it (§7)."""
    if t.get("structure") != "options":
        return
    stop = t.get("stop")
    if isinstance(stop, dict) and stop.get("level") is not None and not stop.get("basis"):
        stop["basis"] = "underlying"


def derive_target_basis(t):
    """Tag an OPTIONS trade's UNDERLYING-price "targets" as guidance, mirroring
    derive_stop_basis (user, 2026-07-12). A vertical's premium value lives in
    [0, strike-width], so a target at or above the lowest strike is an UNDERLYING price
    (where the underlying must trade) — NOT a premium profit target. GLD 395/372 T1 380 /
    T2 372 and KRE reassess 80 / monetization_zone 83 are underlying levels the model
    happened to file as targets (and even labels T1/T2), so the label can't be trusted to
    tell a premium target from an underlying level — Python owns the split (§7). Records
    target.basis = "underlying" when level >= the lowest strike and basis isn't set; the
    display routes an underlying-basis target to the Trigger/Invalidation guidance and
    keeps the Targets block for genuine premium targets (max_value, the spread's worth).
    Non-options targets share the entry's unit (underlying/ratio) and are left untouched."""
    if t.get("structure") != "options":
        return
    strikes = [l.get("strike") for l in (t.get("legs") or []) if l.get("strike") is not None]
    if not strikes:
        return
    lo = min(strikes)
    for tg in (t.get("targets") or []):
        if isinstance(tg, dict) and tg.get("level") is not None \
                and not tg.get("basis") and tg["level"] >= lo:
            tg["basis"] = "underlying"


def derive_ratio_trigger(t):
    """Structure a PAIR-RATIO entry trigger on an OUTRIGHT trade (user, 2026-07-13).
    Some outright positions trigger off a RATIO between two instruments rather than a
    single price — e.g. a MAGS long that enters only when SOXX/MAGS breaks its 50DMA
    (~8.59). The model already emits the pair in the `reference_values` bag as a
    `<num>_<denom>_ratio` key (here `soxx_mags_ratio`, with `soxx_spot`/`mags_spot`
    companions), so this reads that STRUCTURED field (not prose — §7) into a typed
    `ratio_trigger: {numerator, denominator, level}` the display keys off to show the
    ratio in the header and chart the ratio instead of the single stock. Requires the
    trade's own `underlying` to be one leg of the ratio (else a stray `*_ratio` value is
    just a reference stat, not this position's trigger). Post-merge derivation only — no
    extraction/prompt change; skips non-outright trades and trades with no ratio."""
    if t.get("structure") != "outright":
        return
    rv = t.get("reference_values")
    if not isinstance(rv, dict):
        return
    underlying = (t.get("underlying") or "").upper()
    for key, val in rv.items():
        k = str(key).lower()
        if not k.endswith("_ratio"):
            continue
        parts = k[:-len("_ratio")].split("_")
        if len(parts) != 2:
            continue
        num, den = parts[0].upper(), parts[1].upper()
        if underlying and underlying not in (num, den):
            continue                          # ratio isn't about THIS position — reference stat only
        t["ratio_trigger"] = {
            "numerator": num,
            "denominator": den,
            "level": val if isinstance(val, (int, float)) else None,
        }
        return


def derive_status_from_section(t):
    """§ Section-status taxonomy (2026-07-10) — the newsletter SECTION a trade is printed
    under (`source_section`, a document fact, far more stable than a fill judgment) drives
    its status:
      * `closed`  -> status closed   (obvious — the section IS the status)
      * `open`    -> status open      (ONLY a CLEAR held-positions section; a mis-bucketed
                    untriggered conditional is still caught by enforce_untriggered_conditional)
      * `watching`-> status planned   (a standing observation/indicator)
      * `new`/`review`/null -> LEAVE the model's status; the FILL MECHANICS decide
                    (enforce_untriggered_conditional + enforce_scaled_planned, both below).
                    `review` is the NEUTRAL bucket for fuzzy headings (Previous Week Trade
                    Review, Tactical Summary) that span held+untriggered+closed.
    A model-reported abandoned/unresolved is a definitive silence outcome (a silent trade
    isn't under any section) and is never overridden. C.9 (defensive-breadth @ 260615, in a
    fuzzy 'Previous Week Trade Review') is resolved by the scaled guard's CARRIED-FILL
    release, NOT the section — the section can't tell it from the untriggered USDJPY in the
    SAME review."""
    sec = t.get("source_section")
    if sec == "closed":
        t["status"] = "closed"
    elif t.get("status") in DISCARD_STATUSES:
        return                       # abandoned/unresolved — definitive, section can't override
    elif sec == "open":
        t["status"] = "open"
    elif sec == "watching":
        t["status"] = "planned"
    # sec in (None, "new") -> leave the model's status; enforce_scaled_planned (scoped to
    # `new`) may still clamp a scaled entry to planned.


CONDITIONAL_TRIGGERS = ("stop", "level", "premium_target")


def _has_fill_evidence(t):
    """True if the trade has ACTUALLY been entered: a filled/closed tranche, a realized P&L
    logged, or a captured entry/exit price. Distinguishes a triggered conditional from one
    still waiting to fire."""
    if any(tr.get("status") in ("open", "closed") for tr in (t.get("tranches") or [])):
        return True
    if any(isinstance(h.get("pnl"), dict) for h in (t.get("status_history") or [])):
        return True
    return t.get("entry_price") is not None or t.get("exit_price") is not None


def enforce_untriggered_conditional(t):
    """Backstop (§ section-status refinement 2026-07-10): a trade whose entry is an
    UNTRIGGERED conditional — trigger_type in {stop, level, premium_target} with NO fill
    evidence — is definitionally NOT held, so force `planned` REGARDLESS of source_section.
    Corrects a fuzzy-section mis-bucket where a 'Previous Week Trade Review' lists an
    untriggered sell-stop as if held (USDJPY: trigger_type 'stop', 'not yet triggered',
    the model tagged source_section 'open'). Fill evidence means it DID fire -> stand down.
    A terminal status (closed/abandoned/unresolved) is definitive and left alone.

    REFINED 2026-07-12 (user, MSFT 06/22): a LIMIT-style entry (premium_target / level)
    printed in the CLEAR `open` (held-positions) section IS held — a missing captured fill
    is an extraction gap, not proof it never filled — so trust the section and do NOT
    demote (MSFT: a 392/400 bear-call sold for a $0.95 credit, listed under Open Trades,
    was wrongly greyed to `planned`). Only a `stop` (breakout) entry can legitimately sit
    in 'open' while still waiting to trigger, so it STILL requires fill evidence."""
    if t.get("status") in TERMINAL_STATUSES:
        return
    tt = (t.get("entry") or {}).get("trigger_type")
    if tt not in CONDITIONAL_TRIGGERS:
        return
    if _has_fill_evidence(t):
        return
    if t.get("source_section") == "open" and tt != "stop":
        return                       # clear held-position limit entry — trust the section
    t["status"] = "planned"


def enforce_scaled_planned(t):
    """Determinism guard (user 2026-07-09): a SCALED entry is a scale-IN PLAN, so force
    it to `planned` until it has ACTUALLY been active. Removes the open-vs-planned
    COIN-FLIP where the model fabricates a fill (`status:"open"` + an issue-dated
    `entry_date`) on a "[day] open" starter — low#1 read the defensive-breadth pair
    `planned`, low#2 read it `open`. Keyed off the STABLE `entry.trigger_type` primitive,
    NOT the flaky per-tranche fill judgment. Also strips the fabricated fill (tranches ->
    planned, entry_date -> null) so the tranche display and the status agree.

    RELEASE (leave the model's status) when the scaled entry has genuinely been active:
    a closed tranche or realized P&L, OR — added 2026-07-10 — it is CARRIED
    (first_seen != last_mentioned) with a FILLED tranche. A fill confirmed in a SUBSEQUENT
    issue is trustworthy (defensive-breadth @ 260615 reads `open`), unlike a first-appearance
    fabrication (defensive-breadth @ 260608 stays clamped). Section-INDEPENDENT: this
    newsletter's 'Previous Week Trade Review' mixes held + untriggered trades, so the fill
    state — not the heading — must decide."""
    if (t.get("entry") or {}).get("trigger_type") != "scaled":
        return
    tranches = t.get("tranches") or []
    has_closed = any(tr.get("status") == "closed" for tr in tranches)
    has_pnl = any(isinstance(h.get("pnl"), dict) for h in (t.get("status_history") or []))
    if has_closed or has_pnl:
        return   # genuinely been active -> leave the model's status
    carried = bool(t.get("first_seen")) and t.get("first_seen") != t.get("last_mentioned")
    if carried and any(tr.get("status") == "open" for tr in tranches):
        return   # cross-issue-confirmed fill on a carried trade -> trust it
    t["status"] = "planned"
    for tr in tranches:
        tr["status"] = "planned"
        tr["entry_date"] = None


def _is_indicator(t):
    """A standing observation/watchlist READ, not a takeable position."""
    return (t.get("conviction") or {}).get("label") in ("observation_only", "watchlist")


def _never_entered(t):
    """True iff the trade was never actually held — currently `planned` and no
    status_history entry ever reached open/closed (a fill). Distinguishes a
    never-triggered conditional/indicator from a real position that went quiet."""
    if t.get("status") != "planned":
        return False
    return not any(h.get("status") in ("open", "closed")
                   for h in (t.get("status_history") or []))


def _weeks_between(d_early, d_late):
    """Whole-and-fractional weeks between two YYYY-MM-DD strings; None if unparseable."""
    try:
        a = datetime.date.fromisoformat(d_early)
        b = datetime.date.fromisoformat(d_late)
        return (b - a).days / 7.0
    except Exception:
        return None


def apply_offramp(t, issue_date):
    """Retire a NEVER-ENTERED live trade that has aged out of relevance (user,
    2026-07-11). Two off-ramps, both -> `lapsed` (a discard status: lightweight
    stub, out of the scoreboard since it was never a position). Returns True if it
    lapsed. Reserves the indefinite no-auto-close protection for genuinely-entered
    positions; a never-entered read/conditional does not linger forever.

      1. INDICATOR SILENCE: an observation_only/watchlist indicator unreferenced
         (by theme OR constituent) for LAPSE_INDICATOR_SILENCE issues. Indicators
         are exempt from the 1-issue silence rule (they recur intermittently), but
         NOT from eventual lapse. Reads model-tracked `weeks_unmentioned`.
      2. CONDITIONAL MAX-AGE: a never-entered NON-indicator planned trade older than
         its stated `holding_period.max_weeks` (else LAPSE_CONDITIONAL_MAX_WEEKS)
         — catches a conditional that keeps being reiterated but never triggers.
         Python-computed age from `first_seen` -> issue_date.
    """
    if t.get("status") in TERMINAL_STATUSES:
        return False
    reason = None
    if _is_indicator(t):
        wu = t.get("weeks_unmentioned") or 0
        if wu >= LAPSE_INDICATOR_SILENCE:
            reason = f"lapsed — indicator unreferenced {wu} issues"
    elif _never_entered(t):
        horizon = ((t.get("holding_period") or {}).get("max_weeks")
                   or LAPSE_CONDITIONAL_MAX_WEEKS)
        age = _weeks_between(t.get("first_seen"), issue_date)
        if age is not None and age > horizon:
            reason = (f"lapsed — conditional never triggered within {horizon:g} "
                      f"weeks (age {age:.0f}w)")
    if reason:
        t["status"] = "lapsed"
        t.setdefault("status_history", []).append(
            {"date": issue_date, "status": "lapsed", "note": reason})
        return True
    return False


def normalize_derived(t):
    """Run the full derivation over ONE trade, mutating it in place and returning
    validation flags. Sets structure, asset_class, structure_label, bias,
    strategy_id — overwriting any model value (§7.1). Enforces §3 rule 2
    (structure_label null unless options) and §4c (options => optionable)."""
    flags = []
    structure, f1 = classify_structure(t)
    t["structure"] = structure
    flags += f1

    asset_class, f2 = derive_asset_class(t, structure)
    t["asset_class"] = asset_class
    flags += f2

    if structure == "options":
        if asset_class not in OPTIONABLE_ASSET_CLASSES:
            flags.append(f"options trade has non-optionable asset_class {asset_class!r}")
        label, bias, token = classify_legs(t.get("legs"))
        if label is None:                       # exotic residual -> model fallback (§4b/§7.2)
            label = t.get("structure_label")
            bias = t.get("bias")
            token = _leg_signature(t.get("legs"))
        t["structure_label"] = label
        t["bias"] = bias
        t["strategy_id"] = derive_strategy_id(t, structure, token)
    else:
        # §3 rule 2 — structure_label MUST be null off options.
        t["structure_label"] = None
        if structure == "pairs":
            t["bias"] = "neutral"               # §5 — market-neutral by construction
        elif structure == "outright":
            t["bias"] = {"long": "bullish", "short": "bearish"}.get(t.get("direction"))
        else:
            t["bias"] = None
        t["strategy_id"] = derive_strategy_id(t, structure, None)

    compute_break_even(t)          # C.2 — options break-even from legs + credit/debit
    derive_stop_basis(t)           # tag an options underlying-price stop's unit (display routing)
    derive_target_basis(t)         # tag options underlying-price "targets" as guidance (display routing)
    derive_ratio_trigger(t)        # structure a pair-ratio entry trigger on an outright (display routing)
    derive_status_from_section(t)       # § section-status — forces status only where obvious
    enforce_untriggered_conditional(t)  # backstop — untriggered conditional -> planned (any section)
    enforce_scaled_planned(t)           # scaled guard, carried-fill release (§ fill mechanics)
    return flags


def _history_from_tranches(tranches, status, fallback_date):
    """Build a clean status_history for a split child from its OWN tranches. This is
    the fix for the status_history BLEED-THROUGH: the model sometimes emits a single
    CONFLATED history entry covering both a stop-out AND a re-entry, and blindly
    deep-copying it to both children put a realized pnl on the OPEN child (a phantom
    gain it never made) and left the CLOSED child's entry mislabeled `open`. Rebuilding
    per child from its tranches removes both problems — a closed slice yields a `closed`
    entry carrying its exit/pnl; an open slice yields a bare `open` entry with NO
    realized pnl."""
    out = []
    for tr in tranches:
        if tr.get("status") == "planned":
            continue  # a planned/unfilled add hasn't happened — no history event
        if status == "closed":
            e = {"date": tr.get("exit_date") or tr.get("entry_date") or fallback_date,
                 "status": "closed"}
            if tr.get("exit_price") is not None:
                e["exit_price"] = tr["exit_price"]
            if isinstance(tr.get("pnl"), dict):
                e["pnl"] = tr["pnl"]
        else:
            e = {"date": tr.get("entry_date") or fallback_date, "status": "open"}
        out.append(e)
    return out


def split_tranches(t):
    """§8d — deterministic tranche-status split. all-open|all-closed|no-tranche
    -> one record (unchanged). MIXED (>=1 closed AND >=1 open) -> TWO records: a
    `closed` trade (closed slices, carries pnl_pct) + an `open` trade (open
    slices), SHARING strategy_id, told apart by status + an id discriminator.
    This is the copper case and the ONLY source of a two-record split — a plain
    close with no re-entry stays one record. Driven purely by tranche status,
    never a model judgment. Each child's status_history is REBUILT from its own
    tranches (see _history_from_tranches) so a conflated parent entry can't bleed."""
    tr = t.get("tranches") or []
    statuses = {x.get("status") for x in tr if x.get("status")}
    if not ("closed" in statuses and "open" in statuses):
        return [t]
    closed_tr = [x for x in tr if x.get("status") == "closed"]
    open_tr = [x for x in tr if x.get("status") != "closed"]
    fallback = t.get("last_mentioned") or t.get("first_seen")

    closed_rec = copy.deepcopy(t)
    closed_rec["tranches"] = closed_tr
    closed_rec["status"] = "closed"
    closed_rec["id"] = f"{t.get('id')}-closed"      # discriminator (shares strategy_id)
    closed_rec["status_history"] = _history_from_tranches(closed_tr, "closed", fallback)

    open_rec = copy.deepcopy(t)
    open_rec["tranches"] = open_tr
    open_rec["status"] = "open"
    open_rec["status_history"] = _history_from_tranches(open_tr, "open", fallback)
    return [closed_rec, open_rec]


def _closing_hist(t):
    hist = t.get("status_history") or []
    return next((h for h in reversed(hist) if h.get("status") == "closed"), None)


def _blended_entry_exit(t):
    """Size-weighted average ENTRY (and exit, when all filled slices have exited)
    over a scaled position's FILLED tranches — its true cost basis, NOT the first
    slice. `size` is the CUMULATIVE position weight the newsletter states (0.5
    starter -> "add to 1.00" = 1.0 total), so incremental weights are consecutive
    differences; falls back to an equal-weight average when sizes are absent or not
    strictly increasing (e.g. copper, whose sizes the model left null). Returns
    (None, None) for fewer than 2 filled tranches — leaving single/no-tranche trades
    entirely on the existing path (zero blast radius there). (user, 2026-07-12: the
    model computes this blend only ad-hoc — copper yes, the defensive pair no — so
    Python owns it deterministically, per §7.)"""
    filled = [tr for tr in (t.get("tranches") or [])
              if tr.get("entry_price") is not None and tr.get("status") != "planned"]
    if len(filled) < 2:
        return None, None
    sizes = [tr.get("size") for tr in filled]
    def wavg(vals):
        if all(s is not None for s in sizes):          # cumulative -> incremental
            incr, prev, ok = [], 0.0, True
            for s in sizes:
                d = s - prev
                if d <= 0:
                    ok = False
                    break
                incr.append(d)
                prev = s
            if ok and sum(incr) > 0:
                return round(sum(v * w for v, w in zip(vals, incr)) / sum(incr), 4)
        return round(sum(vals) / len(vals), 4)         # equal-weight fallback
    entry_b = wavg([tr["entry_price"] for tr in filled])
    exits = [tr.get("exit_price") for tr in filled]
    exit_b = wavg(exits) if all(e is not None for e in exits) else None
    return entry_b, exit_b


def apply_blended_entry(t):
    """Overwrite entry_price (and exit_price when all filled slices exited) with the
    deterministic blended cost basis for a 2+ filled-tranche scaled position. Makes
    it authoritative for BOTH display (the frontend reads entry_price first) and P&L
    (`_entry_exit_levels` uses the same blend), replacing the model's inconsistent
    ad-hoc value. No-op for single/no-tranche trades."""
    eb, xb = _blended_entry_exit(t)
    if eb is not None:
        t["entry_price"] = eb
    if xb is not None:
        t["exit_price"] = xb


def _has_entry_basis(t):
    """True iff the trade carries ANY entry price/level (top-level, entry.level, or
    a tranche fill) — i.e. its entry is not blank."""
    if t.get("entry_price") is not None:
        return True
    if (t.get("entry") or {}).get("level") is not None:
        return True
    return any(tr.get("entry_price") is not None for tr in (t.get("tranches") or []))


def _entry_basis(t):
    """The trade's authoritative entry value: the blended cost basis over filled
    tranches, else top-level entry_price, else entry.level, else a tranche fill.
    None when the trade has no entry at all."""
    if t is None:
        return None
    eb, _ = _blended_entry_exit(t)
    if eb is not None:
        return eb
    if t.get("entry_price") is not None:
        return t["entry_price"]
    lvl = (t.get("entry") or {}).get("level")
    if lvl is not None:
        return lvl
    for tr in (t.get("tranches") or []):
        if tr.get("entry_price") is not None:
            return tr["entry_price"]
    return None


def _confirmed_entry(t):
    """The trade's CONFIRMED (actually-filled) entry — the blended cost basis over
    filled tranches, else a filled tranche's price, else the top-level entry_price on
    a held position. Excludes a bare `entry.level` (a PLANNED trigger, not a fill)
    and requires the trade to be open/closed (entered). This is the value that gets
    LOCKED once real — user 2026-07-12: "a confirmed entry never changes; it's locked
    until the trade closes." None when the trade is not yet entered."""
    if t is None or t.get("status") not in ("open", "closed"):
        return None
    eb, _ = _blended_entry_exit(t)
    if eb is not None:
        return eb
    for tr in (t.get("tranches") or []):
        if tr.get("entry_price") is not None and tr.get("status") in ("open", "closed"):
            return tr["entry_price"]
    if t.get("entry_price") is not None:
        return t["entry_price"]
    return None


def _entry_exit_levels(t):
    """Source entry/exit price LEVELS for an outright/pairs pnl (§8c input
    plumbing) — the size-weighted blend for a multi-tranche scaled position, else a
    closed tranche carrying both, else the closing status_history exit_price +
    entry.level/entry_price."""
    eb, xb = _blended_entry_exit(t)      # scaled position -> true blended cost basis
    if eb is not None and xb is not None:
        return eb, xb
    for tr in (t.get("tranches") or []):
        if tr.get("status") == "closed" and tr.get("entry_price") is not None \
                and tr.get("exit_price") is not None:
            return tr["entry_price"], tr["exit_price"]
    closing = _closing_hist(t)
    exit_p = closing.get("exit_price") if closing else None
    if exit_p is None:                       # top-level exit_price (plumbing fix — the
        exit_p = t.get("exit_price")         # model often files the close here, not in hist)
    entry_p = (t.get("entry") or {}).get("level")
    if entry_p is None:
        entry_p = t.get("entry_price")
    if entry_p is None:
        for tr in (t.get("tranches") or []):
            if tr.get("entry_price") is not None:
                entry_p = tr["entry_price"]
                break
    return entry_p, exit_p


def _stated_pnl(t):
    """A stated raw pnl {value, unit} from the closing history entry or a closed
    tranche — used as the fallback when levels can't compute (§8c step 3)."""
    closing = _closing_hist(t)
    if closing and isinstance(closing.get("pnl"), dict):
        return closing["pnl"]
    for tr in (t.get("tranches") or []):
        if tr.get("status") == "closed" and isinstance(tr.get("pnl"), dict):
            return tr["pnl"]
    return None


def compute_price_pnl(t):
    """§8c — pnl_pct for a closed OUTRIGHT or PAIRS trade from entry/exit price
    (or ratio) levels; sign from direction (outright) — pairs per-leg sides
    already encode direction so a raw ratio %-change carries the sign. Falls back
    to a stated pnl already in %. Flags a closed trade that yields none."""
    entry_p, exit_p = _entry_exit_levels(t)
    if entry_p is not None and exit_p is not None and entry_p != 0:
        sign = -1 if (t.get("structure") == "outright" and t.get("direction") == "short") else 1
        pct = round((exit_p - entry_p) / entry_p * 100 * sign, 2)
        t["pnl_pct"] = pct
        closing = _closing_hist(t)
        if closing is not None:
            closing["pnl_pct"] = pct
        return []
    stated = _stated_pnl(t)
    if stated and stated.get("unit") == "pct" and stated.get("value") is not None:
        t["pnl_pct"] = round(stated["value"], 2)
        return []
    return [f"closed {t.get('structure')} trade {t.get('id')!r} — no derivable pnl_pct"]


def compute_pnl(t):
    """Dispatch pnl derivation by structure (§7.1 pnl_pct row). Returns flags."""
    structure = t.get("structure")
    if structure == "options":
        return compute_risk_pnl(t)
    if structure in ("outright", "pairs"):
        return compute_price_pnl(t)
    return []


def flag_missing_exit(t):
    """Completeness contract / capture-completeness net (C.17). A CLOSED outright or
    options trade that has an entry basis AND a realized pnl but NO exit price is
    almost certainly a DROPPED stated exit — the two bracketing numbers are present,
    the middle one isn't (exit = entry ± gain would recover it). FORMAT-AGNOSTIC: it
    keys off the OUTPUT shape, not the input phrasing, so it catches a dropped exit
    whatever new prose the author invents (the whole point — you can't prompt for a
    format you haven't seen, but a completeness rule is format-independent). Excludes
    PAIRS (they close on a ratio %/marks and are legitimately exit-price-less, C.15)
    and trades with no derivable pnl (already flagged). Surfaces a SUSPECTED drop for
    review — never auto-fills it (that would mask the engine's parse quality, which we
    deliberately keep observable)."""
    if t.get("status") != "closed" or t.get("structure") not in ("outright", "options"):
        return []
    tranches = t.get("tranches") or []
    if t.get("exit_price") is not None \
            or any(tr.get("exit_price") is not None for tr in tranches):
        return []
    closing = _closing_hist(t)
    if closing and closing.get("exit_price") is not None:
        return []
    has_entry = (t.get("entry_price") is not None
                 or (t.get("entry") or {}).get("level") is not None
                 or any(tr.get("entry_price") is not None for tr in tranches))
    has_pnl = t.get("pnl_pct") is not None or _stated_pnl(t) is not None
    if has_entry and has_pnl:
        return [f"closed {t.get('structure')} trade {t.get('id')!r} has entry + pnl but NO "
                f"exit_price — likely a DROPPED stated exit; check the source"]
    return []


def _compute_single_short_pnl(t):
    """C.12 — realized pnl% for a CLOSED single-leg SHORT option (covered-call
    overwrite, cash-secured put, or naked short) that _spread_credit_or_debit
    can't classify (it requires a 2-leg vertical). A short kept to a WORTHLESS
    expiry (exit_price 0) realizes the full premium = +100% of premium at risk —
    computable WITHOUT the premium's absolute size, which the letter often omits.
    A buyback at exit_price X against a known credit C realizes (C - X)/C. Flags
    when neither is derivable. Return is on the OPTION'S premium; a covered-call
    overlay's small portfolio impact is a scoreboard-bucketing concern (overlay /
    actionability segmentation), not a reason to distort this trade-level number."""
    closing = _closing_hist(t)
    exit_price = closing.get("exit_price") if closing else None
    credit = t.get("entry_price")
    if credit is None:
        credit = (t.get("entry") or {}).get("level")
    if exit_price == 0:                     # expired worthless -> kept 100% of premium
        pnl_pct = 100.0
    elif credit not in (None, 0) and exit_price is not None:
        pnl_pct = round((credit - exit_price) / credit * 100, 1)
    else:
        return [f"closed single-leg short {t.get('id')!r} — no premium/exit to derive pnl_pct"]
    t["pnl_pct"] = pnl_pct
    if closing is not None:
        closing["pnl_pct"] = pnl_pct
    return []


def _structure_max_loss(legs, net_credit):
    """C.18 — the assembled multi-leg options structure's MAX LOSS: the worst-case
    expiry payoff over the whole position, NOT a sum of per-sub-spread max losses
    (a true iron condor's two sides max-loss in OPPOSITE scenarios and can't both
    happen — summing overstates the risk; user 2026-07-11). Evaluates the net
    expiry P&L at every strike boundary plus the tails (0 and above the top strike)
    and takes the minimum. `net_credit` is the net premium received at INITIATION
    (credit +, debit -); use the full assembled structure regardless of the author
    legging in/out over the trade's life. Returns the positive max-loss magnitude,
    or None if it can't be evaluated / the structure never loses."""
    strikes = sorted({l.get("strike") for l in legs if l.get("strike") is not None})
    if not strikes or net_credit is None:
        return None
    span = (strikes[-1] - strikes[0]) or strikes[-1]
    candidates = [0.0] + strikes + [strikes[-1] + span]  # tails bracket every payoff kink
    worst = None
    for S in candidates:
        payoff = net_credit
        for l in legs:
            k = l.get("strike")
            if k is None:
                continue
            typ, act, qty = l.get("type"), l.get("action"), l.get("quantity") or 1
            if typ == "call":
                intrinsic = max(S - k, 0)
            elif typ == "put":
                intrinsic = max(k - S, 0)
            else:
                continue
            payoff += (intrinsic if act == "buy" else -intrinsic) * qty
        if worst is None or payoff < worst:
            worst = payoff
    return round(-worst, 4) if worst is not None and worst < 0 else None


def _price_multi_spread(t):
    """C.18 — price a multi-SPREAD options structure (iron condor, or a rebuilt
    call-spread + put-spread combo) that isn't a clean 2-leg vertical, from its
    per-sub-spread fills. Each sub-spread is signed +1 (credit / net sold) or -1
    (debit / net bought) via _spread_credit_or_debit; the whole structure's
    entry/exit = Sigma(sign * sub-price), pnl = entry - exit, risk_capital = the
    assembled structure's MAX LOSS (_structure_max_loss), pnl_pct = pnl / risk.
    Mutates `t` (risk_capital, pnl_pct, entry_price/exit_price for the card, and the
    closing status_history pnl_pct) and returns True when priced, else False so the
    caller keeps its 'no pnl_pct' flag.

    Sub-spread fills come from a typed `spreads[]` overlay when present (each entry
    = {legs, entry_price, exit_price}); else the reference_values convention the
    model already emits for an iron condor: `{call,put}_spread_{entry,exit}`. Prices
    from the RAW captured slots only, never prose (Section 7). MU 260629 worked
    example: call spread +3.86->2.23, put spread -1.48->0 -> entry 2.38, exit 2.23,
    pnl +0.15, risk 47.62, pnl_pct +0.3%."""
    legs = t.get("legs") or []
    spreads = t.get("spreads")
    if spreads:                                    # typed overlay (preferred, forward)
        subs = [(s.get("legs") or [], s.get("entry_price"), s.get("exit_price")) for s in spreads]
    else:                                          # reference_values fallback (current data)
        calls = [l for l in legs if l.get("type") == "call"]
        puts = [l for l in legs if l.get("type") == "put"]
        rv = t.get("reference_values") or {}
        if len(calls) != 2 or len(puts) != 2:
            return False
        subs = [
            (calls, rv.get("call_spread_entry"), rv.get("call_spread_exit")),
            (puts, rv.get("put_spread_entry"), rv.get("put_spread_exit")),
        ]
    entry_whole = exit_whole = 0.0
    for sub_legs, s_entry, s_exit in subs:
        if s_entry is None or s_exit is None:
            return False                           # can't net an incompletely-priced sub-spread
        kind, _w = _spread_credit_or_debit({"legs": sub_legs})
        if kind is None:
            return False                           # a sub-leg group that isn't a clean vertical
        sign = 1 if kind == "credit" else -1
        entry_whole += sign * s_entry
        exit_whole += sign * s_exit
    risk = _structure_max_loss(legs, round(entry_whole, 4))
    if not risk or risk <= 0:
        return False
    pnl = round(entry_whole - exit_whole, 4)
    t["entry_price"] = round(entry_whole, 4)       # net credit(+)/debit(-) — card Entry
    t["exit_price"] = round(exit_whole, 4)         # net close value — card Exit
    t["risk_capital"] = risk
    pnl_pct = round(pnl / risk * 100, 1)
    t["pnl_pct"] = pnl_pct
    closing = _closing_hist(t)
    if closing is not None:
        closing["pnl_pct"] = pnl_pct
    return True


def compute_risk_pnl(t):
    """Deterministic risk-capital + realized P&L% for a CLOSED defined-risk
    vertical options spread (newsletter-ingestion.md C.1). Mutates `t` in place,
    attaching `risk_capital` and a `pnl_pct` (on the trade AND its closing
    status_history entry) when computable; leaves both absent when risk can't be
    derived from stored fields, in which case the frontend shows the raw $ P&L.

    Entry cost (credit collected / debit paid) comes from `entry.level` when the
    issue that INTRODUCED the trade was imported. When it wasn't (the trade opened
    before the import window, so entry.level is null), the entry cost is INFERRED
    from the close: for either spread type the realized pnl = exit_value - entry_cost
    with the sign the position was quoted on, so `entry_cost = exit_price - pnl`
    (GLD 425/450 debit: 0.95 - (-2.70) = 3.65 -> risk 3.65, -2.70/3.65 = -74%). This
    is why the extraction captures `exit_price` on a close.

    - Credit spread: risk = strike_width - credit_collected.
    - Debit spread:  risk = debit_paid.
    Falls back to the raw $ P&L only when NEITHER entry.level NOR (exit_price + pnl)
    is available. Python owns this, never the extraction model.

    Returns a list of validation flags (empty on success), matching the other
    derived-field functions so the caller can collect them uniformly."""
    if t.get("status") != "closed" or t.get("structure") != "options":
        return []
    legs = t.get("legs") or []
    if len(legs) == 1 and legs[0].get("action") == "sell":
        return _compute_single_short_pnl(t)   # C.12 — single-leg short option
    kind, width = _spread_credit_or_debit(t)
    if kind is None:
        if _price_multi_spread(t):   # C.18 — iron condor / multi-spread structure priced from sub-spreads
            return []
        return [f"closed options trade {t.get('id')!r} is not a clean 2-leg vertical — no pnl_pct"]
    closing = _closing_hist(t)
    pnl = closing.get("pnl") if closing else None
    pnl_val = pnl.get("value") if isinstance(pnl, dict) else None
    exit_price = closing.get("exit_price") if closing else None
    if exit_price is None:                   # top-level exit_price (plumbing fix — the
        exit_price = t.get("exit_price")     # model files the close here on the new format)
    # Entry cost = credit collected (credit spread) or debit paid (debit spread).
    # Prefer the typed entry_price, then entry.level; else infer from the close
    # (a pre-import-window trade whose entry economics were never restated):
    #   debit  -> entry = exit - pnl   (GLD 425/450: 0.95 - (-2.70) = 3.65)
    #   credit -> entry = exit + pnl   (sign flips with the side the spread is on).
    entry_cost = t.get("entry_price")
    if entry_cost is None:
        entry_cost = (t.get("entry") or {}).get("level")
    if entry_cost is None and exit_price is not None and pnl_val is not None:
        entry_cost = round(exit_price - pnl_val, 4) if kind == "debit" \
            else round(exit_price + pnl_val, 4)
    if entry_cost is None:
        return [f"closed options trade {t.get('id')!r} — no entry cost and none inferable"]
    risk = round(width - entry_cost, 4) if kind == "credit" else round(entry_cost, 4)
    if risk <= 0:
        return [f"closed options trade {t.get('id')!r} — nonsensical risk {risk}"]
    t["risk_capital"] = risk
    # Prefer a Python-computed pnl from entry/exit levels over a stated one (§8c);
    # fall back to the stated pnl value when exit_price wasn't given.
    if exit_price is not None:
        pnl_val = round(entry_cost - exit_price, 4) if kind == "credit" \
            else round(exit_price - entry_cost, 4)
    if pnl_val is None:
        return [f"closed options trade {t.get('id')!r} — risk computed but no pnl value"]
    pnl_pct = round(pnl_val / risk * 100, 1)
    t["pnl_pct"] = pnl_pct
    if closing is not None:
        closing["pnl_pct"] = pnl_pct
    return []


def _positioning_list(positioning, as_of=None):
    """Normalize a `thesis.positioning` value to the dated-history list shape
    [{as_of, text}] (C.13). Tolerates the legacy flat STRING (wrap as a single entry
    stamped `as_of`), an already-shaped list (pass through), or falsy -> []."""
    if not positioning:
        return []
    if isinstance(positioning, str):
        return [{"as_of": as_of, "text": positioning}]
    if isinstance(positioning, list):
        return positioning
    return []


def accumulate_positioning(t, prior):
    """C.13 — maintain `thesis.positioning` as an APPEND-ONLY dated history
    [{as_of, text}]. Python owns the list; the model emits only THIS issue's
    positioning read as a string (or null), and never sees the prior history (it is
    stripped from the live set in _build_user_message, so it CANNOT echo). Carry the
    prior trade's history forward and append the model's new read — stamped with this
    issue's date (the trade's `last_mentioned`) — when one was stated. A light
    equality guard skips an accidental verbatim repeat (an echo the strip missed)."""
    thesis = t.get("thesis")
    if not isinstance(thesis, dict):
        return
    prior_thesis = (prior or {}).get("thesis") if isinstance(prior, dict) else None
    prior_hist = _positioning_list(
        prior_thesis.get("positioning") if isinstance(prior_thesis, dict) else None,
        (prior or {}).get("last_mentioned") if isinstance(prior, dict) else None)
    new_val = thesis.get("positioning")
    new_text = new_val.strip() if isinstance(new_val, str) and new_val.strip() else None
    hist = list(prior_hist)
    if new_text and (not hist or hist[-1].get("text") != new_text):
        hist.append({"as_of": t.get("last_mentioned"), "text": new_text})
    thesis["positioning"] = hist or None


def merge_into_store(store, trade_updates, issue_date=None):
    """Apply a model's `trade_updates` (reconciled live set + new + newly-terminal)
    to the persistent store. Returns (store, counts). Deterministic; no model.

    `issue_date` (YYYY-MM-DD) enables the never-entered off-ramps (apply_offramp):
    an aged-out indicator/conditional lapses to a discard stub. Omit (None) to skip
    them (backward-compatible — off-ramps need a date to age against / stamp)."""
    prior_live = {t.get("id"): t for t in store.get("live", [])}
    new_live, archived, discarded = [], [], []
    flags = []
    seen = set()
    # Derive/validate + tranche-split each update BEFORE bucketing (§7, §8d). The
    # split runs AFTER normalize_derived, so both children inherit the derived
    # fields (and a shared strategy_id); the open child keeps the original id, so
    # the prior_live carry-forward below still matches on it.
    processed = []
    for t in trade_updates:
        prior = prior_live.get(t.get("id"))
        # CONFIRMED-ENTRY LOCK (user 2026-07-12): "a confirmed entry never changes —
        # it's locked until the trade closes." Once a position is actually entered,
        # its (blended) fill price is authoritative and must survive every later
        # merge — a newsletter reports a close ("closed for +1.40%") or a carry
        # WITHOUT restating the entry, and the live-set model re-emits the trade
        # thinner than stored, so a wholesale replace would drop the confirmed entry.
        # Capture it here, before re-processing overwrites it.
        locked_entry = _confirmed_entry(prior)
        flags += normalize_derived(t)
        accumulate_positioning(t, prior)  # C.13 — dated positioning history
        children = split_tranches(t)
        is_split = len(children) > 1      # mixed close+open -> the OPEN child is a RE-ENTRY
        for child in children:
            apply_blended_entry(child)    # blended cost basis from THIS record's own tranches
            # Restore the locked confirmed entry onto the CONTINUING position (a
            # non-split record, or the CLOSED child of a split) when this merge
            # dropped it. The OPEN child of a split is a genuine RE-ENTRY — a NEW
            # fill with its own (possibly-unstated) entry — so it starts fresh and
            # does NOT inherit the prior lock. A legitimate new add still re-blends
            # (apply_blended_entry above), since that leaves a basis and isn't a drop.
            if locked_entry is not None and not _has_entry_basis(child) \
                    and not (is_split and child.get("status") != "closed"):
                child["entry_price"] = locked_entry
            processed.append(child)
    lapsed = 0
    for t in processed:
        seen.add(t.get("id"))
        if issue_date and apply_offramp(t, issue_date):  # never-entered -> lapsed (discard)
            lapsed += 1
        st = t.get("status")
        if st in ARCHIVE_STATUSES:
            flags += compute_pnl(t)  # risk_capital/pnl_pct at close-time (§8c)
            flags += flag_missing_exit(t)  # C.17 — completeness net for dropped exits
            archived.append(t)
        elif st in DISCARD_STATUSES:
            discarded.append(_discard_stub(t))
        else:  # open / planned / standing indicator -> stays live
            new_live.append(t)
    # Defensive: if the model omitted a live trade entirely (it shouldn't), carry
    # it forward unchanged rather than lose it — but still run the off-ramp so a
    # never-entered read the model quietly dropped can still lapse.
    carried = 0
    for tid, t in prior_live.items():
        if tid not in seen:
            if issue_date and apply_offramp(t, issue_date):
                discarded.append(_discard_stub(t))
                lapsed += 1
            else:
                new_live.append(t)
                carried += 1
    # Append to archive/discarded, deduped by id: an import retry after a partial
    # write (store committed, marker not) re-applies the same trades — dedup keeps
    # that harmless. `live` is rebuilt fresh each call, so it's idempotent already.
    arch_ids = {t.get("id") for t in store.get("archive", [])}
    disc_ids = {d.get("id") for d in store.get("discarded", [])}
    store["live"] = new_live
    store["archive"] = store.get("archive", []) + [t for t in archived if t.get("id") not in arch_ids]
    store["discarded"] = store.get("discarded", []) + [d for d in discarded if d.get("id") not in disc_ids]
    counts = {
        "live": len(new_live),
        "archived_now": len(archived),
        "discarded_now": len(discarded),
        "lapsed_now": lapsed,  # never-entered indicators/conditionals aged out (off-ramp)
        "carried_unmentioned": carried,
        "flags": flags,  # validation/derivation issues surfaced for manual review
    }
    # `processed` is the fully-derived, tranche-SPLIT representation of this issue's
    # trades (split children + computed pnl live here, not in the caller's raw
    # `trade_updates`). Return it so the per-issue marker/edition file freezes the SAME
    # post-split shape the store got — else a split trade freezes as ONE record and the
    # past-edition view loses the split child (fixed 2026-07-10).
    return store, counts, processed


def ingest_issue(issue_text, store, model=EXTRACTION_MODEL, effort=None):
    """Full one-issue pipeline: run the model against the store's live set, then
    merge its output back in. Returns (issue_data, store, usage, counts).
    `issue_data` is the per-issue extract (envelope + this issue's trade_updates);
    write it as NEWSLETTER_EXTRACTED_DIR/<stem>.json. Atomic write / endpoint
    wiring is the step-3 caller's job.

    effort: passed straight through to run_extraction() for the Layer-0 cost
    experiment — None (API default "high") or "low"/"medium"/"high"/"xhigh"/"max"."""
    data, usage = run_extraction(issue_text, store.get("live", []), model=model, effort=effort)
    store, counts, processed = merge_into_store(
        store, data.get("trade_updates", []), issue_date=data.get("issue_date"))
    data["trade_updates"] = processed  # freeze the post-split shape into the edition file
    return data, store, usage, counts


# Standard Claude Sonnet rates, USD per million tokens (input / cache-write /
# cache-read / output). The token counts are exact regardless; swap rates per tier.
RATE_IN, RATE_CACHE_WRITE, RATE_CACHE_READ, RATE_OUT = 3.00, 3.75, 0.30, 15.00


def _atomic_write_json(path, obj):
    """Temp file + os.replace so the destination only ever appears complete."""
    tmp = os.path.join(os.path.dirname(path), ".tmp_" + os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def ingest_issue_recorded(text, store, extracted_dir, stem, filename, mode,
                          effort=None, model=EXTRACTION_MODEL):
    """Instrumented single-issue ingest — the SHARED path for the CLI
    (run_import.py) and the /import_newsletter endpoint, so BOTH capture identical
    telemetry for review (previously only the CLI did; the endpoint discarded it).

    Splits the pipeline to snapshot the PRISTINE pre-merge extract (a free re-derive
    receipt), writes _store.json then the per-issue marker atomically (marker LAST =
    the completion signal), then records ALL telemetry:
      - thinking trace -> thinking_logs/
      - store + marker + raw_extract + response -> run_archive/ (tagged stem/effort/stamp)
      - a token+cost row appended to cost_experiment_log.jsonl

    Callers own their pre-checks (cold/force/traversal/start-date/marker) and pass the
    already-loaded store + extracted PDF text. Returns a dict:
      {data, store, counts, usage, cost_usd, run_stamp, thinking_log, experiment_log}.
    """
    import copy as _copy, time as _time
    t0 = _time.time()
    data, usage = run_extraction(text, store.get("live", []), model=model, effort=effort)
    raw_extract = _copy.deepcopy(data)
    store, counts, processed = merge_into_store(
        store, data.get("trade_updates", []), issue_date=data.get("issue_date"))
    data["trade_updates"] = processed  # marker/edition freezes the post-split shape
    elapsed = _time.time() - t0

    store_path = os.path.join(extracted_dir, "_store.json")
    marker = os.path.join(extracted_dir, stem + ".json")
    _atomic_write_json(store_path, store)   # store first...
    _atomic_write_json(marker, data)        # ...marker LAST (completion signal)

    it = usage.get("input_tokens") or 0
    cw = usage.get("cache_creation_input_tokens") or 0
    cr = usage.get("cache_read_input_tokens") or 0
    ot = usage.get("output_tokens") or 0
    thinking_tokens = usage.get("thinking_tokens") or 0
    final_tokens = usage.get("final_tokens") or 0
    cost = (it * RATE_IN + cw * RATE_CACHE_WRITE + cr * RATE_CACHE_READ
            + ot * RATE_OUT) / 1_000_000

    effort_label = effort or "default(high)"
    run_stamp = _time.strftime("%Y%m%d-%H%M%S")

    # Thinking trace (previously 100% discarded).
    thinking_log_dir = os.path.join(extracted_dir, "thinking_logs")
    os.makedirs(thinking_log_dir, exist_ok=True)
    thinking_log_path = os.path.join(
        thinking_log_dir, f"{stem}__effort-{effort_label}__{run_stamp}.txt")
    with open(thinking_log_path, "w", encoding="utf-8") as f:
        f.write(usage.get("thinking_text") or "")

    # Reusable receipts: store snapshot + marker + PRISTINE pre-merge extract (free
    # re-derive) + raw response text (the literal JSON we paid for).
    run_archive_dir = os.path.join(extracted_dir, "run_archive")
    os.makedirs(run_archive_dir, exist_ok=True)
    base = f"{stem}__effort-{effort_label}__{run_stamp}"
    _atomic_write_json(os.path.join(run_archive_dir, base + "__store.json"), store)
    _atomic_write_json(os.path.join(run_archive_dir, base + "__marker.json"), data)
    _atomic_write_json(os.path.join(run_archive_dir, base + "__raw_extract.json"), raw_extract)
    with open(os.path.join(run_archive_dir, base + "__response.txt"), "w", encoding="utf-8") as f:
        f.write(usage.get("final_text") or "")

    # One JSON-lines row per run — directly diffable across runs/effort levels.
    experiment_log_path = os.path.join(extracted_dir, "cost_experiment_log.jsonl")
    with open(experiment_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": run_stamp, "filename": filename, "stem": stem, "mode": mode,
            "effort": effort_label, "elapsed_s": round(elapsed, 1),
            "input_tokens": it, "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr, "output_tokens": ot,
            "thinking_tokens": thinking_tokens, "final_tokens": final_tokens,
            "cost_usd": round(cost, 4),
            "thinking_log_file": os.path.basename(thinking_log_path),
            "source": "dashboard" if mode.startswith("dashboard") else "cli",
        }) + "\n")

    return {"data": data, "store": store, "counts": counts, "usage": usage,
            "cost_usd": round(cost, 4), "elapsed_s": round(elapsed, 1),
            "run_stamp": run_stamp, "thinking_log": thinking_log_path,
            "experiment_log": experiment_log_path}
