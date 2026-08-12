---
paths:
  - "heatmap_3d.py"
  - "ridgeline.py"
  - "save_oi_snapshot.py"
  - "test_heatmap_3d*.py"
  - "oi_snapshot_*.json"
---

# 3D Options Heatmap — `heatmap_3d.py`

**STATUS: LOCKED.** Validated against AMD, MU, ARM, AVEX and others.
Do not modify without explicit instruction from the user.

## Isolation from the rest of the project

This subsystem is fully standalone. It does **not** read `tickers.json`,
`market_data.json`, `actionable_moves.json`, or `macro_regime.json`, and does not
interact with `market_data_engine.py` or `trader_dashboard.html` in any way — the
ticker is passed as a CLI argument and options data comes straight from yfinance.
**Do not open engine or dashboard files while working on heatmap code unless the
task explicitly requires it.**

## Running it

```powershell
python heatmap_3d.py AMD             # live data during market hours
python heatmap_3d.py AMD --snapshot  # from saved OI snapshot
python save_oi_snapshot.py AMD       # save snapshot before midnight rollover
```

Snapshot files: `oi_snapshot_TICKER_YYYY-MM-DD.json`. Auto-finds the most recent
snapshot for a ticker if no path is given. Use `--snapshot` any time yfinance
returns zero OI (common after-hours/weekends — `openInterest` updates overnight
after settlement; a flat terrain with `[OI] Total samples: 0` in console output
is a data-timing issue, not a code bug).

## Architecture — pipeline

1. `fetch_options_data()` — yfinance chain, filtered strikes ±30% price range
2. `compute_stem_heights()` — OI → world-Y (two-tier). Single source of truth.
   Returns stem list `[{dollars, dte, y}]` per side.
3. `compute_blanket()` — orchestrates ridgelines + terrain, returns grids for JS.
4. `compute_ridgeline()` — **LOCKED** (also saved standalone as `ridgeline.py`).
   Piecewise catenary envelope. Cable factor 1.2x uniform. All math in
   world-X/world-Y space.
5. `compute_terrain()` — Gaussian splat terrain beneath the ridgeline.
6. `render_html()` — bakes grids into HTML as JSON. JS builds PlaneGeometry mesh.

## Key constants

- `GRID_S = 100` — fixed strike grid columns
- `GRID_D = 50` — fixed DTE grid rows (0→90 days)
- `OI_FLOOR = 100` — stems below this not rendered
- `MAX_HEIGHT = 4.4` world units
- Cable factor: `1.2` uniform for all catenary segments (edge and internal)
- `SIGMA_CI_BASE = 3.0` — price-axis splat sigma (grid columns)
- `SIGMA_RI_BASE = 1.2` — DTE-axis splat sigma for non-buried stems
- `SIGMA_RI_MAX = 5.0` — DTE-axis splat sigma for fully buried stems

## Ridgeline (`compute_ridgeline` / `ridgeline.py`) — LOCKED

Piecewise catenary envelope. **Do not modify.** Saved independently as `ridgeline.py`
so it can be imported unchanged.

- All math in world-X/world-Y space (both ±10 units) — critical for correct scaling
- Edge anchors at Y=0 (floor). Top-2 stems by world-Y as initial poles.
- Iterative violation loop inserts stems as poles until all stems are met exactly.
- Returns GRID_S heights — the inviolable ceiling the terrain must rise to meet.

## Terrain (`compute_terrain`)

1. **Ceiling grid** — ridgeline interpolated across all GRID_D rows in compressed
   DTE space.
2. **Gaussian splat** — each stem radiates `stem_y * w_ri * w_ci` to nearby cells
   using `max()` accumulation. Buried stems get wider DTE sigma.
3. **Terrain floor** (`compute_terrain_floor`) — lifts valleys between expirations.
   Applied as `max()` nudge before the ceiling clamp.
4. **Effective ceiling clamp** — `max(ceiling, terrain_floor)` so the floor is
   never cut by interpolated ceiling values between two tall expirations.
5. **Pin** — terrain pinned to ridgeline at each expiration's home row using
   `max()` — only ever raises, never lowers.

### `compute_terrain_floor` algorithm

For each price column, walks adjacent expiration pairs along the DTE axis:
- Higher of the two ridgeline Y values: kept exactly (peak preserved)
- Lower of the two ridgeline Y values: replaced by `(y_hi + y_lo) / factor`
- `max()` accumulation so a low point adjacent to two tall peaks gets the higher lift
- `FLOOR_FACTOR = 2.0` (tunable) — lower = more aggressive valley lifting

## Bugs already fixed — do not "fix" these again

