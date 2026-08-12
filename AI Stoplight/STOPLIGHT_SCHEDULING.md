# STOPLIGHT — Scheduling & Event Model (source-oriented design)

**Drafted 2026-07-19 (session 31).** Captures the scheduling/cadence architecture
worked out after the silicon_payback extraction exploration. Companion to
`SESSION_DELTA_2026-07-18.md` (factor specs) and `STOPLIGHT_SOURCES.md` (per-factor
URLs + the cadence/catalyst/highlight taxonomy). Status: DESIGN — not yet built.

---

## 0. Why this exists

The first build treated each factor as ONE pull on ONE cadence. Two findings broke
that:

1. **Dilution** (proven, silicon_payback): one web search covering 5 companies
   returns the top-N by relevance to the *blended* query, so a recency-sensitive
   leg (NVIDIA's latest quarter) got a stale doc. A focused per-company search fixed
   it. → **one search per SOURCE, never multiplex.**
2. **Heterogeneous cadence**: a single factor's inputs update on *different*
   schedules — NVIDIA on its earnings date, OpenAI/Anthropic on rolling journalism,
   Copilot/Gemini on MSFT/GOOGL earnings. A single factor `asof` is a lie.

Both point to the same model: a factor is an assembly of **sources**, each with its
own search, trigger, and freshness.

---

## 1. The source-oriented data model

A factor decomposes into one or more **sources**. Each source carries:

| field | meaning |
|-------|---------|
| `value` | the extracted/pulled number |
| `asof` | when THIS source's value was last refreshed (its own, not the factor's) |
| `source` | provenance (URL / publication / "seed") |
| `trigger` | what schedules this source's refresh (see §2) |
| `search` | the focused, single-source query (billed sources only) |

The factor's light is DERIVED from the assembly of its sources' latest values
(unchanged §7 doctrine: Python derives, model/pull only supplies primitives). A
source refreshing does NOT mark the whole factor fresh — each source ages
independently; the factor's displayed `asof` is the OLDEST load-bearing source
(so staleness surfaces honestly).

### Worked example — silicon_payback (6 sources, 3 trigger types)

```
silicon_payback:
  openai_rev_b:     {value: 25,   asof, source: Reuters/Information, trigger: weekly-sweep}
  anthropic_rev_b:  {value: 47,   asof, source: CNBC,                trigger: weekly-sweep}
  copilot_rev_b:    {value: 9,    asof, source: MSFT call,           trigger: earnings:MSFT}
  gemini_rev_b:     {value: 5,    asof, source: GOOGL earnings,      trigger: earnings:GOOGL}
  nvda_dc_qtr_b:    {value: 75.2, asof, source: NVDA Q1 FY27,        trigger: earnings:NVDA}
  nvda_accel_share: {value: 0.72, asof, source: Mercury/JPR est,     trigger: earnings:NVDA}
```

Single-source factors (copper, leverage, rate_path, …) are the degenerate case:
one source == the whole factor.

---

## 2. Trigger types

| trigger | fires when | used by |
|---------|-----------|---------|
| `poll:<cadence>` | every interval (hourly…daily), silently | all FREE factors (FRED, yfinance) |
| `earnings:<TICKER>` | on/just-after that ticker's next earnings date | silicon (Copilot/Gemini/NVDA), infra_backlog (VRT/GEV), capex×2 (5 hyperscalers), memory (MU/SK Hynix) |
| `weekly-sweep` | every 7 days, web search | silicon OpenAI/Anthropic legs; regulatory sweep |
| `self-gate:<date>` | a computed one-off date | copper (~Sep 1), heavy_haul (~Sep 10) |
| `data-release:<sched>` | a published release date | inflation (PCE/CPI), rate_path (FOMC context) |

**"On or slightly after":** event triggers fire on the FIRST scheduler check AFTER
the event date, and only if the source hasn't already refreshed since that event. A
billed source is NEVER polled — it waits for its event.

**Report-session guard (added 2026-07-20, user):** the fire date is NOT always the
event date — a pull must never run *before* the report actually lands. Each earnings
event carries a `session` (bmo/amc/unknown) that `refresh_calendar()` reads from the
yfinance report time (~08:00 ET = before open, 16:00 ET = after close), and a computed
`pull_date`:
- **BMO** (morning) → `pull_date = event date` — the print is out before a same-day
  afternoon pull, so no need to wait.
- **AMC / unknown** (evening/ambiguous) → `pull_date = event date + 1` — otherwise an
  afternoon poll would scrape *pre-earnings* data and mislabel it as the update.
- **FOMC** is a 2pm announcement → also +1 (same "let the noise settle" rationale).

The compact-view marker always shows the EVENT date; `pull_date` is only the fire time.
The event-driven billed scheduler (step 4 below) reads `pull_date`, not `next_date`.

---

## 3. Billed vs free — the cost-control principle

- **FREE sources** (FRED, yfinance, SSGA, FINRA) → `poll`. Polling costs nothing, so
  precise timing is a bonus, not a requirement. They stay on the current interval
  scheduler.
