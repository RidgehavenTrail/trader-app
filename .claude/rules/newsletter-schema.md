---
paths:
  - "newsletter*.py"
  - "watchtower.html"
  - "watchtower_engine.py"
---
<!-- 2026-07-13: removed retired market_data_engine.py entry (retired 2026-07-12). -->


# Newsletter Schema — Structured Extraction & Trade Lifecycle (drafted 2026-07-05)

**Status (updated 2026-07-13):** SHIPPED. Schema was drafted and confirmed against
3 real newsletter issues (2026-06-09, 2026-06-22, 2026-06-29), then built and
consolidated into `watchtower_engine.py`/`watchtower.html` (sessions 16-23,
2026-07-08 through 2026-07-13). The line that used to be here — "Not yet
implemented — no ingestion/parsing code exists against this schema yet" — was
accurate on 2026-07-05 but was never updated across two subsequent edit passes
(session 16 on 2026-07-08, session 21 on 2026-07-12) even as the rest of this file
kept growing; don't assume a status line here is current just because nearby
content looks fresh. The design/schema details below remain the settled target
shape and are still accurate — only this status paragraph was stale. This
supersedes the rough schema draft in the "Original brainstorm" section at the
bottom of `newsletter-tracker.md` — that section's schema was speculative; this
one is evidence-based against real issues and should be treated as the current
target shape. Leave the brainstorm section in place for historical context but
do not build against it.

## Design principles confirmed against real issues

- Weekly section skeleton is stable across all 3 issues reviewed: What's New →
  What We're Watching → SPX Gamma Positioning → Key SPY Levels → Notable Flow →
  New Trade Setups → Open Trades → Closed Trades → Portfolio House View. Same
  shape every issue, safe to parse against structurally.
- `portfolio_house_view` and `market_structure` (Key SPY Levels) are the most
  rigidly structured, most diffable content — same 7 asset classes, same level
  concepts (call wall / hedge wall / put wall / desk pivot / deep support), every
  week. Good first build/test target before tackling trade parsing.
- A basket/pairs "leg" (loose desk usage) and an options "leg" (strike/expiry/
  right/action — the actual technical term) are different things and must not
  share a field. Equity/pairs components use `basket`; options structures use
  `legs`. `type` field on each leg is `"call"|"put"` (not `right`, for schema
  readability — same underlying legal concept, more familiar wording).
- Silence in a subsequent issue means different things depending on status:
  - `planned` / conditional-not-triggered → silence = abandoned. No explicit
    close event is needed for this transition. **Correction (2026-07-06):**
    USDJPY was originally cited here as the silent-abandonment example, but the
    real PDF run (issues 2026-05-25 → 2026-06-29) shows it was mentioned every
    week it was live and then EXPLICITLY retired on 2026-06-22 (BoJ hiked and
    USDJPY ran to 161.4, against the short) — not silently dropped. The
    asymmetric rule still stands on its own logic, but across all six real
    issues this diligent publisher never dropped a live trade silently, so the
    silent-abandonment branch is real yet DORMANT in practice for this source.
  - `open` / `active` → silence is NEVER treated as a close. Only an explicit
    "closed at $X" / "stopped" / "expired worthless" line resolves it. If an
    open trade goes unmentioned 2+ issues, set `stale_flag: true` and keep
    tracking — do not auto-resolve. Only a manual user action (delete) removes
    a stale-but-open trade from the tracker.
- Some trades are indicators, not tradeable recommendations (`role: "indicator"`,
  conviction `label: "observation_only"` or `"watchlist"` instead of a dot score)
  — e.g. the software dispersion basket was explicitly a working, tested spread
  but flagged Observation Only because its job was to be a read on whether the
  market rewards real AI monetization vs. sector beta broadly, not a position to
  take yet. Captured via `indicates` (free text on what broader question this is
  a proxy for) and `linked_theme` (points at the issue-level `themes[]` array).
  Same concept applies to playbook candidates (see World Cup example below).
- A trade `strategy_id` is separate from a trade `id` — the same strategy (e.g.
  the defensive rotation basket) can close and re-open as a genuinely new trade
  instance within or across issues (confirmed: it closed and re-entered within
  issue 2 itself, then closed differently in issue 3). Grouping by `strategy_id`
  is what makes a future hit-rate/conviction tracker possible; grouping by `id`
  alone would treat each re-entry as unrelated.
