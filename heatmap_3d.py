"""
Options open interest 3D blanket model — ridge-line approach.
Pipeline:
  1. fetch_options_data()   -- yfinance chain data
  2. compute_stem_heights() -- OI -> world-Y (two-tier). Single source of truth.
  3. compute_blanket()      -- For each expiration, compute a softmax-weighted
                               ridge line across the price axis (tallest stems
                               dominate). Interpolate between ridges on the DTE
                               axis. Blanket guaranteed >= every stem.
  4. render_html()          -- JS reads pre-baked grids, builds fixed-res mesh.

Tunable constants in compute_blanket():
  SIGMA_DOLLARS -- Gaussian proximity radius for ridge (dollars)
  TEMPERATURE   -- softmax temperature (world-Y units); lower = peaks dominate more

Usage:
    python heatmap_3d.py AMD
    python heatmap_3d.py AAPL
"""

import sys
import json
import math
import webbrowser
import tempfile
from datetime import datetime, date

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# -- Grid resolution (fixed regardless of data density) -----------------------
GRID_S   = 100   # strike axis points (columns)
GRID_D   = 50    # DTE axis points (rows, 0..90 days)
OI_FLOOR = 100   # OI below this: stem not drawn, does not prop blanket
# -----------------------------------------------------------------------------


def load_from_snapshot(path):
    """Load options data from a saved OI snapshot JSON file."""
    with open(path) as f:
        snap = json.load(f)

    ticker        = snap['ticker']
    current_price = snap['current_price']
    print(f"[SNAP] Loading {ticker} from snapshot: {snap['snapshot_date']} @ ${current_price:.2f}")

    today = date.today()
    valid_exps = []
    all_strikes = set()
    chain_data  = {}

    for exp, chain in snap['chain'].items():
        exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
        dte = (exp_date - today).days
        if 0 <= dte <= 90:
            valid_exps.append((dte, exp))
            for s, d in chain['puts'].items():
                all_strikes.add(s)
            for s, d in chain['calls'].items():
                all_strikes.add(s)
            chain_data[dte] = {
                'puts':  {s: d['oi'] for s, d in chain['puts'].items()},
                'calls': {s: d['oi'] for s, d in chain['calls'].items()},
            }
            print(f"[SNAP] {exp} ({dte} DTE): {len(chain['puts'])} puts, {len(chain['calls'])} calls")

    if not valid_exps:
        print("No expirations within 90 days in snapshot."); sys.exit(1)

    sorted_strikes = sorted(all_strikes, key=lambda s: float(s))
    lower, upper   = current_price * 0.70, current_price * 1.30

    def max_oi(strike):
        best = 0
        for data in chain_data.values():
            best = max(best, data['calls'].get(strike, 0), data['puts'].get(strike, 0))
        return best

    filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= 100]
    for fallback in [50, 10, 1]:
        if len(filtered) >= 20: break
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= fallback]

    print(f"[FILTER] {len(filtered)} strikes (${float(filtered[0]):.0f}–${float(filtered[-1]):.0f})")

    # Peak OI summary
    max_call_oi, max_call_strike, max_call_dte = 0, None, None
    max_put_oi,  max_put_strike,  max_put_dte  = 0, None, None
    for dte, data in chain_data.items():
        for s in filtered:
            if data['calls'].get(s, 0) > max_call_oi:
                max_call_oi, max_call_strike, max_call_dte = data['calls'][s], s, dte
            if data['puts'].get(s, 0) > max_put_oi:
                max_put_oi, max_put_strike, max_put_dte = data['puts'][s], s, dte

    return {
        'ticker':        ticker,
        'current_price': current_price,
        'strikes':       filtered,
        'expirations':   sorted([dte for dte, _ in valid_exps]),
        'chain':         {str(dte): data for dte, data in chain_data.items()},
        'peak_call':     {'strike': max_call_strike, 'dte': max_call_dte, 'oi': max_call_oi},
        'peak_put':      {'strike': max_put_strike,  'dte': max_put_dte,  'oi': max_put_oi},
        'exp_count':     len(valid_exps),
    }


def fetch_options_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    try:
        hist = stock.history(period="2d")
        if hist.empty:
            print(f"No price history for {ticker_symbol}"); sys.exit(1)
        current_price = float(hist['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching price: {e}"); sys.exit(1)

    print(f"[DATA] {ticker_symbol} current price: ${current_price:,.2f}")

    expirations = stock.options
    if not expirations:
        print(f"No options data for {ticker_symbol}"); sys.exit(1)

    today = date.today()
    valid_exps = []
    for exp in expirations:
        exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
        dte = (exp_date - today).days
        if 0 <= dte <= 90:
            valid_exps.append((dte, exp))

    if not valid_exps:
        print("No expirations within 90 days."); sys.exit(1)

    print(f"[DATA] Found {len(valid_exps)} expirations: {[f'{d}d' for d, _ in valid_exps]}")

    all_strikes = set()
    chain_data  = {}

    for dte, exp in valid_exps:
        try:
            chain = stock.option_chain(exp)
            puts  = chain.puts[['strike', 'openInterest']].copy()
            calls = chain.calls[['strike', 'openInterest']].copy()
            for strike in puts['strike'].values:
                all_strikes.add(str(float(strike)))
            for strike in calls['strike'].values:
                all_strikes.add(str(float(strike)))
            chain_data[dte] = {
                'puts':  {str(float(s)): int(o) for s, o
                          in zip(puts['strike'].values, puts['openInterest'].values)},
                'calls': {str(float(s)): int(o) for s, o
                          in zip(calls['strike'].values, calls['openInterest'].values)},
            }
            print(f"[DATA] {exp} ({dte} DTE): {len(puts)} put, {len(calls)} call strikes")
        except Exception as e:
            print(f"[WARN] Could not fetch {exp}: {e}")

    sorted_strikes = sorted(all_strikes, key=lambda s: float(s))
    lower, upper = current_price * 0.70, current_price * 1.30

    def max_oi(strike):
        best = 0
        for d in chain_data.values():
            best = max(best, d['calls'].get(strike, 0), d['puts'].get(strike, 0))
        return best

    filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= OI_FLOOR]
    for fallback in [50, 10, 1]:
        if len(filtered) >= 20: break
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= fallback]
    if len(filtered) < 10:
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper]

    if filtered:
        print(f"[FILTER] {len(filtered)} strikes (${float(filtered[0]):.0f}-${float(filtered[-1]):.0f})")

    max_call_oi, max_call_strike, max_call_dte = 0, None, None
    max_put_oi,  max_put_strike,  max_put_dte  = 0, None, None
    for dte, side_data in chain_data.items():
        for s in filtered:
            c_oi = side_data['calls'].get(s, 0)
            p_oi = side_data['puts'].get(s, 0)
            if c_oi > max_call_oi: max_call_oi, max_call_strike, max_call_dte = c_oi, s, dte
            if p_oi > max_put_oi:  max_put_oi,  max_put_strike,  max_put_dte  = p_oi, s, dte

    return {
        'ticker':        ticker_symbol,
        'current_price': current_price,
        'strikes':       filtered,
        'expirations':   sorted([dte for dte, _ in valid_exps]),
        'chain':         {str(dte): data for dte, data in chain_data.items()},
        'peak_call':     {'strike': max_call_strike, 'dte': max_call_dte, 'oi': max_call_oi},
        'peak_put':      {'strike': max_put_strike,  'dte': max_put_dte,  'oi': max_put_oi},
        'exp_count':     len(valid_exps),
    }


