# AI BUBBLE STOPLIGHT — Compact View Design Spec
**Locked 2026-07-18.** Visual source of truth: `stoplight_mockup.html` (this folder) — open it
in a browser to see the exact pixels. This doc captures the DECISIONS the HTML can't self-document.

## WHERE IT LIVES
Left sidebar of watchtower.html, as one of three collapsible `<details>` sections:
Macro Regime · AI Bubble · Watchlists. All three use the same collapse grammar (the sidebar
watchlist groups already use `<details>`/`<summary>` — reuse that CSS).

## THE COMPACT VIEW (AI bubble expanded)
16 factors in a single CONVICTION rank (NOT the Macro/Credit/Capex section bins — those move to
the future detail view). One row each: `[rank] [glyph] [dot] [name] [metric]`.
- Rank number in a left gutter (small, #64748b). Optional — position implies rank — but useful.
- GLYPH sits to the LEFT of the dot (↓ / + / −), right-aligned in a 12px column, bold #cbd5e1.
  Empty for unmodified rows. Creates a left "gutter" you can scan for which factors carry a
  directional/corroborator signal. Arrow ↑/↓ = physical-stoplight position (↓ = toward burst).
  ± = corroborator agrees(+)/contradicts(−). Glyph rides WITH the light, not the name.
- DOT = the stoplight (green #4ade80 / yellow #facc15 / red #f87171). 9px.
- NAME fixed 118px column (sized to longest label "Earnings durability"); truncate+title if longer.
- METRIC on a fixed 72px rail, mono #94a3b8. Includes a STATE LABEL where the number alone is
  ambiguous (Rate path: "+0.56 tght"). Abbreviate to stay single-line (tght/quiet/invt).
- NEXT-UPDATE RAIL (added 2026-07-20): a fixed 38px right-aligned mono #64748b column after the
  metric. Shows `D` for a genuine daily/hourly poller (refreshes every day), else the soonest
  dated catalyst feeding the factor as `M/D` (e.g. `7/22`); a weekly poller with no discrete
  catalyst shows its next release day. Server-computed in `events.factor_markers()` and delivered
  as `row.cat`; "truly daily" comes from the seed's `_pollers` block, NOT registry cadence
  (regulatory reads cadence=daily but is a weekly sweep → shows its sweep date, not `D`). Daily
  precedence is deliberate: memory_canary/heavy_haul/copper are `D` even though they also carry a
  catalyst, since they move every day regardless.
- The whole block is `width:fit-content; margin:0 auto` → CENTERED, margins balanced. Metrics
  form a clean vertical rail immediately after names (compact), NOT justified to the panel edge.
- Small 5px gaps originally separated bins; in the ranked view they're optional visual breathers.

## CORE PRINCIPLE (applies everywhere)
COMPACTNESS over filling margins. Maximum meaning per pixel. Center content; never stretch a row
to the panel width just to fill it. This is a standing preference for the whole dashboard.

## COLLAPSED STATE (morning glance)
- Macro collapsed: its HEADLINE text survives in the header row.
- AI bubble collapsed: header shows the FRESHEST print — the fresh factor's OWN light (dot) +
  name + metric + state label, plus a "when" tag (Thu/today). NO separate cyan section-identity
  dot; the content dot does the talking. Answers "has anything changed since I looked?"

## SILICON E (the earnings module — NOT a 17th light)
Sits BELOW the ranked 16, past a divider, set apart. Centered white-drum ODOMETER gauge:
white face + black numeral + inset shadow (curved-drum illusion), `$`___`B` framing.
Nameplate "SILICON E" centered UNDER THE DRUMS (offset for the corner %), lime backlight
(#bef264 text + text-shadow rgba(132,204,22,.9)/.5 two-layer glow). `+22%` pinned to the top-right
corner (absolute), quiet reference, NOT beside the drums. Green ↑ implied by the %; flips red if
the composite turns down. On live build: digits ROLL vertically (~300ms) on recompute.
Basket NVDA/AVGO/MU/AMD/MRVL, fwd net income, recomputes daily off a quarterly base.

## HIGHLIGHT / FRESHNESS MECHANICS (two independent triggers)
1. NEW-DATA tag (green "new", see .badge-new + .row-new box): fires ONLY for factors updating
   LESS often than daily. A fresh value after its gap. NEVER for daily/continuous factors.
   Shows the delta (e.g. "3.28→3.41×") not just the level. Header-pins per the rule below.
2. STATE-CHANGE highlight: fires for ANY factor whose light flips color, cadence-independent.
   This is what gives continuous factors (copper) their moment at a threshold cross.
Both can co-fire (data lands AND flips a light) — treatments must visually coexist.

HEADER-PIN RULE: freshest update holds the collapsed header slot until displaced; a
monthly-or-longer arrival PINS for the trading day (daily noise can't evict it); two long-cadence
prints same day → longer cadence wins.

STALE COUNTER (.badge-stale, amber "41d"): renders once a factor passes its expected cadence
(from stoplight_events.json). Inverse cue to "new data" — flags a rotting input.

CONTINUOUS vs EVENT (drives which triggers apply):
- CONTINUOUS (daily/finer): yield curve, concentration, market credit, memory canary, heavy haul,
  copper. → state-change highlight only, never "new" tag.
- EVENT (monthly/slower): rate path (weekly), leverage, inflation, net liquidity, silicon payback +
  the quarterlies. → earn "new" tag on arrival.

## DETAIL VIEW (v1 BUILT 2026-07-20 — shared deep-dive panel)
Rides the **SAME shared deep-dive panel** as the ticker (`populated-state`) and newsletter
(`newsletter-dive`) dives — a fourth toggled sibling `#ai-bubble-dive` inside `#deep-dive-panel`,
NOT a modal. (The doc originally leaned modal for "doesn't evict a selected ticker", but the user
chose 2026-07-20 to reuse the same area — selecting a ticker/thesis replaces it, and vice-versa; it
has no close button, matching dd/nd.) `openBubbleDetail(factorId)` (stoplight.js) hides the empty/
ticker/newsletter siblings and shows `#ai-bubble-dive`; the two other entry points (`updateContext`
in charts.js, `showNewsletterDive` in newsletter-dive.js) hide it in turn. Opened by a small
**"detail" button** in the AI Bubble section header; `factorId` is stored in `_abFactor` so a FUTURE
factor-row click deep-links into the same panel — v1 always shows Overview. Tabs mirror the deep-dive
pattern (view id `ab`, reuses `.view-tabs`/`.view-tab`): **Overview** (built) + two **TBD** placeholders.
Overview layout is COMPACT (user, 2026-07-20): a headline tally line, then TWO width-constrained
columns (`.ab-cols`) — thesis prose + earnings durability ~half-width left (`.ab-col-prose`), calendar
~third-width right (`.ab-col-cal`); never full-bleed. Calendar rows are packed left (date · label ·
ONE-WORD factor · countdown all adjacent) so the countdown stays near the eye — the factor ref is the
feed id's first token, de-duped (`capex_pressure`+`capex_spigot` → `capex`).
Overview = headline tally (live lights) + thesis-in-brief (static `AB_THESIS_HTML`) + earnings
durability (Silicon E module) + the **Calendar** (`/get_stoplight` now returns `catalysts` =
`events.upcoming(90)`). Renders from the cached `_slBoard`; a poll while open re-renders it.
- FUTURE (the dense per-factor view): per-factor reading + threshold ladder + chart + caveats +
  catalysts (sessions 28-30 produced ~12 charts feeding it) — lands on the TBD tabs / factor-click.
- Collapse-state persistence (localStorage) vs reset-to-default — undecided.
- Whether the rank-number gutter stays or goes.

## BUILD-PHASE NOTE
Integration into watchtower.html (endpoint + render fn + <details> wiring + odometer roll) is
multi-file, live-in-browser work — flagged for Claude Code, not chat.