- Overlay trades — short-dated options written against a persistent core
  position, e.g. the SOXX collar/covered call into MU earnings — point back at
  the core trade via `overlay_of` rather than existing as free-floating trades.
  A core position also needs `is_core_position: true` so it can be excluded from
  tactical-book P&L aggregation (the letter itself does this explicitly for SOXX
  — "not including this in our performance illustration"). **Set it ONLY on that
  explicit exclusion, not on descriptive wording (confirmed 2026-07-06):** the
  2026-06-01 issue calls the SMH/SOXX long a "standout core position," but that
  is flavor, not a P&L-exclusion statement, so it stays `is_core_position:
  false`. Require the explicit "excluded from performance" language.
- `type` (trade structure: `pairs` / `options_spread` / `options_condor` /
  `options_collar` / `single_option` / `outright_equity` / `outright_future` /
  `outright_forex` / `seasonal_equity`) is a different axis from `asset_class` (`equity` / `future`
  / `forex` / `pair`) — resolves the open reconciliation question originally
  flagged at the bottom of `newsletter-tracker.md`. `type` describes the trade's
  structure; `asset_class` describes what underlies it. **`outright_forex` added
  2026-07-06** during the first real ingestion pass (issue 2026-05-25, USDJPY /
  EURUSD outright shorts) — the enum previously had `outright_equity` and
  `outright_future` but no forex-outright value even though `asset_class`
  already includes `forex`. It is the third member of the outright trio, nothing
  more; the settled forex handling (Narrative/Chart tabs, no Options tab,
  `=X`-suffix detection in `get_asset_class()`) is unchanged.
- **`single_option` — one option leg (added 2026-07-06).** For any single-leg
  option position: a covered-call overwrite, a cash-secured put, a standalone
  long call/put. `legs` holds the one leg; `structure_label` names the strategy
  (`covered_call`, `cash_secured_put`, …). Added when the 2026-06-22 SOXX Jun-18
  650 covered-call overwrite had no matching multi-leg `type`.
  **A COVERED CALL IS MODELED AS TWO OBJECTS, NEVER ONE:**
  1. the persistent equity core — an `outright_equity` trade that continues
     untouched (e.g. `smh-long-2026-05-25`, the SOXX/SMH long);
  2. the short call written against it — a `single_option` overlay with
     `overlay_of` pointing at the core and `structure_label: "covered_call"`.
  The "covered" aspect lives entirely in `overlay_of`, not in the option
  structure — the overlay itself is just one short call. When the call expires,
  the overlay object goes `closed` (premium kept as its own P&L) and the equity
  core simply continues ("becomes a straight equity play" again); nothing merges.
  **Rolls insert cleanly:** rolling a covered call = close the old `single_option`
  overlay and open a NEW `single_option` overlay instance sharing the same
  `strategy_id` (same re-entry pattern as any strategy_id re-entry), all
  `overlay_of` the same equity core. Each written call thus keeps its own
  strikes/expiry/premium for a hit-rate/P&L scoreboard.
- **Options tab / heatmap-hook gating must key off trade structure, not
  `asset_class` alone (caught 2026-07-06).** `asset_class: 'equity'` is true
  for both an outright single-name trade AND a multi-ticker equity basket/pairs
  trade (e.g. the RKLB/SPCE/RDW basket below) — so gating the Options tab on
  `asset_class === 'equity'` alone would incorrectly show it for a basket,
  which has no single options chain. The correct signal is presence of `legs`
  (single-underlying options structure — spread/condor/collar/overlay, all
  have a real chain) or a plain single-ticker outright equity/future, vs.
  presence of `basket` (multiple tickers, no single chain — always hide).
  Multi-leg options structures are NOT the exception here; they should show
  the Options tab and heatmap hook exactly like outright equity does, gated
  further by the existing equity/ETF-only rule in `heatmap-dashboard-hook.md`
  (futures/forex `legs`-based trades, if they ever exist, still get no
  heatmap — no yfinance options chain to draw from).
- **`underlying` (ticker string, required whenever `legs` is non-null)** —
  added so the Options tab and the future heatmap-hook launch (`heatmap_3d.py
  TICKER --snapshot`) have a reliable field to key off, instead of parsing it
  out of the `id` string (fragile the moment `id` naming drifts). Null for
  `basket`-based trades (no single underlying). For `overlay_of` trades,
  `underlying` should match the core position's underlying, not be inferred
  from the overlay's own `id`.
- **`underlying` also holds the single instrument for a PLAIN OUTRIGHT (added
  2026-07-06).** The schema originally showed `underlying` only for `legs`-based
  options trades; the first real ingestion pass surfaced plain single-name
  outrights (TSM long, TLT long, HG copper long, USDJPY short) that have neither
  `legs` nor a `basket`. Convention: an outright single-name trade puts its one
  instrument in `underlying`, with `basket` = null and `legs` = null. So
  `underlying` is the single-instrument slot for BOTH options structures (the
  ticker the chain is written on) and bare outrights (the instrument itself).
  Options-tab/heatmap gating keying off "presence of `legs` OR a single-ticker
  outright" (per the gating bullet above) is satisfied by this.
