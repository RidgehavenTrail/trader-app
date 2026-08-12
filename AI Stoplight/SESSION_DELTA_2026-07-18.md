# STOPLIGHT — Session Delta (2026-07-18, "watchtower integration" session)

Working checkpoint. Records decisions locked THIS session for merge into
`AI_BUBBLE_STOPLIGHT_BOARD.md` (canonical) and `stoplight_events.json` (registry).
Companion builder written this session: `rate_path.py` (validated, live).

Scope this session: designed the compact sidebar view (ranked board + Silicon E gauge),
defined update mechanics, and completed the per-factor SOURCE + CADENCE scrub.
STATUS: ALL 16 factors + the Silicon E module are LOCKED to spec-grade (measure / thresholds /
source-with-exact-URLs / cadence / caveats / events). The programmatic ones were live-verified
against real data this session; the earnings-gated/irregular ones (8,10,12,13) have methodology +
verified source URLs captured. Nothing left to spec. Builders: only rate_path.py written — the other
15 + Silicon E are specced-but-unbuilt (build phase = Claude Code). See STOPLIGHT_SOURCES.md for the
one-page source/status reference.

---

## GLOBAL: conviction ranking replaces section bins (NEW)

The compact sidebar lists all 16 factors in a single CONVICTION RANK, not the
Macro/Credit/Capex GICS-style bins from the original board. Bins still live in the
detail view for navigation; the sidebar is a priority queue. Locked order:

1  Yield curve      — definitional anchor (window open?)
2  Concentration    — magnitude of what's inflated
3  Rate path        — predictive Fed trigger (the fuse)
4  Premium share    — kill-mechanism (commoditization)
5  Silicon payback  — is demand real
6  Leverage         — how violent the unwind
7  Market credit    — the spark
8  Infra backlog    — most-leading early warning
9  Memory canary    — glut sub-mechanism
10 Regulatory       — earnings drag
11 Heavy haul       — freight (continuous)
12 Capex pressure   — ORCL canary lives here
13 Capex spigot     — the bet still being placed
14 Copper           — Dr. Copper (continuous)
15 Inflation        — keeps Fed trapped
16 Net liquidity    — softest macro leg

Yield curve is PERMANENTLY #1 (definitional: if the bubble case dies, so does this factor).

---

## GLOBAL: update mechanics (NEW — two-trigger model)

Atomic event = DATA ARRIVAL, not light flips. Every factor carries metric, prev_metric,
updated_at, cadence.

TWO INDEPENDENT HIGHLIGHT TRIGGERS:
1. NEW-DATA tag — fires only for factors that update LESS often than daily (a trading day).
   A fresh value posting after its gap earns the "new" tag. NEVER fires for hourly/daily
   (state-change-only) factors (copper, heavy haul, etc.) — an intraday/daily arrival is the tick, not news.
2. STATE-CHANGE highlight — fires for ANY factor whose light flips color, cadence-independent.
   This is what gives the hourly/daily factors (copper) their moment: the threshold cross, not the
   intraday/daily reprint.