def dte_to_depth_frac(dte):
    """Compressed DTE scale -- matches JS dteToDepthFrac() exactly."""
    if dte <= 14: return (dte / 14) * 0.42
    if dte <= 42: return 0.42 + ((dte - 14) / 28) * 0.33
    return min(1.0, 0.75 + ((dte - 42) / 48) * 0.25)


def compute_stem_heights(data):
    """
    OI -> world-Y (two-tier) for every (DTE, strike, side).
    Returns stem lists with physical positions (dollars, dte) and world-Y.
    Single source of truth -- blanket reads these Y values directly.
    """
    strikes = data['strikes']
    exps    = data['expirations']
    chain   = data['chain']

    all_oi = []
    for dte in exps:
        d = chain.get(str(dte), {})
        for s in strikes:
            c = (d.get('calls', {}).get(s, 0) or 0) - OI_FLOOR
            p = (d.get('puts',  {}).get(s, 0) or 0) - OI_FLOOR
            if c > 0: all_oi.append(c)
            if p > 0: all_oi.append(p)

    all_oi.sort()
    p95       = all_oi[int(len(all_oi) * 0.95)] if all_oi else 1
    max_oi_2x = p95 * 2
    MAX_H     = 10 * 2 * 0.22  # 4.4 world units -- matches JS MAX_HEIGHT

    def oi_to_y(oi):
        adj = oi - OI_FLOOR
        if adj <= 0: return 0.0
        if adj <= p95:
            return (adj / p95) * MAX_H
        t = min((adj - p95) / max(max_oi_2x - p95, 1), 1.0)
        return MAX_H + t * MAX_H

    print(f"[STEMS] p95={p95}  tier2_cap={max_oi_2x}  MAX_H={MAX_H:.2f}")

    stems_call, stems_put = [], []
    for dte in exps:
        d = chain.get(str(dte), {})
        for s in strikes:
            c_y = oi_to_y(d.get('calls', {}).get(s, 0) or 0)
            p_y = oi_to_y(d.get('puts',  {}).get(s, 0) or 0)
            if c_y > 0: stems_call.append({'dollars': float(s), 'dte': dte, 'y': c_y})
            if p_y > 0: stems_put.append( {'dollars': float(s), 'dte': dte, 'y': p_y})

    print(f"[STEMS] {len(stems_call)} call stems, {len(stems_put)} put stems above floor")
    return stems_call, stems_put, p95


def _catenary_y(x, a, x0, c):
    """Evaluate catenary: y = a * cosh((x - x0) / a) + c"""
    return a * math.cosh((x - x0) / a) + c


def _solve_catenary(x1, y1, x2, y2, cable_length):
    """
    Given two endpoints (x1,y1),(x2,y2) and a cable length,
    solve for catenary parameters (a, x0, c) via bisection.
    Returns (a, x0, c) or None if no solution found.
    Falls back to linear interpolation at call site on None.
    """
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-9:
        return None

    min_len = math.sqrt(dx*dx + dy*dy)
    if cable_length <= min_len:
        cable_length = min_len * 1.001

    def arc_length_for_a(a):
        if a <= 0:
            return float('inf')
        dxa = dx / a
        # Bisect on u1 to satisfy the dy constraint:
        #   a*(cosh(u1+dxa) - cosh(u1)) = dy
        def dy_res(u1):
            u2 = u1 + dxa
            try:
                return a * (math.cosh(u2) - math.cosh(u1)) - dy
            except OverflowError:
                return float('inf')
        lo, hi = -10.0, 10.0
        flo, fhi = dy_res(lo), dy_res(hi)
        if flo * fhi > 0:
            return float('inf')
        for _ in range(60):
            mid = (lo + hi) / 2
            fm = dy_res(mid)
            if abs(fm) < 1e-10:
                break
            if flo * fm <= 0:
                hi, fhi = mid, fm
            else:
                lo, flo = mid, fm
        u1 = (lo + hi) / 2
        u2 = u1 + dxa
        x0 = x1 - a * u1
        c  = y1 - a * math.cosh(u1)
        try:
            arc = a * (math.sinh(u2) - math.sinh(u1))
        except OverflowError:
            return float('inf')
        return arc, x0, c

    def get_arc(a):
        r = arc_length_for_a(a)
        return r if isinstance(r, float) else r[0]

    a_lo, a_hi = 1e-6, max(abs(dx), abs(dy), 1.0) * 1000
    arc_lo, arc_hi = get_arc(a_lo), get_arc(a_hi)
    if arc_lo < cable_length or arc_hi > cable_length:
        return None

    for _ in range(80):
        a_mid = (a_lo + a_hi) / 2
        arc_mid = get_arc(a_mid)
        if isinstance(arc_mid, float) and math.isinf(arc_mid):
            a_lo = a_mid; continue
        if abs(arc_mid - cable_length) < 1e-8:
            break
        if arc_mid > cable_length:
            a_lo = a_mid
        else:
            a_hi = a_mid

    a = (a_lo + a_hi) / 2
    r = arc_length_for_a(a)
    if isinstance(r, float):
        return None
    _, x0, c = r
    return (a, x0, c)


def _eval_segment(x_points, x1, y1, x2, y2, cable_len):
    """Evaluate catenary segment at x_points; linear fallback on solve failure.
    Clamps output to <= max(y1, y2): the blanket only drapes downward between
    poles, never arches above them (a catenary can solve either way but we want
    the hanging-cable shape, not an arch)."""
    params = _solve_catenary(x1, y1, x2, y2, cable_len)
    ceiling = max(y1, y2)
    out = []
    for x in x_points:
        if params is None:
            t = (x - x1) / (x2 - x1) if abs(x2 - x1) > 1e-9 else 0.0
            out.append(max(0.0, y1 + (y2 - y1) * max(0.0, min(1.0, t))))
        else:
            a, x0, c = params
            out.append(max(0.0, min(ceiling, _catenary_y(x, a, x0, c))))
    return out