- **`underlying_alias` — equivalent index/ETF vehicle (added 2026-07-06).** When
  the newsletter names an index and its tradeable ETF proxy for the SAME
  exposure (e.g. SOXX index quoted alongside the SMH ETF; SPX alongside SPY),
  that is ONE outright position, NOT a two-ticker basket. Put the tradeable
  vehicle in `underlying` (the one with a real chart/options chain — SMH, SPY)
  and the index/equivalent it is also quoted as in `underlying_alias` (string,
  null when there is no alias). Confirmed with the user during the 2026-05-25
  pass: "SMH/SOXX are not pairs — they are equivalent vehicles," same as
  SPY/SPX. This is the trade-level analog of how `market_structure.levels`
  already dual-quotes every level as `{spx, spy}`. Keeping the alias lets a
  later issue that names *either* ticker still match the same trade on diff.
  Distinct from the still-open `CL1!` vs `CL=F` display-vs-fetchable-symbol item
  below (that is one instrument under two notations; this is two equivalent
  instruments for one exposure). **`underlying_alias` may cross asset classes
  (confirmed 2026-07-06, held-out 2026-06-01 pass):** an ETF-options trade
  written on a commodity — e.g. a GLD Jun 425/450 call spread the letter quotes
  with a "GC (August) reference for the underlying" — is `underlying: "GLD"`
  (the tradeable options vehicle, `asset_class: "equity"` since the chain is
  GLD's) + `underlying_alias: "GC"`, with the commodity-price levels (gold
  ~4,950) in `reference_values`.
- Reference numbers (e.g. "spot reference $87.29", "reference credit ~$18.20")
  are informational anchors, not actionable triggers — kept in a separate
  `reference_values` object rather than mixed into `entry`/`stop`/`targets`.
- `campaign_title` (free text, e.g. `"Re-join the Trend"`) is a third,
  human-facing identifier distinct from `id`/`strategy_id` — only populated
  when the newsletter gives one, never invented. Useful for telling apart
  multiple simultaneous trades on the same underlying (e.g. TLT's spot long
  vs. its later Dec 18 88/92 call spread) and as a mnemonic hook for the
  trade's thesis.
- `key_dates` (array of `{date, event, significance, passed}`) captures a
  trade's catalyst calendar — confirmed valuable even for a conditional trade
  that never triggered (e.g. USDJPY's BOJ/CPI/NFP calendar tracked over 2-3
  weeks). `passed` is a display-only checkbox flag and never drives lifecycle
  logic; a fully checked-off list does not abandon or stale-flag the trade.
  **`passed` is display-COMPUTED, not stored-authoritative (confirmed
  2026-07-06):** the extractor always emits `passed:false` and must not compute
  it from the issue date; `watchtower.html` compares each `date` to today live
  and renders passed dates with a check/strikethrough. This avoids a stored flag
  going stale as time passes after import.
- **`status_history` logs material parameter changes, not just status/P&L
  (added 2026-07-06, held-out 2026-06-01 pass).** Append a
  `{date, status, pnl?, note?}` entry when the status changes, a P&L is
  reported, OR a material risk parameter (stop / target / sizing) changes even
  with status unchanged — e.g. the META bear-call spread had a hard $650
  close-stop added on 2026-06-01 with no status/P&L change; that is logged as an
  `open` entry with a `note` describing the tightening, giving an audit trail of
  risk-management moves. Pure wording/thesis rephrasing is NOT logged.
- `positioning_note` (free text, 1-2 sentences) replaces a raw weekly COT
  table — only populated when the newsletter explicitly ties futures
  positioning to a specific trade's thesis, paraphrased rather than storing
  the underlying weekly numbers. General CFTC commentary not tied to a
  specific trade stays out of the trade object entirely.
- `holding_period` (`{stated_text, min_weeks, max_weeks}`) captures an
  explicitly stated expected duration (e.g. "2-4 Week Hold") — only when the
  newsletter states one; left null otherwise, including for options trades,
  where `legs[].expiry` already provides a hard mechanical horizon. The
  newsletter never restates a countdown week to week, so nothing here should
  either — a display layer computes elapsed time against `first_seen` live
  rather than expecting a weekly-updated remaining-time value. If a later
  issue explicitly revises the expectation, log it as a dated override rather
  than replacing the original stated range.
