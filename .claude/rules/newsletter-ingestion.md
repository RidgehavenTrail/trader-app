---
paths:
  - newsletter_ingest.py
  - watchtower_engine.py
  - watchtower.html
  - engine/newsletter.py
---
# Newsletter Ingestion — standing rules (thin)

Full design/build documentation lives in **`docs/newsletter-ingestion.md`** — a plain
doc, freely editable (no `.claude` config-guard prompt). This file holds ONLY the
load-bearing directives that must be in context when working on the newsletter code.

**Where ongoing work goes (updated 2026-07-13, feature SHIPPED):** `docs/newsletter-ingestion.md`
is now HISTORICAL — it's marked as such at its own top banner and should not receive
new build-log/fix-queue/handoff entries anymore. That guidance conflicted with the
line that used to be here ("put build-log material in docs/…, NOT here") — this is
the fix. Going forward: **session-by-session changes go in `SESSIONS.md`** (Repository
root, per `CONTEXT.md`'s "Session Documentation" section); **settled schema/behavior
changes go in the relevant standing rule file** (`newsletter-schema.md`,
`newsletter-schema-tightening.md`, `newsletter-tracker.md`, or this file) since those
auto-load by path already. `docs/newsletter-ingestion.md` stays as read-only history
for *why* something was built a certain way.

**Code layout — engine split, phase 1 (2026-07-13, commit `169a3eb`).** The newsletter
HTTP layer no longer lives in `watchtower_engine.py`. The newsletter-ingestion +
trade-quote routes (`list_pending_newsletters`, `import_newsletter`,
`get_newsletter_state`, `get_extracted_newsletter`, `get_trade_quote`) and their
helpers now live in **`engine/newsletter.py`** as a self-contained **Flask Blueprint**
(`bp = Blueprint('newsletter', __name__)`), registered by the engine with
`app.register_blueprint(newsletter_bp)`. It imports nothing from `watchtower_engine`
(so no circular import) — only stdlib, flask, yfinance, and `newsletter_ingest`. The
`NEWSLETTER_PDF_DIR`/`NEWSLETTER_EXTRACTED_DIR`/`NEWSLETTER_START_DATE` config moved
there too. **When editing newsletter endpoints, edit `engine/newsletter.py`, not the
engine.** **Phase 2 (2026-07-20): price-history extracted the same way** —
`/get_price_history/<ticker>` + `get_asset_class()` + the cache helpers/constants/lock
now live in **`engine/price_history.py`** (verbatim move; relative cache path kept, so
behavior is identical). **Phase 3 (2026-07-21): macro extracted** — `generate_macro_regime`, `macro_loop`,
and `/get_macro_regime` now live in **`engine/macro.py`**. First phase to move a
BACKGROUND THREAD, so that blueprint exports **`start_macro_loop()`** alongside `bp`
(same shape as stoplight's `start_scheduler`); the engine calls it from `__main__`.
`ET` + `market_state()` were promoted to **`engine/common.py`** because `fetch_loop`
needs them too — they could not live in the macro blueprint without recreating the
cycle. **Phase 4 (2026-07-22): market data + ticker management extracted** —
`/get_market_data`, `/add_ticker`, `/delete_ticker`, `/sync_tickers` now live in
**`engine/market.py`** (routes only, no thread). `TICKERS_FILE`/`DATA_FILE`/
`get_tickers()`/`save_tickers()` promoted to **`engine/common.py`** — `fetch_loop`
reads the ticker list and WRITES the market-data snapshot these routes serve.
`/get_actionable_moves` + `/dismiss_actionable` deliberately did NOT move: they ride
`actionable_file_lock`/`patch_actionable_move`, which `fetch_loop` uses constantly,
so they belong to the final phase. **Remaining: actionable/synthesis-core** (those two
routes + `fetch_loop` + the synthesis path) — the last and most entangled phase.
**Session 42 (2026-08-10/11) added THREE more blueprints/modules under `engine/`,** built new
rather than split out, so phase 5 is unaffected: **`engine/strategy.py`** (Rocket Strategy —
`GET /get_strategy_dial`, the Fed Dial B state + portfolios), **`engine/qqq_system.py`** (the QQQ
system's live state behind a CONTRACT dict; `_adapt_full_system()` is the only strategy-aware
function, and it imports the canonical backtests from `Documents/Macro Newsletters/backtests/`
— **RESOLVED session 43 (2026-08-12): `backtests/live/` is now its OWN git repo gated by
`_assert_blessed()`, and `strategy_config.py` joined it — the dial's series/thresholds, the
regime->allocation map, the warning rule, the profit target and the sleeve names all live
there and are read back through `engine/live_config.py`. They had to leave because `master`
is a PUBLIC remote; it was pushed clean the same day.**), and **`engine/news_archive.py`**
(`GET /get_news_archive/<ticker>`, reads `archive/*.json` + the live card, no new capture).
The per-ticker NEWS PATH in `watchtower_engine.py` was also overhauled (freshness cutoff,
materiality ranking, T+30/15:00 scheduling via `news_loop`) — that code is part of the
still-unsplit synthesis core, so phase 5 now has MORE to move, not less.

Frontend JS is likewise split into `static/js/*` (see `newsletter-tracker.md`).
Restart the `:5001` engine after any engine/blueprint code change (stale in-memory).

## Authoritative specs — read these
- **`.claude/rules/newsletter-schema-tightening.md`** — the CURRENT target; supersedes
  the ambiguous derived-field parts of `newsletter-schema.md`. Root principle: the model
  emits prose→primitives; **Python derives everything computable** (`structure`,
  `asset_class`, `strategy_id`, `bias`, `structure_label`, `pnl_pct`) and NEVER parses
  prose. Built + committed (`ef10326`).
- **`.claude/rules/newsletter-schema.md`** — target JSON shape + trade lifecycle state
  machine.
- **`.claude/rules/newsletter-tracker.md`** — schema→dashboard display mapping.

## Storage — Python owns accumulation, never the model
`_store.json` = `{live, archive, discarded}`. `live` = open/planned + standing
observation-only indicators (the ONLY set fed to the model next issue); `archive` = full
`closed` trades (the scoreboard source); `discarded` = lightweight abandoned/unresolved
stubs. **Atomic, last-step-only write** (temp + `os.replace`): the per-issue marker
file's existence is the "already imported" signal, so a failed/partial run must leave NO
file behind.

## Live-set model
The model is fed and returns ONLY the live working set + this issue's new/newly-terminal
trades — never the full history. Python accumulates. Keeps per-extract cost flat as the
store grows.

## Lifecycle (full detail in newsletter-schema.md)
- Silence abandons only `planned` trades (→ `abandoned` if the ticker is absent,
  `unresolved` if still discussed); silence NEVER closes an `open` trade.
- `open` vs `planned` is decided by ENTRY MECHANICS, not prose enthusiasm.
- **Determinism guard:** a `scaled` entry is FORCED to `planned` in Python (tranches
  normalized, `entry_date` nulled) until it has a closed tranche or realized P&L
  (`enforce_scaled_planned`, tightening spec §7.3a).

## Tooling (offline, $0; run from the main `Trader App` dir on master)
- `python stats.py` — cumulative billed-run ledger (`cost_experiment_log.jsonl`).
- `python compare_narratives.py <stem>` — narratives × effort across runs.
- `python q.py <substr>` — store inspector. Use this, NOT `python -c` (which prompts).
- `python run_import.py <stem> [--cold] [--effort=…]` — billed extraction (ASK the user
  first — `prompt-before-billed-runs` memory; auto-saves the raw_extract to `run_archive/`).

See **`docs/newsletter-ingestion.md`** for the build log, the card-fix queue (A/B/C/D/E +
C.2–C.8), the session handoffs, the endpoints, and the token/reasoning-cost investigation.
