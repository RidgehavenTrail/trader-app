# STOPLIGHT — DATA SOURCES (exact pull reference)
**The build reference. Every factor's exact URL or method — so the coding session never has to ask
"where do I get this?"** Verified entries were live-pulled 2026-07-18. ALL 16 + Silicon E = LOCKED.

## TAXONOMY — THREE INDEPENDENT AXES ("continuous" and the old "event" highlight-label are RETIRED)
- **Cadence** = pure UPDATE/REFRESH (CHECK) RATE — how often you re-pull/recompute. Does NOT change the
  calculation basis. Ladder: `hourly` → `daily` → `weekly` → `monthly` → `quarterly`.
  (NOTE: "irregular" is NOT a cadence — a factor whose underlying data changes irregularly is still
  CHECKED on a clock. Regulatory changes irregularly but is CHECKED daily → cadence = daily.)
- **Catalyst** = the scheduled CALENDAR event that drives an update, if any (this is what "event" really
  means — a dated happening you wait for): `earnings` · `data-release` (Fed/FOMC, FINRA, PCE, H.4.1) ·
  `self-gate` (a calendar-computed date, no external release) · `none` (just polled on a clock).
- **Highlight** = DISPLAY behavior on a fresh value: `new-tag` (a fresh print is news → tag it) vs
  `state-change` (fresh value is just the tick → highlight ONLY on a color flip).

## AT-A-GLANCE (all 16 + module)
| # | Factor | Cadence | Catalyst | Highlight | Status |
|---|--------|---------|----------|-----------|--------|
| 1 | Yield curve | daily | none | state-change | L |
| 2 | Concentration | daily | none | state-change | L |
| 3 | Rate path | weekly (Thu) | data-release (FOMC) | new-tag | L |
| 4 | Premium share | daily | none | state-change | L |
| 5 | Silicon payback | quarterly | earnings | new-tag | L |
| 6 | Leverage | monthly | data-release (FINRA) | new-tag | L |
| 7 | Market credit | daily | none | state-change | L |
| 8 | Infra backlog | quarterly | earnings (VRT/GEV) | new-tag | L |
| 9 | Memory canary | daily | none | state-change | L |
| 10 | Regulatory | **daily** | none (irregular data, daily check) | new-tag on a hit | L |
| 11 | Heavy haul | daily | self-gate (~Sep 10) | state-change | L |
| 12 | Capex pressure | quarterly | earnings | new-tag | L |
| 13 | Capex spigot | quarterly | earnings | new-tag | L |
| 14 | Copper | **hourly** | self-gate (~Sep 1) | state-change | L |
| 15 | Inflation | monthly | data-release (PCE) | new-tag | L |
| 16 | Net liquidity | weekly | data-release (H.4.1) | new-tag | L |
| — | Silicon E | daily | none | state-change | L |

## SOURCE DETAIL — FRED (5 factors)
Template: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>` — native unit (rates in PERCENT,
×100 for bps). Needs retry/fallback (FRED intermittent: curl 28 timeouts, not rate-limit). No key.

| # | Factor | Series | Compute notes |
|---|--------|--------|---------------|
| 1 | Yield curve | DGS10, DGS3MO | spread = DGS10 − DGS3MO, sequence-aware |
| 3 | Rate path | DGS2, FEDFUNDS | pivot = 5d-avg DGS2 − FEDFUNDS; floored Δ26wk ≥+0.50 |
| 7 | Market credit | BAMLH0A0HYM2 | HY OAS; ×100 for bps (271bps live). "stays wide" clause |
| 15 | Inflation | PCEPILFE | core PCE; YoY = pct_change(12)×100 on INDEX; color core-PCE not CPI (3.41% live) |
| 16 | Net liquidity | WALCL, WTREGEN, RRPONTSYD | WALCL/1e6 − WTREGEN/1e6 − RRPONTSYD/1e3 ($T). UNIT TRAP (WALCL/TGA millions, RRP billions). ±$0.2T band on 3mo change ($5.99T live) |

## SOURCE DETAIL — API / file (4 factors)
| # | Factor | Exact source | Key? |
|---|--------|-------------|------|
| 2 | Concentration | **SUPERSEDED 2026-07-19 (build session): SSGA SPY daily holdings xlsx** `https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx` — iShares IVV .ajax is bot-gated beyond header fixes (Akamai TLS fingerprinting: curl/requests/UA/cookies/siteEntryPassthrough ALL return the HTML shell; verified live). SPY = same index, direct file, per-name Weight (header row 4; Sector col is "-" — GICS membership lives in `stoplight/inputs/semi_membership.json`, seeded w/ the 19, newcomers yfinance-classified). **BASIS CHANGE rides along: ETF weights are FLOAT-ADJUSTED (the spec's stated correct convention) and read ~1.09× ABOVE the raw-cap basis of the 2026-07-18 figures (16.01% raw → 17.40% float same market). Raw-basis peak 18.03% (06-22) kept as labeled reference in extras; the float-basis history was RECONSTRUCTED 2026-07-19 (price-ratio scaling, validated to 0.01pp against the live file) and backfilled into the snapshot log: FLOAT-BASIS PEAK 19.83% on 2026-06-22 (same date as raw). Thresholds stay 15/20 (user, 2026-07-19). Never mix the bases.** Build: `stoplight/sources/ssga.py` + `factors/concentration.py`. | no |
| 4 | Premium share | OpenRouter: `GET https://openrouter.ai/api/v1/datasets/rankings-daily` (token volume — REQUIRES free key; public no-key = Top 12 only = insufficient) + `GET https://openrouter.ai/api/v1/models` (prices, public). | **YES** |
| 5 | Silicon payback | Multi-source composite (no single URL): NVDA/MSFT/GOOGL earnings (IR+SEC); OpenAI/Anthropic via weekly journalism sweep (The Information originator); NVDA accel-share from Mercury/JPR/TrendForce/IDC. | — |
| 6 | Leverage | FINRA xlsx (VERIFIED): `https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx` — NO API/feed, xlsx only. Cols: debit / free-credit-cash / free-credit-margin. Denom = cash+margin summed. | no |

