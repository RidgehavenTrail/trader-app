---
paths:
  - watchtower_engine.py
  - turtle_indicator*.py
  - volume_indicator*.py
---

# Turtle Trade Indicator & 2x Volume Indicator

**Status: BUILT, MERGED, and RUNNING LIVE.** (Corrected 2026-07-16, session 29 — this
file's title still said "design spec, not yet built" and its status line said "NOT
STARTED" two days after the feature shipped. Both were stale; the spec below describes
SHIPPED behavior, not a future target.)

- Spec settled 2026-07-13; built 2026-07-14 on `feature/turtle-2x-indicators`
  (bucket-list priority 1 = Turtle, 2 = 2x volume).
- **Merged to `master` 2026-07-16** as merge commit `274d6e9` (`--no-ff`, so the 21
  commits stay revertable as one unit). Revert tag: `known-good-pre-turtle-2026-07-14`.
  NOT pushed — local master only.
- **Confirmed live 2026-07-16:** engine restarted 08:12 ET; real breakouts firing
  (CAG / KHC / O / UPS / XNDU-short) — not the QQQ `--as-of-date` test card.
- Code: `turtle_indicator.py`, `volume_indicator.py`, wired into `watchtower_engine.py`;
  display in `watchtower.html` + `static/js/actionable.js`.
- Summon a test breakout without waiting for a live one:
  `python watchtower_engine.py --as-of-date 260602 --ticker QQQ`.

## Turtle Trade Indicator (priority 1)

- **Window:** 55-day rolling high/low of daily HIGH/LOW price (Turtle System 2
  entry) — NOT closing price.
- **Trigger:** current price crosses above the 55-day high (long breakout) OR
  below the 55-day low (short breakout). Fires once on the crossing event, not
  on every subsequent bar the price remains outside the range.
- **Direction:** both directions fire — long and short are both valid alerts.
- **Data need:** ~55+ trading days of daily high/low per ticker. Use a yfinance
  `period` with buffer for weekends/holidays (e.g. `period="4mo"`).
- **Card condition tag:** `turtle_long` / `turtle_short`.

## 2x Volume Indicator (priority 2)

> **SESSION 44 (2026-08-13) SUPERSEDES CORRECTION (1) BELOW — the 1m fetch is GONE, and the
> mechanism it was fixed for was never the one operating.** `compute_volume_ratio` now reads
> today's cumulative volume from the LAST ROW OF THE DAILY FRAME, which it was already
> fetching for the baseline. One call, one source, no 1-minute data anywhere.
>
> The session-43 fix trimmed multi-SESSION 1m responses. The real fault, caught live in 33
> paired samples of both sources (3 corrupt, ~9%):
> ```
> 12:44:16  NVDA  195 bars  daily  52,781,066   1m 447,657,208   8.48x
> 12:44:16  TSLA  195 bars  daily  15,516,464   1m  62,006,573   4.00x
> 12:45:01  NVDA  195 bars  daily  52,850,045   1m  52,848,190   1.00x
> ```
> Correct bar count, ONE session, no duplicates — the per-bar Volume VALUES were transiently
> inflated, clearing within one 45s sample, hitting two tickers at once while a third stayed
> clean. **A session-trim can never see this.** The "about five sessions each" below was
> inferred from the implied cumulative, never observed; a corrupt 1m read on NVDA computes to
> 3.18x, which fits the same evidence with no extra sessions at all.
> **The daily bar was correct and monotonic in all 33 samples**, including during both events,
> on the very tickers that were corrupt — it is one row and nothing is summed, so it cannot
> express this fault. NOT gated: a confirmation gate (cumulative volume cannot fall, so a 2x
> read must survive a later sample) was designed and left unbuilt — this had not surfaced in a
> month and the source switch removes the observed fault. Build the gate only if inflation
> ever appears in the DAILY bar.
>
> **STILL OPEN (unfixed by choice):** `patch_actionable_move` unions `conditions` and the
> volume branch only runs when the ratio is ABOVE 2.0, so nothing ever clears the tag or
> corrects the stored ratio downward — one bad read survives until the midnight clear. That is
> what left NVDA showing 2.8x all afternoon on a true 0.34x day.
>
> **TWO CORRECTIONS, session 43 (2026-08-12) — historical; (1) is superseded above.**
> **(1) The 1m fetch must be trimmed to ONE session.** `compute_volume_ratio` summed
> `stock.history(period="1d", interval="1m")` and trusted the period. yfinance serves 1-minute
> data from a rolling ~7-day window and sometimes returns SEVERAL sessions, turning "volume so
> far today" into a multi-day total. Observed live: NVDA reported **3.2x** and TSLA **3.5x** in
> the same sweep on a day both traded BELOW average (true **0.64x** / **0.60x**) — implied
> cumulatives of ~4.4 and ~5.4 days, about five sessions each. Now trimmed to the last session
> present in the DATA (not the wall clock, so stale data fails safe at ~1x rather than as a
> false spike). Commit `1f52dfb`.
> **(2) A volume hit ALWAYS earns its own news pull, once/day/ticker.** This shipped in
> `0033699` and was silently lost in `e776b3b`, which replaced the direct synthesis call with
> `schedule_news_pull()` and inherited that function's no-op-if-already-pulled guard — correct
> for a repeat PRICE trigger, wrong here. Volume usually arrives WITH definitive news, so a
> spike is evidence something printed since the morning attempt. Restored as
> `schedule_volume_news_pull()`, which re-arms the SHARED state machine (so the budget counter,
> banding and context tiers all apply) rather than running a private path.
> `run_synthesis_in_background()` has had NO CALLER since `e776b3b` — it is dead code.

