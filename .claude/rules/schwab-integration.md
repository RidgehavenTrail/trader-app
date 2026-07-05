---
paths:
  - "market_data_engine.py"
  - "schwab*.py"
---

# Schwab Data Source Integration — NOT YET BUILT

**Status:** Architecture decided in a planning conversation (2026-07-03). No code
written yet. This file captures the design so implementation can start without
re-deriving it. Update `## Status` at the top once work begins.

## Why

- yfinance zeros out open interest after hours instead of holding the last settled
  value — confirmed via direct observation, not just a timing/refresh-cadence issue.
  This makes yfinance untrustworthy for deep-dive options chain analysis outside
  active market hours, which is specifically when the user wants to do that analysis.
- Schwab's own quote/chain feed has been directly observed to hold a real OI value
  at all times (yesterday's or today's, never zeroed) — confirmed by the user's own
  usage of the Schwab platform, not just vendor claims.
- User's actual requirement is **not** low-latency streaming — 30s polling is
  explicitly "overkill" per the user, and real-time WebSocket streaming was ruled
  out entirely. The dashboard's job is to be an **alert engine that flags what to
  look at**, not a live tick monitor — for anything requiring closer attention than
  that, the user goes to their actual trading platform (thinkorswim). This
  significantly simplifies the integration: plain REST polling on a timer, same
  pattern as the existing engine, no persistent connection/subscription management.

## Data source assignment (final)

| Data | Source | Cadence |
|---|---|---|
| Equity/option underlying price | Schwab REST quote (`/marketdata/v1/quotes`) | 60s situational-awareness mode / 30s active-trader mode |
| Options chain (ATM strike, put premium, IV, put/call walls) | Schwab REST chain (`/marketdata/v1/chains`) | Independent slow timer (~15-30 min, or once at market open) — NOT tied to the price poll cadence |
| Options chain — deep-dive (user clicks a ticker in Deep Dive panel) | Schwab REST chain, on-demand | Fetched fresh at click time, any hour including after-hours |
| Single watched option strike (real-time interest case) | Schwab REST quote via OSI-format option symbol | Same cadence as underlying price |
| Futures (metals/energy/ag/index) price + chart | yfinance (`=F` continuous tickers) | 60s, unchanged from today |
| Forex spot | yfinance (`=X` tickers) | 60s, unchanged from today |

Schwab cannot provide futures order routing or futures historical bars (confirmed:
futures quotes work via `/ES`-style symbols, but historical price history is
equities/ETFs only) and has no forex coverage at all — those legs stay on yfinance
permanently, not as a stopgap.

## Key architectural decoupling: price poll vs. chain refresh

These must NOT be coupled the way `analyze_options_structure()` currently is inside
`fetch_loop` (called every single pass, alongside the price check). Instead:

- **Fast loop** (30s or 60s depending on mode): poll Schwab price only, compare
  against a **cached** expected-move threshold already computed from the chain.
  Does not touch the chain endpoint at all.
- **Slow refresh** (independent timer): pulls the chain, recomputes the expected-move
  % (ATM put premium / price), updates the cache the fast loop reads from.

This means the (more expensive to parse) chain endpoint runs a handful of times a
day per ticker, not on every poll.

## Mode design

"Active-trader mode" is NOT a different code path or a switch to streaming — it's
the same polling engine at a shorter interval (30s vs 60s) for a defined window
(first 30-45 minutes of the session), possibly paired with a tighter
`MIN_ABSOLUTE_TRIGGER_PCT` since that's when real moves happen. A mode flag adjusts
`time.sleep()` duration and threshold constants; no architectural fork.

## Why Schwab's chain response is more work to parse than yfinance's

yfinance hands back two flat pandas DataFrames (puts/calls) with columns already
named (`strike`, `lastPrice`, `bid`, `ask`, `openInterest`, `impliedVolatility`) —
`analyze_options_structure()` operates on them directly. Schwab's `/marketdata/v1/chains`
returns nested JSON: expiration → strike-price map → list of contract objects (a list
even when there's exactly one contract at that strike). A new parser
(`analyze_options_structure_schwab()` or similar) needs to walk that structure to
extract the same fields into the same shape the rest of the engine already expects.
Also: Schwab identifies option contracts via 21-character OSI symbols
(e.g. `AAPL  240419C00150000`), not yfinance's implicit strike/expiration columns —
a symbol-formatting helper is needed anywhere the two sources are cross-referenced
(e.g. converting a strike/expiration the user picked from a yfinance-sourced deep-dive
into the Schwab OSI symbol for the single-strike watch feature).

## Auth

Schwab requires OAuth2: access token ~30 min, refresh token ~7 days (hard cap,
resets on each successful refresh). Needs a `SchwabAuth` class mirroring the
existing `RateLimiter` pattern — proactively refreshes the access token in the
background (~every 25 min) whenever the engine is running. As long as the engine
touches the Schwab API at least once within any 7-day window (trivially satisfied
by normal active-trader-mode usage), the refresh token renews indefinitely and the
one-time interactive browser login is never needed again. If the engine is idle
for >7 consecutive days, the refresh token expires and the ~5-minute manual browser
re-login must be repeated once.

## Build list (in dependency order)

1. `SchwabAuth` — token lifecycle / background refresh loop
2. `fetch_schwab_quote()` — replaces yfinance price pull for equities/options in `fetch_loop`
3. `fetch_schwab_chain()` — nested-JSON chain parser; called from the slow refresh timer AND on-demand for deep-dive clicks
4. OSI option symbol formatter — strike/expiration/type → Schwab's 21-char symbol string
5. Mode flag threading through `fetch_loop` — adjusts poll interval and trigger threshold between situational-awareness and active-trader modes

## Open question (not yet decided)

Whether yfinance is dropped from the equities stack entirely once Schwab quotes +
chain are live, or kept as a fallback. Leaning toward full replacement for equities
(Schwab's own price-history endpoint covers ~15 years daily for equities/ETFs), but
not committed yet — revisit when implementation actually starts.