def compute_ridgeline_dte(stems_at_price, grid_dtes):
    """
    Compute the DTE-axis ridgeline for a single price column.

    Same linear pole-insertion algorithm as compute_ridgeline_linear but
    operating across the DTE axis instead of the price axis.

    stems_at_price : list of {'dte': int, 'y': float} — all stems at one strike,
                     across all expirations.
    grid_dtes      : list of GRID_D DTE values (0..90).

    Returns list of GRID_D floats — the ridgeline height at each DTE row
    for this price column.
    """
    if not stems_at_price:
        return [0.0] * GRID_D

    dte_min  = grid_dtes[0]
    dte_max  = grid_dtes[-1]
    dte_span = dte_max - dte_min

    def dte_to_frac(d):
        return (d - dte_min) / dte_span if dte_span > 1e-9 else 0.0

    def frac_to_ri(f):
        return max(0, min(GRID_D - 1, round(f * (GRID_D - 1))))

    # Initial poles: top-2 stems by world-Y + zero-height edge anchors
    top2 = sorted(stems_at_price, key=lambda s: s['y'], reverse=True)[:2]
    top2.sort(key=lambda s: s['dte'])
    poles = ([(dte_min, 0.0)] +
             [(s['dte'], s['y']) for s in top2] +
             [(dte_max, 0.0)])
    deduped = {}
    for d, y in poles:
        deduped[d] = max(deduped.get(d, 0.0), y)
    poles = sorted(deduped.items())

    def eval_envelope(poles_list):
        ridge = [0.0] * GRID_D
        for si in range(len(poles_list) - 1):
            d1, py1 = poles_list[si]
            d2, py2 = poles_list[si + 1]
            for ri, gd in enumerate(grid_dtes):
                if d1 <= gd <= d2:
                    t = (gd - d1) / (d2 - d1) if (d2 - d1) > 1e-9 else 0.0
                    ridge[ri] = max(ridge[ri], py1 + (py2 - py1) * t)
        for pd, py in poles_list:
            ri = frac_to_ri(dte_to_frac(pd))
            ridge[ri] = max(ridge[ri], py)
        return ridge

    MAX_POLES = 30
    ridge = [0.0] * GRID_D
    for _iter in range(MAX_POLES):
        ridge = eval_envelope(poles)
        worst, worst_excess = None, 0.0
        for stem in stems_at_price:
            ri     = frac_to_ri(dte_to_frac(stem['dte']))
            excess = stem['y'] - ridge[ri]
            if excess > worst_excess:
                worst_excess = excess
                worst = stem
        if worst is None or worst_excess < 1e-6:
            break
        existing = {d for d, _ in poles}
        if worst['dte'] in existing:
            break
        poles = sorted(poles + [(worst['dte'], worst['y'])])

    return ridge


def compute_ridgeline_linear(stems_at_dte, grid_prices):
    """
    Compute the ridgeline using piecewise LINEAR segments instead of catenaries.

    Same iterative pole-insertion algorithm as compute_ridgeline:
      Pass 1:  Top-2 stems by world-Y become initial poles. Left/right edges
               anchored at Y=0. Three linear segments connect them.
      Pass 2+: Find tallest stem violating the envelope. Insert as new pole,
               splitting the spanning segment into two new linear segments.
               Repeat until no violations remain (max 30 poles).

    All price coordinates normalized to world-X space for consistent scaling,
    though for linear interpolation this only affects distance calculations
    (which aren't used here — linear segments are purely geometric).

    Returns list of GRID_S floats — the ridgeline heights.
    """
    if not stems_at_dte:
        return [0.0] * GRID_S

    price_min  = grid_prices[0]
    price_max  = grid_prices[-1]
    price_span = price_max - price_min

    def price_to_frac(p):
        return (p - price_min) / price_span if price_span > 1e-9 else 0.0

    def frac_to_ci(f):
        return max(0, min(GRID_S - 1, round(f * (GRID_S - 1))))

    # Initial poles: top-2 by world-Y + zero-height edge anchors
    top2 = sorted(stems_at_dte, key=lambda s: s['y'], reverse=True)[:2]
    top2.sort(key=lambda s: s['dollars'])
    poles = ([(price_min, 0.0)] +
             [(s['dollars'], s['y']) for s in top2] +
             [(price_max, 0.0)])
    deduped = {}
    for p, y in poles:
        deduped[p] = max(deduped.get(p, 0.0), y)
    poles = sorted(deduped.items())

    def eval_envelope(poles_list):
        ridge = [0.0] * GRID_S
        for si in range(len(poles_list) - 1):
            p1, py1 = poles_list[si]
            p2, py2 = poles_list[si + 1]
            for ci, gp in enumerate(grid_prices):
                if p1 <= gp <= p2:
                    t = (gp - p1) / (p2 - p1) if (p2 - p1) > 1e-9 else 0.0
                    ridge[ci] = max(ridge[ci], py1 + (py2 - py1) * t)
        # Pin poles exactly
        for px, py in poles_list:
            ci = frac_to_ci(price_to_frac(px))
            ridge[ci] = max(ridge[ci], py)
        return ridge

    # Iterative violation loop — identical to catenary version
    MAX_POLES = 30
    ridge = [0.0] * GRID_S
    for _iter in range(MAX_POLES):
        ridge = eval_envelope(poles)
        worst, worst_excess = None, 0.0
        for stem in stems_at_dte:
            ci     = frac_to_ci(price_to_frac(stem['dollars']))
            excess = stem['y'] - ridge[ci]
            if excess > worst_excess:
                worst_excess = excess
                worst = stem
        if worst is None or worst_excess < 1e-6:
            break
        existing = {p for p, _ in poles}
        if worst['dollars'] in existing:
            break
        poles = sorted(poles + [(worst['dollars'], worst['y'])])

    return ridge


def compute_ridgeline(stems_at_dte, grid_prices):
    """
    Compute the ridgeline — a 1D array of GRID_S world-Y heights for one
    expiration. This is the fixed ceiling the terrain must rise up to meet.

    All math in world-X/world-Y space (both ±10 range) so axes are scaled.
    Returns list of GRID_S floats, one height per grid price column.
    """
    if not stems_at_dte:
        return [0.0] * GRID_S

    price_min  = grid_prices[0]
    price_max  = grid_prices[-1]
    price_span = price_max - price_min
    TERRAIN_HALF_W = 10.0

    def price_to_wx(p):
        frac = (p - price_min) / price_span if price_span > 1e-9 else 0.0
        return -TERRAIN_HALF_W + frac * TERRAIN_HALF_W * 2

    def price_to_frac(p):
        return (p - price_min) / price_span if price_span > 1e-9 else 0.0

    def frac_to_ci(f):
        return max(0, min(GRID_S - 1, round(f * (GRID_S - 1))))

    # Top-2 stems by world-Y become the initial poles, sorted by price.
    # Left and right edges are anchored at zero (floor).
    top2 = sorted(stems_at_dte, key=lambda s: s['y'], reverse=True)[:2]
    top2.sort(key=lambda s: s['dollars'])
    poles = ([(price_min, 0.0)] +
             [(s['dollars'], s['y']) for s in top2] +
             [(price_max, 0.0)])
    deduped = {}
    for p, y in poles:
        deduped[p] = max(deduped.get(p, 0.0), y)
    poles = sorted(deduped.items())

    def eval_envelope(poles_list):
        ridge = [0.0] * GRID_S
        n = len(poles_list)
        for si in range(n - 1):
            p1, py1 = poles_list[si]
            p2, py2 = poles_list[si + 1]
            wx1, wx2 = price_to_wx(p1), price_to_wx(p2)
            dist = math.sqrt((wx2 - wx1)**2 + (py2 - py1)**2)
            clen = dist * 1.2
            seg_wxs, seg_is = [], []
            for ci, gp in enumerate(grid_prices):
                if p1 <= gp <= p2:
                    seg_wxs.append(price_to_wx(gp))
                    seg_is.append(ci)
            if not seg_wxs:
                continue
            seg_ys = _eval_segment(seg_wxs, wx1, py1, wx2, py2, clen)
            for ci, y in zip(seg_is, seg_ys):
                ridge[ci] = max(ridge[ci], y)
        for px, py in poles_list:
            ci = frac_to_ci(price_to_frac(px))
            ridge[ci] = max(ridge[ci], py)
        return ridge

    # Iteratively insert violating stems as poles until all stems are met.
    MAX_POLES = 30
    ridge = [0.0] * GRID_S
    for _iter in range(MAX_POLES):
        ridge = eval_envelope(poles)
        worst, worst_excess = None, 0.0
        for stem in stems_at_dte:
            ci     = frac_to_ci(price_to_frac(stem['dollars']))
            excess = stem['y'] - ridge[ci]
            if excess > worst_excess:
                worst_excess = excess; worst = stem
        if worst is None or worst_excess < 1e-6:
            break
        existing = {p for p, _ in poles}
        if worst['dollars'] in existing:
            break
        poles = sorted(poles + [(worst['dollars'], worst['y'])])

    return ridge