- **Baseline:** 50-day average daily volume (full-day totals).
- **Trigger:** raw cumulative volume-so-far-today exceeds 2x the 50-day average.
  Deliberately NOT pro-rated for time-of-day — realistically a mid-afternoon-or-
  later trigger most days, and that's intentional, not a bug.
- **Check cadence:** polled at :15 and :45 past every hour during market hours
  (9:45, 10:15, 10:45, 11:15 ... etc.) — not continuous, not once-daily.
- **Card condition tag:** `volume_2x`.
- **Displayed value:** the actual ratio (e.g. "2.4x"), not just a fired/
  not-fired boolean — lets a 2.0x squeaker be distinguished from a 5x anomaly
  at a glance.
- **Regular market hours volume only** — both the cumulative volume-so-far-
  today figure and the 50-day baseline average EXCLUDE pre-market and
  after-hours volume entirely. Consistent with yfinance's regular-session
  volume field, not `fast_info` or any pre/post market volume source.
- Market-wide context (Fed days, CPI prints, broad-market volume spikes) —
  explicitly NOT wanted; this indicator stays per-ticker only, no
  cross-referencing against the macro panel.

## Shared mechanics (both indicators, plus existing 1-sigma trigger)

- Either condition can independently generate a card, same as the existing 1-sigma
  expected-move trigger — these are ADDITIVE triggers, not gates on the existing one.
- **One card per ticker regardless of how many conditions fire — no duplicate cards.**
- Card schema needs a SET of fired conditions, not a single reason string, since
  Turtle + 2x-volume + 1-sigma can all be true simultaneously on the same ticker.
  This is a schema change to whatever `actionable_moves.json` cards look like today
  (single `why`/reason field -> a conditions array or similar) — not just a
  frontend sort tweak.
- **Sort/display priority when multiple conditions are present:**
  `Turtle > 2x volume > 1-sigma` — highlighting reflects ALL fired conditions on
  the card, but sort position in the actionable moves list is driven by the
  highest-priority condition in that set.
- Conditions meeting either trigger get highlighted and bubbled to the very top
  of the actionable trades list (above plain 1-sigma-only cards).

## Not yet decided / open when this gets built

- Exact `patch_actionable_move()` schema for the conditions set (list of tag
  strings? dict with per-condition metadata like breakout price/date?).
- Whether Turtle/2x-volume checks run in the same main loop as the existing
  yfinance polling, or a separate background thread given the 55-day history
  pull is heavier than the current per-tick price check.
- Visual treatment for "stacked" highlights when 2+ conditions fire on one card.

## Turtle card display spec (settled 2026-07-13)

Displays in the slot where options data normally shows on the card (see also
`.claude/rules/heatmap-dashboard-hook.md` re: that same "Options Data" quadrant
— confirm no collision once both features are being built).

- **ATR (N)** — 20-day Average True Range. This is "N" in every calc below.
  Assumption carried forward: 20-day is the standard Turtle lookback for N;
  flag/revisit if a different period is ever wanted.
- **55-day breakout level** — the specific high/low price that was crossed
  (not just "breakout happened", the actual level).
- **Suggested stop-loss** — entry price +/- 2N (classic Turtle stop distance).
- **20-day opposite channel** — the System 2 exit reference level (20-day
  high if short, 20-day low if long) — informational only, not automated.
- **Pyramid levels** — ALL remaining add levels up to the 4-unit max shown at
  once (not just the next one). Each level = entry + 0.5N increments in the
  trade's direction, per unit already filled up to unit 4.