## SOURCE DETAIL — yfinance (5 factors + Silicon E)
| # | Factor | Symbols / method |
|---|--------|------------------|
| 9 | Memory canary | eps_revisions: MU + 000660.KS (SK Hynix Korean line — both verified pull clean). Count downs in last-5 pooled; daily snapshot+diff to reconstruct. Confirm: Stanford DAM CSV `https://dam.stanford.edu/assets/memory-prices/memory-prices.csv` (no key). |
| 11 | Heavy haul | batched, 16 names EQUAL-WEIGHT rebased-100: ODFL SAIA XPO ARCB KNX WERN HTLD MRTN SNDR CVLG LSTR JBHT UNP CSX NSC CTOS (all verified). 4-state ladder w/ ORANGE; 63-bar gate. builder: heavy_haul.py |
| 12 | Capex pressure | quarterly_cashflow, TTM (last-4-qtr sum) capex÷OCF per name: MSFT GOOGL AMZN META ORCL. Unweighted, 5 lights + majority + tie-breaks. Verified live (ORCL 174%, AMZN 102% through gate). Alt: Silicon Analysts hyperscaler-ai-capex. |
| 14 | Copper | HG=F (front-month). 200-bar MA + 63-bar/52wk-high ladder. Verified live. HOURLY refresh (price), daily-bar math. |
| — | Silicon E | forwardEps × sharesOutstanding, 5 semis NVDA/AVGO/MU/AMD/MRVL summed = $601B live. +22% = 63-bar roll; gain=🟢/loss=🔴. Needs daily snapshot log for the 63-bar change (like #9). |

## SOURCE DETAIL — extraction / irregular (3 factors, no clean API — READ+CLASSIFY, not a pull)
| # | Factor | Source / method |
|---|--------|-----------------|
| 8 | Infra backlog | VRT book-to-bill (FLOW÷FLOW, NOT backlog): 🔴>1.0 / 🟡0.9-1.0 / 🟢<0.9 ×2 consecutive. ± = GEV available-GW by year (shrinking=🔴/growing=🟢). From earnings materials (call/10-Q). Catalysts: GEV Jul 22, VRT Jul 29. |
| 10 | Regulatory | Count STATE-WIDE cost-shift policy only (3 tests: state-wide + general/threshold-defined + not project/single-utility). PRIMARY: MultiState insider `https://www.multistate.us/insider/` (VERIFIED, 3=CA/OH/UT). Cross-refs to classify: DELTa `https://sepapower.org/large-load-tariffs-database/`, Halcyon, EEI. GUARDRAIL: do NOT use EEI's "~24 approved" raw (single-utility tariffs). ± enhancer: Data Center Watch `https://www.datacenterwatch.org/report` (VERIFIED, quarterly; MIGRATE if better source found — it's a paywalled B2B intel product). |
| 13 | Capex spigot | hyperscaler fwd capex GUIDANCE growth YoY (basket aggregate). 🔴>+10% / 🟡±10% / 🟢<−10% (cut=green). Source: earnings calls + 10-Q; Silicon Analysts `hyperscaler-ai-capex` = recommended pullable primary. Pin basket to the 5 (=#12). No arrow (it's a rate). |

## KEYS NEEDED in .env (per project rule — never hardcode)
- ANTHROPIC_API_KEY (existing — news pipeline + extraction factors 5/8/10/13)
- OPENROUTER_API_KEY (NEW — required for #4 Premium share rankings-daily; public pull = Top-12 = insufficient)
- FRED, FINRA, iShares, yfinance, Stanford DAM = NO key