def compute_terrain_floor(ridges, sorted_exps, grid_prices, grid_dtes,
                          factor=2.0):
    """
    Compute a soft terrain floor grid (GRID_D x GRID_S) by lifting valleys
    between adjacent expirations along each strike column.

    For each price column and each adjacent pair of expirations:
      - The higher ridgeline Y value is kept exactly (peak preserved)
      - The lower ridgeline Y value is replaced by (y_hi + y_lo) / factor
        (valley lifted toward the average — factor is tunable)

    All interpolation between adjusted endpoints is done in world-Z space
    (depth-fraction × TERRAIN_DEPTH) so the floor respects the compressed
    DTE scale used in the renderer.

    This is a SOFT constraint — the terrain should be nudged toward this
    floor but is not required to meet it (unlike the ridgeline which is hard).

    Parameters
    ----------
    ridges      : dict {dte: [GRID_S heights]}
    sorted_exps : list of DTE ints, ascending
    grid_prices : list of GRID_S dollar prices
    grid_dtes   : list of GRID_D raw DTE values (0..90)
    factor      : float — divisor for valley lifting (default 2.0 = average)

    Returns
    -------
    GRID_D x GRID_S float grid — terrain floor heights
    """
    floor_grid = [[0.0] * GRID_S for _ in range(GRID_D)]

    # Pre-compute world-Z for each expiration (calls side: positive Z)
    # We work in depth-fraction space (0→1) which is proportional to world-Z.
    # Actual world-Z = frac * TERRAIN_DEPTH but since we only need ratios
    # for interpolation, depth-fraction is sufficient and side-agnostic.
    exp_fracs = [dte_to_depth_frac(e) for e in sorted_exps]

    # Pre-compute grid row depth-fracs for fast lookup
    grid_fracs = [dte_to_depth_frac(g) for g in grid_dtes]

    for ci in range(GRID_S):
        # Ridgeline Y values at each expiration for this price column
        ridge_ys = [ridges[dte][ci] for dte in sorted_exps]

        # Walk adjacent pairs, compute adjusted Y values
        # adjusted_ys[i] is the floor-adjusted value at sorted_exps[i]
        adjusted_ys = list(ridge_ys)  # start as copy of ridgeline

        for i in range(len(sorted_exps) - 1):
            y0 = ridge_ys[i]
            y1 = ridge_ys[i + 1]
            y_hi = max(y0, y1)
            y_lo = min(y0, y1)
            lifted = (y_hi + y_lo) / factor

            # Only lift — never lower. Apply to whichever endpoint is lower.
            if y0 <= y1:
                adjusted_ys[i] = max(adjusted_ys[i], lifted)
            else:
                adjusted_ys[i + 1] = max(adjusted_ys[i + 1], lifted)

        # Interpolate adjusted_ys onto the full grid in world-Z (depth-frac) space
        for ri, gf in enumerate(grid_fracs):
            if gf <= exp_fracs[0]:
                floor_grid[ri][ci] = adjusted_ys[0]
            elif gf >= exp_fracs[-1]:
                floor_grid[ri][ci] = adjusted_ys[-1]
            else:
                for ei in range(len(sorted_exps) - 1):
                    f0, f1 = exp_fracs[ei], exp_fracs[ei + 1]
                    if f0 <= gf <= f1:
                        t = (gf - f0) / (f1 - f0) if f1 > f0 else 0.0
                        floor_grid[ri][ci] = (adjusted_ys[ei] +
                                              (adjusted_ys[ei + 1] - adjusted_ys[ei]) * t)
                        break

    return floor_grid