## Turtle signal persistence (settled 2026-07-13)

Once triggered, the Turtle flag on a card is GATED for the rest of the day —
it does not clear if price re-enters the 55-day channel intraday. Resets at
daily rollover (same rhythm as the existing midnight-clear logic already in
the engine). This mirrors the "no reset until next day" behavior, not the
volume indicator's continuous-recheck behavior.

## Turtle historical breakout stats (settled 2026-07-13)

Deliberately NOT unit-sizing (no account-size input on the dashboard — N alone
is enough for the user to work out sizing off-dashboard; keep dashboard inputs
minimal).

Historical stat shown alongside the live signal, computed over a MULTI-YEAR
lookback (several years — short lookbacks like 6mo don't give enough episodes
to be meaningful):

- **Episode definition:** an "episode" starts at the FIRST 55-day crossing in
  a given direction. Subsequent same-direction 55-day crossings within that
  same episode do NOT start new episodes — a genuine trending breakout will
  keep making new highs/lows and must not be double-counted as repeated
  separate breakout signals. A new episode only starts once the prior one has
  concluded (see exit simulation below) and a fresh crossing occurs.
- **Success/failure classification:** simulate the System 2 exit (20-day
  opposite-channel breach) for each episode. Exit at a loss vs. entry = FAILED
  episode. Exit at a profit = SUCCESSFUL episode.
- **Displayed stats:**
  - Count of failed vs. successful episodes (over the multi-year lookback)
  - Average win % (mean profit, as percent price move, across successful episodes)
  - Average loss % (mean loss, as percent price move, across failed episodes)
  - Units are PERCENT PRICE MOVE only (not N-units) — chosen for cross-ticker
    comparability.


## Card vs. detail-panel placement (settled 2026-07-13)

Mockups reviewed in chat this session (both compact card and detail panel).

- **Compact actionable-strip card** (the horizontal-scroll card in
  `#actionable-container`): shows CONDITION BADGES ONLY — e.g. "Turtle",
  "2.4x vol" — no metric data. Keep it lean; this is the glance view.
- **Detail panel (clicked-in view):** the full metrics block (ATR, breakout
  level, suggested stop, 20-day opposite channel, pyramid levels, historical
  win/loss stats) occupies the EXISTING "Options Data" quadrant directly —
  it does not get its own separate tab/selector alongside Narrative/Chart/
  Options. Same collision note as above re: `heatmap-dashboard-hook.md`
  wanting that same quadrant — resolve before either feature is built.


## Testing & verification strategy (settled 2026-07-13)

Real-time verification is a poor fit here — breakouts are rare and can't be
manufactured on demand. Two separate layers, both needed (one isn't a
substitute for the other):

### Layer 1 — trigger-logic tests (offline, no dashboard involved)
Feed historical price/volume arrays straight into the calculation functions
in isolation; assert correct ATR, correct breakout level, correct crossing
detection, correct episode/failed-breakout counting. Fast, no engine running,
verifies the math only — does NOT verify the dashboard renders anything.

### Layer 2 — date-injection test (verifies the dashboard itself works)
Extends the engine's EXISTING `--test` flag (already used to bypass market
hours) with a new `--as-of-date YYMMDD --ticker <SYMBOL>` mode:
- Format is `YYMMDD` (e.g. `260530` for 2026-05-30) — settled 2026-07-13.
- Engine pulls real historical data up through that date, treats it as
  "today," and runs the NORMAL trigger evaluation against it.
- If a condition fires, it writes a REAL card through the normal
  `patch_actionable_move()` path — same as live — not a mock/stub card.
- User then opens the actual dashboard and visually confirms: card appears,
  correct badges, correct sort/bubble position, and clicking in shows correct
  ATR/breakout/stop/pyramid/historical-stats data in the Options Data quadrant.
- This is genuine UI verification (the dashboard has no idea it isn't really
  that date), not just a math-only confidence check.

### Golden-file regression plan
- Starting symbol: **QQQ**.
- Pick a known historical QQQ breakout date, run it through the Layer 2
  date-injection mode, save the resulting card JSON as a reference fixture.
- Any future change to the trigger logic gets re-run against the same
  date/ticker — if the output silently changes, something broke.
- Additional tickers/dates can be added to the fixture set over time; not
  fully enumerated now.

## Pyramiding & how the strategy is MANAGED — BUILT session 27 (read this to run it)