- `paired_with` (a trade `id`) + `pairing_note` (free text) capture a
  deliberate cross-trade hedge relationship between two otherwise unrelated
  trades — distinct from `overlay_of` (options written against the *same*
  underlying position) and from `strategy_id` (re-entries of the *same* idea
  over time). Confirmed via the 2026-05-04 issue: a META conditional short
  was explicitly sized dollar-neutral against a separate TSM long specifically
  to offset that position in a broad-selloff scenario — two different
  instruments, deliberately paired for portfolio-level risk, not a repeat of
  one idea. Only populate when the newsletter states the relationship
  explicitly; do not infer pairings from proximity or theme alone.
- **`entry.level` / `stop.level` / `targets[].level` must hold a bare number
  (or `null`), never prose — RESOLVED 2026-07-08 (surfaced 2026-07-07 by the first
  real card-design pass against the 06-08 import).** The initial extraction prompt
  let these fields absorb whatever phrasing the newsletter used — e.g. `entry.level:
  "$0.70-$0.80 credit; do not chase below $0.60"` — which is unusable for display
  (can't render on a compact card) or computation (can't sort/compare/plot).
  Confirmed inconsistent even within one issue: copper's `targets[0].level` came
  back as a clean `6.68`, proving the model can do this correctly; it just wasn't
  required to. **Finalized shape:** `entry`, `stop`, and every `targets[]` entry
  each get `level` (bare number or `null` — never fabricated when the newsletter
  states no number, e.g. SMH's purely qualitative "continued outperformance after
  the pullback"), `level_high` (bare number, populated only for a genuine stated
  range — `level` is the lower/nearer bound, `level_high` the upper/farther one;
  `null` otherwise), and **`note`** (chosen over `condition` — matches the schema's
  existing pervasive `note` convention; short paraphrase of qualifying/conditional
  language, e.g. "do not chase below $0.60"; detail-panel content only, never
  rendered on the card). See `.claude/rules/newsletter-ingestion.md` section B.1 for
  the full `EXTRACTION_SYSTEM` prompt language and worked before/after examples.
- **`underlying` must be a bare ticker/symbol string, never prose — RESOLVED
  2026-07-08 (reinforced 2026-07-07).** Already the documented shape, but the first
  real extraction violated it once: copper's `underlying` came back as `"HG
  (front-month copper future)"` instead of `"HG"`. No new field needed — this was a
  prompt-adherence gap on an already-correct rule; fixed via an `EXTRACTION_SYSTEM`
  addition, no schema change. See newsletter-ingestion.md section B.2.
- **Outright trades get a real `direction` field (`"long"` | `"short"` | `null`) —
  RESOLVED 2026-07-08 (recommended 2026-07-07).** Populated only on
  `outright_equity`/`outright_future`/`outright_forex` trades (`null` for spreads,
  baskets, and single-option overlays, whose side is already implied by structure /
  per-leg `side`); replaces the previous fragile pattern of parsing direction out of
  the `id` string's `-long`/`-short` suffix. **Display decision (user, 2026-07-08):**
  show the direction word on every outright card, colored green for Long / red for
  Short (reusing the card's existing P&L green/red tokens). See
  newsletter-ingestion.md section D (Outright card) for the resolved card spec.
- **Closed defined-risk options trades carry a computed `risk_capital` and
  `pnl_pct` once closed — IMPLEMENTED 2026-07-08 (session 16), Python's job, not
  the model's.** A closed credit spread's max risk is `strike_width -
  credit_collected`; a closed debit spread's max risk is simply the debit paid.
  Real worked examples: DOCU (credit spread) risked $4.49, realized +11.4%; the
  GLD bull call spread (debit spread) risked $3.65, realized -74%. Getting the
  credit-vs-debit formula right matters — applying the credit-spread formula to a
  debit spread was tried once during design and produces a badly wrong (far too
  optimistic) percentage. Computed **deterministically in Python** at close-time
  (`compute_risk_pnl()` in `newsletter_ingest.py`, called from `merge_into_store()`),
  matching the principle that Python owns deterministic bookkeeping, never the
  extraction model. **Entry economics that predate the import window are no longer a
  raw-$ fallback:** the extraction now also captures `exit_price` on a close, and
  `compute_risk_pnl()` infers the entry cost from it (debit: `entry = exit − pnl`;
  credit: `entry = exit + pnl`) — GLD's -74% is computed this way (exit_price 0.95
  from the letter, inferred debit 3.65). Raw $ is shown ONLY when neither the entry
  cost NOR (`exit_price` + `pnl`) is available. See newsletter-ingestion.md section
  C.1 and its "C.1 extension" subsection for the full formulas, prompt language, and
  the GLD backfill note.