def compute_terrain(stems_at_dte_side, ridges, sorted_exps, grid_prices, grid_dtes):
    """
    Build a GRID_D x GRID_S terrain grid for one side (calls or puts).

    Each stem radiates a Gaussian splat in both price (CI) and DTE (RI) axes.
    Buried stems spread wider in DTE — the more buried, the wider the base.
    Final grid is clamped to [0, ridgeline ceiling] at every point.

    Uses max-accumulation (not averaging) so peaks stay at full height.
    """
    price_min  = grid_prices[0]
    price_max  = grid_prices[-1]
    price_span = price_max - price_min

    def price_to_frac(p):
        return (p - price_min) / price_span if price_span > 1e-9 else 0.0

    def frac_to_ci(f):
        return max(0, min(GRID_S - 1, round(f * (GRID_S - 1))))

    sorted_fracs = [dte_to_depth_frac(e) for e in sorted_exps]

    # --- Step 1: interpolate ridgeline ceiling across the full grid ---
    ceiling = [[0.0] * GRID_S for _ in range(GRID_D)]
    for ri, g_dte in enumerate(grid_dtes):
        gf = dte_to_depth_frac(g_dte)
        if gf <= sorted_fracs[0]:
            ceiling[ri] = list(ridges[sorted_exps[0]])
        elif gf >= sorted_fracs[-1]:
            ceiling[ri] = list(ridges[sorted_exps[-1]])
        else:
            for ei in range(len(sorted_exps) - 1):
                f0, f1 = sorted_fracs[ei], sorted_fracs[ei + 1]
                if f0 <= gf <= f1:
                    t  = (gf - f0) / (f1 - f0) if f1 > f0 else 0.0
                    ra = ridges[sorted_exps[ei]]
                    rb = ridges[sorted_exps[ei + 1]]
                    ceiling[ri] = [ra[ci] + (rb[ci] - ra[ci]) * t
                                   for ci in range(GRID_S)]
                    break

    # --- Step 2: Gaussian splat each stem onto the terrain grid ---
    # Each stem writes stem_y * gaussian_weight to nearby cells using max().
    # Peak stays at full height; signal falls off with distance.
    # Buried stems get wider DTE sigma — deeper burial = broader base.

    terrain = [[0.0] * GRID_S for _ in range(GRID_D)]

    SIGMA_CI_BASE  = 3.0   # price-axis sigma (grid columns) — always applied
    SIGMA_RI_BASE  = 1.2   # DTE-axis sigma (grid rows) for a non-buried stem
    SIGMA_RI_MAX   = 5.0   # DTE-axis sigma for a fully buried stem

    # Pre-compute DTE midpoints for spread limits
    dte_midpoints = {}
    for i, dte in enumerate(sorted_exps):
        prev_mid = (sorted_exps[i-1] + dte) / 2.0 if i > 0 else dte
        next_mid = (dte + sorted_exps[i+1]) / 2.0 if i < len(sorted_exps)-1 else dte
        dte_midpoints[dte] = (prev_mid, next_mid)

    by_dte = {}
    for s in stems_at_dte_side:
        by_dte.setdefault(s['dte'], []).append(s)

    for dte in sorted_exps:
        here = by_dte.get(dte, [])
        if not here:
            continue

        ridge_at_dte = ridges[dte]

        # Find which grid row corresponds to this exact DTE
        dte_frac = dte_to_depth_frac(dte)
        home_ri  = min(range(GRID_D),
                       key=lambda ri: abs(dte_to_depth_frac(grid_dtes[ri]) - dte_frac))

        for stem in here:
            ci       = frac_to_ci(price_to_frac(stem['dollars']))
            stem_y   = stem['y']
            ridge_y  = ridge_at_dte[ci]

            # Burial fraction: 0 = at ridgeline, 1 = on the floor
            bury_frac = max(0.0, (ridge_y - stem_y) / ridge_y) if ridge_y > 1e-6 else 0.0

            # DTE sigma scales with burial — buried stems spread further
            sigma_ri = SIGMA_RI_BASE + (SIGMA_RI_MAX - SIGMA_RI_BASE) * bury_frac

            # Splat radius in each axis
            r_ci = int(math.ceil(SIGMA_CI_BASE * 3))
            r_ri = int(math.ceil(sigma_ri * 3))

            for dri in range(-r_ri, r_ri + 1):
                nri = home_ri + dri
                if not (0 <= nri < GRID_D):
                    continue
                w_ri = math.exp(-dri * dri / (2 * sigma_ri * sigma_ri))
                for dci in range(-r_ci, r_ci + 1):
                    nci = ci + dci
                    if not (0 <= nci < GRID_S):
                        continue
                    w_ci = math.exp(-dci * dci / (2 * SIGMA_CI_BASE * SIGMA_CI_BASE))
                    val  = stem_y * w_ri * w_ci
                    terrain[nri][nci] = max(terrain[nri][nci], val)

    # --- Step 3: compute terrain floor and apply as soft nudge ---
    # Floor lifts valleys between expirations. Applied before the ceiling
    # clamp so the floor can exceed the interpolated ceiling between peaks
    # (the interpolated ceiling undershoots between two tall expirations).
    # The hard ceiling clamp in Step 4 still enforces the absolute maximum.
    FLOOR_FACTOR = 2.0  # tunable: lower = more aggressive valley lifting
    terrain_floor = compute_terrain_floor(ridges, sorted_exps, grid_prices,
                                          grid_dtes, factor=FLOOR_FACTOR)
    for ri in range(GRID_D):
        for ci in range(GRID_S):
            terrain[ri][ci] = max(terrain[ri][ci], terrain_floor[ri][ci])

    # --- Step 4: clamp terrain to [0, effective ceiling] ---
    # Effective ceiling = max(interpolated ridgeline, terrain floor) so the
    # floor is never cut down by the linear interpolation between ridgelines.
    for ri in range(GRID_D):
        for ci in range(GRID_S):
            eff_ceiling = max(ceiling[ri][ci], terrain_floor[ri][ci])
            terrain[ri][ci] = max(0.0, min(terrain[ri][ci], eff_ceiling))

    # --- Step 5: pin terrain to price-axis ridgeline at each expiration's home row ---
    # Uses max() — only raises terrain to meet the ridgeline, never lowers it.
    # This preserves the terrain floor lift at low-ridgeline expiration rows.
    for dte in sorted_exps:
        dte_frac = dte_to_depth_frac(dte)
        home_ri  = min(range(GRID_D),
                       key=lambda ri: abs(dte_to_depth_frac(grid_dtes[ri]) - dte_frac))
        for ci in range(GRID_S):
            terrain[home_ri][ci] = max(terrain[home_ri][ci], ridges[dte][ci])

    return terrain, ceiling


def compute_blanket(stems_call, stems_put, data):
    """
    Build terrain grids for calls and puts.
    Ridgelines computed first (locked ceiling), terrain filled beneath them.
    """
    strikes   = data['strikes']
    exps      = data['expirations']
    price_min = float(strikes[0])
    price_max = float(strikes[-1])

    grid_prices = [price_min + (price_max - price_min) * i / (GRID_S - 1)
                   for i in range(GRID_S)]
    grid_dtes   = [90.0 * i / (GRID_D - 1) for i in range(GRID_D)]
    sorted_exps = sorted(exps)

    print(f"[TERRAIN] {GRID_S}x{GRID_D} grid | ${price_min:.0f}-${price_max:.0f}")

    all_ridges    = {}
    blanket_calls = [[0.0]*GRID_S for _ in range(GRID_D)]
    blanket_puts  = [[0.0]*GRID_S for _ in range(GRID_D)]

    for side in ('call', 'put'):
        stems  = stems_call if side == 'call' else stems_put
        result = blanket_calls if side == 'call' else blanket_puts

        if not stems:
            print(f"[TERRAIN] {side}: no stems -- skipping"); continue

        # Compute locked ridgelines for every expiration
        by_dte = {}
        for s in stems:
            by_dte.setdefault(s['dte'], []).append(s)

        ridges = {}
        for dte in sorted_exps:
            here = by_dte.get(dte, [])
            ridges[dte] = (compute_ridgeline(here, grid_prices)
                           if here else [0.0]*GRID_S)

        # Build terrain beneath the ridgelines
        terrain, ceiling = compute_terrain(
            stems, ridges, sorted_exps, grid_prices, grid_dtes)

        for ri in range(GRID_D):
            result[ri] = terrain[ri]

        n_above = sum(1 for ri in range(GRID_D) for ci in range(GRID_S)
                      if result[ri][ci] > 0.01)
        print(f"[TERRAIN] {side}: {n_above}/{GRID_S*GRID_D} grid points above floor")

        all_ridges[side] = {str(dte): ridges[dte] for dte in sorted_exps}

    return blanket_calls, blanket_puts, grid_prices, grid_dtes, all_ridges


def render_html(data):
    stems_call, stems_put, p95 = compute_stem_heights(data)
    blanket_calls, blanket_puts, grid_prices, grid_dtes, all_ridges = compute_blanket(
        stems_call, stems_put, data)

    # Compute DTE-axis ridgelines — one per price column, per side.
    # All DTE values mapped to depth-fraction space (0→1) so the ridge
    # positions are consistent with the compressed Z axis in world space.
    price_min  = grid_prices[0]
    price_max  = grid_prices[-1]
    price_span = price_max - price_min
    def price_to_frac(p): return (p - price_min) / price_span if price_span > 1e-9 else 0.0
    def frac_to_ci(f): return max(0, min(len(grid_prices)-1, round(f*(len(grid_prices)-1))))
    def dte_to_frac(dte):
        if dte <= 14: return (dte / 14) * 0.42
        if dte <= 42: return 0.42 + ((dte - 14) / 28) * 0.33
        return min(1.0, 0.75 + ((dte - 42) / 48) * 0.25)

    data_json          = json.dumps(data)
    blanket_calls_json = json.dumps(blanket_calls)
    blanket_puts_json  = json.dumps(blanket_puts)
    grid_prices_json   = json.dumps(grid_prices)
    grid_dtes_json     = json.dumps(grid_dtes)
    p95_json           = json.dumps(p95)
    ridges_json        = json.dumps(all_ridges)

    ticker     = data['ticker']
    curr_price = data['current_price']
    peak_call  = data['peak_call']
    peak_put   = data['peak_put']
    n_strikes  = len(data['strikes'])
    n_exps     = data['exp_count']

    pc_label = ('$' + f"{float(peak_call['strike']):.0f}" + ' &middot; ' +
                str(peak_call['dte']) + ' DTE') if peak_call['strike'] else 'N/A'
    pp_label = ('$' + f"{float(peak_put['strike']):.0f}" + ' &middot; ' +
                str(peak_put['dte']) + ' DTE') if peak_put['strike'] else 'N/A'

    html_head = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} Options Blanket Model</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/renderers/CSS2DRenderer.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#f8fafc;height:100vh;display:flex;flex-direction:column;overflow:hidden;}}
