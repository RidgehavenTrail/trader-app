# Factor evidence views — Ledger / Two lenses

**For Argus, from Euphemus (2026-08-21).** The prototype these come from is published at
**https://claude.ai/code/artifact/0d4c13d9-266e-4953-adcc-7b7fc49b5d7c** — open it before
building; both views are live there on ten days of real data and it is faster to look than
to read this.

---

## READ THIS FIRST — the work is PART-DONE and UNCOMMITTED

At the time of writing, `git status` shows **five modified files that are not committed and
are not mine**:

```
M static/js/stoplight.js      M stoplight/__init__.py
M stoplight/factors/premium_share.py   M stoplight/store.py   M watchtower.html
```

A concurrent session built the **backend and the switcher scaffolding**. `HEAD` contains
none of it (`git show HEAD:stoplight/__init__.py | grep -c get_factor_ledger` → 0). So:

- **Do not rebuild any of it.** Read the working tree first, not `HEAD`.
- **Do not commit it as your own** without checking with the user whose it is.
- If it has vanished when you arrive, it was never committed — this doc plus the artifact
  are then the only record of the design, which is exactly why this file exists.

**What already exists in the tree:**

| piece | where | state |
|---|---|---|
| `ledger(days=10, top=10)` | `stoplight/factors/premium_share.py` | built — returns the exact shape below |
| `GET /get_factor_ledger?factor=&days=` | `stoplight/__init__.py` | built — day-cached, locked, `has_ledger` capability flag, never 500s on a dead source |
| capability discovery `_ledger_fn()` | `stoplight/__init__.py` | built — a factor "has a ledger" iff its module exports `ledger()`; no list to maintain |
| evidence block + view switcher (`.ab-vbtn`, `aria-pressed`) | `static/js/stoplight.js` | scaffolding built; renders only when a factor has >1 view |
| a GENERIC stand-in view | `static/js/stoplight.js` | built — what a factor with no ledger shows |

**The gap is the two real views themselves**, plus declaring them for `premium_share` so the
switcher has something to switch between. A comment in the in-flight JS says the ledger "does
not exist yet" — that comment is now stale; `ledger()` landed after it was written. Verify
before trusting it.

---

## The payload you are rendering

`GET /get_factor_ledger?factor=premium_share&days=10` →

```jsonc
{ "factor": "premium_share", "has_ledger": true, "days": [ /* NEWEST FIRST */
  { "date": "2026-08-20", "share": 43.2, "light": "yellow",
    "floor": 0.165, "line": 8.26, "comm_tok": 94.6,
    "total_rev": 7820000, "n_models": 51, "overlap": 1,
    "by_rev": [ { "r": 1, "slug": "moonshotai/kimi-k3-20260715", "name": "MoonshotAI: Kimi K3",
                  "rev": 1134680, "revs": 14.5, "ts": 1.73, "out": 15.0, "prem": true }, ... ],
    "by_tok": [ ... same shape, ranked by tokens ... ] } ] }
```

`revs` = share of the day's dollars, `ts` = share of the day's tokens — **both in %, on purpose,
so the two lenses are read on one scale.** `prem` is the premium/commodity side of the 50×-floor
line. `days` is newest-first (matching `store.history()`); a sparkline wants the other order and
must reverse it itself.

---

## Where it goes

**The evidence block is CONTENT, so it belongs in the SCROLLING PANE** — not the sub-header
band. That band is chrome (About box + light-scale legend): it stays put, survives a tab
switch, and is deliberately outside `overflow-y:auto`. Evidence scrolls. Keep that line; it is
what four failed placements bought (see the comment above `renderBubbleSubhead`).

---

## View A — "Ledger"

One table, **ranked by revenue**, because revenue is what the light measures. Ten rows.