- **BILLED sources** (the OpenRouter extractors) → EVENT-triggered ONLY. Never poll a
  paid call. A quarterly earnings leg fires once, ~1 day after the report; a
  weekly-sweep leg fires once every 7 days. This is the whole reason the event
  calendar exists on the scheduler side.

The $5.37 overrun (2026-07-19) is the standing reminder: billed pulls must be timed,
bounded, and per-source.

---

## 4. The event calendar (two consumers, one dataset)

A single calendar of dated events feeds BOTH the scheduler (timing) and the sidebar
(awareness). An event = `{date, label, factors[], kind}`.

### 4a. Sourcing — self-maintaining where possible
| event kind | source | rot |
|-----------|--------|-----|
| earnings dates | **yfinance `get_earnings_dates()`** for NVDA/VRT/GEV/MSFT/GOOGL/AMZN/META/ORCL (+ SK Hynix/MU) — verified live 2026-07-19 | none (auto) |
| PCE / CPI releases | **FRED release calendar** (release dates per series) | none (auto) |
| copper / heavy_haul self-gates | **computed** from factor data (63-bar off the June highs) | none (computed) |
| FOMC meetings | maintained list, 8/yr | low (annual) |

### 4b. Display filter — cadence vs catalyst
The calendar DISPLAYS discrete, anticipate-worthy catalysts; it does NOT list
high-frequency clockwork.

- **Listed** (monthly-or-rarer / one-off): FOMC, PCE, CPI, earnings, self-gates.
- **NOT listed** (weekly-or-finer, silent poll): **H.4.1** (net_liquidity's weekly
  Thursday release — regular enough that you never "wait" for it), daily FRED pulls.

Rule of thumb: *if it happens weekly or more often, it's cadence (poll silently);
if monthly or rarer, or a one-off, it's a catalyst (list it).* This is the board's
existing three-axis taxonomy — the calendar is the `catalyst` axis minus the
high-frequency members.

### 4c. Display — the "Catalysts" sidebar section
Upcoming events, soonest first, each tagged with the factor(s) it moves and a
countdown: `GEV — infra backlog — 3d`. Same collapse grammar as the other sidebar
sections. Makes a quiet factor legible ("next catalyst: Aug 26") and replaces the
canonical doc's static hand-typed DATED CATALYSTS line with a live one.

---

## 5. The per-source search principle (the dilution fix)

For any billed source: **one focused search, one source.** Never multiplex multiple
companies/topics into a single web search — Exa ranks the top-N by relevance to the
blended query, so a recency-sensitive leg loses its slot to a topically-strong stale
doc (the NVDA Q4-FY2026-vs-Q1-FY2027 failure). A focused single-source query
re-ranks all results around that one source. Proven twice on the isolated NVDA probe
(75.2, correct) vs the diluted run (62.3, stale).

Corollary: once split per source, each extraction is a trivial single-number pull —
a fair task for a CHEAP model, so per-source search may be both more stable AND
cheaper than one Sonnet call on a diluted query. The stage-2 model stays on the
config knob so this is testable.

---

## 6. Build order (when we build this)

1. **Source data model** — migrate `extracted_inputs` from flat records to
   per-source `{value, asof, source, trigger}`. The derivers read the assembly.
2. **Event calendar module** (`events.py`) — yfinance earnings auto-pull + FRED
   release dates + computed self-gates + the FOMC list; the display filter.
3. **Per-source extractors** — split silicon (6 sources) and capex spigot (5) into
   focused per-source searches. Reuse one "focused search+extract" helper.
4. **Event-driven scheduler** — billed sources fire on their calendar event
   (+1 day), free sources keep polling. **BUILT 2026-07-20** (`events.due_billed_pulls`
   + `scheduler._maybe_fire_billed`): each of the 4 billed extractors fires on the
   fire_date of its feeding events (`pull_date` = earnings report-session guarded),
   with coalescing (quarterly factors WAIT for the whole earnings cluster via
   `settle_days`; weekly-sweep factors fire on the sweep with a `min_interval_days`
   floor). **SAFETY GATE:** actual firing is behind `STOPLIGHT_BILLED_AUTOFIRE=1`,
   DEFAULT OFF — disarmed = detect + log + record `state['pending_billed']`, never
   spends (per prompt-before-billed-runs); arming is standing approval for recurring
   autonomous billed calls. `asof` on the stored inputs is the due-baseline, so a
   manual CLI run clears the due flag too.
5. **Catalysts sidebar section** — render the upcoming calendar. (still open — the
   only unbuilt display piece; `pending_billed` could surface here too.)

## 7. Open / to confirm
- FINRA margin (monthly, leverage) — borderline: monthly so listable, but semi-
  routine. Lean list-it (it IS the leverage catalyst). Confirm.
- Weekly-sweep sources with no calendar date (OpenAI/Anthropic) — surface in the
  calendar as "next sweep: <date>", or omit (they're not discrete events)? Lean omit
  from DISPLAY (not anticipate-worthy), keep as a scheduler trigger only.
- Per-source `asof` → factor `asof` = oldest load-bearing source. Confirm that's the
  staleness rule wanted.