#header{{padding:10px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(71,85,105,.4);flex-shrink:0;}}
#header .title{{font-size:15px;font-weight:500;}}
#header .subtitle{{font-size:12px;color:#94a3b8;margin-left:10px;}}
.legend{{display:flex;gap:16px;font-size:12px;color:#94a3b8;align-items:center;}}
.legend-swatch{{width:12px;height:8px;border-radius:2px;display:inline-block;margin-right:4px;}}
#canvas-container{{flex:1;position:relative;overflow:hidden;}}
#canvas-container canvas{{display:block;}}
#tiles{{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);display:flex;gap:8px;pointer-events:none;}}
.tile{{background:rgba(15,23,42,.85);border:1px solid rgba(71,85,105,.4);border-radius:8px;padding:8px 14px;text-align:center;min-width:130px;backdrop-filter:blur(8px);}}
.tile-label{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;}}
.tile-value{{font-size:13px;font-weight:500;color:#f1f5f9;}}
.tile-value.call{{color:#84cc16;}} .tile-value.put{{color:#fb923c;}}
#hint{{position:absolute;top:10px;right:14px;font-size:11px;color:rgba(255,255,255,.3);pointer-events:none;}}
.price-label{{background:rgba(10,30,50,.82);color:rgba(241,245,249,.95);font-size:10px;font-family:monospace;padding:2px 6px;border-radius:3px;border:1px solid rgba(241,245,249,.25);white-space:nowrap;pointer-events:none;user-select:none;}}
.price-label.current{{background:rgba(120,80,0,.88);color:#f59e0b;border-color:rgba(245,158,11,.5);font-weight:600;}}
.dte-label{{background:rgba(10,20,40,.75);color:rgba(148,163,184,.85);font-size:10px;font-family:sans-serif;padding:1px 5px;border-radius:3px;border:1px solid rgba(148,163,184,.2);white-space:nowrap;pointer-events:none;user-select:none;}}
</style>
</head>
<body>
<div id="header">
  <div>
    <span class="title">{ticker}</span>
    <span class="subtitle">Open interest blanket model &middot; {n_exps} expirations &middot; {n_strikes} strikes &middot; drag to rotate &middot; scroll to zoom</span>
  </div>
  <div class="legend">
    <span><span class="legend-swatch" style="background:#84cc16;"></span>Calls</span>
    <span><span class="legend-swatch" style="background:#fb923c;"></span>Puts</span>
    <span><span style="display:inline-block;width:20px;height:2px;background:#f59e0b;vertical-align:middle;margin-right:4px;"></span>${curr_price:,.2f}</span>
  </div>
</div>
<div id="canvas-container">
  <div id="hint">Puts &larr; 0 DTE center &rarr; Calls</div>
  <div id="tiles">
    <div class="tile"><div class="tile-label">Current price</div><div class="tile-value">${curr_price:,.2f}</div></div>
    <div class="tile"><div class="tile-label">Peak call OI</div><div class="tile-value call">{pc_label}<br><span style="font-size:11px;">{peak_call['oi']:,}</span></div></div>
    <div class="tile"><div class="tile-label">Peak put OI</div><div class="tile-value put">{pp_label}<br><span style="font-size:11px;">{peak_put['oi']:,}</span></div></div>
    <div class="tile"><div class="tile-label">Expirations</div><div class="tile-value">{n_exps} &middot; up to 90 DTE</div></div>
  </div>
</div>"""

    html_script = f"""
<script>
const DATA          = {data_json};
const BLANKET_CALLS = {blanket_calls_json};
const BLANKET_PUTS  = {blanket_puts_json};
const GRID_PRICES   = {grid_prices_json};
const GRID_DTES     = {grid_dtes_json};
const SHARED_P95    = {p95_json};
const RIDGES        = {ridges_json};
const SHARED_MAX_OI = SHARED_P95 * 2;

const TERRAIN_HALF_W = 10;
const TERRAIN_DEPTH  = 8;
const MAX_HEIGHT     = TERRAIN_HALF_W * 2 * 0.22;
const OI_FLOOR       = 100;
const PRICE_MIN      = GRID_PRICES[0];
const PRICE_MAX      = GRID_PRICES[GRID_PRICES.length-1];

function priceToX(d) {{
  return -TERRAIN_HALF_W + ((d-PRICE_MIN)/(PRICE_MAX-PRICE_MIN))*TERRAIN_HALF_W*2;
}}
function dteToDepthFrac(dte) {{
  if(dte<=14) return (dte/14)*0.42;
  if(dte<=42) return 0.42+((dte-14)/28)*0.33;
  return Math.min(1.0,0.75+((dte-42)/48)*0.25);
}}
function oiToHeight(oi) {{
  const adj=oi-OI_FLOOR; if(adj<=0) return 0;
  if(adj<=SHARED_P95) return (adj/SHARED_P95)*MAX_HEIGHT;
  return MAX_HEIGHT+Math.min((adj-SHARED_P95)/(SHARED_MAX_OI-SHARED_P95),1)*MAX_HEIGHT;
}}
function heightToColor(wy,side) {{
  const t=Math.pow(Math.min(wy/(MAX_HEIGHT*2),1),0.45);
  const sl=[.059,.090,.165], pk=side==='call'?[.10,.66,.10]:[.98,.16,.12];
  let r=sl[0]+(pk[0]-sl[0])*t, g=sl[1]+(pk[1]-sl[1])*t, b=sl[2]+(pk[2]-sl[2])*t;
  // Snow cap: only triggers in top 15% of height range (wy > MAX_HEIGHT*1.7)
  const snowStart = MAX_HEIGHT * 1.7;
  const sn=Math.max(0,Math.min((wy-snowStart)/(MAX_HEIGHT*2-snowStart),1));
  return new THREE.Color(r+(1-r)*sn, g+(1-g)*sn, b+(1-b)*sn);
}}

// Scene
const container=document.getElementById('canvas-container');
const renderer=new THREE.WebGLRenderer({{antialias:true}});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(container.clientWidth,container.clientHeight);
renderer.setClearColor(0x0f172a,1);
container.appendChild(renderer.domElement);
const scene=new THREE.Scene();
scene.fog=new THREE.FogExp2(0x0f172a,0.018);
const camera=new THREE.PerspectiveCamera(45,container.clientWidth/container.clientHeight,.1,200);

// Orbit controls
(function(){{
  const el=renderer.domElement;
  let drag=false,lx=0,ly=0,sph={{theta:Math.PI*.50,phi:Math.PI*.32,radius:38}};
  const tgt=new THREE.Vector3(0,1,0);
  function upd(){{
    camera.position.set(sph.radius*Math.sin(sph.phi)*Math.sin(sph.theta)+tgt.x,
      sph.radius*Math.cos(sph.phi)+tgt.y,sph.radius*Math.sin(sph.phi)*Math.cos(sph.theta)+tgt.z);
    camera.lookAt(tgt);
  }}
  upd();
  el.addEventListener('mousedown',e=>{{drag=true;lx=e.clientX;ly=e.clientY;}});
  window.addEventListener('mouseup',()=>drag=false);
  window.addEventListener('mousemove',e=>{{
    if(!drag)return;
    sph.theta-=(e.clientX-lx)*.005;
    sph.phi=Math.max(.05,Math.min(Math.PI*.48,sph.phi+(e.clientY-ly)*.005));
    lx=e.clientX;ly=e.clientY;upd();
  }});
  el.addEventListener('wheel',e=>{{sph.radius=Math.max(8,Math.min(60,sph.radius+e.deltaY*.03));upd();e.preventDefault();}},{{passive:false}});
}})();

// Lighting
scene.add(new THREE.AmbientLight(0x334466,.7));
const sun=new THREE.DirectionalLight(0xffffff,1.0);
sun.position.set(-8,12,6); scene.add(sun);

// Base platform
const baseGeo=new THREE.BoxGeometry(TERRAIN_HALF_W*2+.5,.4,TERRAIN_DEPTH*2+.5);
const base=new THREE.Mesh(baseGeo,new THREE.MeshLambertMaterial({{color:0x1e293b}}));
base.position.y=-.2; scene.add(base);
const bel=new THREE.LineSegments(new THREE.EdgesGeometry(baseGeo),
  new THREE.LineBasicMaterial({{color:0x475569,transparent:true,opacity:.5}}));
bel.position.y=-.2; scene.add(bel);

// Floor grid
const grid=new THREE.GridHelper(Math.max(TERRAIN_HALF_W*2,TERRAIN_DEPTH*2),20,0x1e3a5f,0x1e3a5f);
grid.position.y=.01; scene.add(grid);

// Current price line
const priceX=priceToX(DATA.current_price);
scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
  new THREE.Vector3(priceX,.02,-TERRAIN_DEPTH),new THREE.Vector3(priceX,.02,TERRAIN_DEPTH)]),
  new THREE.LineBasicMaterial({{color:0xf59e0b,transparent:true,opacity:.9}})));

// DTE labels as depth-tested sprites — occluded by terrain when behind it
function makeDteSprite(text, pos) {{
  const canvas = document.createElement('canvas');
  canvas.width = 44; canvas.height = 20;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(10,20,40,0.75)';
  ctx.roundRect(0, 0, 44, 20, 3);
  ctx.fill();
  ctx.strokeStyle = 'rgba(148,163,184,0.35)';
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = 'rgba(241,245,249,0.95)';
  ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 22, 10);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({{map: tex, depthTest: true, depthWrite: false, transparent: true}});
  const sprite = new THREE.Sprite(mat);
  sprite.position.copy(pos);
  sprite.scale.set(0.85, 0.35, 1);
  return sprite;
}}

// CSS2D
const css2d=new THREE.CSS2DRenderer();
css2d.setSize(container.clientWidth,container.clientHeight);
css2d.domElement.style.cssText='position:absolute;top:0;left:0;pointer-events:none;';
container.appendChild(css2d.domElement);
function makeLabel(text,pos,cls){{
  const d=document.createElement('div'); d.className=cls||'price-label'; d.textContent=text;
  const l=new THREE.CSS2DObject(d); l.position.copy(pos); return l;
}}
DATA.expirations.forEach(dte=>{{
  const df=dteToDepthFrac(dte);
  ['call','put'].forEach(side=>{{
    const wz=side==='call'?df*TERRAIN_DEPTH:-df*TERRAIN_DEPTH;
    [TERRAIN_HALF_W+.3,-TERRAIN_HALF_W-.3].forEach(lx=>{{
      scene.add(makeDteSprite(dte+'d', new THREE.Vector3(lx, 0, wz)));
    }});
  }});
}});

// Stems — disabled (kept for debugging, set SHOW_STEMS=true to re-enable)
const SHOW_STEMS = false;
const sphereGeo=new THREE.SphereGeometry(.12,8,6);
let stemCount=0;
DATA.expirations.forEach(dte=>{{
  const d=DATA.chain[String(dte)]; if(!d) return;
  const df=dteToDepthFrac(dte);
  ['call','put'].forEach(side=>{{
    const oiMap=side==='call'?d.calls:d.puts;
    const wz=side==='call'?df*TERRAIN_DEPTH:-df*TERRAIN_DEPTH;
    DATA.strikes.forEach(s=>{{
      const oi=oiMap[s]||0; if(oi<OI_FLOOR) return;
      const wx=priceToX(parseFloat(s)), wy=oiToHeight(oi);
      if(wy<=0) return;
      const col=heightToColor(wy,side);
      if(SHOW_STEMS) {{
        scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(wx,.01,wz),new THREE.Vector3(wx,wy,wz)]),
          new THREE.LineBasicMaterial({{color:col,transparent:true,opacity:.35}})));
        const sph=new THREE.Mesh(sphereGeo,new THREE.MeshLambertMaterial({{color:col,transparent:true,opacity:.45}}));
        sph.position.set(wx,wy,wz); scene.add(sph); stemCount++;
      }}
    }});
  }});
}});
console.log('[STEMS] rendered',stemCount);

