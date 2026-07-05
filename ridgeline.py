"""
ridgeline.py — Locked catenary ridgeline computation.
Standalone module. No external dependencies beyond math.

LOCKED 2026-06-25. Do not modify.

Public API:
    compute_ridgeline(stems_at_dte, grid_prices, grid_s=100) -> list[float]

    stems_at_dte : list of {'dollars': float, 'y': float}
                   All stems for a single expiration, in world-Y units.
    grid_prices  : list of floats, evenly spaced dollar prices (GRID_S points).
    grid_s       : number of grid columns (default 100, must match grid_prices).

    Returns a list of grid_s world-Y heights — the ridgeline for that
    expiration. This is the fixed ceiling the terrain must rise up to meet.

Algorithm:
    - All catenary math in world-X space (mapped to ±TERRAIN_HALF_W = ±10)
      so X and Y are on the same scale.
    - Pass 1: top-2 stems by world-Y become initial poles. Left/right edges
      anchored at zero. Three catenary segments, cable factor 1.2x.
    - Pass 2+: find tallest stem violating the envelope, insert as new pole,
      repeat until no violations remain (max 30 poles).
    - Returns heights that touch every stem exactly and drape smoothly
      between them.
"""

import math

TERRAIN_HALF_W = 10.0   # world-X half-width — must match JS constant
CABLE_FACTOR   = 1.2    # catenary cable length = straight-line * this factor
MAX_POLES      = 30     # maximum poles before stopping violation loop


def _catenary_y(x, a, x0, c):
    """Evaluate catenary: y = a * cosh((x - x0) / a) + c"""
    return a * math.cosh((x - x0) / a) + c


def _solve_catenary(x1, y1, x2, y2, cable_length):
    """
    Solve for catenary parameters (a, x0, c) given two endpoints and cable
    length. Returns (a, x0, c) or None if no solution found (linear fallback
    used at call site).
    """
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-9:
        return None

    min_len = math.sqrt(dx * dx + dy * dy)
    if cable_length <= min_len:
        cable_length = min_len * 1.001

    def arc_length_for_a(a):
        if a <= 0:
            return float('inf')
        dxa = dx / a

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
            if not math.isfinite(fm):
                hi = mid; continue
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

    a_lo = 1e-6
    a_hi = max(abs(dx), abs(dy), 1.0) * 1000
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
    """
    Evaluate catenary segment at x_points (in world-X space).
    Clamps to <= max(y1, y2) — blanket only drapes, never arches above poles.
    Falls back to linear interpolation if catenary solve fails.
    """
    params  = _solve_catenary(x1, y1, x2, y2, cable_len)
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


def compute_ridgeline(stems_at_dte, grid_prices, grid_s=100):
    """
    Compute the ridgeline for one expiration.

    Parameters
    ----------
    stems_at_dte : list of dict with keys 'dollars' (float) and 'y' (float)
    grid_prices  : list of floats — dollar prices at each grid column
    grid_s       : int — number of grid columns (must equal len(grid_prices))

    Returns
    -------
    list of float, length grid_s — world-Y height at each grid column.
    """
    if not stems_at_dte:
        return [0.0] * grid_s

    price_min  = grid_prices[0]
    price_max  = grid_prices[-1]
    price_span = price_max - price_min

    def price_to_wx(p):
        frac = (p - price_min) / price_span if price_span > 1e-9 else 0.0
        return -TERRAIN_HALF_W + frac * TERRAIN_HALF_W * 2

    def price_to_frac(p):
        return (p - price_min) / price_span if price_span > 1e-9 else 0.0

    def frac_to_ci(f):
        return max(0, min(grid_s - 1, round(f * (grid_s - 1))))

    # Initial poles: top-2 stems by world-Y + zero-height edge anchors
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
        ridge = [0.0] * grid_s
        n = len(poles_list)
        for si in range(n - 1):
            p1, py1 = poles_list[si]
            p2, py2 = poles_list[si + 1]
            wx1, wx2 = price_to_wx(p1), price_to_wx(p2)
            dist = math.sqrt((wx2 - wx1) ** 2 + (py2 - py1) ** 2)
            clen = dist * CABLE_FACTOR
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

    # Violation loop: insert stems that pierce the envelope as new poles
    ridge = [0.0] * grid_s
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
