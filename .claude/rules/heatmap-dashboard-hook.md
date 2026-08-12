---
paths:
  - "watchtower.html"
  - "heatmap_3d.py"
  - "save_oi_snapshot.py"
---
<!-- 2026-07-13: removed retired trader_dashboard.html entry (retired 2026-07-12). -->


# Heatmap Dashboard Hook — Options Data Quadrant (decided 2026-07-05, documented late)

**Status:** Design intent only. Not built. This decision was made verbally in an
earlier session and never written down — caught 2026-07-05 when the user
referenced it mid-conversation and it didn't match anything in this file or
`heatmap-3d.md`. Writing it down now so it doesn't drift further.

## What this is

The "Options Data" quadrant (upper-right box in both the ticker deep-dive
`dd-pane-narrative` and the newsletter thesis deep-dive `nd-pane-narrative` in
`watchtower.html` — ATM Strike/Put Premium/Expiration/IV/Put Wall/Call Wall) was
deliberately positioned there as the **future launch point for the 3D options
heatmap** (`heatmap_3d.py`). This is the reason for its placement — it was not
an arbitrary layout choice.

## Settled scope (confirmed 2026-07-05)

- **Placeholder only for now.** No actual click-through/launch behavior exists
  or should be built yet — just a visual affordance in the quadrant indicating
  a heatmap view is coming, gated the same way the Options tab already is.
- **Equity/ETF only** — matches the existing `asset_class === 'equity'` gating
  already used for the Options tab (`setOptionsDataVisibility()` /
  `setTabsForAssetClass()`). `heatmap_3d.py` needs a real yfinance options
  chain; futures/forex/pairs have none.
- **Data source, once built: a daily-updated snapshot, not live.** Matches the
  existing `oi_snapshot_TICKER_YYYY-MM-DD.json` / `--snapshot` pattern already
  built for `heatmap_3d.py` and `save_oi_snapshot.py` — not a live yfinance
  pull triggered per dashboard click.

## Explicitly NOT decided yet (do not build ahead of this)

- Launch mechanism (new tab vs. inline iframe vs. something else)
- Whether the daily snapshot job is scheduled automatically or still manual
  (`save_oi_snapshot.py` today is run by hand before midnight)
- Whether this uses the existing `heatmap_3d.py` output as-is or needs a
  lighter-weight embeddable variant

## Critical constraint — does not touch locked heatmap code

`heatmap_3d.py` is **LOCKED** (see `heatmap-3d.md`) and is explicitly documented
as not interacting with `market_data_engine.py` or either dashboard HTML file
"in any way." That isolation is about the heatmap script itself not reading
engine data files — it is a separate concern from the dashboard eventually
*launching* it (e.g. shelling out to `python heatmap_3d.py TICKER --snapshot`,
or navigating to its rendered HTML output). When this is actually built, do
not modify `heatmap_3d.py`, `ridgeline.py`, or the terrain/ridgeline algorithm
to accommodate the hook — the hook is a dashboard-side launch mechanism only.