// Blanket
function buildBlanket(grid2d,side){{
  const nr=GRID_DTES.length, nc=GRID_PRICES.length;
  const geo=new THREE.PlaneGeometry(TERRAIN_HALF_W*2,TERRAIN_DEPTH,nc-1,nr-1);
  geo.rotateX(-Math.PI/2);
  const pos=geo.attributes.position, colors=new Float32Array(pos.count*3);
  for(let ri=0;ri<nr;ri++) for(let ci=0;ci<nc;ci++){{
    const idx=ri*nc+ci, wy=grid2d[ri][ci];
    const wx=priceToX(GRID_PRICES[ci]);
    const wz=(side==='call'?1:-1)*dteToDepthFrac(GRID_DTES[ri])*TERRAIN_DEPTH;
    pos.setXYZ(idx,wx,wy,wz);
    const col=heightToColor(wy,side);
    colors[idx*3]=col.r; colors[idx*3+1]=col.g; colors[idx*3+2]=col.b;
  }}
  geo.setAttribute('color',new THREE.BufferAttribute(colors,3));
  geo.computeVertexNormals();
  return new THREE.Mesh(geo,new THREE.MeshLambertMaterial({{vertexColors:true,side:THREE.DoubleSide}}));
}}
scene.add(buildBlanket(BLANKET_CALLS,'call'));
scene.add(buildBlanket(BLANKET_PUTS,'put'));