## Schema
### Issue envelope

```json
{
  "issue_date": "2026-06-29",
  "title": "Burnout: the AI trade got heavy",
  "themes": ["AI/semi unwind", "rotation into breadth", "disinflation from crude"],
  "market_structure": { "...": "see below" },
  "portfolio_house_view": [ "...see below" ],
  "notable_flow_summary": "paraphrased, own-words condensation, not reproduced verbatim",
  "trade_updates": [ "...new trades + status_history entries for existing ones" ],
  "playbooks": [ "...see below" ]
}
```

### `market_structure`

```json
{
  "index_close": { "spx": 7354.02, "spy": 735.40 },
  "levels": [
    { "spx": 7500, "spy": 750, "label": "call_wall", "note": "main upside ceiling" },
    { "spx": 7400, "spy": 740, "label": "hedge_wall", "note": "reclaim improves tape" },
    { "spx": 7300, "spy": 730, "label": "put_wall", "note": "first major support" },
    { "spx": 7000, "spy": 700, "label": "deep_support", "note": "downside magnet" }
  ]
}
```

Labels normalized to a fixed set (`call_wall`/`hedge_wall`/`put_wall`/`gamma_flip`/
`desk_pivot`/`deep_support`) since exact wording shifts slightly issue to issue but
the underlying concepts don't.
### `portfolio_house_view`

```json
[
  { "asset_class": "equities", "view": "constructive, but rotational", "key_driver": "..." },
  { "asset_class": "gold", "view": "bearish", "key_driver": "..." }
]
```

Fixed 7 rows every issue (equities, gold, oil, short-end rates, long-end rates,
credit, dollar) — `view` string is directly diffable week over week.

### Trade object (persistent entity; each issue supplies updates via `trade_updates`)

```json
{
  "id": "rklb-vs-spce-rdw-2026-06-09",
  "strategy_id": "space-quality-dispersion",
  "type": "pairs",
  "asset_class": "equity",
  "role": "tradeable",
  "conviction": { "scale": 4, "max_scale": 5, "label": null },
  "indicates": null,
  "linked_theme": null,

  "underlying": null,
  "underlying_alias": null,
  "direction": null,
  "beta_neutral": true,
  "basket": [
    { "ticker": "RKLB", "side": "long", "weight": 1.0 },
    { "ticker": "SPCE", "side": "short", "weight": 0.53 },
    { "ticker": "RDW",  "side": "short", "weight": 0.53 }
  ],
  "legs": null,
  "structure_label": null,

  "sizing": { "risk_unit": 0.5, "note": "starter, add to 1.0 on confirmation" },
  "tranches": [
    { "date": "2026-06-09", "level": null, "size": 0.5, "note": "starter" }
  ],
  "entry": { "trigger_type": "immediate", "level": null, "level_high": null, "note": null },
  "stop": { "level": 5.00, "level_high": null, "basis": "raw_spread_close", "note": null },
  "targets": [
    { "label": "T1", "level": 5.57, "level_high": null, "note": null },
    { "label": "T2", "level": 6.00, "level_high": 6.25, "note": null }
  ],
  "reference_values": { "raw_spread_current": 5.38, "raw_spread_200dma": 5.57 },
  "thesis": "paraphrased summary, not reproduced verbatim",
  "campaign_title": null,
  "key_dates": [],
  "positioning_note": null,
  "holding_period": { "stated_text": null, "min_weeks": null, "max_weeks": null },

  "is_core_position": false,
  "overlay_of": null,
  "paired_with": null,
  "pairing_note": null,

  "first_seen": "2026-06-09",
  "last_mentioned": "2026-06-29",
  "status": "closed",
  "stale_flag": false,
  "weeks_unmentioned": 0,
  "status_history": [
    { "date": "2026-06-09", "status": "open" },
    { "date": "2026-06-22", "status": "open", "pnl": { "value": 8, "unit": "pct" } },
    { "date": "2026-06-29", "status": "closed", "pnl": { "value": 9.5, "unit": "pct" } }
  ]
}
```
**Options-trade variant** — same object shape, different fields populated:

```json
{
  "id": "fivn-jun18-2530-bearcall-2026-06-09",
  "type": "options_spread",
  "structure_label": "bear_call_spread",
  "asset_class": "equity",
  "underlying": "FIVN",
  "basket": null,
  "legs": [
    { "strike": 25, "expiry": "2026-06-18", "type": "call", "action": "sell" },
    { "strike": 30, "expiry": "2026-06-18", "type": "call", "action": "buy" }
  ],
  "reference_values": { "entry_credit": 0.60 }
}
```