1. **Ceiling clamp cutting the floor** — interpolated ceiling between two tall
   expirations undershot the floor value. Fixed: effective ceiling =
   `max(interpolated_ceiling, terrain_floor)`.
2. **Pin destroying floor lift** — pin step hard-assigned
   `terrain[home_ri][ci] = ridges[dte][ci]`, overwriting the floor lift at
   low-ridgeline rows. Fixed: `max(terrain[home_ri][ci], ridges[dte][ci])`.

## Known open issues / priorities for next session

1. **Snow cap vertex bleed** — white peak color interpolates down steep face
   triangles (`MeshLambertMaterial` vertex-color interpolation). Tightened to
   `snowStart = MAX_HEIGHT * 1.7` (top 15%), reduced but not eliminated at steep
   price edges. Real fix: replace with `ShaderMaterial` for per-fragment color
   from world-Y (vertex shader passes Y, fragment shader computes gradient
   per-pixel — no interpolation). Requires ~20-30 lines of GLSL diffuse lighting.
   Medium complexity, high visual impact — treat as its own dedicated session.
2. **Test against other stocks** — validate with different price ranges, strike
   densities, OI distributions once market opens. `python save_oi_snapshot.py TICKER`
   before midnight to preserve data; `--snapshot` to render from it.
3. **Price axis label overlap** near dense strike clusters — consider minimum
   pixel-distance deduplication in JS.

## Validated design decisions — do not revisit without explicit instruction

- `compute_ridgeline` is locked — import from `ridgeline.py`, never modify inline
- Cable factor 1.2× uniform — chosen after testing 2.0×, 1.5×/1.2×, 1.2×/1.2×
- Price normalized to world-X before catenary solve — critical for correct scaling
- Edge anchors Y=0 (floor) — Gaussian edge anchors caused false peaks
- `max()` accumulation for splat, never averaging — averaging collapses signal to ~0.18
- Pin uses `max()`, not hard assignment — hard assignment destroys terrain floor lift
- Effective ceiling = `max(interpolated_ceiling, terrain_floor)` — prevents floor being cut
- **Resolved:** put-side OI sparsity (previously flagged as possibly needing a
  separate Gaussian sigma per side) is no longer an issue — `compute_terrain_floor()`'s
  valley-lift plus the ridgeline ceiling guarantee fill sparse regions
  architecturally, so calls and puts keep sharing `SIGMA_CI_BASE`/`SIGMA_RI_BASE`/
  `SIGMA_RI_MAX`. Do not revisit unless a specific ticker shows a real visual gap.
- Stems disabled (`SHOW_STEMS = false`) — too visually busy, kept for debugging only
- DTE labels: depth-tested sprites — CSS2D has no depth awareness, bleeds through terrain
- Price labels: CSS2D — always visible, intentional for price-axis orientation
- Price contour lines: slate white `0xf1f5f9`, opacity 0.45
- Ridge lines: cyan `0x5eead4`, opacity 0.85 — kept on, they show ground truth
- Current price line: amber `0xf59e0b`, opacity 0.9
- Snow cap threshold: `MAX_HEIGHT * 1.7`
- Strike labels snapped to actual strikes in `DATA.strikes` — no interpolated prices
- Dynamic contour step: `priceRange / 13`, rounded up to nearest nice number
- Price label font: slate white `rgba(241,245,249,0.95)` matching contour line color
- DTE label font: slate white `rgba(241,245,249,0.95)` — different rendering (sprite vs
  CSS2D) but same color intent

## Coordinate system

- X axis: price (dollars), mapped via `priceToX()` to ±`TERRAIN_HALF_W`
- Z axis: DTE (days), compressed scale to ±`TERRAIN_DEPTH`. Calls: +Z, Puts: -Z.
  Compressed: 0–14 DTE = 42%, 14–42 DTE = 33%, 42–90 DTE = 25% of depth.
- Y axis: world height (two-tier scale, 0 → `MAX_HEIGHT * 2`)

## Workflow when iterating on this code

1. **Snapshot first** — copy the target file to the repository mirror before any
   edit (rollback point):
   `C:\Users\pguth\OneDrive\Desktop\Claude Repository\Stock Dashboard - Culling Engine\`
2. Edit in the live Trader App directory
3. Run via `python heatmap_3d.py TICKER`
4. Screenshot the rendered output to verify visually rather than assuming
5. Diagnose from screenshot + console output, not from a description alone

For anything not covered here — architectural history, why v1 (`test_heatmap_3d.py`
/ `_v1.py`) was superseded, or broader project state — see `CONTEXT.md` in the
repository, which is the authoritative fast-load session brief for this project.