// Ridge lines — cyan, floating 0.08 above blanket surface
const RIDGE_COLOR  = 0x5eead4;
const RIDGE_OFFSET = 0.08;
['call','put'].forEach(side => {{
  const sideRidges = RIDGES[side];
  if (!sideRidges) return;
  Object.entries(sideRidges).forEach(([dteStr, heights]) => {{
    const dte = parseInt(dteStr);
    const df  = dteToDepthFrac(dte);
    const wz  = (side==='call' ? 1 : -1) * df * TERRAIN_DEPTH;
    const pts = GRID_PRICES.map((p, ci) =>
      new THREE.Vector3(priceToX(p), heights[ci] + RIDGE_OFFSET, wz)
    );
    scene.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({{color: RIDGE_COLOR, transparent: true, opacity: 0.85}})
    ));
  }});
}});

// Strike price contour lines — trace terrain surface front-to-back
// Dynamic step size targeting ~8-10 labels across the strike range.
const CONTOUR_OFFSET = 0.06;
const strikeMin = GRID_PRICES[0], strikeMax = GRID_PRICES[GRID_PRICES.length-1];
const priceRange = strikeMax - strikeMin;
const rawStep = priceRange / 13;
const niceSteps = [0.5,1,2,2.5,5,10,20,25,50,100,200,250,500,1000];
// Round up to nearest nice number, then round up to nearest multiple of strikeIncrement
// so all displayed strikes are guaranteed to land on actual strike prices.
const actualStrikes = DATA.strikes.map(s => parseFloat(s));
const strikeIncrement = actualStrikes.length > 1
  ? Math.round((actualStrikes[1] - actualStrikes[0]) * 1000) / 1000
  : rawStep;
const niceStep = niceSteps.find(s => s >= rawStep) || niceSteps[niceSteps.length-1];
const CONTOUR_STEP = Math.ceil(niceStep / strikeIncrement) * strikeIncrement;

// Build label set from ACTUAL strikes only.
const labelStrikes = new Set();
const labelStart = Math.ceil(actualStrikes[0] / CONTOUR_STEP) * CONTOUR_STEP;
for(let s = labelStart; s <= strikeMax; s += CONTOUR_STEP) {{
  const nearest = actualStrikes.reduce((best, a) =>
    Math.abs(a - s) < Math.abs(best - s) ? a : best);
  if(Math.abs(nearest - s) <= strikeIncrement * 0.5) labelStrikes.add(nearest);
}}

// Current price: nearest dollar as reference line — handled separately above

// Current price reference line — drawn separately, not snapped to any strike
((() => {{
  const cp = DATA.current_price;
  const wx = priceToX(cp);
  const labelText = '$' + (cp < 10 ? cp.toFixed(2) : Math.round(cp));
  ['call','put'].forEach(side => {{
    const grid2d = side === 'call' ? BLANKET_CALLS : BLANKET_PUTS;
    const sign   = side === 'call' ? 1 : -1;
    const pts = GRID_DTES.map((dte, ri) => {{
      const wz = sign * dteToDepthFrac(dte) * TERRAIN_DEPTH;
      const wy = grid2d[ri][Math.round((cp - PRICE_MIN) / (PRICE_MAX - PRICE_MIN) * (GRID_PRICES.length-1))] + CONTOUR_OFFSET;
      return new THREE.Vector3(wx, wy, wz);
    }});
    scene.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({{color: 0xf59e0b, transparent: true, opacity: 0.9}})
    ));
    const lastRi = GRID_DTES.length - 1;
    const labelZ = sign * dteToDepthFrac(GRID_DTES[lastRi]) * TERRAIN_DEPTH;
    const labelY = grid2d[lastRi][Math.round((cp - PRICE_MIN) / (PRICE_MAX - PRICE_MIN) * (GRID_PRICES.length-1))] + CONTOUR_OFFSET + 0.15;
    scene.add(makeLabel(labelText, new THREE.Vector3(wx, labelY, labelZ), 'price-label current'));
  }});
}}))();

labelStrikes.forEach(targetStrike => {{
  // Find closest grid column
  let ci = 0;
  GRID_PRICES.forEach((p,i) => {{ if(Math.abs(p-targetStrike)<Math.abs(GRID_PRICES[ci]-targetStrike)) ci=i; }});
  const wx = priceToX(GRID_PRICES[ci]);
  const isCurrent = false;  // current price handled separately
  const lineColor = 0xf1f5f9;
  const lineOpacity = 0.45;
  const labelCls = 'price-label';
  const labelText = '$' + (Number.isInteger(targetStrike) ? targetStrike : targetStrike.toFixed(1));

  ['call','put'].forEach(side => {{
    const grid2d = side === 'call' ? BLANKET_CALLS : BLANKET_PUTS;
    const sign   = side === 'call' ? 1 : -1;

    // Build points tracing terrain surface across all DTE rows
    const pts = GRID_DTES.map((dte, ri) => {{
      const wz = sign * dteToDepthFrac(dte) * TERRAIN_DEPTH;
      const wy = grid2d[ri][ci] + CONTOUR_OFFSET;
      return new THREE.Vector3(wx, wy, wz);
    }});

    scene.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({{color: lineColor, transparent: true, opacity: lineOpacity}})
    ));

    // Label at the far edge (last grid row = outermost DTE)
    const lastRi = GRID_DTES.length - 1;
    const labelZ  = sign * dteToDepthFrac(GRID_DTES[lastRi]) * TERRAIN_DEPTH;
    const labelY  = grid2d[lastRi][ci] + CONTOUR_OFFSET + 0.15;
    scene.add(makeLabel(labelText, new THREE.Vector3(wx, labelY, labelZ), labelCls));
  }});
}});

// Resize & render
window.addEventListener('resize',()=>{{
  camera.aspect=container.clientWidth/container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth,container.clientHeight);
  css2d.setSize(container.clientWidth,container.clientHeight);
}});
function animate(){{ requestAnimationFrame(animate); renderer.render(scene,camera); css2d.render(scene,camera); }}
animate();
</script>
</body>
</html>"""

    return html_head + html_script


def main():
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AMD'
    print(f"[START] Building blanket model for {ticker}...")

    # Use snapshot if --snapshot flag provided, otherwise live yfinance
    if '--snapshot' in sys.argv:
        snap_path = next((sys.argv[i+1] for i, a in enumerate(sys.argv)
                          if a == '--snapshot' and i+1 < len(sys.argv)), None)
        if snap_path is None:
            # Auto-find today's snapshot for this ticker
            import glob, os
            pattern = os.path.join(r'C:\Users\pguth\OneDrive\Desktop\Trader App',
                                   f'oi_snapshot_{ticker}_*.json')
            matches = sorted(glob.glob(pattern), reverse=True)
            if not matches:
                print(f"No snapshot found for {ticker}"); sys.exit(1)
            snap_path = matches[0]
        data = load_from_snapshot(snap_path)
    else:
        data = fetch_options_data(ticker)
    html = render_html(data)
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.html', prefix=f'blanket_{ticker}_',
        delete=False, encoding='utf-8'
    ) as f:
        f.write(html)
        path = f.name
    print(f"[DONE] Written to: {path}")
    webbrowser.open(f'file://{path}')


if __name__ == '__main__':
    main()