Both can co-fire (e.g. FINRA posts AND flips leverage's light) — treatments must visually coexist.
(Cadence vocabulary: hourly→daily→weekly→monthly→quarterly→irregular; "continuous" RETIRED — see
STOPLIGHT_SOURCES.md cadence taxonomy. Highlight class = state-change-only [hourly/daily] vs event [weekly+].)

HEADER PIN RULE (collapsed sidebar line shows the freshest print):
- Freshest update holds the header slot until displaced.
- A monthly-or-longer arrival PINS for the trading day (daily noise can't evict it).
- Two long-cadence prints same day → longer cadence wins.

STALE COUNTER: a per-factor "days since update" badge renders once a factor passes its
expected cadence (e.g. memory canary "41d"). Inverse cue to "new data."

---

## SILICON E (the earnings module — FULLY SPECCED, live-verified 2026-07-18)

The durable-earnings module, named **Silicon E** = composite FORWARD NET INCOME of the AI-compute semis.
A MODULE, not one of the 16 lights — a number-with-direction, displayed below the ranked 16 as a centered
white-drum ODOMETER gauge (lime-lit nameplate), digits roll on recompute.

- MEASURE: Σ (forward EPS × shares outstanding) across the basket = composite forward net income ($).
  Basket: NVDA, AVGO, MU, AMD, MRVL (the 5 AI-compute semis).
- CURRENT: **$601B** (live 2026-07-18 = $600.8B, rounded). Per-name fwd NI: NVDA $310.8B · AVGO $92.4B
  · MU $170.3B · AMD $22.0B · MRVL $5.4B. (Confirms the pre-compaction $599.8B/$600B figure — real, not
  estimated; the drift is a few days of estimate movement.)
- CHANGE METRIC (the "+22%"): the composite's RISE over 63 TRADING BARS (1 quarter) — composite_now ÷
  composite_63bars_ago − 1. (Same 63-bar quarter convention as copper #14 and heavy haul #11.)
  NOTE: this is NOT the fwd-vs-ttm figure (that's +143% live) — it's the 63-bar roll of the composite itself.
- FLIP RULE: GAIN over the 63-bar window = 🟢, LOSS = 🔴. Sign of the quarterly roll. (Inverted board:
  🟢 = rising forward semi-earnings = the earnings-melt-up that IS the bubble signal = pro-burst; consistent
  with the "it's an EARNINGS bubble not a multiple bubble" thesis. Parabolic forward-earnings = the tell.)
- SOURCE: yfinance .info forwardEps × sharesOutstanding per name, summed. Verified live (all 5 return
  clean fwd EPS + shares). BUILD WRINKLE: yfinance gives only CURRENT fwd EPS, not historical — so the
  63-bar change needs a DAILY SNAPSHOT LOG of the composite (same mechanic as memory canary #9: snapshot
  daily, diff against the value 63 bars back). Can't be computed from a single pull.
- CADENCE: recomputes daily off a quarterly earnings base (fwd EPS estimates refresh continuously; the
  hard resets land on the 5 semis' earnings). Display-and-input grade (a real computed number, not
  fuzzy-by-permission).
- ROUNDING: display rounded to a clean whole $B ($601B).

---

## FACTOR SPECS LOCKED THIS SESSION

> CADENCE/CATALYST/HIGHLIGHT AUTHORITY = the AT-A-GLANCE table in STOPLIGHT_SOURCES.md (three axes:
> cadence=check-rate · catalyst=dated driver or none · highlight=new-tag vs state-change). Where an
> individual spec line below still says the older "event/continuous" phrasing, the SOURCES table wins.
> Key corrections since those lines were written: "continuous" → daily/state-change; copper = HOURLY;
> Regulatory = DAILY check (not "irregular"); "event" split into catalyst (earnings/data-release/self-gate).


### #1 · Yield curve — 🟢 +0.86 — rank 1 (PERMANENT)
- Measure: DGS10 − DGS3MO, sequence-aware (inversion → crossover).
- Source: FRED (DGS10, DGS3MO). Cadence: daily → highlight class state-change-only (no "new" tag).
- Events: none.
- Note: needs FRED retry/fallback wrapper (FRED intermittent per prior sessions).

### #2 · Concentration — 🟡 ~16.01% (peak 18.03%) — rank 2
- Measure: semiconductor weight in S&P 500 = (Σ IVV semi position values) ÷ (IVV total net assets).
  Unitless ratio; proportional IVV positions are fine (scale factor cancels). Float-adjusted (correct
  concentration convention).
- Constituents: LIVE S&P 500 filtered by GICS sub-industry ∈ {Semiconductors, Semiconductor
  Materials & Equipment}. NO hand list — GICS filter self-maintains. FSLR stays (GICS classifies it
  Semiconductors); no manual include/exclude.
- Current resolution (2026-07-18, 19 names):
  Semis (14): NVDA AVGO AMD QCOM TXN INTC MU ADI NXPI MCHP MPWR ON MRVL FSLR
  Equip (5): AMAT KLAC LRCX TER Q
- SCRUB THIS SESSION vs old hand list: ADDED MRVL (was missing though it's in Silicon E basket),
  ADDED Q (Qnity, new 2025-11-03), DROPPED SWKS (no longer in S&P 500), DROPPED ENPH (never in
  semi GICS anyway). This is why the GICS-filter-not-hand-list rule matters — hand lists rot.
- Source: SINGLE iShares IVV holdings file supplies BOTH legs — per-name market-value column
  (→ filter+sum semis = numerator) and fund total net assets (→ denominator). One file, two jobs,
  no 500-call fan-out, no Slickcharts 403.
  IMPL NOTE: the IVV .ajax CSV endpoint returns page HTML on a naive GET — needs proper headers or
  Claude-in-Chrome route. Confirm column names against the real file before wiring.
  FALLBACKS: numerator via yfinance batched market_cap of the 19; denominator via Slickcharts
  (browser) or ^GSPC×divisor. Slickcharts demoted to periodic sanity-check.
- Cadence: daily → highlight class state-change-only (no "new" tag). Membership refresh
  low-frequency (on S&P rebalance), cached.
- Events: none.

### #3 · Rate path — 🟢 +0.56 tightening — rank 3 — **REDEFINED THIS SESSION**
- WAS "Fed / real rates" (blended real-FF + pivot, 🟡 trapped). Real-FF/inflation leg REMOVED.
  Now a purely predictive rate-expectation factor. Builder: rate_path.py (validated, live).
- Measure: pivot = (5-day avg DGS2) − FEDFUNDS. floored_delta = pivot_now − max(pivot_26wk_ago, 0).
  Negatives floored to 0 so a fading inversion is NOT misread as tightening.
- STATES (no yellow — no armed middle here):
  🟢 tightening : floored_delta ≥ +0.50   (the CAUSE — rates repriced up into the bubble)
  🟢 inverted   : raw pivot < 0            (the REACTION — market pricing cuts)
  🔴 quiet      : otherwise                (status quo / higher-for-longer)
- Metric display carries a STATE LABEL next to the number: "+0.56 tght" / "quiet" / "invt".
- Rationale: tightening (widening pivot) is the burst CAUSE; easing (inversion) is the reaction.
  Level alone is NOT the signal — a flat +0.5 is status quo; the CHANGE (Δpivot) is predictive.
  Rescue-vs-emergency ambiguity dissolves: it only lived on the easing side, now the wide/lagging edge.
- Thresholds set from real history (FRED pull this session): post-'94 mean +0.31, range ~−1.5
  (2024 deepest inversion) to +2.2 (2022 widest). +0.50/6mo caught 2022 by Dec'21 (pre-hike),
  fires ~17% of months. Amplitude = strength gauge (watch, not a threshold; +1.0+ = 2022-grade).
- Source: FRED (DGS2 daily, FEDFUNDS ~8×/yr). Cadence: WEEKLY, recompute THURSDAYS (captures
  Wed FOMC). EVENT factor (weekly < daily) → CAN carry "new" tag on Thursday recompute.
- Events: rate_path_weekly (recurring Thu); fomc_meeting (context, ~6wk).
- Caveat: FRED intermittent — needs retry/fallback.

### #5 · Silicon payback — 🟡 0.21 — rank 5 (WHETHER-leg: is demand real?)
- Ratio: services revenue ÷ silicon spend = $86.5B ÷ $412B ≈ 0.21.
- NUMERATOR (~$86.5B AI services revenue), by disclosure regime:
  · OpenAI ~$24.5B — reported/private, originator The Information → others re-report. Weekly sweep.
  · Anthropic ~$47B — reported, DISPUTED swing input ($9→$47B Jan→May). Weekly sweep.
  · MSFT Copilot ~$9B — DERIVED not looked-up: strip MSFT's ~$37B "AI run rate" (mostly Azure rails)
    to Copilot only (M365 ~$7B @20M+ seats + GitHub ~$1.5-2B). Quarterly (earnings).
  · GOOGL Gemini ~$6B — estimated build-up: seats ($30/$50)×~8M + consumer (~$1.2B disclosed).
    Quarterly (earnings).
- DENOMINATOR (~$412B accelerator spend) = NVDA DC revenue ÷ NVDA accelerator share:
  · NVDA DC rev: $75.2B (Q1 FY27) ×4 = $300.8B. HARD (audited), cleanest input on board.
    RULE: DC segment line ×4, NEVER TTM (TTM understates fast-growing run-rate).
  · NVDA share: 0.73 → $412B. SOFT estimate (Mercury/JPR/TrendForce/IDC/Gartner, 70-75%).
    RULE: re-pull each quarter — divisor DRIFTS DOWN as TPU/Trainium grow ~3× merchant GPU.
    Stale share divides by too-large a number → understates spend → ratio looks artificially
    healthier (a PRO-BUBBLE bias — dangerous on a burst board).
- VALIDATION MODEL (provenance, NOT vote-counting):
  · Reported inputs (OpenAI/Anthropic): trace each number to its ORIGINATOR; re-reporting is not
    independent confirmation. Accept if originator is on the curated reliable-source list. A source
    that proves unreliable is DROPPED from the spec. Reliability curated at source-list level, once.
  · Independent-estimate inputs (NVDA share): genuine cross-source comparison DOES apply — Mercury/
    JPR/TrendForce/IDC run own methodologies, so the 70-75% spread is real (divisor uncertainty band).
- Cadence: EVENT factor, quarterly-dominant (earns "new" tag when any leg lands). Public legs on
  fixed earnings dates; private legs on weekly sweep.
- FUTURE STEP-CHANGE: OpenAI/Anthropic S-1 filing upgrades numerator from voluntary/estimated to
  audited/filed — raises whole factor's reliability tier. Flag to watch.
- EXTRACTION: Copilot decomposition + private-revenue sweep both suit the Claude news-synthesis
  pipeline ("read prose, extract one validated number, trace its origin").
- Events: nvda_earnings, msft_earnings, googl_earnings, nvda_share_estimates (quarterly research),
  openai_rev, anthropic_rev (weekly sweep), openai_s1/anthropic_s1 (watching).

### #4 · Premium share — 🔴− 57.1% — rank 4 (WHETHER-leg 2: does quality command a premium?)
- Formula: premium models' revenue ÷ total revenue (OpenRouter). revenue(model) = token volume × output price.
- Thresholds: 🔴 ≥50% · 🟡 35-50% · 🟢 <35%. Anchored on the MAJORITY line (does premium tier earn
  most of the money?). ~10% floor = true zero-point (premium rev-share converges to premium token-share
  = no premium left); 50/35 set above it. Current 🔴− 57.1% (Opus 4.7 + 4.8).
- PREMIUM/COMMODITY CUTOFF (the load-bearing definition):
  · Commodity floor = cheapest ranked model's OUTPUT price, RE-READ every pull (shifts daily; was
    DeepSeek V4 Flash $0.28/M).
  · Premium = output price ≥ 50× the floor (= $14/M now). Captures Opus-and-above; excludes Sonnet ($10/M).
  · MULTIPLE not fixed $ — floor deflates ~80%/yr, an absolute line would sweep in models from deflation
    alone (sliding-window trap). The multiple self-adjusts. THIS is the key design choice.
- SOURCES:
  · Token volume: OpenRouter GET /api/v1/datasets/rankings-daily — REQUIRES a FREE OpenRouter API key
    (no card, no cost; it's a data read not inference; limits 30/min, 500/day). Returns dated rows
    (top-50/day + aggregate "other"); lookback comes with it.
    KEY IS REQUIRED, not optional: the PUBLIC no-key pull gives only the Top 12, which is INSUFFICIENT
    for the revenue-share math — it misses the commodity long tail, undercounting total revenue AND the
    commodity token-share crack (the ± enhancer). Must use the keyed top-50+"other" endpoint.
  · Prices: OpenRouter GET /api/v1/models — public, no key. Use OUTPUT ($/M completion) price.
  · Citation on republish: "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}."
  · BUILD: rankings-daily → join /models prices → classify by 50× rule → sum revenue by tier →
    premium÷total. SCRIPT NOT YET WRITTEN (to-build list).
- ± ENHANCER (agreement flag, same grammar as GEV/infra-backlog; light DOMINATES, ± never softens):
  commodity models' % TOKEN share. + agrees / − contradicts. Current − : commodity token share 83%
  and rising (Chinese models 1.2%→~51% over 18mo) contradicts the 🔴. "Red with a crack" — premium
  still earns most of the MONEY while commodity takes more of the VOLUME monthly.
- METHODOLOGY RULES (load-bearing):
  1. REVENUE not tokens — cross-provider token counts incommensurate (per-provider tokenizers); dollars
     compare. (Why the ± token-share is a footnote, not the signal.)
  2. OUTPUT price for both threshold and revenue calc (output is meaningful; 3-5× input).
  3. In/out blend caveat: rankings-daily gives TOTAL tokens but prices differ in/out. Approximated
     80/20 in/out; ROBUST (57.1% @80/20, 58.1% @50/50). Use split if OpenRouter exposes it; else blend+note.
  4. Opus 4.7 "Fast" SKU ($30/$150) is a RED HERRING — price 4.7 at standard ($25/M), not priority-speed.
- Cadence: daily (both endpoints refresh daily) → highlight class state-change-only, no "new" tag.
- Events: none.

### #6 · Leverage — 🟢 3.41× — rank 6 (how violent the unwind; LOADED not fired)
- Formula: margin debt ÷ free credit balances (leverage vs investors' cash cushion).
- Thresholds:
  🟢 > 2.0×  — leverage MAXED = tank full = primed to unwind = pro-burst (NOT "crack fired" — loaded)
  🟡 1.5-2.0×
  🔴 < 1.5×
- 2.0× line ANCHORED not chosen: avg of the two peaks that matter — 2000 dot-com 1.85× and 2021
  mania 2.19× (avg ≈2.02 → 2.0). RED near-moot BY DESIGN (like concentration): at record 3.41× the
  bubble pops long before leverage bleeds back to 1.5×, so red rarely reads. Direction: 🟢 = leverage
  MAXED = pro-burst, the fuel-air mixture at maximum, NOT the crack firing.
- Current: 3.41× — ALL-TIME RECORD, 100th pctile 1997-2026. Refs: 2000=1.85×, 2007=1.17×, 2021=2.19×,
  2008 bottom=0.61×. Driven by NUMERATOR: margin debt $936B→$1.50T (+60%) while free credit ~flat
  ($427B→$441B).
- SOURCE (self-contained, no FRED): FINRA margin statistics xlsx, FIXED VERIFIED PATH:
  https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx
  (verified live 2026-07-18; FINRA keeps it current, history to Jan-1997. FINRA states NO data feed/API
  exists — the xlsx download is the ONLY programmatic path.)
  Columns: Month/Year · Debit Balances in Customers' Securities Margin Accounts (= margin debt, numerator)
  · Free Credit Balances in Customers' Cash Accounts · Free Credit Balances in Customers' Securities
  Margin Accounts. DENOMINATOR = cash-FC + margin-FC SUMMED (confirmed: 1,502,072 ÷ (217,441+223,412)
  = 3.41× at Jun-26). PARSE CAVEAT: pre-2010 rows combine the two free-credit columns into ONE.
- Cadence: MONTHLY, released ~3rd week of the month following the reference month. EVENT factor →
  earns "new" tag on release. (This is the canonical pinned-monthly-print example for the header rule.)
- CAVEATS (load-bearing):
  · WHO unresolved: FINRA = customer margin, retail-skewed but includes RIAs/mid-institutions; EXCLUDES
    prime brokerage, repo, total-return swaps (Archegos ran $100B+ via swaps, invisible here) and
    leveraged single-stock ETFs (internal swaps). UNDERSTATES system leverage; can't be pinned on retail.
    Bias runs SAFE for a burst board — real leverage is even more extreme than shown.
  · Minor deflator: post-2020 idle cash sweeps to money funds/T-bills rather than sitting as "free
    credit" → denominator modestly understated → ratio looks slightly higher. Footnote; numerator does
    the work.
  · WHY this denominator (not /GDP or YoY): YoY is a rate (mean-reverts, times poorly); /GDP barely
    changes the story (GDP ~5% vs margin 20-50%) and is the wrong denominator (margin is borrowed
    against stocks, not GDP). Free credit = the relevant self-contained cash-cushion denominator —
    leverage vs the dry powder that would absorb a drawdown.
- Events: finra_margin (monthly release, ~3rd week).

### #7 · Market credit — 🔴 272bps — rank 7 (the spark)
- Measure: ICE BofA US High-Yield Option-Adjusted Spread, in bps. The actual credit spread (up = stress).
- Thresholds:
  🔴 < ~400bps — tight, firewall holding, complacency
  🟡 ~400-500bps — widening off lows / brief scare
  🟢 > ~500bps AND STAYS WIDE — doesn't heal within weeks
  The "AND STAYS WIDE" clause is LOAD-BEARING: the gauge already threw two false alarms that healed,
  so level alone whipsaws. (Validated live 2026-07-18: Apr-2025 spiked to 461bps into the yellow band
  but never crossed 500/stayed → correctly did NOT fire green. The clause works on real data.)
  Direction: 🟢 = credit stress FIRING (pro-burst); 🔴 = no stress now (bubble-supportive).
- Current: 272bps (live 271bps 2026-07-16) — deeply 🔴, at/near record tights = MAXIMUM COMPLACENCY.
  Strongest anti-burst datapoint on the board.
- Reference points: record tights ~250-300 (live min 259 Jan-2025) · long-run avg ~500 · stress 600-800
  · 2020 ~1100 · 2008 ~2000. (Note: FRED series starts ~1996; the ~500 long-run avg blends broader
  history — this pull's mean over available window was 318bps.)
- SOURCE: FRED BAMLH0A0HYM2 (daily, %). EXACT URL (verified by live pull 2026-07-18, returned 271bps):
  https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2
  (FRED CSV template — same for ALL FRED factors, swap the id=: yield curve DGS10/DGS3MO, rate path
  DGS2/FEDFUNDS, inflation PCEPILFE, net liquidity WALCL/WTREGEN/RRPONTSYD. Value is in PERCENT — ×100
  for bps.) FALLBACK is DIRTY: HYG/IEF (yfinance) — IEF is 7-10yr duration so the ratio rises on falling
  yields even with zero credit change (rates-contaminated). USE THE FRED OAS.
- Cadence: daily → highlight class state-change-only, no "new" tag. FRED retry/fallback needed.
- CAVEATS (load-bearing):
  · RED = "no stress NOW" NOT "safe." 2007 echo locked: spreads ~record tights (~250bps) early-mid 2007
    right before the blowout. Tight = no risk premium = no cushion; complacency is the PRECONDITION for
    a credit event, not its absence. A deeply red reading is the setup, not reassurance.
  · THE ASYMMETRY is the point: distance to green is huge (272 must nearly double to 500+) BUT the speed
    is violent — tights→600+ took WEEKS in 2008 and 2020. You get a GAP not a slide. Don't read
    "far from green" as "slow to fire" — it won't drift toward green, it'll jump.
- THE CREDIT PAIR (why deliberately un-blended with #? Debt-funded edge/CRWV):
  Market credit (broad firewall) + Debt-funded edge (CRWV, AI-credit canary) answer 2000-vs-2008 in two
  lights. debt-edge 🟢 ALONE = contained AI credit problem. debt-edge 🟢 + market-credit 🟢 TOGETHER =
  contained→systemic. NOW: CRWV stressed (🟢, AI-credit broken) while broad credit 272bps record tights
  (🔴) = AI leverage problem is real, confirmed, and QUARANTINED. A blended index would erase exactly
  this distinction — which is why they stay separate.
- Events: none.

### #14 · Copper — 🔴 +8.9% vs 200DMA — rank 14 (Dr. Copper, continuous, leading)
- Measure (user rule — deliberately AGGRESSIVE, explicitly NOT backtested):
  🟢 = below the 200-day MA (green dominates)
  🟡 = above 200DMA BUT no new 52-week high for 63 TRADING BARS
  🔴 = everything else (above 200DMA WITH a 52wk high inside 63 bars = humming)
  GATE = 63 TRADING BARS (a quarter of trading), NOT calendar days. HG=F trades 252 bars/yr same as
  equities (the "copper trades an extra day" premise was FALSE → 63 for both copper AND Heavy Haul #11).
- Direction: 🟢 = below trend = real economy ROLLING = pro-burst; 🔴 = above trend humming = bubble-supportive.
- Current: 🔴 — $6.22, +8.9% vs 200DMA (live: +8.7%, $6.22 vs $5.72 200-bar MA 2026-07-17); 52wk high
  $6.6495 on 2026-06-02 (verified live). → flips 🟡 ~Sep 1 absent a new high = SELF-EXECUTING gate,
  no report needed (63 bars from the Jun-02 high).
- SOURCE: yfinance HG=F (COMEX copper front-month). Verified live 2026-07-18, pulls clean, 251 bars/1y.
  LME marginally cleaner but not worth the pipeline (tariff premium distorts LEVEL not TREND).
  BUILD NOTE: 200DMA = 200 TRADING bars (pull >200 bars; naive period="200d" gives calendar days, short).
- DESIGN RATIONALE (for spec):
  · NO absolute price line — copper's level has no fixed meaning ($3 expensive in 2005, cheap in 2025);
    fixed threshold = sliding-window trap. Relative to its own 200-day. (Same anti-rot principle as #4
    floor, #5 divisor.)
  · NO persistence clause on green, BY CHOICE — aggression is the point; recent regime says it's free.
    (A %-deviation band w/o persistence was rejected: median episode below any band = 3 days, 71-82%
    die within 10 = pure whipsaw.)
  · Base rate confirms the thesis (why aggression is defensible): copper's green-rate collapsed
    40%→30%→21%→15.5%→0% (2001→2026 YTD); has NOT closed below its 200DMA once in 2026. A green here
    breaks a 10-month streak = a real event, not noise.
- CAVEATS:
  · Survived the contamination test that killed EMPLOYMENT — contamination needs a 2nd axis: SPEED.
    Employment contaminated + lagging → useless. Copper contaminated + LEADING (continuously-traded
    forward price) → contamination becomes information. Copper roll = real economy weakening OR AI capex
    rolling, both = the burst. Slots above VRT in leading hierarchy purely on frequency (copper daily,
    VRT quarterly).
  · AI contamination ~15% of marginal copper demand — a FLOOR and growing (counts copper INSIDE the
    datacenter; excludes the grid built to serve it). True AI share higher and rising → factor DEGRADES
    over time. Note in spec.
  · Tariff worry dismissed by user's own test: COMEX HG=F carries a Section-232 premium over LME, but
    untariffed industrials (zinc, tin at 4yr highs) rallied too → move is INDUSTRIAL not US-policy. Use HG=F.
  · Copper/gold is DEAD as a proxy — gold's monetary repricing swamps the ratio (94th pctile 1yr vs
    18th 10yr same day). Don't resurrect it.
- Cadence: HOURLY (HG=F price refreshes intraday) → highlight class state-change-only, no "new" tag.
  (Cadence = refresh rate only; the 200-bar MA + 63-bar gate math stays on DAILY bars regardless.)
- Events: copper_gate ~Sep 1 (self-executing 63-bar gate off the Jun-02 high; no external data needed).

### #11 · Heavy haul — 🔴 +32.7% vs 200DMA — rank 11 (custom freight index, daily, leading; the ORANGE factor)
- THE INDEX: equal-weight index of freight that PHYSICALLY moves the buildout (earth movers,
  transformers, oversized industrial loads). 16 names, verified all pull clean on yfinance 2026-07-18:
    LTL:        ODFL, SAIA, XPO, ARCB
    Truckload:  KNX, WERN, HTLD, MRTN, SNDR, CVLG
    Flatbed/oversize: LSTR (Landstar)
    Intermodal: JBHT
    Rail:       UNP, CSX, NSC
    Utility eq: CTOS (Custom Truck One Source)
  EXCLUDES (deliberate): airlines (consumer travel — biggest contaminant), parcel (UPS/FDX = e-commerce),
  general forwarders (GXO/EXPD/CHRW/HUBG). RXO optional — adding it barely moves it (+96.7 vs +98.6 cum),
  so the signal isn't one name.
- WEIGHTING: EQUAL-weight (not cap — breadth question; cap-weight lets marginal names shrink to rounding,
  same logic as #12 capex-pressure). Rebased to 100, MEAN of the members.
- SOURCE: yfinance, batched download of the 16 tickers, ["Close"]. Chart+builder: heavy_haul.{png,py}.
  Verified live 2026-07-18: 16/16 pulled, 251 bars/1y.
- THE 4-STATE LADDER (unique on board — has ORANGE). Two conditions, evaluated ONLY while price >200DMA:
    cond1: price below the 50 DMA
    cond2: no new 52-week high for 63 TRADING BARS (quarter; same gate as copper #14)
  🟢 GREEN  = price below the 200 DMA — ANY breach. Dominates everything.
  🟡 YELLOW = above 200DMA AND BOTH conditions true (below 50DMA AND no 52wk-high 63 bars)
  🟠 ORANGE = above 200DMA AND exactly ONE condition true
  🔴 RED    = above 200DMA AND neither (above 50DMA, recent 52wk high) = humming
  Direction: 🟢 = below trend = freight rolling = pro-burst; 🔴 = humming = bubble-supportive.
- Current: 🔴 — +32.7% vs 200DMA (94th pctile 5yr, 98th 23yr) [live: +33.6%], +7% above 50DMA
  [live +6.5%], 52wk high 2026-06-11 [verified exact], now -1.7% below high. → flips 🟠 ~Sep 10 absent
  a new high (63 bars off Jun-11) = SELF-EXECUTING gate, no report needed. (5yr rebased: HH 211/S&P 175/XTN 155.)
- WHY THE LADDER (hysteresis is the whole point): after a green episode ends → ORANGE 86% · YELLOW 12%
  · RED only 2%. A brief 200-breach that recovers CAN'T snap back to red (50DMA/63-bar conditions still
  true) → lands in orange. Solves whipsaw STRUCTURALLY, no persistence clause bolted on.
  YELLOW is RARE (~2.5% of 23yr): in a downtrend the 50DMA falls below the 200, so recrossing the 200
  puts you above the 50 → cond1 false → orange not yellow. Yellow needs price BETWEEN 50 and 200 with
  momentum dead = classic distribution top. Of 53 episodes >20% above 200DMA that rolled green, 45
  SKIPPED yellow. Treat yellow as a rare topping flag; ORANGE does the day-to-day work.
- WHY CUSTOM not off-the-shelf: ^DJT is price-weighted (1884 construction), nearly threw a false yellow
  (its 52wk high 2026-04-21 while IYT/XTN + 7 names made highs the same day). Airlines = biggest
  contaminant (transports by a taxonomy predating the airplane). DJT÷SPY rejected — conflates transports
  with concentration (falls when SPX rips, not when freight weakens).
- HONEST CAVEAT: mechanism not fully isolated — at n=5 annual obs can't cleanly separate "AI buildout"
  from "ordinary industrial-freight cycle." Two things point AI: HH beats PARCEL by +44pts (specific to
  industrial freight, not just "no airlines") and beats S&P 500 by +9pts over the biggest AI melt-up ever.
  Suggestive, not conclusive — documented as such.
- Cadence: daily → CONTINUOUS factor → state-change highlight only, no "new" tag.
- Events: heavyhaul_gate ~Sep 10 (self-executing 63-bar gate off Jun-11 high; no external data).

### #15 · Inflation — 🟡 3.41% — rank 15 (hottest macro factor; keeps Fed trapped)
- Measure: core PCE YoY (the Fed's targeted gauge, NOT headline CPI).
- Thresholds (LEVEL-ONLY / current-state — deliberate simplification, NO direction or lookback):
  🔴 ≤ 2%     — at/below target → Fed can ease → rescue available
  🟡 2-3.5%   — elevated but manageable ("market handles low-3s fine")
  🟢 > 3.5%   — hot → Fed forced tighter / trapped hard, no rescue
  Direction: 🟢 = hot inflation = Fed trapped = pro-burst; 🔴 = ≤2% = Fed can cut = bubble-supportive.
- Current: 3.41% (verified live 2026-07-18, May-2026 print) — barely 🟡, ONE TICK from the >3.5% green
  line = hottest macro factor on the board. Fed genuinely trapped (Fed put nearly unreachable). Trail is
  CLIMBING: 2.97→3.10→3.05→3.25→3.32→3.41 over 6mo — grinding toward the green flip.
- SOURCE: FRED PCEPILFE. URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPILFE
  MECHANICAL NOTES:
  · FRED gives the INDEX not the rate — do the division: YoY = idx ÷ idx[-12mo] − 1 (e.g. 130.08÷125.79−1
    = +3.41%). pct_change(12)×100 on the monthly series.
  · CPI prints ~2wk earlier as a faster proxy BUT color on core PCE — thresholds are on core PCE, which
    runs ~0.3-0.5pp BELOW headline CPI. NEVER read a CPI number against these lines.
- Cadence: MONTHLY (data lags ~4-6wk; latest is May-2026). EVENT factor → earns "new" tag on release.
- CAVEATS:
  · BLIND SPOT (accepted, not a bug): level-only loses the non-monotonic tail — a demand-collapse
    disinflation to ≤2% would mis-color 🔴 when it's really 🟢. SAFE only because the board is
    multi-factor: in that scenario the demand factors (copper, transports) go green simultaneously and
    the board catches it. NEVER read inflation ≤2% as "all clear" standalone — it only means "Fed can
    ease," which the rest of the board must corroborate.
  · MONETARY CLUSTER: Rate path (#3) + Inflation (#15) + Net liquidity (#16) CO-MOVE — count as ~ONE
    signal, not three. A cluster greening together is one monetary read, not three independent
    confirmations. (This is why inflation ranks low at #15 despite being live/hot.)
- Events: pce_release (monthly).

### #16 · Net liquidity — 🟡 ~$5.96T — rank 16 (softest macro leg; monetary cluster)
- Measure: net_liq = WALCL − WTREGEN(TGA) − RRPONTSYD, in $T. Signal on the 3-MONTH (13-week) CHANGE,
  noise-aware and sustained.
- Thresholds (on the 3mo change, vs a ±$0.2T noise band — CALIBRATED this session, see below):
  🟢 DRAINING  — 3mo change below −$0.2T (past ~1SD) AND confirmed by 6mo trend / level below MA
  🟡 FLAT      — 3mo change within ±$0.2T (the noise band)
  🔴 EXPANDING — 3mo change above +$0.2T AND sustained
  The "AND sustained / 6mo-confirmed" clause is LOAD-BEARING: TGA swings ±$200-400B/qtr dominate,
  so don't flip on one Treasury-account move. Direction: 🟢 = liquidity DRAINING = pro-burst;
  🔴 = expanding = bubble-supportive tailwind.
- Current: 🟡 — net liq ~$5.96T (live $5.99T 2026-07-15), 3mo change was +$0.25T at spec time
  (right at the boundary) but live +$0.033T = deeply inside band = solidly flat. Neutral backdrop,
  not a firm tailwind.
- BAND CALIBRATION (the one open number on the board — was estimated ~$0.3T because FRED timed out
  during the build; COMPUTED clean this session 2026-07-18):
    2018+ regime:  3mo-change SD = $0.388T (n=446) — where the old ~$0.3T estimate came from
    last-3yr:      3mo-change SD = $0.176T (n=159) — QT more than HALVED the volatility
  Per the "recent regime is the right band" rule → use last-3yr, rounded UP to a clean ±$0.2T.
  (Meaningfully tighter than the old $0.3T; the 2018+ window was inflated by the COVID BS explosion.)
- SOURCE: 3 free weekly FRED series:
  WALCL (Fed balance sheet, $ MILLIONS, weekly Wed H.4.1)
  WTREGEN (Treasury General Account, $ MILLIONS, weekly)
  RRPONTSYD (o/n reverse repo, $ BILLIONS, DAILY — forward-fill to weekly)
  URLs: fredgraph.csv?id=WALCL / =WTREGEN / =RRPONTSYD
- UNIT TRAP (build-critical, verified live — I hit this bug and got −$749T before catching it):
  WALCL & TGA are in MILLIONS, RRP is in BILLIONS. Align: WALCL/1e6 − WTREGEN/1e6 − RRPONTSYD/1e3 (→$T).
  (Equivalent to the user's "×1000 the RRP" framing.) Get this wrong and the whole factor is nonsense.
- Cadence: WEEKLY (WALCL/WTREGEN weekly; RRP daily ffill). EVENT factor → "new" tag on H.4.1 release.
- CAVEATS:
  · RRP BUFFER ~EMPTY (~$0, down from ~$2.5T in 2022, live confirms ~$0.0002T). So a drain from HERE
    hits bank reserves DIRECTLY = bites harder than 2022 at the same headline number. Same color, worse
    bite — note on the instrument.
  · TGA leg is the FASTEST early-warning (issuance schedules semi-known in advance).
  · MONETARY CLUSTER: Rate path (#3) + Inflation (#15) + Net liquidity (#16) co-move = ~ONE signal, not
    three. Net-liq is currently the NEUTRAL member of that cluster.
- Events: h41_release (weekly).

### #9 · Memory canary — 🔴 0/5 dn — rank 9 (memory-glut sub-mechanism; WHEN factor)
- What it watches: memory-market HEALTH, not HBM in isolation. REFRAME: DDR5 strength is AI-CAUSED not
  anti-AI — capacity diverted into HBM starved commodity DRAM, so AI lifts the whole complex directly
  (HBM) and indirectly (the DDR5 shortage it created). A real AI-demand crack = HBM AND DDR5 rolling
  TOGETHER, not one segment softening while the other absorbs.
- PRIMARY METRIC (locked): of the last 5 forward-EPS revisions POOLED across MU + SK Hynix, count the
  DOWNWARD ones:
  🔴 ≤ 1 down
  🟡 2-3 down
  🟢 ≥ 4 down
  Update DAILY. Direction: 🟢 = estimates CRACKING = pro-burst; 🔴 = estimates holding/rising = supportive.
- Current: 🔴, 0-of-5 down (verified live 2026-07-18: MU 28up/~0-1 down 7d = a DDR5 burst; SK Hynix
  ~0-3 up/0-1 down; pooled ~31 up / 0-1 down). Deeply not-fired — estimates revised sharply UP.
  (Ladder boundary: RED = ≤1 down, so 0 or 1; 2 would already be YELLOW.)
- THE BASKET — MU + SK HYNIX ONLY:
  · SK Hynix 000660.KS (KOREAN line) — 56% HBM share = the HBM-concentrated pure play. Full yfinance
    analyst data (14 analysts). NOT SKHYV (new US listing → NaN estimates) nor thin German ADRs — the
    Korean line is the one with coverage. (Verified pulls clean despite prior flakiness notes; keep the
    caveat.)
  · Micron MU — the other pure play, but ~90% COMMODITY (5-10% HBM share).
  WHY BOTH (load-bearing): MU alone hides HBM softness under DDR5 strength; SK Hynix carries the HBM
  signal, MU is the commodity read. NVDA OUT (commoditization target, not a memory play). Samsung OUT
  (too diversified — logic/foundry/phones/displays; memory a fraction).
- SOURCE & MECHANICS: yfinance eps_revisions = true EPS estimate DIRECTION (up/down counts). NOT
  upgrades_downgrades (rating actions = reiteration noise, no direction — a firm stays "Overweight"
  while cutting EPS = wrong lens).
  DATA CAVEAT: yfinance gives COUNTS over 7d/30d windows, not a timestamped list. So "last 5" is
  APPROXIMATED from the down-share of the 7d window (fall back to 30d if <5 in 7d).
  DELTA RECOVERS EVENTS: snapshot counts daily and DIFF them — a 0→2 jump in downLast7days = two fresh
  downgrades that day. Daily logging turns the count into a real event stream, reconstructing "last 5."
  FREQUENCY (measured): event-clustered — ~3-7 revisions/wk baseline, spiking 20-40 in an event week
  (earnings/guidance/pricing). Daily pulls sit flat between bursts then jump on a catalyst. Daily is
  for catching the burst the day it lands.
  ATTRIBUTION not cleanly free: eps_revisions gives direction w/o names, upgrades_downgrades gives names
  w/o direction; firm-level estimate direction is paid (FactSet/Refinitiv). So: count the downs, forget
  the who. Script: scratchpad/memory_canary.py.
- CONFIRMATION LAYERS (slower cross-checks, NOT the daily signal):
  · Gross margins MU+SK Hynix (quarterly at earnings) = disclosed profit-per-wafer proxy. Compressing
    = the crack confirming behind the revisions.
  · Stanford DAM free CSV: https://dam.stanford.edu/assets/memory-prices/memory-prices.csv (no key).
    Best series: HBM $/TBps (cost-per-bandwidth = performance-adjusted commoditization; 352→297 declining
    even as blended $/GB holds) + HBM spend $B (aggregate demand). Caveat: sparse/lagged (~semi-annual)
    → rough backdrop, not timely.
  · Earnings: SK Hynix ~07-28, MU ~09-23. Offset calendars → a memory read ~every 6 weeks.
- CADENCE: daily → highlight class state-change-only, no "new" tag (though revisions are
  event-clustered; the daily pull catches bursts).
- RATIONALE: DXI daily index de-prioritized (clean number paywalled $4k/yr; memory doesn't crack in a
  day while revisions are already continuous). Commoditization test underneath: even sold out, HBM can't
  restore its premium on scarcity — contract-locked pricing + concentrated buyers (NVDA plays the 3
  makers off each other) + incoming supply wave + rising HBM4 cost. Big picture: the AI memory-price
  surge is the biggest UP-blip in memory's ~70-yr decline; anomalies in a falling market tend to revert.
- Events: skhynix_earnings ~07-28, mu_earnings ~09-23 (confirmation layer, not the daily signal).

### #10 · Regulatory — 🔴↓ 3 states — rank 10 (earnings-durability DRAG, not a timing canary)
- REFRAME: a DRAG on earnings durability (input to the earnings question), NOT an independent timing
  signal. Federal is brake-only / currently hands-off (free market in control) = background pro-bubble,
  nothing to track. The ACTION is state/local, where the jobs-to-disruption ratio is terrible (a GW
  datacenter = ~50-100 permanent jobs + power bill + drained aquifer + tax abatement = the NIMBY fight
  that wins).
- PRIMARY MEASURE — STATE-WIDE cost-shift policy count: count of states with a policy action establishing
  a cost-shift rule for large loads (datacenters fund their own power infra / higher rate class instead of
  socializing onto ratepayers). Purest earnings-durability metric — converts the free ride into a cost the
  hyperscaler bears.
- COUNTING RULE (all THREE tests must hold — this is what makes the count 3, not 24):
  1. STATE-WIDE — binds all utilities/large loads in the state, NOT one utility's service territory.
     (Legislative statute qualifies inherently; a PUC/regulatory rule qualifies only if applied state-wide.)
  2. GENERAL + THRESHOLD-DEFINED — a rule for a CLASS with a definable threshold (e.g. "loads ≥25MW pay
     their own infrastructure"), not a discretionary case-by-case action.
  3. NOT project/single-utility-specific — a single utility's tariff (Dominion GS-5, AEP Ohio) or one
     datacenter's negotiated terms does NOT count, even if threshold-defined, because it isn't state-wide.
  GUARDRAIL: do NOT lift EEI/Columbia's "~24 states approved a large-load tariff" as the count — that number
  is mostly SINGLE-UTILITY PUC tariff approvals (fails test #1/#3). Each candidate must pass all three tests
  first. This is a JUDGMENT step (read the action, classify it), not a raw number — fits the Claude sweep.
- Thresholds:
  🔴 < 10 states
  🟡 10-20
  🟢 20+
  Rationale (RELOCATION ARBITRAGE): below 10, hyperscalers just relocate to a free-ride state → no bite.
  10 = "start of a movement" (relocation gets hard). 20 = "essentially federal / nowhere to run" = free
  ride over. (5 rejected as too small.) Direction: 🟢 = constraint rising = pro-burst; 🔴 = free ride on.
- Current: 🔴 — only 3 states enacted (CA, OH, UT).
- KEY DISCIPLINE — GATE ON ENACTED LAW, NOT THE PIPELINE. The noise FEELS 🟡: 300+ state bills in a 6wk
  span across 30+ states, 27 states "considering," NY's first-state ban, OK SB1488 100MW+ moratorium to
  2029. But only 3 bindingly ENACTED cost-shift → free ride still on in 47 states. Vibe said 🟡; statute
  count says 🔴 — TRUST THE STATUTE. This is the anti-narrative rigor of the whole board in one factor.
  PIPELINE = the leading tell: 27 considering → if a third enact, primary flips 🟡. Bill velocity (regime
  shift from incentive→restriction policy) is the early warning.
- ± ENHANCER — Data Center Watch blocked-project count, as a DIRECTIONAL ARROW (↓/↑), NOT the +/− glyph:
  uses physical-stoplight direction like capex-pressure — more blocks = ↓ (toward burst) / fewer = ↑.
  Monitors the populist swell (grassroots opposition — the fast layer under the slow statutory primary).
  DCW method: counts denials OR withdrawals (solves "developer pulls app before formal no-vote" undercount),
  splits definitively-blocked from reactivatable-delayed (treat BLOCKED as the hard number). Quarterly.
  Current: 🔴↓ — blocks accelerating 20 proj/$98B (Q2'25) → 75/$130B (Q1'26); active anti-DC groups
  396→833 in one quarter, now in 49 states.
  BIAS HANDLED BY CONSTRUCTION: DCW is advocacy-adjacent (selection bias toward opposition wins) — but the
  "light dominates, ± is a footnote, never softens the color" rule quarantines it. The enhancer can only
  move the ARROW; the color stays gated on unbiased enacted statutes. So using the only aggregator that
  exists, bias and all, is safe. Rejected: Shovels.ai (rigorous/unbiased true denial-rate + timelines,
  but PAID, permit-stage-only = blind to pre-permit zoning kills, narrower). Keep in reserve for a true rate.
- SOURCE (IRREGULAR — no API/schedule; manual or weekly-sweep read of trackers, NOT a programmatic pull;
  each candidate CLASSIFIED by the 3-test rule above before it counts — a judgment step, not a raw number):
  · Enacted/state-wide count (PRIMARY): MultiState "Policy Watch: Data Centers" (subscription tracker) +
    free insider articles at https://www.multistate.us/insider/... (VERIFIED — confirms 3 enacted CA/OH/UT,
    27 considering, 2026-04). Cross-refs (candidates to CLASSIFY, not lift raw): SEPA/NCCETC "DELTa"
    database https://sepapower.org/large-load-tariffs-database/ (free, 100+ tariffs); EEI large-load list;
    Halcyon tracker halcyon.io/large-load-tariff-tracker (188 filings); Columbia Climate Law blog.
    datacenterbans.com (moratoria) — from prior session, NOT verified this pass.
  · Blocked count (± ENHANCER): Data Center Watch — https://www.datacenterwatch.org/report (VERIFIED),
    quarterly updates e.g. https://www.datacenterwatch.org/q22025. Backed by 10a Labs (AI-industry intel
    firm — so pro-industry backing yet still catalogues opposition = arguably MORE credible, not less).
    Figures VERIFIED: $64B blocked/delayed 2023→Mar'25, then $98B in Q2'25 alone. DCW itself warns delays
    aren't purely opposition-driven → keep the "definitively-blocked = hard number" split.
    ⚠️ SOURCE-RISK FLAG (migrate if a better source appears): DCW is NOT an advocacy tracker — it's a B2B
    INTELLIGENCE PRODUCT (10a Labs) sold to hyperscalers/Fortune-10 as siting intel. Hence the paywall
    (the puzzle: why would "advocacy" hide behind a paywall? because it isn't advocacy — the opposition is
    the SUBJECT, the industry is the CUSTOMER). Implications: (a) TIMELINESS — publishes on its own slow
    cadence, free-facing numbers lag the paid product; (b) ACCESS RISK — a gated vendor can move fully
    behind the wall / change terms / discontinue free summaries, and then the blocked-count source vanishes;
    (c) BIAS is INDUSTRY-ward (frame opposition as a manageable trackable risk), not opposition-ward as the
    spec first assumed — the ±-can't-change-color quarantine still handles it. MIGRATION TARGET if wanted:
    Shovels.ai (true unbiased denial-rate + permit timelines; paid, permit-stage-only). User wants to move
    off DCW if a better/free/timelier blocked-project source is found — treat DCW as the interim aggregator.
  NOT live-verifiable as a pull — the count is a READ+CLASSIFY of trackers. Fits the Claude news-synthesis
  pipeline (legislative sweep = "read the action, apply the 3-test rule, count state-wide cost-shift policy").
- THE MECHANISM (how it drags earnings — critical): regulation does NOT knock over the AI giants — it
  takes out NVIDIA and the BUILDOUT. A construction moratorium/taper = no new datacenters = no new GPU
  orders. Entrenches incumbents-with-capacity (supply freeze = scarcity pricing = reverses commoditization
  for them = a moat; silicon-payback & premium-share move AWAY from green for them). Works through
  EARNINGS not the multiple: NVDA 15.8× fwd has no growth premium to compress, but a growth multiple
  cracks on DECELERATION — so a permitting TAPER (not even a national ban) is sufficient to break the E.
  Colored 🟢-ward as constraint rises (hits the buildout, where the board's reds already live).
- STRATEGIC COROLLARY: a regulated DEFLATE gives no clean bottom to buy — it's the fiber-2000 slow bleed.
  A rising regulatory drag quietly undermines "wait in cash for the crash" → tilts toward measured
  participation. (Note on unwind SHAPE, not a color.)
- Cadence: DAILY check (three-axis: cadence=daily / catalyst=none — nothing on a calendar announces a
  statute, you sweep daily and occasionally catch one / highlight=new-tag ON A HIT). The data CHANGES
  irregularly but is CHECKED daily — "irregular" is the data's nature, NOT the cadence.
- Events: reg_watch (irregular sweep); dcw_quarterly (DCW report, quarterly).

### #12 · Capex pressure — 🔴↓ (2 of 5 through the gate) — rank 12 (ORCL canary lives here)
- Measure: capex ÷ operating cash flow (OCF), PER COMPANY. Basket: MSFT, GOOGL, AMZN, META, ORCL.
  UNWEIGHTED — individual lights + arrows, then a MAJORITY read (NOT a blended basket number).
- MAJORITY TIE-BREAK RULES (a 5-light basket can deadlock; "up" = up the PHYSICAL traffic light = toward
  RED = conservative / away from calling the burst):
  · RULE 1 — green/red tie → YELLOW. 2🟢 / 2🔴 / 1🟡 → composite 🟡 (extremes cancel, ambiguous middle).
  · RULE 2 — two ADJOINING tiers tied → defer UP toward red. 2🔴/2🟡 → 🔴 ; 2🟡/2🟢 → 🟡.
  Worked cases: 2🟢/2🔴/1🟡 → 🟡 · 2🔴/2🟡/1🟢 → 🔴 · 2🟡/2🟢/1🔴 → 🟡.
  DESIGN NOTE: the tie-break is deliberately CONSERVATIVE on this inverted board — ties resolve toward
  the more bubble-supportive color, so the board waits for a CLEAR majority before leaning toward burst.
  Consistent with the board's anti-false-alarm philosophy (don't cry burst on a deadlock).
- Thresholds (PER COMPANY):
  🔴 < 75%    — self-funding = supportive
  🟡 75-100%  — burning too much
  🟢 > 100%   — funding the bet with the balance sheet / debt = the bet won't pay = pro-burst
  Direction: 🟢 = spending beyond cash generation = maxed = pro-burst; 🔴 = comfortably self-funded.
- Current: 🔴↓ (majority) — MSFT 57%🔴 · GOOGL 63%🔴 · META 61%🔴 · AMZN 102%🟢 · ORCL 174%🟢
  → 3🔴 / 0🟡 / 2🟢 = 🔴 majority, arrow ↓ (all five deteriorating YoY). Live TTM 2026-07-18.
  (AMZN has now CROSSED the 100% gate on TTM — the queue advanced: ORCL 174% + AMZN 102% both through;
  META/GOOGL/MSFT next in line at 61/63/57%.)
- BASIS (LOCKED): TTM — trailing four quarters (this quarter + prior three), capex ÷ OCF per name,
  compared to the year-ago TTM for the ↑/↓ arrow. TTM chosen to SMOOTH seasonality (Q4 capex patterns
  differ from Q1) and cut single-quarter noise — a full trailing year is automatically season-complete.
  Verified live via yfinance quarterly_cashflow, last-4-quarters summed (Operating Cash Flow + Capital
  Expenditure rows). Be consistent across the basket. NOTE: AMZN sits just over the 100% line on TTM
  (102%) — near the boundary, watch it.
- THE ↓ ARROW (read carefully — physical-stoplight mnemonic resolves the ambiguity): per-company ratios
  are RISING (47→…, burning more), but "burning more" moves the stoplight position DOWN toward burst.
  Arrow = STOPLIGHT POSITION, not the metric's raw direction. Ratios up = arrow down.
- WHY UNWEIGHTED (design rationale): no dollar-weighting — same principle as Heavy Haul + Silicon E.
  Dollar-weighting would shrink ORCL from CANARY to rounding error (~5.6% of basket capex $). ORCL's
  whole value is being the small stretched one that cracks first. Blending also hides dispersion
  (violates the un-blended principle). Keep individual lights + arrows, read the majority. Revisit only
  if real dispersion emerges.
- KEY INTERPRETATION:
  · >100% is a BET, not a death sentence — Amazon ran it for years building AWS = one of the great
    capital allocations. Fatal only on a specific combo: DEBT-FUNDED + returns don't materialize +
    interest compounds = the CRWV snowball. Same ratio, opposite outcomes: net-cash AMZN 94% vs levered
    ORCL 174% (FCF −$24B).
  · BUT this is a RACE not AWS-alone. Amazon built into empty space (no competition, monopoly margins).
    This is EVERYONE building simultaneously = the fiber-2000 structure (capacity glut → commoditized
    prices → builders die, rails get used by someone else). Competitive structure flips the analogy →
    ties to the commoditization thesis: competition destroys the returns.
- THE COMBINED READ (why it pairs with #13 Spigot): PRESSURE LEADS the spigot. The two capex lights move
  OPPOSITE — companies spend faster (spigot 🔴, guidance +77%) while capacity to fund it erodes
  (pressure 🔴↓). Spending faster as the tank drains = the strain that eventually forces a guidance cut.
  So: pressure greens FIRST (companies breach 100%), THEN the spigot greens (the forced cut). ORCL
  already through at 174%; AMZN at the gate at 94%. That's the queue.
- SOURCE: company financials — capex & OCF from cash-flow statements (LATEST QUARTER primary, TTM
  cross-check; consistent across basket). Verified pullable via yfinance quarterly_cashflow (Operating
  Cash Flow + Capital Expenditure rows) 2026-07-18. Silicon Analysts `hyperscaler-ai-capex` = pullable
  alternative for the capex side.
- Cadence: QUARTERLY (earnings-gated). EVENT factor → "new" tag when a name reports.
- Events: msft_earnings, googl_earnings, amzn_earnings, meta_earnings, orcl_earnings (5 hyperscaler dates;
  shared with #13 Spigot).

### #13 · Capex spigot — 🔴 +73% YoY — rank 13 (the confirming half of the capex pair)
- Measure: hyperscaler forward capex GUIDANCE growth (YoY, basket aggregate). "Is the money still flowing?"
- Thresholds:
  🔴 > +10%      — spigot wide open = bubble-supportive
  🟡 −10% to +10% — flat / decelerating
  🟢 < −10%      — guidance CUT = the demand-side flip = pro-burst
  NO ARROW (correct): the measure is a RATE, so direction is already in the number — an arrow would be
  the 2nd derivative (is growth accelerating?) = over-engineering a glyph. Contrast #12 capex-pressure,
  which is a LEVEL and does carry an arrow. Direction: 🔴 = spigot open = money flowing = supportive;
  🟢 = guidance cut = demand flip = pro-burst.
- Current: 🔴 — deeply red, ~7× the threshold. $725B 2026 guide: AMZN $200B, GOOGL $185B, META
  $125B, MSFT $120B (~75% AI-related = ~$450-540B). Trend 🔴→🔴, no deceleration, 2026 guided higher.
- BASIS PINNED (settled 2026-07-18, replaces the old "news-scan, don't trust exact figure" caveat):
  the MEASURE is forward GUIDANCE growth (from calls / Silicon Analysts) — but for a verifiable
  basket-consistent ANCHOR, reported capex on the pinned 5 names (annual cashflow, yfinance) =
  last-FY $413B vs prev-FY $238B = **+73% YoY** (MSFT +45 / GOOGL +74 / AMZN +59 / META +87 / ORCL +162).
  This +73% reported-capex number sits inside the +69-77% guidance-scan range → the light is unambiguous
  and the figure is now REPRODUCIBLE (scratch/check_spigot2.py). Guidance (the true forward measure) runs
  ahead of reported capex; both deeply red. Use +73% as the anchor, guidance for the live read.
- SOURCE: company guidance (earnings calls + 10-Q). Silicon Analysts `hyperscaler-ai-capex` ($B by company)
  = pullable alternative that beats news scans (recommended primary for a clean number). Extraction from
  calls fits the Claude news-synthesis pipeline.
- THE KEY LAG STRUCTURE (why this is NOT the leading factor):
  · Guidance is quarterly (10-Q + call, ~3-6wk after quarter-end) = fine on cadence. BUT reported capex
    lags the DECISION by 2-4 quarters (spend committed once ground broken / chips ordered). So the signal
    you watch is a guidance CUT, not a reported decline (by the time reported capex falls, it's ancient news).
  · LEADINGNESS HIERARCHY: VRT/GEV orders & book-to-bill (earliest) → capex GUIDANCE (the decision) →
    reported capex (laggiest). This is exactly why infra-backlog (#8) is its own, MORE-leading factor —
    it sits UPSTREAM of the spigot.
- THE COMBINED READ (spigot + pressure = the pair; the story neither tells alone): the two capex lights
  move OPPOSITE — companies spend FASTER (spigot 🔴 +77%) while capacity to fund it ERODES (pressure 🔴↓).
  Spigot opening wider as the tank drains = the strain that eventually forces a guidance cut. PRESSURE is
  the leading indicator FOR the SPIGOT: pressure greens first (breach 100% capex/OCF), THEN spigot greens
  (the forced cut lands in guidance). ORCL through at 174%, AMZN through at 102% (TTM) — that's the queue;
  watch pressure to anticipate the spigot. Given the lag, a GREEN here is a CONFIRMATION not a warning —
  the warning comes one layer up (pressure + infra-backlog).
- Cadence: QUARTERLY (earnings-gated). EVENT factor → "new" tag when a name guides. Shares #12's 5 dates.
- Events: msft/googl/amzn/meta/orcl_earnings (5 hyperscaler dates, shared with #12 Pressure).

### #8 · Infra backlog — 🔴+ 2.9× — rank 8 (MOST-LEADING factor of the capex complex; tip of the spear)
- WHY RANK 8 (above the capex pair): leadingness hierarchy = VRT/GEV book-to-bill (EARLIEST) → capex
  guidance (#13) → reported capex (laggiest). Orders/b-t-b move BEFORE guidance does → infra-backlog sits
  UPSTREAM of everything the capex pair measures.
- PRIMARY — VRT book-to-bill. DEFINITION (nail this — stock/flow confusion caused real errors):
  book-to-bill = NEW orders booked in the period (a FLOW) ÷ shipments/billings in the period (a FLOW).
  NOT cumulative backlog (a STOCK). Identity: Backlog(end)=Backlog(start)+orders−shipments, so
  ΔBacklog = orders − shipments.
- Thresholds (tightened from the proposed >1.2):
  🔴 > 1.0
  🟡 0.9-1.0
  🟢 < 0.9, AND two CONSECUTIVE prints under 0.9 to fire (b-t-b is lumpy — one print is a data point,
     two is a turn).
  WHY SO TIGHT: VRT's backlog is only ~0.9 YEARS of revenue = NOT saturated = no cushion, so you need
  b-t-b >1 just to hold ground. ("Less than a year is hardly a backlog… new orders are vitally important.")
  Direction: 🟢 = orders evaporating = pro-burst; 🔴 = orders still flooding in = supportive.
- Current: 🔴 — 2.9× (Q4'25), VERIFIED from VRT's own Q4'25 press release + earnings call (2026-07-18
  web-verified): "book-to-bill ratio was ~2.9x, backlog $15.0B up 109%." NOT a scan artifact — VRT
  REPORTS the ratio directly. Recent trajectory: Q1'25 ~1.4× → Q3'25 ~1.4× → Q4'25 ~2.9× (organic
  orders +252% YoY into Q4) = ACCELERATING, deep red, no rollover. VRT reports Q2 ~JULY 29 = next read.
  BUILD RULE: READ the reported book-to-bill ratio from the release/call — do NOT compute it from backlog
  deltas (that's the stock/flow trap; the old "$15.0B vs $12.45B → implausible 0.25×" ghost was exactly
  this error — $15.0B is BACKLOG, a stock, and differencing two backlog snapshots ≠ book-to-bill).
- WHY B-T-B BEATS BACKLOG GROWTH: backlog growth is ambiguous — VRT's same data reads −17% sequential OR
  +80% YoY (YoY lags, sequential noisy). B-t-b separates "backlog fell because we shipped a mountain"
  (healthy) from "orders died" (the signal) — ΔBacklog alone can't tell them apart.
- KEY RESULT — the green CAN'T BE FAKED by share loss: for b-t-b to fall 2.9×→<0.9, orders must drop ~70%
  — share loss can't do that (you'd lose the majority of your business in a quarter). So a green cannot be
  a competitive-share-loss artifact — it's DEMAND, full stop. (In a supply-constrained market, 3×
  oversubscribed, share loss can't even show in the order book.) Company-specific reads (product/tech
  shift) survive only in YELLOW; can never produce a green → the − earns its keep in yellow, near-
  meaningless at green.
- ± CORROBORATOR — GEV remaining available GW (agreement glyph on VRT's color: + supports / − contradicts):
  🔴 available GW shrinking · 🟡 flat (deadband ±5 GW) · 🟢 available GW GROWING (slots opening back up =
  orders stopped cold = the cleanest demand-evaporation signal on the board).
  Current: + — entering Q1'26 ~10 GW available in 2029 → exiting Q1 ~10 GW across 2029 AND 2030 combined
  (burned 2029, dug into 2030 in one quarter). CEO expects fully sold out through 2030 by end-2026 →
  shrinking → +. GEV reports Jul 22.
  WHY AVAILABLE-GW (not sold-out date / not total backlog):
  · NOT the sold-out date — measuring HORIZON in months has built-in downward drift (a static 2030 date
    shrinks one month every month from the calendar alone = false greens from passage of time). If you
    must use the date: track the DATE, not the horizon. Also year-granular → ±6mo deadband incoherent.
  · NOT total backlog GW (100→110) — contaminated: grows when GEV adds FACTORY CAPACITY, conflating
    demand with supply expansion.
  · Available GW wins — directly measures demand-vs-capacity balance, continuous, granular, can't drift
    with the calendar, disclosed broken out by year.
- HOW TO READ THE ± (lag structure — CRITICAL): VRT has a ~1yr book, swings quarterly = genuinely LEADING.
  GEV has a 4-5yr book, glacial (2029/2030 slots committed years ago) = badly LAGGING. So the TIMING of a
  − tells you what it is:
  · − right as VRT turns = GEV latency → IGNORE it.
  · − persisting several quarters after VRT turns = genuine VRT-specific divergence.
  · + RETURNING after VRT went green = the slow book finally confirmed = the real, sector-wide signal.
  A + arriving AFTER a green is worth far more than the + sitting next to today's red.
- CAVEATS:
  · CANCELLATIONS break the ΔBacklog identity — backlog can fall because orders were cancelled (bear
    signal), but a cancellation usually isn't booked as a negative order → won't show in b-t-b either.
    Watch cancellations as SEPARATE disclosure.
  · TEST THE ARITHMETIC before promoting a flag — scan-sourced backlog figures ($15.0B Q4'25 vs $12.45B
    Q1'26) implied an implausible b-t-b ≈0.25×, which was itself the tell they weren't comparable (RPO vs
    backlog vs different dates). Don't repeat that.
  · NEWSFEED = qualitative context, not a colored measure — order press releases are positively biased
    (announce wins, bury cancellations) → track the boom, blind to the rollover. Useful continuous channel
    = the cancellation beat (Data Center Dynamics, analyst channel checks).
- SOURCE: VRT earnings (book-to-bill from call/10-Q) + GEV earnings (available GW by year). Both quarterly.
  NOT a clean API pull — extraction from earnings materials (fits the Claude news-synthesis pipeline).
- Cadence: QUARTERLY (earnings-gated). EVENT factor → "new" tag on VRT/GEV report.
- Events: vrt_earnings ~Jul 29 (PRIMARY, the clean read), gev_earnings ~Jul 22 (± corroborator).
