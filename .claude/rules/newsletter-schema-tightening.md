# Newsletter Schema — Tightening Spec (drafted 2026-07-08)

**Status (corrected 2026-07-13):** IMPLEMENTED. Built and committed same-day as this
file's own creation — commit `ef10326` (2026-07-09), "Newsletter tightening:
deterministic Python derivation + display + tooling." The line that used to be here
("DESIGN SPEC, not yet implemented... no code... has been written against this
yet") was written before that commit landed and never revised afterward — the same
stale-header pattern already found in `CONTEXT.md` and `newsletter-schema.md`. The
field decisions and derivation rules below are the settled, shipped behavior, not
a future target. `strategy_id` (§8a) and `pnl_pct` (§8c) are DECIDED and live;
`structure` is the discriminant name (§2), `linked_theme` is freeform on purpose
(§8b).

## Why this exists — the motivating failures

The 2026-07-08 effort/cost token test (8 billed runs on the 260608 issue, see
`newsletter-ingestion.md`'s Layer-0 section and the `run_archive/` snapshots)
showed the *quantitative* trade mechanics (entry/stop/targets/sizing) are rock-solid
at every effort level, but the **derived/classified fields coin-flip run-to-run** —
independent of effort. On the same defensive-breadth pairs trade, two runs diverged:

- **high** emitted `asset_class: "equity"`, `structure_label: null`.
- **low** emitted `asset_class: "pair"`, `structure_label:
  "beta_neutral_relative_value"`.

At the time neither could be called wrong, because the OLD schema was ambiguous:
`asset_class` listed `pair` as a value AND was defined as "the underlying
INSTRUMENT" (so an all-ETF basket reads equally as "equity"), and the one worked
pairs example was itself tagged `equity` — the enum and the example contradicted
each other, so the few-shot taught the divergence. That ambiguity is the real
motivator for this pass.

The tightening below resolves it by dropping `pair` as an `asset_class` and making
`basket → asset_class: equity` + `structure: pairs`. Under those resolved rules the
verdict is unambiguous: **high was correct** (equity + null label), and **low was
wrong twice** — `asset_class: "pair"` (a value that no longer exists) and a
fabricated `structure_label` (which should be `null` on a non-options trade). The
fix is not more reasoning effort; it is to define these fields as **mechanical
rules, not judgments**, fix the contradicting example, and **enforce them in
Python** (matching the existing principle that Python owns deterministic
bookkeeping — `pnl_pct`/`risk_capital` already work this way).

This is deliberately NOT a heavy ontology/type-system. It is a short set of
if-then rules + enum enforcement, validated once in Python — closer to a form
validator than a framework.

---

## 1. Asset-class model — three classes, structure only under equity

`asset_class ∈ { equity, future, forex }`. **`pair` is removed as an asset_class.**

Rationale (agreed with user 2026-07-08): only `equity` has internal structure.
Futures and forex, for this source, are atomic outright directional trades — they
do not decompose. Every pair we have is an equity basket, and futures/forex do not
combine into pairs (yet), so "pair" is not a peer asset class — it is a *structure*
under equity (a basket), signalled by the `basket` field, not by `asset_class`.

```
equity
 ├─ outright        (single ticker + direction long/short)
 ├─ pairs           (basket of tickers; priced as a ratio/spread; market-neutral)
 └─ options         (legs + structure_label)
future  → outright only   (underlying + direction)
forex   → outright only   (underlying + direction)
```

Nothing downstream breaks from dropping `pair` as an `asset_class`: the Options-tab
/ chart gating already keys off **`basket` presence vs `legs` presence**, not off
`asset_class` (per `newsletter-tracker.md`). A pair still renders as a ratio chart
with no Options tab because it has a `basket`.

### Deferred, on purpose (conscious "not yet", not holes)
- **Cross-asset pairs** (e.g. long gold future vs short an equity) do not exist
  under this model. When one appears, that is the moment futures/forex gain
  structure; revisit then.
- **Futures/forex options** do not exist under this model. Captured via the
  `OPTIONABLE_ASSET_CLASSES` set (section 4) = `{ equity }` today; add `future`
  there in one place if Schwab-style futures options ever become real.

---

## 2. Two clean axes replace the overloaded `type` enum

The current `type` enum mixes asset class and structure together
(`outright_equity`, `outright_future`, `outright_forex`, `options_spread`,
`options_condor`, `options_collar`, `single_option`, `pairs`, `seasonal_equity`).
Split into two orthogonal fields:

- **`asset_class`** ∈ `{ equity, future, forex }` — what the trade is.
- **`structure`** ∈ `{ outright, pairs, options }` — how it is expressed.
  (DECIDED 2026-07-08: name it `structure` — a NEW field, not the reused `type`
  name. A fresh name avoids the trap of a same-named field with changed meaning.)

Migration mapping from the old `type`:

| Old `type`            | `asset_class` | `structure` | notes |
|-----------------------|---------------|-------------|-------|
| outright_equity       | equity        | outright    |       |
| pairs                 | equity        | pairs       | `basket` populated |
| options_spread        | equity        | options     | `structure_label: vertical_spread` (or as named) |
| options_condor        | equity        | options     | `structure_label: iron_condor` etc. |
| options_collar        | equity        | options     | `structure_label: collar` |
| single_option         | equity        | options     | `structure_label: single` / covered_call / cash_secured_put |
| outright_future       | future        | outright    |       |
| outright_forex        | forex         | outright    |       |
| **seasonal_equity**   | equity        | outright    | **collapses to outright** — "seasonal" is a THESIS/theme property, not a structure; lives in `thesis`/`linked_theme`, not the structure field |

---

## 3. Field-coherence rules (the whole guard — enforce in Python)

Three rules. This is the entire garbage-defense; it catches both observed failures
and is validatable in one pass.

1. **`asset_class` — derived for baskets, a validated model primitive for single
   names** (CORRECTED 2026-07-09; the original "derive from the `underlying` suffix"
   was backwards — see box).
   - `basket` populated → `asset_class = equity`, `structure = pairs`. Python-derived;
     overwrites any model value.
   - options (`legs` present) → `asset_class = equity` (the only optionable class
     today, §4c). Python-derived.
   - else single underlying → `asset_class` is a **model-extracted primitive**
     (`equity`/`future`/`forex`, read from the prose — "copper future", "USDJPY";
     100% reliable across the effort test). Python **validates it against the enum**
     and flags an off-enum value; it does NOT derive it from a suffix.
   *(Kills high's equity-on-a-basket error via the basket rule.)*

   > **Why the suffix rule was backwards (2026-07-09).** The store keeps **bare**
   > tickers (`HG`, `USDJPY`, `GLD`) — the newsletter never writes `=F`/`=X`; those
   > are yfinance conventions we append only to *fetch* data. A bare ticker does not
   > encode its class, and there is no bare→class table, so a suffix rule can never
   > fire. The dependency is **inverted**: we don't read the class off the suffix, we
   > need the class to know which suffix to append. So `asset_class` is the source of
   > truth and the **fetch symbol is a pure function of it** — `equity → TICKER`,
   > `future → TICKER=F`, `forex → TICKER=X` (all `chartSymbol()` / `fetch_symbol()`
   > should be). One classification decision, one source of truth: the stored field
   > and the data pull cannot drift. **Do NOT build a bare→class lookup table.**

2. **`structure_label` is null unless `structure == options`.** For outright and
   pairs it MUST be null. *(Kills low's `beta_neutral_relative_value` fabrication —
   the bug was placement, a label on a pairs trade, not vocabulary.)*

3. **Exactly one container is populated:** `legs` (options) XOR `basket` (pairs) XOR
   bare-`underlying`-only (outright). Flag any trade violating this.

**Escape hatch:** a trade the engine genuinely cannot fit gets
`structure: "unclassified"` (or equivalent) and is surfaced for manual review,
rather than being force-fit to a wrong structure. Keeps the rules strict without
being brittle against a novel newsletter construction.

---

## 4. Options branch

### 4a. `legs` is the authoritative, fully-general representation
Any options structure — strangle, iron condor, calendar, diagonal, ratio, or one
not yet seen — is just a set of legs. This is the extensibility mechanism: new
structures need NO schema change because `legs` already expresses them.

Per-leg shape:
```
{ strike, expiry, type: "call"|"put", action: "buy"|"sell", quantity }
```
- **`quantity` is NEW (add now).** Currently every leg is implicitly 1×; ratio
  spreads (1×2), unbalanced condors, and back/ratio structures cannot be
  represented without it. Adding it now avoids a forced schema change the first
  time the newsletter prints a ratio spread.
- **Leg-expiry consistency (validation).** A *same-expiry* structure — any vertical
  (`vertical_spread`), `iron_condor`, `strangle`, `straddle`, `collar` — MUST have
  **one shared `expiry` across all legs**. A `calendar`/`diagonal` is the only
  structure whose legs legitimately differ in expiry. Enforce it, and if one leg
  carries a more precise date than another (e.g. short `2026-06-18`, long
  `2026-06`), **propagate the precise date to all legs** rather than leave them
  mismatched. *(Observed META 260608: high emitted short `2026-06-18` / long
  `2026-06` on a vertical — internally inconsistent, reads like a calendar; low
  emitted `2026-06` on both — consistent but imprecise. The rule gives BOTH:
  `2026-06-18` on both legs, beating either run.)*

### 4b. `structure_label` — OPEN vocabulary, not a closed enum
- Curated **seed** of canonical snake_case names for consistency/diffability:
  `vertical_spread`, `strangle`, `straddle`, `iron_condor`, `calendar`,
  `diagonal`, `collar`, `covered_call`, `cash_secured_put`, `single`.
- **New snake_case values are allowed** — the model may name a structure not in
  the seed list. `legs` is the ground truth, so an unfamiliar label is harmless.
- Guard is placement (rule 2), not vocabulary: label only on options, null
  otherwise. Downstream never needs to *recognize* a label (Options tab gates on
  `legs`, not on label meaning).

### 4c. `OPTIONABLE_ASSET_CLASSES = { equity }`
Options structures require an optionable underlying. Today only `equity` is
optionable; this is the single place to extend for futures/forex options later.
Validation: `structure == options` ⇒ `asset_class ∈ OPTIONABLE_ASSET_CLASSES`.

### 4d. Greek binning (vocabulary routing — NO live calculation)
Purpose: the engine must know which bucket a Greek term belongs to. This source
references these constantly. This is binning only; real-time Greek values are a
separate future tool, explicitly out of scope here.

| Term | What it is | Home |
|------|------------|------|
| delta, theta, vega, rho | option price sensitivities | the **options trade** |
| gamma | option convexity **or** dealer positioning | **context-dependent — see rule** |
| beta  | market-exposure sensitivity | equity/pairs side → `beta_neutral`; **never options** |
| alpha | excess return vs benchmark | `thesis` attribution; **structure-agnostic**, not tied to single equities |

- **Gamma disambiguation rule:** gamma tied to dealers / positioning / a flip
  level / an index level → `market_structure` (existing `gamma_flip`). Gamma tied
  to a specific trade/leg/strike → that options trade. Market-structure gamma is
  the dominant case in this source.
- **beta stays on equity/pairs** — it is the concept behind `beta_neutral`;
  routing "beta" to options would re-create the exact confusion this pass removes.
- **alpha is a return-attribution concept**, not a structure. A beta-neutral pair
  is itself an alpha vehicle (beta stripped to isolate idiosyncratic return); a
  plain index long is pure beta with no alpha. So alpha does NOT map to single
  equities — it lives in `thesis`/`indicates` free text.

### 4e. `greeks` slot on options trades (optional, records what the issue SAID)
When the newsletter states a trade-level Greek exposure (usually qualitative:
"short vega", "positive theta", "long gamma", "30-delta call"), record it — do not
compute it. Small, qualitative-friendly shape:
```
greeks: [ { greek, exposure, value?, note? } ]   // e.g. { greek:"delta", value:30 }, { greek:"vega", exposure:"short" }
```
- Records the issue's own statement → never goes stale (it is history, not a live
  value). If the real-time Greek tool is built later, it computes fresh and this
  field remains "what the newsletter claimed at the time."
- Optional / omit when no Greek is stated.

### 4f. Target representation for expires-worthless structures (validation)
A credit / defined-risk spread that profits by **expiring worthless** achieves max
profit when the spread's value goes to **zero**. Rule (REVISED 2026-07-09 — targets
are NUMERIC, never prose/label-only; user):

- Such a trade's target = `{ label: "expiration_worthless", level: 0 }` — the `level`
  is a real **0** (the spread is worth 0 at max profit), NOT null. Display renders it
  as `0`.
- Do **NOT** emit the short strike as the target. The short strike already lives in
  `legs`; repeating it as a `targets[].level` misrepresents a boundary as a price to
  hit, and **violates B.1** ("never fabricate a number when the newsletter states
  none").
- **Corollary (targets are numeric only):** a purely QUALITATIVE "target" with no
  stated number (e.g. SMH "continued outperformance after the pullback") is NOT a
  target — emit NO `targets[]` entry for it; route the guidance to a `status_history`
  note instead (it's useful context, just not a price). No prose in `targets[].note`.

*(Observed twice — FIVN and META 260608: high emitted `max_profit: 640`/`25.0` (the
short strike); low emitted `expiration_worthless: null`. Low is correct; high
fabricated the level. This is high being wrong, not a neutral representation
choice.)* Genuine directional structures that DO have a price target (a long
outright, a debit spread targeting a level) keep their numeric `targets[]` as
normal.

---

## 5. Direction, bias & entry trigger

Two DIFFERENT direction concepts; keep both.

### `direction` — mechanical execution side
- **Outright:** `direction ∈ { long, short }`. First-class.
- **Pairs:** trade-level `direction = null`; side is **per-leg** (`basket[].side`
  = long/short + weight). The ratio's direction ("long the ratio" = long numerator
  / short denominator) is fully encoded by per-leg sides — no extra field.
- **Options:** trade-level `direction = null`; side is **per-leg**
  (`legs[].action` = buy/sell, with `type` call/put).

### `bias` — directional VIEW (bullish / bearish / neutral)
Distinct from long/short. Not universally required — auto-known for two structures,
optional for one:
- **Pairs → `neutral`** by construction (market-neutral is the point). The ratio
  directionality lives in per-leg `side`; `beta_neutral: true` flags the explicit
  hedge. No bull/bear on a pair.
- **Outright → derived** from `direction` (long → bullish, short → bearish).
  Python fills it; not a model decision.
- **Options → OPTIONAL, engine-filled.** The only place `bias` is a real judgment.
  Set `bullish` / `bearish` / `neutral` when the issue states or clearly implies a
  lean (`bear_call_spread` → bearish; `strangle`/`calendar` → often neutral);
  leave **null** when there is no directional read (pure vol play, ambiguous custom
  structure). NOTE: with open-vocab `structure_label`, bias is NOT reliably
  recoverable from the label (`strangle`/`condor`/`calendar` carry no bull/bear
  prefix) — which is exactly why the explicit field earns its place.

Coverage summary:
- mechanical side → `direction` (outright) + per-leg `side`/`action` (pairs/options)
- ratio direction → per-leg `side` (pairs)
- directional view → `bias` (neutral for pairs; derived for outright; optional for options)

### `entry.trigger_type` — CLOSED enum (define + enforce; a real judgment, not derived)

Worth capturing (it's *how you get into the trade*), but today it is freeform and
values proliferate (`credit_target`, `debit_target`, `scaled`, `sell_stop`,
`dip_buy`, `ratio_level`, `held_from_prior_breakout`, `credit`, `immediate`, …).
Unlike `asset_class`/`strategy_id`, this is a genuine extraction judgment — so the
fix is a **defined closed enum + enforcement** (reject/normalize off-enum values),
not derivation. Six values, collapsed on the *action required*:

| Value | Means | Absorbs |
|-------|-------|---------|
| `market` | enter now, no condition | immediate |
| `level` | enter when price/ratio reaches `entry.level` (a limit you transact at) | dip_buy, ratio_level, pullback-to-X |
| `stop` | enter on a breakout *through* `entry.level` in the momentum direction | sell_stop, buy_stop |
| `premium_target` | options: open when the spread hits `entry.level` credit/debit | credit_target, debit_target, "credit" |
| `scaled` | multi-tranche entry; tiers live in `tranches[]` | scaled, tiered |
| `pre_existing` | position carried from before the tracking window; no entry action this issue | held_from_prior_breakout, "already established" |

- **`level` vs `stop` is a real, opposite-momentum distinction** — a limit ("buy the
  pullback to 6.15") vs a breakout stop ("sell-stop at 157.50, triggers *through*
  it"). Keep them separate.
- **`credit_target`/`debit_target` merge into `premium_target`** — credit-vs-debit
  is already derivable from the structure (sold spread = credit, bought spread =
  debit), so one value + the structure suffices. *(DECIDED 2026-07-08: merge into
  the single `premium_target`.)*
- Qualifying nuance ("do not chase below $0.60", "on a pullback") stays in
  `entry.note`, as it does today.
- `entry.level` remains a bare number or `null` per B.1 (`market`/`pre_existing`
  carry `null`).

---

## 6. Removed fields & display routing

### `role` — REMOVE from the schema (decided 2026-07-08)
`role` was documented as `{ tradeable, indicator }`, but the model emits
`tactical`/`core` (the `is_core_position` axis, off-enum), and its only real job —
flagging an observation-only indicator — is already carried by `conviction.label`.
**Remove the field.** Indicator-ness is defined solely by:

> A trade is an **indicator** iff `conviction.label ∈ { observation_only, watchlist }`;
> otherwise it is **tradeable**.

This preserves the silence-exemption rule (indicators exempt from
abandonment/staleness) with no `role` field.

### `thesis` → structured `{ rationale, positioning }`; remove `positioning_note` (decided 2026-07-08)
The current flat-string `thesis` comes out too lightweight, and `positioning_note`
duplicates positioning content the thesis already carries (confirmed USDJPY 260608:
the crowded-carry read appeared in BOTH `thesis` and `positioning_note`). Fold them:

```
thesis: {
  rationale:   "the trade's full reasoning — why it's on, what confirms/invalidates it",
  positioning: "CoT / futures-positioning context tied to THIS trade; free text,
                numbers OK; null when the issue doesn't tie positioning to the trade"
}
```
- **Naming is deliberate prompt-steering:** `rationale` (not `summary`) — a "summary"
  label nudges the model to COMPRESS the why; "rationale" nudges it to JUSTIFY, which
  is what we want since the thesis is currently too thin. The *definition* must match
  the name — describe it as full reasoning, never use "brief"/"summary" wording.
- **`positioning_note` is REMOVED** — folded into `thesis.positioning`. No
  paraphrase/number-stripping rule (raw CoT figures are fine).
- **`positioning` optional (null default)** — only USDJPY/gold/copper-type trades
  with a stated CoT angle fill it.
- **Display:** the whole `thesis` object renders in the deep-dive / narrative
  dropdown (rationale paragraph + a positioning line), **never on the card** (would
  crowd it — user, 2026-07-08). **CONFIRMED GOOD 2026-07-09:** with the tightened
  extraction live, the user reviewed the rendered detail panel and specifically liked
  how the `positioning` line displays — a settled keeper; do not strip it or fold it
  back into `rationale`.
- Scope kept minimal (`rationale` + `positioning` only); no `catalyst`/`risk` slots
  now — extend later if needed.

### Indicator display routing (display-layer decision — CHANGES current behavior)
Observation-only indicators (per the `conviction.label` test above) render ONLY in
the **weekly digest dropdown** — alongside `analysis_features` and `playbooks`, the
other non-position content — **NOT** as cards in the Newsletter Plays strip. This
matches the user's model: an indicator is a market *read*, not a takeable position,
so it doesn't belong in the plays strip.
- Gate the strip renderer to exclude `conviction.label ∈ {observation_only,
  watchlist}`; add a lightweight digest rendering (title + thesis + constituents).
- **Changes the session-10 build**, which currently shows indicators as strip cards
  with a text label.
- Data stays a full trade object (needed for lifecycle tracking + the
  constituent-ticker silence-exemption); only DISPLAY moves.
- Implementation home: `watchtower.html` renderer + a note in `newsletter-tracker.md`.

---

## 7. Extraction vs. derivation — the ownership principle

The root principle behind this whole pass. Two jobs, cleanly split:

- **Model = prose → structured primitives.** The one thing only an LLM can do: read
  varied newsletter prose and emit typed fields — `legs`, entry/stop/target levels,
  `underlying`, `sizing`, `conviction`, `status`, `campaign_title`, `key_dates`,
  `entry.trigger_type`, the `thesis` text, and (per §8d) the typed tranche records.
- **Python = primitives → everything derived/computed.** `asset_class`, `structure`,
  `strategy_id`, `structure_label`, `bias`, `pnl_pct`/`risk_capital` — derived
  deterministically and, where the model also emitted a value, **overwritten**.

**Python never parses prose.** Structured fields are the model↔Python contract. Prose
fields (`thesis`, any `note`) are DISPLAY-ONLY — Python never reads them to make a
decision. If Python ever needs a fact that only exists in a sentence, that is a
SCHEMA BUG: add a typed field the model fills. *(This is the root cause of the
`pnl_pct` flip — the credit sometimes landed in a prose `note` instead of a typed
slot, so the deterministic compute went blind.)*

### 7.1 Derivation map — which primitive feeds which derived field, per structure

| Derived field | outright | pairs | options |
|---------------|----------|-------|---------|
| `asset_class` | validated model primitive (equity/future/forex; §3 rule 1) | `equity` (basket present) | `equity` |
| `structure`   | bare `underlying` present | `basket` present | `legs` present |
| `strategy_id` | `{underlying}-{direction}` | `{long-vs-short basket}` | `{underlying}-{legs-structure}` |
| `structure_label` | — (null) | — (null) | from `legs` |
| `bias`        | from `direction` | `neutral` (constant) | from `legs` (or null) |
| `pnl_pct`     | entry/exit prices | entry/exit prices | credit/debit or exit+pnl |

- `asset_class`, `structure`, `strategy_id`, `pnl_pct`, `bias` are Python-derived
  across **all** structures — just from structure-appropriate primitives.
- `structure_label` is the only genuinely **options-exclusive** field (null
  elsewhere); where it exists it is derived from `legs`.
- The legs-based rows are simply the **options column** of a general rule, NOT a
  separate options-only mechanism.

### 7.2 Refines §4b and §5 (structure_label / bias)

For a **recognized** structure, Python DERIVES `structure_label` and options `bias`
from `legs` and overwrites the model. The model's emitted `structure_label`/`bias`
are authoritative ONLY for the **exotic residual** the legs-classifier cannot name
(the open-vocab fallback of §4b). So "model provides `structure_label` (open vocab)"
now means: the model provides it as a *fallback* for unrecognized structures;
recognized structures are Python-derived and overwritten.

### 7.3a Status determinism guard — scaled entries (added 2026-07-09)

`status` is model-owned (below) EXCEPT one deterministic override that removed a real
run-to-run flip. A `scaled` entry (`entry.trigger_type == "scaled"`) is a scale-IN
PLAN, but on the two low#2 vs low#1 runs the model coin-flipped the defensive-breadth
pair `open` vs `planned` — in the `open` run it fabricated a fill (`status:"open"` +
an issue-dated `entry_date` on the starter tranche). Fix (`enforce_scaled_planned()`,
`newsletter_ingest.py`): **a scaled entry is FORCED to `planned` — tranches normalized
to `planned`, `entry_date` nulled — until it has actually been active (a `closed`
tranche OR a realized P&L).** Keyed off the STABLE `trigger_type` primitive, not the
flaky per-tranche fill judgment. Accepts occasionally under-calling a genuinely-filled
scale-in in exchange for a deterministic status (user's explicit call: "take ambiguity
out even if the reasoning engine gets it wrong"). Leaves genuinely-held trades alone
(copper is `level` + has a closed tranche; SMH/META aren't `scaled`). Verified free by
re-deriving the low#2 extract: pair -> `planned`, §10 still 10/10.

### 7.3 What the model still genuinely OWNS (not derivable)

The primitives above, plus the real judgments: `status` (open/planned/closed — except
the scaled-entry guard §7.3a),
`thesis` text, `entry.trigger_type` (enum-enforced), `conviction`, `campaign_title`,
which trades exist and their lifecycle, and the exotic-residual
`structure_label`/`bias`. Python derives/validates everything else, enforces the
enums, and rejects/normalizes out-of-enum values — the existing `compute_risk_pnl()`
pattern, generalized to every derived field.

### 7.4 The field-taxonomy heuristic — ambiguity vs. decision-role (design rule)

The reusable generalization of this whole pass (distilled 2026-07-09). Every field
sits in ONE of four categories, and the category — not a gut feel about whether a
field "seems hard" — dictates who owns it and whether its run-to-run variance is
acceptable.

| category | example fields | owner / treatment |
|----------|----------------|-------------------|
| **unambiguous primitive** | strike, expiry, entry/exit price, a `market_structure` level NUMBER | model extracts; byte-stable across runs AND effort; decision-grade as-is |
| **reducible-but-mechanical classification** | `asset_class`, `structure`, `structure_label`, `strategy_id`, `pnl_pct`, `bias` | DERIVE in Python from primitives; deterministic; overwrite the model |
| **reducible-but-fuzzy classification** | `market_structure` level LABELS (call_wall / hedge_wall / …) | mechanize ONLY if a decision consumes it; else leave as display color |
| **irreducibly subjective** | `linked_theme`, `thesis` prose | always color; NEVER a key, grouping, or computation input |

**The governing test is not "is this field ambiguous?" — it is "does anything
downstream DECIDE based on it?"** A fuzzy field that only ever renders to a human is
free to stay fuzzy; the discipline is never letting a color field get quietly
promoted into a key or a computation input.

Two axes, orthogonal — do not conflate them (the source of most confusion here):
- **Effort** is a COST dial (a ceiling on deliberation). It buys more reasoning but
  NEVER buys convergence on a genuinely ambiguous field — `high` still coin-flipped
  `asset_class` and the copper split ~1-in-8 (the token test). You cannot spend your
  way to determinism.
- **Determinism** is a task-STRUCTURE property: an output is stable iff it is a
  mechanical function of unambiguous inputs. The reasoning engine is inherently
  stochastic, so determinism comes from minimizing its role in producing
  must-be-stable values — extract stable primitives, compute the rest in Python.
- "Sorting out" ambiguity is therefore a DESIGN act (define it away before the model
  runs), not a runtime act the model can perform at any effort.
- **A field's row can depend on its USE, not just its content.** `market_structure`
  labels are fuzzy, but because they are display-only today their variance is
  harmless (color). If a proximity-trigger ever consumes `market_structure`, note it
  would key off the level NUMBERS (primitives), not the labels — so the decision
  still rides the deterministic part. Re-file a field the moment a decision starts
  reading it. (`market_structure` is also the biggest reasoning-token consumer in
  extraction — a COST concern distinct from this determinism axis; see the
  `market-structure-token-cost` memory.)

---

## 8. Still to spec (tightening pass NOT complete)

These derived fields showed the same coin-flip in the token test and still need the
same treatment (define as a rule, fix any contradicting example, enforce).

### 8a. `strategy_id` — DERIVED from taxonomy fields (granularity DECIDED)

**Observed (trade-by-trade review, 260608 high vs low):** `strategy_id` is the
*least* stable identifier while `id` is the *most* stable — the inverse of what you
want, because `strategy_id` is the scoreboard's grouping key. The **options** slugs
flipped (`gld-callspread-425-450` vs `gld-425-450-callspread`); the outright/forex
slugs that were already strategy-level (`hg-copper-long`, `usdjpy-short`,
`smh-soxx-long`) reproduced perfectly. Strike-inclusion is BOTH the instability
source AND the roll-grouping breaker.

**Why both fields exist (keep both):** `id` = unique THIS-instance handle (per-issue
occurrence; carries the issue date). `strategy_id` = cross-time LINEAGE / grouping
key that ties re-entries/rolls of the same idea together (a copper long that closes
and re-opens = two `id`s, one `strategy_id`). The hit-rate scoreboard groups by
`strategy_id`.

**DECIDED (2026-07-08): strategy-level, strikes excluded, composed only from
taxonomy fields, and DERIVED in Python (the model's value is overwritten).**

| structure | `strategy_id` = | derived from |
|-----------|-----------------|--------------|
| outright  | `{underlying}-{direction}` | `underlying` + `direction` |
| options   | `{underlying}-{structure-from-legs}` | `underlying` + **`legs`** |
| pairs     | `{sorted-long-tickers}-vs-{sorted-short-tickers}` | `basket` |

Examples: `hg-long`, `usdjpy-short`, `smh-long`, `fivn-bear-call-spread`,
`gld-bull-call-spread`, `gld-bear-put-spread`, `xlf-xlp-xlv-vs-igv`.

- **The options structure token is derived from `legs`, NOT from `structure_label`
  or `bias`** — both of those are themselves model-authored / optional (see §7), so
  sourcing the key from them would reintroduce the non-determinism. Bull-vs-bear
  comes from which strike carries the buy vs the sell (relative strike order), which
  captures direction WITHOUT embedding the absolute strikes — so a rolled spread at
  new strikes keeps the same token and still groups. Needs a small deterministic
  legs→structure classifier (trivial for verticals) with a generic leg-signature
  fallback for structures it can't name.
- **Excludes** strikes, expiries, aliases, and descriptions: `HG` not "copper",
  `SMH` not the `SOXX` alias. Existing slugs simplify accordingly
  (`hg-copper-long → hg-long`, `smh-soxx-long → smh-long`) — fine, since Python
  overwrites.
- **Residual collision:** two *same-structure, same-ticker* trades open at once (two
  GLD bull call spreads) collapse to one key. Rare, and disambiguated by
  `campaign_title` + the per-instance `id`. Accepted rather than reintroducing
  strikes.
- **Determinism fixes reproducibility; strategy-level fixes roll-grouping.** Both the
  observed flip AND the schema's roll rule (a rolled covered call keeps the same
  `strategy_id` at new strikes) require strikes OUT of the key — two independent
  reasons pointing the same way.

### 8b. `linked_theme` — DECIDED: leave freeform (model-owned display color)

The review flagged `linked_theme` as flipping run-to-run (high bespoke phrases, low
loose buckets). **DECISION (2026-07-08): leave it alone — do NOT mechanize it.**

Unlike `strategy_id` (a grouping KEY that must match) or `pnl_pct` (a NUMBER that must
be right), `linked_theme` is **narrative color** — a freeform distillation that gives
a trade character, shown in display, never used as a key or a computation input. Its
run-to-run variation ("Gold trend reversal" vs "rates and inflation catalysts") is
therefore **harmless**: both are reasonable and nothing downstream groups or scores by
it. This is exactly the judgment the reasoning engine is FOR (§7 — genuine judgments
the model owns); forcing it into a rote category would strip the character without
buying correctness anywhere. So `linked_theme` stays freeform, model-owned,
display-only — no reference-into-`themes[]`, no canonical vocabulary, no enforcement.

**Consequence — FUTURE CONSIDERATION (not needed now):** leaving `linked_theme`
freeform means **no cross-issue theme grouping / theme scoreboard** — trades can't be
tracked by theme over time (the labels won't match across issues). This is fine for
the CURRENT scope: the user (2026-07-08) cares only about the newsletter's **overall
performance** — aggregate hit-rate / P&L — NOT how it performs broken down by theme.
If a per-theme breakdown is ever wanted, revisit this decision; a canonical
cross-issue theme vocabulary (model picks from a curated, growing set; Python
normalizes near-duplicates) is what would be needed then.

**Reclassifies the §9 synthesis:** `linked_theme`'s appearance in the
"derived/classified fields that flip" list is now understood as *acceptable* variation
(display color), not a defect to fix — distinct from the flips that corrupt the
scoreboard (`strategy_id`, `pnl_pct`).

### 8c. `pnl_pct` / `risk_capital` — value hierarchy, input plumbing, unit enum

**Confirmed mechanism (DOCU + GLD closed-trade review):** `pnl_pct`/`risk_capital`
are Python-computed (`compute_risk_pnl`, `newsletter-schema.md` C.1). The
inconsistency was NOT the model computing differently — the computation only fires
when its INPUT lands in the field the function reads, and neither run placed it
reliably:

- **DOCU (credit spread):** HIGH put the credit in `entry.level: 0.51` → computed
  (+11.4%). LOW left `entry.level: null`, credit in `reference_values` → no input →
  pnl silently absent.
- **GLD 425/450 (debit spread):** LOW carried `status_history[].exit_price: 0.95` →
  inferred debit 3.65 → computed (−74%). HIGH had NO `exit_price` → no input → pnl
  silently absent.

Each run supplied the input for ONE of the two closed trades — a field-PLACEMENT
problem, not a math problem.

**Value hierarchy (the clean model — the model provides LEVELS, Python derives the %):**
1. **`entry_price` / `exit_price`** — the raw transaction LEVELS in the instrument's
   native unit: **dollars** (options/outrights) or a **ratio** (pairs). This is the
   normal thing the model extracts and the PRIMARY input to derivation. (Levels were
   byte-identical across every run — the model nails these.)
2. **`pnl: { value, unit }`** — an OPTIONAL stated raw gain, only when the newsletter
   explicitly prints one (a $ amount, ratio points, or a %).
3. **`pnl_pct`** — ALWAYS Python-derived. An OUTPUT, never model-authored.

**Resolution order (derivation):**
- entry+exit levels present → `pnl_pct = (exit − entry)/entry` (outright & pairs; sign
  from `direction` / basket sides), or `pnl ÷ risk_capital` for defined-risk spreads.
- else a stated `pnl` in $/points + entry cost → compute (the GLD back-compute).
- else a stated `pnl` already in `%` → use it.
- else → null, and **flag** a closed trade that yields none of these — never drop it.

**Precedence — PREFER computed over stated (DECIDED 2026-07-08).** When the newsletter
states a % AND Python can compute one, use the **Python-computed** value on the
canonical basis (`pnl ÷ risk_capital` for defined-risk; price/ratio %-change for
outright/pairs). The newsletter normally prints LEVELS, not percentages, so
compute-from-levels is the *normal* path anyway; a stated % is a cross-check /
fallback, not the primary source. Keeps every `pnl_pct` in the store on one
comparable basis for the scoreboard.

**Fix the input plumbing:** `compute_risk_pnl` must source its input from every
plausible location (`entry.level`/`entry_price` credit-or-debit,
`reference_values.credit`, `status_history[].exit_price` + `.pnl`, and the typed
`tranches[]` of §8d) — OR extraction must guarantee a closed trade's cost / `exit_price`
lands in one canonical slot.

**`pnl.unit` enum — normalized; the basis is load-bearing:**
`{ pct, usd_per_share, usd_total, points }` (the observed `usd` vs `usd_per_share`
inconsistency computes to different percentages, so the basis must be explicit).
- **single-instrument** (options/outright): `usd_per_share`, `usd_total`, `points`, `pct`.
- **pairs/ratios:** `pct` (ratio %-change) — **never** the `usd_*` units (no per-share
  dollar quote on a ratio); `points` only for a raw *ratio-point* move.

### 8d. Tranched positions & the closed-slice split (tranche-as-entity)

**Observed (HG copper 260608):** a scaled position whose FIRST tranche closed
(+1.97%) while the position stayed OPEN was represented four different ways across
runs — realized P&L buried in `reference_values` (high, scoreboard-invisible), in
`tranches[0]` plus a muddled `status_history` `closed`-on-`open` pair (low), or split
into two trades (run 1). The realized gain landed somewhere different — sometimes
invisible — every run, which corrupts the scoreboard (it groups closed trades by
`strategy_id`).

**Resolution: tranche-as-ENTITY + a Python-deterministic split.**

Each tranche is ONE record holding its own entry and (optional) exit — NOT an
entry/exit event log (an event log would force Python to pair an exit back to its
entry before it can compute anything). Typed shape:
```
tranches: [
  { size?, entry_price?, entry_date?, status: "open"|"closed"|"planned",
    exit_price?, exit_date?, pnl?: { value, unit } }
]
```
- **`status: "planned"` — a scaled ADD level named but not yet triggered (added
  2026-07-09, C.3).** The original two-status model (`open`/`closed`) had no home
  for an unfilled add (copper "add at $6.15", the pair "add on ratio close >3.22"),
  so the model dropped it to `entry.note` prose — or, worse, dropped it entirely
  (copper 6.15 vanished on the tightening re-import). A `planned` tranche carries
  `entry_price` = the trigger/add level with entry_date/exit/pnl null. It is NOT a
  fill: `_history_from_tranches` skips it (no status_history event) and the split
  keeps it with the OPEN record (`open_tr` = everything not `closed`). Display shows
  it as a distinct "planned add @ level" row.
- **`entry_price` AND `exit_price` are both optional.** entry absent = the slice
  predates the tracking window (GLD → back-compute from exit+pnl) or is held-from-
  prior with no stated fill (SMH); exit absent = the slice is still open. A tranche
  may be entry-only, exit-only, both, or — if only a stated `pnl` `%` is given —
  neither price.
- **Minimum-to-form:** a `closed` slice needs enough to derive `pnl_pct` (entry+exit,
  OR exit+pnl, OR a stated `%`); if it has NONE of those, **flag it — never silently
  drop it** (that would erase a realized trade like GLD). An `open` slice may carry no
  prices at all.

**The split is Python-deterministic, driven by tranche `status` — never a model
judgment:**
- all tranches `open` → one open trade record.
- all tranches `closed` → one closed trade record.
- **mixed** (some closed, some open) → **TWO records**: a `closed` trade (the closed
  slices, carrying `pnl_pct`) + an `open` trade (the open slices), **sharing
  `strategy_id`**. This is the copper case, and the session-16 "split-into-two-trades"
  intent, now deterministic.

**A plain close is ONE record — the split is NOT "every close makes two."** A
cold-start closed position with no re-entry (DOCU, GLD call) is a single `closed`
record; we never fabricate a prior `open` record for an entry we never tracked. Two
records arise ONLY when a `closed` slice coexists with an `open` slice (a genuine
re-entry).

**Differentiation & `id`:** the two records from a split SHARE `strategy_id` (same
lineage — exactly what lets the scoreboard see two instances of one strategy) and are
differentiated by `id` + `status`. Since they share `strategy_id` AND the issue date,
the `id` template collides — so `id` gets a discriminator (append `status` or a
sequence index): e.g. `hg-long-closed-2026-06-08` vs `hg-long-2026-06-08`.

**Prerequisite:** the typed `tranches[]` above is required for the deterministic
split. If a close-event lives only in a prose `note` (as it did in some runs), Python
is blind to it (§7 — Python never parses prose).

*(This line used to read "Also open: the `structure` vs `type` field-naming decision
(section 2)." It was not open. §2 records it DECIDED on 2026-07-08 — the same day this
file was written — as `structure`, a new field rather than the reused `type` name, and it
shipped in `ef10326`. A status line outlived its own resolution by six hundred lines in
the same document. Corrected 2026-08-14; nothing else in §8d changes.)*

## 9. Cross-trade synthesis (all 9 trades reviewed — 260608 high vs low)

Character-exact field comparison of every 260608 trade across the high and low
`run_archive/` snapshots. Per-trade tables live in the session transcript; this is
the zoom-out — the patterns that held across the whole batch.

### 9.1 What's rock-stable (leave it alone)
- **Trade mechanics** — `legs`, entry/stop/target *levels*, `sizing`, `conviction`,
  `direction`, `status` — identical or numerically identical high-vs-low on nearly
  every trade. Only exception: META leg-expiry precision.
- **Outright/forex identifiers + simple `strategy_id` slugs** (`hg-copper-long`,
  `usdjpy-short`, `smh-soxx-long`) reproduced perfectly.
- **Non-closed lifecycle fields** (`stale_flag`, `weeks_unmentioned`,
  `status_history` for open/planned) were clean.
- `asset_class` for equity/future/forex was never wrong; the only asset_class
  divergence was the pair/basket ambiguity (defensive breadth), now resolved (§1/§3).

### 9.2 Where high and low each systematically err (symmetric, not directional)
- **HIGH over-includes** — sometimes genuine richness (`reference_values`,
  `key_dates`, thesis detail), sometimes a RULE VIOLATION:
  - fabricated credit-spread target `max_profit=short_strike` (FIVN, META) → §4f
  - inconsistent per-leg expiry on a vertical (META) → §4a
  - raw CoT numbers in positioning (USDJPY) → moot (§6 drops the strip rule)
- **LOW drops / misplaces** —
  - flattened leg expiry to month-only (META) → §4a
  - dropped the CPI catalyst entirely (`key_dates: []`, GLD put)
  - fabricated `structure_label: beta_neutral_relative_value` (defensive breadth) → §3
  - embellished `campaign_title` with invented text (FIVN, GLD)
  - misfiled the pnl input into `reference_values` instead of `entry.level` (DOCU) → §8c

Neither is "better." High errs by over-reach, low errs by omission — different
trades, different fields.

### 9.3 It's a field-CLASS story, not an effort story
Every divergence sits in the **derived/classified** fields — `strategy_id`,
`linked_theme`, `pnl_pct`, `structure_label`, `reference_values`, `targets`
representation, `campaign_title`. These flip at BOTH effort levels; the quantitative
core never flips. Confirms the token-test headline trade-by-trade: **effort does not
buy correctness on these fields** — deterministic Python + enum enforcement does.

### 9.4 The scoreboard-risk inversion (headline finding)
The two fields MOST critical to the hit-rate scoreboard are the LEAST stable:
- **`pnl_pct`** (realized P&L) — each run computed one of the two closed trades and
  missed the other (field-placement bug, §8c).
- **`strategy_id`** (the grouping key) — flips on strike-specific option slugs (§8a).

What you most need stable is what's least stable. Strongest argument for the whole
tightening pass, and unfixable by effort.

### 9.5 Divergence scales with lifecycle: closed > open > planned
- **Closed** (DOCU, GLD call) diverged MOST — they activate the
  pnl/risk_capital/status_history layer, the flakiest.
- **Open** (META, SMH, copper) — stable except copper's tranche representation (§8d).
- **Planned** (FIVN, defensive-breadth, GLD put, USDJPY) — stable core, divergence
  only in soft fields.

### 9.6 Rule-generation map (what the review produced)
| Observation | Spec rule |
|---|---|
| pair/basket asset_class (defensive breadth) | §1, §3 — basket → equity + pairs |
| fabricated structure_label (defensive breadth) | §3 — null unless options |
| credit-spread target = short strike (FIVN, META) | §4f — expiration_worthless/null |
| inconsistent vertical leg expiry (META) | §4a — one shared expiry |
| entry trigger values (all trades) | §5 — closed enum (level/stop confirmed live) |
| strategy_id slug flip (options) vs stable (outright) | §8a — derive + granularity |
| pnl input misfiled (DOCU, GLD) | §8c — source input from all fields |
| positioning duplicated in thesis + note (USDJPY) | §6 — thesis.{rationale,positioning} |
| role = tactical/core off-enum (SMH) | §6 — remove role |
| copper tranche partial-close (copper) | §8d — canonical tranche-P&L rep |

**Bottom line:** the extraction is TRUSTWORTHY for trade mechanics at any effort
level, and UNRELIABLE for derived/bookkeeping fields at any effort level. The fix is
structural (this spec), not a tuning knob.

---

## 10. Acceptance criterion — the 260608 regression fixture

The build (prompt tightening + Tier-1 validator) is validated by **re-extracting the
260608 PDF through the NEW engine** and asserting against the answer key below — NOT
by diffing the old-schema `_store.json` (that data is the unreliable output this whole
pass exists to fix; validating against it would be untethered). Ground truth is the
PDF plus the answer key.

### Pass/fail
1. **Exactly 10 trades** — 7 live/planned + 3 closed. The old engine produced 9 or 10
   depending on the run; 9 is WRONG (it folded the copper tranche). 10 is correct
   (copper split: closed first tranche + open re-entry).
2. **Copper is split** into two records sharing `strategy_id: hg-long`, differentiated
   by `status` + `id` (§8d).
3. **All three closed trades carry `pnl_pct`** — the old engine never got all three in
   one run (§8c). DOCU +11.4, GLD −74, copper tranche +1.96 (computed).
4. **Canonical, stable `strategy_id`s** (§8a) — see table.
5. **DETERMINISTIC across repeats** — run the extraction 3–5× and assert the SAME 10
   trades, ids, statuses, and pnls every time. This determinism IS the proof the
   tightening worked; a single 10-trade run is necessary but not sufficient.
6. **Effort-independent** — should hold at `low` effort too (primitives are stable at
   any effort; Python owns the derived fields). If it passes at `low`, imports run at
   `low` for the ~50% cost saving the token test found.

### Answer key — correct 260608 extraction (10 trades)

| # | trade | `strategy_id` | `structure` | `status` | `pnl_pct` |
|---|-------|---------------|-------------|----------|-----------|
| 1 | FIVN 25/30 bear call spread | `fivn-bear-call-spread` | options | planned | — |
| 2 | Defensive breadth: long XLV/XLP/XLF vs short IGV | `xlf-xlp-xlv-vs-igv` | pairs | planned | — |
| 3 | GLD 395/372 bear put spread | `gld-bear-put-spread` | options | planned | — |
| 4 | META 640/670 bear call spread | `meta-bear-call-spread` | options | open | — |
| 5 | SMH/SOXX long | `smh-long` | outright | open | — |
| 6 | Copper long — open re-entry (6.37) | `hg-long` | outright | open | — |
| 7 | USDJPY conditional short | `usdjpy-short` | outright | planned | — |
| 8 | GLD 425/450 bull call spread | `gld-bull-call-spread` | options | closed | **−74.0** |
| 9 | DOCU 65/70 bear call spread | `docu-bear-call-spread` | options | closed | **+11.4** |
| 10 | Copper long — closed first tranche (6.375→6.50) | `hg-long` | outright | closed | **+1.96** |

Notes: `asset_class` = equity for 1–4, 8, 9; equity for 2 (pairs is a structure, not an
asset_class); future for 6, 10; forex for 7; equity for 5. Copper's two records (6, 10)
share `hg-long` and are told apart by `status` + an `id` discriminator. The two GLD
trades (3, 8) get distinct keys via structure (put spread vs call spread). GLD −74 is
back-computed from `exit_price 0.95` + `pnl −2.70` → debit 3.65 (§8c). Copper +1.96 is
computed from 6.375→6.50 (newsletter stated +1.97%; prefer-computed per §8c).

### Pointer to the source material (the answer key's provenance)
All artifacts live under `NEWSLETTER_EXTRACTED_DIR` = `C:\Users\pguth\Documents\Macro Newsletters\extracted\`.
- **`run_archive/260608__effort-default(high)__20260708-213926__store.json`** and
  **`...__effort-low__20260708-214122__store.json`** — the two preserved snapshots.
  They hold the trade PRIMITIVES (legs, entry/stop/target levels — byte-identical and
  reliable) but are the **9-trade** versions (copper NOT split), so they are the
  primitive source, not the answer.
- **`thinking_logs/260608 ..._effort-default(high)__20260708-211027.txt`** — run 1's
  reasoning trace, which narrates the copper split into a closed tranche (+1.97%) and
  an open re-entry. This is the evidence for the 10-trade result.
- The **character-by-character per-trade review** (session 2026-07-08) is what verified
  every field; this table is its durable distillation.
- **The correct 10-trade store was never persisted** — run 1's `_store.json` was
  overwritten by later cold runs before the `run_archive/` auto-save existed. That is
  exactly why this written answer key exists rather than a pointer to a stored file.