**Outright-trade variant** (bare single-instrument long/short — added 2026-07-08 to
show `direction` populated; HG copper long):

```json
{
  "id": "hg-copper-long-2026-05-25",
  "type": "outright_future",
  "asset_class": "future",
  "underlying": "HG",
  "underlying_alias": null,
  "direction": "long",
  "basket": null,
  "legs": null,
  "entry": { "trigger_type": "scaled", "level": 6.45, "level_high": null, "note": "half size" },
  "stop": { "level": 6.11, "level_high": null, "basis": null, "note": null },
  "targets": [ { "label": "T1", "level": 6.68, "level_high": null, "note": null } ]
}
```

**Overlay-trade variant** (SOXX collar written against the core SOXX long):

```json
{
  "id": "soxx-collar-jun26-2026-06-22",
  "overlay_of": "soxx-long-2026-04",
  "type": "options_collar",
  "structure_label": "collar",
  "underlying": "SOXX",
  "legs": [
    { "strike": 645, "expiry": "2026-06-26", "type": "call", "action": "sell" },
    { "strike": 572.5, "expiry": "2026-06-26", "type": "put", "action": "buy" }
  ]
}
```
**Indicator/observation variant** (software dispersion basket):

```json
{
  "id": "software-dispersion-basket-2026-06-09",
  "type": "pairs",
  "role": "indicator",
  "conviction": { "scale": null, "max_scale": 5, "label": "observation_only" },
  "indicates": "whether the market is rewarding real AI monetization vs sector beta broadly",
  "linked_theme": "AI/semi unwind",
  "basket": [
    { "ticker": "CRWD", "side": "long", "weight": null },
    { "ticker": "PANW", "side": "long", "weight": null },
    { "ticker": "NET", "side": "long", "weight": null },
    { "ticker": "WIX", "side": "short", "weight": null },
    { "ticker": "FIVN", "side": "short", "weight": null },
    { "ticker": "PD", "side": "short", "weight": null }
  ]
}
```

## Status state machine (confirmed rules)

`planned → { abandoned (silent AND ticker absent from the whole issue),
unresolved (trade-silent but ticker still discussed in commentary),
lapsed (never-entered off-ramp: an indicator unreferenced 2+ issues, or a
never-triggered conditional past its holding_period.max_weeks / 4-week default),
triggered → open }`

`open → { open (flag via stale_flag/weeks_unmentioned if unmentioned 2+ issues),
closed (explicit mention only), deleted (manual, user-initiated) }`