Status: **BUILT** on branch `feature/turtle-2x-indicators` (`turtle_indicator.py` pure math,
Layer-1 tested; engine wiring `34aed71`; pyramided stats `84b3b07`). Not merged to master.
See the `turtle-2x-next-action` memory for the running state.

### Pyramiding is the CORE of the edge — it is modeled, not decorative
The system's expectancy comes from putting **4 units on winners and ~1 on losers**. Single-unit
stats HIDE this (they equal-weight every episode) — that was the key methodology correction this
session. Mechanics (all in `turtle_indicator.py`):
- **Enter unit 1** at the 55-day breakout level (the crossed extreme).
- **Add units 2, 3, 4** at **+0.5N increments** in the trade's direction (0.5N / 1.0N / 1.5N past
  entry), up to **4 units**, as price runs — each add only if price actually reaches the level.
- **Raise the whole-position stop** to **2N below** (long) / above (short) the **most recently
  added** unit on every add (classic Turtle stop-raising).
- **Exit ALL units together** at whichever binds first: the raised stop OR the **20-day
  opposite-channel** breach (System 2 exit).
- **N = 20-day ATR. 1R = one unit's initial 2N risk.** A fully-pyramided whipsaw loses ~−2.5R; a
  4-unit runner can be +10 to +25R.

### Stats are PYRAMIDED aggregate-R, SPLIT BY DIRECTION
`pyramided_episodes()` + `pyramid_stats()` compute aggregate R per episode (sum of each filled
unit's move ÷ 2N). `compute_turtle_snapshot()` stores `stats: {long, short}`; a fired signal shows
**only its own direction's** record (a long breakout must never show short-diluted stats — user's
explicit call). Rendered in the detail-panel "Trade Data" quadrant (narrow bordered card, colored
expectancy). The single-unit `breakout_episodes`/`episode_stats` remain as a primitive but are NOT
used by the snapshot.

### How to run / inspect / extend
- **Summon a breakout on demand** (breakouts are rare): `python watchtower_engine.py --as-of-date
  YYMMDD --ticker SYM` (e.g. `--as-of-date 260602 --ticker QQQ`) — pulls real history through that
  date, evaluates the trigger, writes a real card. Non-destructive; needs a normal engine restart
  after to return to live.
- **`turtle_indicator.py` is the reusable backtest engine** — it powered all the session-27
  strategy backtests too.
- **KEY BACKTEST FINDING (QQQ 10y, long-only): plain 55-day long-only is best (+102R).** The
  200-SMA long filter, the 52-week-high entry filter, and shorts ALL HURT on QQQ — because QQQ
  V-recovers off bottoms while still below the 200-SMA, so every "wait for confirmation" filter
  forfeits those early-recovery breakouts (the biggest winners). This is QQQ-specific (a resilient
  index); the same filters would likely HELP on single stocks / secular bears. See the
  `qqq-timing-backtests` memory. Constants (top of `turtle_indicator.py`): 55-entry / 20-exit /
  20-ATR / 4-unit / 0.5N step / 2N stop.
- **No news synthesis on Turtle** (the metrics ARE the content); it fires quietly and lets a
  same-day 1-sigma/volume trigger handle any narrative.

## 2026-08-27 (session 47) — a 2x miss that could NOT be diagnosed after the fact

NVDA closed at **2.29x** (297,197,891 against a 50-day average of 129,666,886) and the sweep never
fired. It was the ONLY watchlist name above 2.0x that day — next highest 1.29x — so nothing else could
corroborate. Two candidates, and they could not be separated retroactively:

1. it crossed after **15:45**, the last :15/:45 window before the close (the threshold was 259.3M against
   a 297.2M close, so the last ~12.7% of the day's volume had to still be outstanding); or
2. the daily frame was LAGGING at the check windows and `compute_volume_ratio` **failed closed**, which
   is what it is designed to do when `daily.index[-1].date() != today`.

**Deferred by the user: add logging only if it recurs.** The instrument would be one line per sweep —
`(ticker, slot, ratio_or_None)` — which distinguishes "ratio was 1.7 at 15:45" from "no reading" and
costs nothing.

**AND THE SESSION-44 CORRUPTION IS LIVE, NOT HISTORICAL.** Reconstructing the intraday crossing from 5m
bars gave a cumulative of **1,714,494,181** against the daily bar's 297,197,891 — a 5.8x inflation, 78
bars, one session, correct bar count. Exactly the fault that moved this indicator onto the daily bar. It
was nearly reported as "crossed at 10:20 ET" before being checked against the daily bar. **Any intraday
Yahoo series needs the daily bar as a cross-check.**