| col | source | notes |
|---|---|---|
| rank | `r` | |
| model | `name` over `slug` | name in Inter, slug beneath in mono at ~9.5px, both ellipsised |
| out $/M | `out` | `$15.00`; `—` when 0 |
| est. revenue / day | `revs` + a bar + `rev` | bar width = `rev / max(rev)`, tinted by `prem` |
| tokens | `ts` | `1.73%` — 2 dp, this is the column that disagrees with the money |
| tier | `prem` | chip: gold `premium` / steel `commodity` |

Densest read of a single day. This is the **reference** view.

## View B — "Two lenses"

Money ranking beside volume ranking, `by_rev` left and `by_tok` right. Mark models appearing in
**both** lists (compute the intersection client-side from the two `slug` sets, or trust
`overlap` for the count). Footer line: *"N of 10 models appear in both lists — the rest earn
without volume, or serve volume without earning."*

This is the **instrument** view, and it exists for one reason: **the factor's whole ± glyph is
whether money and volume agree, and this is that question made visible.** On 2026-08-20 the two
top-tens overlapped by **1**; ten days earlier it was 4. The money is Kimi/Opus/Fable at 1–2%
token share; the volume is DeepSeek/Tencent/Xiaomi earning almost nothing.

**Keep both.** The user was explicit: A is the better reference, B is the better instrument.
Do not collapse them into one.

---

## The switcher

Match the in-flight pattern already in `stoplight.js` — `.ab-vbtn` + `aria-pressed`, the same
grammar as `.vbtn` in the prototype and `view-tab` elsewhere in the dashboard. Rules:

- **Render it only when a factor declares >1 view.** That guard is already written; honour it.
  An always-visible switcher over a single view is a control that does nothing.
- Views are declared per factor, so a future factor with three views needs no layout work.
- **Selected view is per-panel state, not global** — it must not leak between factors.
- Switching must not refetch. One `/get_factor_ledger` call feeds both views; the day rail
  selects the day, the switcher selects the lens.

## The day rail

Left rail, ~112px, newest at top, one row per day: light dot · `MM-DD` + weekday · the day's
`share`. Clicking sets the day for whichever view is showing.

**Generalise it as "history at this factor's cadence"** — daily factors get days, quarterly ones
(`capex_spigot`, `infra_backlog`) get reported periods, event factors get events. Same rail,
same interaction, different granularity. Do not hard-code "10 days" into the renderer.

---

## Traps — every one of these cost me time or would have

1. **Rank by revenue, not tokens.** The light measures dollars. Ranking by tokens produces a
   completely different, wrong-looking table.
2. **Revenue is ESTIMATED**, not reported: tokens × the 80/20 in/out blend of listed prices.
   Label it "est." wherever it appears. Do not let it read as a measured figure.
3. **The light flips RED on weekends.** Aug 15–16 read 56.2 / 60.5 against 42–49 on weekdays,
   because commodity coding traffic drops and premium's revenue share rises mechanically. This
   factor's highlight is `state-change`, so a weekend flip is a calendar artifact, not a signal.
   Click 08-16 in the rail to see it. Worth a note in the UI eventually.
4. **The overlap number is the story, not a stat.** If you cut one thing from view B, do not cut
   the footer count.
5. **`days` is newest-first.** A sparkline drawn straight from it runs backwards.
6. **It is free.** `rankings_daily()` returns ~30 days × 51 rows on every call and `compute()`
   keeps only the latest. 10 or 30 days costs the same nothing. The route caches per ET day.
7. **A factor with no ledger is not an error.** `has_ledger: false` → render the generic view.
   The route deliberately returns 200, not 404.

## Measurements from the prototype (a starting point, not gospel)

Panel ~1288px wide: rail 112 · table min-width ~610 · lens columns 1fr/1fr, stacking below
780px. Row padding 6–7px, data in `ui-monospace` at 12px with `tabular-nums`, model names in
Inter at 12px. Premium gold `#e0b155`, commodity steel `#5b7089` — semantic, and deliberately
distinct from the red/yellow/green light scale so a tier chip is never mistaken for a light.