**`open` vs `planned` is decided by ENTRY MECHANICS, not prose (added
2026-07-06).** A trade is `open` only when the issue confirms it is actually held
— explicit ownership ("own at $X", "we entered", "hold"), a reported P&L, or a
tranche stated as filled/stopped. A trade whose entry is still levels to act on —
a sell-stop, "enter on a close above / pullback to X", or a SCALED / TWO-TIER
entry (e.g. copper's "$6.45 half, $6.30 add") with no confirmed fill — is
`planned`, even when the surrounding prose is bullish ("breakout confirmed, held
through pullbacks"). The tactical table's entry column outranks the narrative:
the real 2026-05-25 → 06-01 run showed the model reading copper `open` off the
enthusiastic prose when the tiered entry meant `planned`, correctly becoming
`open` on 06-01 once the letter said "Own at $6.375". Put the tiers in `tranches`
with `entry.trigger_type:"scaled"` and hold `planned` until ownership/P&L is
reported (transition keeps the same `strategy_id`).

Silence never auto-closes an `open` trade. This is a deliberately asymmetric
rule. (Note 2026-07-06: the USDJPY case originally cited as confirmation was, on
the real PDF run, explicitly retired 2026-06-22 rather than silently dropped —
see the correction under "Design principles" above. The rule holds; only the
example was mislabeled. No live trade was dropped silently in any of the six
real issues ingested.)

**`unresolved` — planned-trade silence is not always abandonment (added
2026-07-06, surfaced by the 2026-06-08 pass).** A "trade-level update" is a
status/entry/exit/stop line in the tactical table, closed list, or per-trade
review — NOT the ticker merely appearing in market commentary. When a `planned`
trade gets no trade-level update, split on whether its ticker appears anywhere in
the issue: **wholly absent → `abandoned`** (the clean silence signal); **still
discussed in commentary** (its thesis narrated as playing out, e.g. the DDOG
conditional put spread whose "software crack" was described as "arriving on
schedule" with no trade-level trigger/entry/status) **→ `unresolved`**, with a
`note` on the `status_history` entry. `unresolved` protects a trade that may have
quietly triggered and worked from being erased as `abandoned` — it is a
manual-judgment resting state, not a terminal loss, and matters for a future
hit-rate scoreboard. In both cases `last_mentioned` stays at its prior value (the
trade itself was not mentioned).

**Observation-only indicators get a LONGER silence leash, not permanent exemption
(revised 2026-07-11 — was "exempt from silence, retired only on explicit drop").**
A trade with `conviction.label: "observation_only"/"watchlist"` (e.g. the software
winners/losers dispersion basket) is a STANDING watchlist read, not a position, so
a SINGLE issue of silence never abandons or unresolves it (it recurs
intermittently). A reference to its theme OR any of its constituent tickers
anywhere in the issue counts as a mention: update `last_mentioned`, reset
`weeks_unmentioned = 0`, carry it forward. **But it is NOT exempt forever** — once
it goes `weeks_unmentioned >= 2` it LAPSES to a `lapsed` discard stub (the
never-entered off-ramp; see below and newsletter-ingestion.md item J). User's
rule (2026-07-11): "at some point the trade is no longer relevant — there has to
be an off-ramp, especially if there's never an entry." Python owns the lapse
(deterministic, §7); the model just tracks `weeks_unmentioned` faithfully. It is
also retired immediately on an explicit drop. (Confirmed on 2026-06-22 the theme +
a constituent FIVN recurred without a restate, keeping it live then; it later went
silent 06-29 + 07-06 and lapsed at 07-06.)

**Never-entered off-ramps, generalized (2026-07-11).** The indefinite no-auto-close
protection is reserved for genuinely-ENTERED positions (real risk). Anything
**never entered** (currently `planned`, no `status_history` entry ever reached
open/closed) eventually lapses: an indicator after 2 unreferenced issues (above);
a never-triggered conditional past its stated `holding_period.max_weeks` (else a
4-week default). Both → `lapsed` (a discard status: lightweight stub, out of the
scoreboard since it was never a position).
## `playbooks` — standing recurring signals, not single trades

Some newsletter content is a conditional rule that can fire repeatedly against a
bracket of candidates, not a single trade instance — e.g. the World Cup
elimination-fade trade (short a country's home index the session after its team
is eliminated). Forcing this into the trade schema would lose the "pre-built,
fires on confirmation" nature of it.

```json
{
  "id": "world-cup-elimination-fade-2026",
  "role": "indicator",
  "trigger_rule": "short home index next session after home team's elimination",
  "candidates": [
    { "entity": "Brazil", "index": "IBOV", "next_event_date": "2026-06-30", "status": "pending" },
    { "entity": "Germany", "index": "DAX", "next_event_date": "2026-06-30", "status": "pending" }
  ],
  "sizing_per_trigger": 0.5,
  "hold_sessions": "1-2"
}
```

## `analysis_features` — one-off/periodic content, not a trade or market_structure

Some newsletter content is analytical context that occasionally informs a trade
without being one, and doesn't appear on a fixed weekly cadence — e.g. a 23-ETF
sector/factor composite model (published irregularly, "we last published in
February") or an ad-hoc single-asset deep-dive the newsletter itself flags as
outside its standard template (e.g. "Oil: The Iran Variable"). Two variants,
same lightweight bucket — a title, a short paraphrased summary, and (only for
rankings) a couple of ticker lists. Deliberately not trying to mirror the
newsletter's full underlying analytical machinery (e.g. not storing all 23 ETF
scores, just the useful ends of the ranking).

**Ranking variant:**

```json
{
  "id": "sector-rotation-model-2026",
  "type": "sector_model",
  "title": "2026 Sector Rotation",
  "summary": "Model ranks 23 sector/factor ETFs on momentum, trend, vol edge, and rate sensitivity. Energy (XOP, XLE) ranks near the bottom on the deal-regime shift, while VLUE stands out as the one name combining cheap options with confirmed momentum.",
  "top_ranked": ["VLUE"],
  "bottom_ranked": ["XOP", "XLE"],
  "linked_theme": null
}
```

**Deep-dive variant** (no ranking, just context):

```json
{
  "id": "oil-iran-variable-2026-05-25",
  "type": "deep_dive",
  "title": "Oil: The Iran Variable",
  "summary": "Crude fell from $109.47 to $91.61 across the week on a potential Iran peace-deal framework, the sharpest weekly collapse since April 2020. A finalized deal targets the mid-$80s; risk is asymmetric to the downside pending resolution.",
  "top_ranked": null,
  "bottom_ranked": null,
  "linked_theme": "war premium unwind"
}
```

## Open items — not yet resolved

- Ticker display-name vs. yfinance-fetchable-symbol mapping (`CL1!` vs `CL=F`) —
  still no schema field for this; carried over unresolved from
  `newsletter-tracker.md`'s original brainstorm. Distinct from the new
  `underlying` field below — `underlying` solves "which ticker is this
  options structure written on," not "what's the fetchable symbol for a
  futures/forex display name."
- **Resolved 2026-07-06:** Options tab / heatmap-hook gating was designed
  around `asset_class === 'equity'` alone, which also matches multi-ticker
  equity baskets that have no single options chain. Added an `underlying`
  field (required whenever `legs` is present, null for `basket`) so gating
  can key off trade structure instead. See the design-principles bullet
  above. Still needs implementing in `watchtower.html`'s
  `setOptionsDataVisibility()`/`setTabsForAssetClass()` — this file only
  defines the corrected target shape, not the JS fix.
- Whether `reference_values` needs a stricter per-trade-type shape or stays a
  loose key-value bag — left loose for now, revisit once real parsing is
  attempted against more issues.
- `analysis_features` bucket — not yet designed. A 4th issue (2026-05-25,
  reviewed as a stress test) surfaced periodic, irregularly-published content
  (a 23-ETF sector/factor composite model, an ad-hoc "Oil: The Iran Variable"
  deep-dive explicitly described as outside the standard template) that isn't
  a trade or `market_structure` — informs decisions (e.g. trimming energy
  names) without being one. Needs its own freeform title/description/
  optional-data-table shape. Pending decision.
- Section-skeleton label drift — the same 2026-05-25 stress-test issue used
  "Tactical Summary" + "Closed/Expired this week" + "Previous Week Trade
  Review" where the June issues use "New Trade Setups" + "Open Trades" +
  "Closed Trades." The underlying content (a trade-row table, per-trade prose
  updates) is consistent even when section labels aren't. Any parser built
  against this schema should key off content shape, not fixed section names.
  Not yet resolved how to formalize that rule in this file.
- Ingestion/parsing implementation itself — this file defines the target shape
  only. No extraction prompt, paste UI, or storage code exists yet. Building
  that is the next real step, not covered by this file.
- Schema has been validated/stress-tested against 5 issues (2026-05-04,
  2026-05-25, 2026-06-09, 2026-06-22, 2026-06-29) from one newsletter. TLT and
  copper trades appearing to "silently vanish" between non-consecutive issues
  reviewed were confirmed to be sampling artifacts, not a lifecycle rule
  failure — not something to redesign around. The 2026-05-04 and 2026-05-25
  issues share one section-skeleton/format (Tactical Summary + Previous Week
  Trade Review); the 2026-06-09/22/29 issues share a different one (New Trade
  Setups + Open Trades + Closed Trades) — looks like a real format transition
  the newsletter went through, not per-issue noise. Not yet stress-tested
  against a different newsletter's format.
- `analysis_features` bucket — resolved and added above (`sector_model` and
  `deep_dive` variants), confirmed against the 2026-05-25 issue (23-ETF sector
  model, "Oil: The Iran Variable" deep-dive). Not yet exercised against a
  second real instance of either variant, so treat as provisional until a
  future issue confirms the shape holds.
- A "Performance Disclosure" legal boilerplate paragraph appears at least once
  (2026-05-04) — pure noise, not structured content; a future parser should
  recognize and skip standard legal/disclaimer text rather than attempt to
  extract anything from it.
- **Conviction score is dropped once a trade's status leaves `planned` — RESOLVED
  2026-07-08 (surfaced 2026-07-07).** Every `open`/`closed` trade in the real 06-08
  import has `conviction: {scale: null, ...}`; the worked example earlier in this
  file showing a `closed`-status trade retaining a real score was aspirational, not
  a confirmed rule. **User decision:** blank-after-planned is acceptable — no
  `EXTRACTION_SYSTEM` change to carry conviction forward. A trade may legitimately
  show no conviction dots once it goes `open`/`closed`; display handles the blank
  per newsletter-ingestion.md A.4. No further action needed here.
- **B.1/B.2/direction field additions — RESOLVED 2026-07-08, folded into the
  design-principles bullets above.** `level`/`level_high`/`note` shape, bare
  `underlying` prompt fix, and the new `direction` field (with green-Long/red-Short
  card display) are all specified above and in `.claude/rules/newsletter-ingestion.md`
  sections B.1/B.2/D. Not yet implemented in `newsletter_ingest.py`'s
  `EXTRACTION_SYSTEM` or `watchtower.html`'s card renderers — that build, plus a
  re-import of the 06-08 issue once the prompt is tightened, is the next real step.
