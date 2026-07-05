"""
Options open interest 3D relief model — Three.js implementation.
Fetches real options chain data via yfinance and renders a self-contained
HTML file with a WebGL terrain model using Three.js.

Design decisions (from prototyping session):
- Butterfly layout: puts left (red), calls right (green), 2 DTE center FRONT, 86 DTE back edges
- Viewing angle: 45° isometric, ~35° elevation, OrbitControls for rotation/zoom
- Vertical scale: ~1/4 of horizontal terrain width (subtle relief model proportions)
- Lighting: DirectionalLight upper-left + AmbientLight fill
- Contour lines: cyan dashed at labeled strikes, amber at current price
- CSS2DRenderer for price labels anchored in 3D space

Usage:
    python3 test_heatmap_3d.py AMD
    python3 test_heatmap_3d.py AAPL
    python3 test_heatmap_3d.py SPY
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


def fetch_options_data(ticker_symbol):
    """
    Fetches the full options chain for all expirations up to 90 days out.
    Returns a dict ready to pass into the 3D renderer.
    Strike keys stored as str(float(strike)) throughout to avoid type mismatch.
    Uses .values arrays (not iterrows()) to avoid DataFrame index leaking into keys.
    """
    stock = yf.Ticker(ticker_symbol)

    try:
        hist = stock.history(period="2d")
        if hist.empty:
            print(f"No price history for {ticker_symbol}")
            sys.exit(1)
        current_price = float(hist['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching price: {e}")
        sys.exit(1)

    print(f"[DATA] {ticker_symbol} current price: ${current_price:,.2f}")

    expirations = stock.options
    if not expirations:
        print(f"No options data available for {ticker_symbol}")
        sys.exit(1)

    today = date.today()
    valid_exps = []
    for exp in expirations:
        exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
        dte = (exp_date - today).days
        if 0 <= dte <= 90:
            valid_exps.append((dte, exp))

    if not valid_exps:
        print("No expirations found within 90 days.")
        sys.exit(1)

    print(f"[DATA] Found {len(valid_exps)} expirations: {[f'{d}d' for d, _ in valid_exps]}")

    all_strikes = set()
    chain_data = {}

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
                'puts':  {str(float(s)): int(o) for s, o in zip(puts['strike'].values,  puts['openInterest'].values)},
                'calls': {str(float(s)): int(o) for s, o in zip(calls['strike'].values, calls['openInterest'].values)},
            }
            print(f"[DATA] {exp} ({dte} DTE): {len(puts)} put strikes, {len(calls)} call strikes")
        except Exception as e:
            print(f"[WARN] Could not fetch chain for {exp}: {e}")

    # Strike filter: OI threshold + ±30% price range
    sorted_strikes = sorted(all_strikes, key=lambda s: float(s))
    lower, upper = current_price * 0.70, current_price * 1.30

    def max_oi(strike):
        best = 0
        for data in chain_data.values():
            best = max(best, data['calls'].get(strike, 0), data['puts'].get(strike, 0))
        return best

    filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= 100]
    for fallback in [50, 10, 1]:
        if len(filtered) >= 20:
            break
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper and max_oi(s) >= fallback]
    if len(filtered) < 10:
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper]

    print(f"[FILTER] {len(filtered)} strikes "
          f"(${float(filtered[0]):.0f}–${float(filtered[-1]):.0f})" if filtered else "[FILTER] No strikes")

    # Compute peak OI for summary tiles
    # chain_data keys are int DTE; iterate filtered strikes as strings (matching chain dicts)
    max_call_oi, max_call_strike, max_call_dte = 0, None, None
    max_put_oi,  max_put_strike,  max_put_dte  = 0, None, None
    for dte, side_data in chain_data.items():
        for s in filtered:
            c_oi = side_data['calls'].get(s, 0)
            p_oi = side_data['puts'].get(s, 0)
            if c_oi > max_call_oi:
                max_call_oi, max_call_strike, max_call_dte = c_oi, s, dte
            if p_oi > max_put_oi:
                max_put_oi, max_put_strike, max_put_dte = p_oi, s, dte

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


def render_html(data):
    data_json = json.dumps(data)
    ticker      = data['ticker']
    curr_price  = data['current_price']
    peak_call   = data['peak_call']
    peak_put    = data['peak_put']
    n_strikes   = len(data['strikes'])
    n_exps      = data['exp_count']

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} Options Relief Model</title>

<!-- Three.js r128 -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/renderers/CSS2DRenderer.js"></script>

<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0f172a;
  color: #f8fafc;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}
#header {{
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(71,85,105,0.4);
  flex-shrink: 0;
}}
#header .title {{ font-size: 15px; font-weight: 500; }}
#header .subtitle {{ font-size: 12px; color: #94a3b8; margin-left: 10px; }}
.legend {{ display: flex; gap: 16px; font-size: 12px; color: #94a3b8; align-items: center; }}
.legend-swatch {{ width: 12px; height: 8px; border-radius: 2px; display: inline-block; margin-right: 4px; }}
#canvas-container {{
  flex: 1;
  position: relative;
  overflow: hidden;
}}
#canvas-container canvas {{ display: block; }}
#tiles {{
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 8px;
  pointer-events: none;
}}
.tile {{
  background: rgba(15,23,42,0.85);
  border: 1px solid rgba(71,85,105,0.4);
  border-radius: 8px;
  padding: 8px 14px;
  text-align: center;
  min-width: 130px;
  backdrop-filter: blur(8px);
}}
.tile-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3px; }}
.tile-value {{ font-size: 13px; font-weight: 500; color: #f1f5f9; }}
.tile-value.call {{ color: #84cc16; }}
.tile-value.put  {{ color: #fb923c; }}
#hint {{
  position: absolute;
  top: 10px;
  right: 14px;
  font-size: 11px;
  color: rgba(255,255,255,0.3);
  pointer-events: none;
}}

/* CSS2DRenderer labels */
.price-label {{
  background: rgba(10,30,50,0.82);
  color: rgba(94,234,212,0.95);
  font-size: 10px;
  font-family: monospace;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid rgba(94,234,212,0.3);
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
}}
.price-label.current {{
  background: rgba(120,80,0,0.88);
  color: #f59e0b;
  border-color: rgba(245,158,11,0.5);
  font-weight: 600;
}}
.dte-label {{
  background: rgba(10,20,40,0.75);
  color: rgba(148,163,184,0.85);
  font-size: 10px;
  font-family: sans-serif;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(148,163,184,0.2);
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
}}
</style>
</head>
<body>

<div id="header">
  <div>
    <span class="title">{ticker}</span>
    <span class="subtitle">Open interest relief model · {n_exps} expirations · {n_strikes} strikes · drag to rotate · scroll to zoom</span>
  </div>
  <div class="legend">
    <span><span class="legend-swatch" style="background:#84cc16;"></span>Calls</span>
    <span><span class="legend-swatch" style="background:#fb923c;"></span>Puts</span>
    <span><span style="display:inline-block;width:20px;height:2px;background:#f59e0b;vertical-align:middle;margin-right:4px;"></span>${curr_price:,.2f}</span>
    <span><span style="display:inline-block;width:20px;height:1px;border-top:1px dashed #5eead4;vertical-align:middle;margin-right:4px;"></span>Strike levels</span>
  </div>
</div>

<div id="canvas-container">
  <div id="hint">← Puts · 0 DTE center · Calls →</div>

  <div id="tiles">
    <div class="tile">
      <div class="tile-label">Current price</div>
      <div class="tile-value">${curr_price:,.2f}</div>
    </div>
    <div class="tile">
      <div class="tile-label">Peak call OI</div>
      <div class="tile-value call">
        {'$' + f"{float(peak_call['strike']):.0f}" + ' · ' + str(peak_call['dte']) + ' DTE' if peak_call['strike'] else 'N/A'}<br>
        <span style="font-size:11px;">{peak_call['oi']:,}</span>
      </div>
    </div>
    <div class="tile">
      <div class="tile-label">Peak put OI</div>
      <div class="tile-value put">
        {'$' + f"{float(peak_put['strike']):.0f}" + ' · ' + str(peak_put['dte']) + ' DTE' if peak_put['strike'] else 'N/A'}<br>
        <span style="font-size:11px;">{peak_put['oi']:,}</span>
      </div>
    </div>
    <div class="tile">
      <div class="tile-label">Expirations</div>
      <div class="tile-value">{n_exps} · up to 90 DTE</div>
    </div>
  </div>
</div>

<script>
// ─── DATA ──────────────────────────────────────────────────────────────────
const DATA = {data_json};

// ─── CONSTANTS ─────────────────────────────────────────────────────────────
const TERRAIN_HALF_W = 10;   // half-width of terrain in world units (strike axis)
const TERRAIN_DEPTH  = 8;    // depth of terrain (DTE axis per side)
const MAX_HEIGHT     = TERRAIN_HALF_W * 2 * 0.22; // shared height ceiling for calls AND puts
const OI_FLOOR = 100; // minimum meaningful OI — base plate level

// Single shared OI scale across all calls and puts.
// Two-tier height model:
//   Tier 1 (OI_FLOOR → P95):  log-scaled to 0 → MAX_HEIGHT
//   Tier 2 (P95 → max OI):    linear extension to MAX_HEIGHT → MAX_HEIGHT * 2
// Snow cap color triggers in tier 2 (above MAX_HEIGHT).
const {{ SHARED_P95, SHARED_MAX_OI }} = (() => {{
  const all = [];
  DATA.expirations.forEach(dte => {{
    const d = DATA.chain[String(dte)];
    if (!d) return;
    DATA.strikes.forEach(s => {{
      const c = (d.calls[s] || 0) - OI_FLOOR;
      const p = (d.puts[s]  || 0) - OI_FLOOR;
      if (c > 0) all.push(c);
      if (p > 0) all.push(p);
    }});
  }});
  all.sort((a,b) => a-b);
  const p95    = all[Math.floor(all.length * 0.95)] || 1;
  const maxOI  = p95 * 2; // tier 2 ceiling = 2×p95, not raw max — keeps peaks at true 2× scale
  console.log('[OI] Total samples:', all.length, '| p95:', p95, '| raw max:', all[all.length-1], '| tier2 cap:', maxOI);
  console.log('[OI] Tier 1: OI_FLOOR→p95 maps to 0→MAX_HEIGHT');
  console.log('[OI] Tier 2: p95→max maps to MAX_HEIGHT→MAX_HEIGHT*2 (snow cap zone)');
  return {{ SHARED_P95: p95, SHARED_MAX_OI: maxOI }};
}})();

const N_STRIKES = DATA.strikes.length;
const N_EXPS    = DATA.expirations.length;

// Compressed DTE scale — matches 2D heatmap zones
// 0-14 DTE = 42%, 14-42 DTE = 33%, 42-90 DTE = 25% of half-depth
function dteToDepthFrac(dte) {{
  if (dte <= 14) return (dte / 14) * 0.42;
  if (dte <= 42) return 0.42 + ((dte - 14) / 28) * 0.33;
  return Math.min(1.0, 0.75 + ((dte - 42) / 48) * 0.25);
}}

// Two-tier OI → height mapping:
//   Tier 1 (floor → p95): LINEAR 0 → MAX_HEIGHT (evenly spread, no compression)
//   Tier 2 (p95 → max):   linear 0 → MAX_HEIGHT on top (total ceiling = MAX_HEIGHT * 2)
// Snow cap color triggers in tier 2 (above MAX_HEIGHT).
function oiToHeight(oi) {{
  const adjusted = oi - OI_FLOOR;
  if (adjusted <= 0) return 0;

  if (adjusted <= SHARED_P95) {{
    // Tier 1: linear — OI spreads evenly across 0→MAX_HEIGHT
    return (adjusted / SHARED_P95) * MAX_HEIGHT;
  }} else {{
    // Tier 2: linear extension p95→max → MAX_HEIGHT→MAX_HEIGHT*2
    const tier2Frac = Math.min((adjusted - SHARED_P95) / (SHARED_MAX_OI - SHARED_P95), 1.0);
    return MAX_HEIGHT + tier2Frac * MAX_HEIGHT;
  }}
}}

// Gaussian smoothing across strike axis
// Missing strikes return 0 (treated as below the 100-contract floor)
function smoothedOI(strikeIdx, expIdx, side) {{
  const dte = DATA.expirations[expIdx];
  const d   = DATA.chain[String(dte)];
  if (!d) return 0;
  const oiMap = side === 'call' ? d.calls : d.puts;
  const sigma = 0.85; // adjacent strike gets ~50% weight
  let total = 0, weight = 0;
  DATA.strikes.forEach((s, i) => {{
    const rawOI = oiMap[s] || 0; // missing strike = 0, treated as below floor
    const w = Math.exp(-(i - strikeIdx)*(i - strikeIdx) / (2*sigma*sigma));
    total  += rawOI * w;
    weight += w;
  }});
  return total / weight;
}}

// ─── THREE.JS SETUP ────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const renderer  = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setClearColor(0x0f172a, 1);
renderer.shadowMap.enabled = true;
container.appendChild(renderer.domElement);

const scene  = new THREE.Scene();
scene.fog    = new THREE.FogExp2(0x0f172a, 0.018);

// Camera
const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 200);

// ─── ORBIT CONTROLS (inline — no import needed for r128) ───────────────────
// Lightweight OrbitControls implementation
(function() {{
  const el = renderer.domElement;
  let isDragging = false, lastX = 0, lastY = 0;
  let spherical = {{ theta: Math.PI * 0.50, phi: Math.PI * 0.32, radius: 38 }};
  const target = new THREE.Vector3(0, 1, 0);

  function updateCamera() {{
    const x = spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta);
    const y = spherical.radius * Math.cos(spherical.phi);
    const z = spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta);
    camera.position.set(x + target.x, y + target.y, z + target.z);
    camera.lookAt(target);
  }}
  updateCamera();

  el.addEventListener('mousedown', e => {{ isDragging = true; lastX = e.clientX; lastY = e.clientY; }});
  window.addEventListener('mouseup', () => {{ isDragging = false; }});
  window.addEventListener('mousemove', e => {{
    if (!isDragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    spherical.theta -= dx * 0.005;
    spherical.phi    = Math.max(0.05, Math.min(Math.PI * 0.48, spherical.phi + dy * 0.005));
    lastX = e.clientX; lastY = e.clientY;
    updateCamera();
  }});
  el.addEventListener('wheel', e => {{
    spherical.radius = Math.max(8, Math.min(60, spherical.radius + e.deltaY * 0.03));
    updateCamera();
    e.preventDefault();
  }}, {{ passive: false }});

  // Touch support
  let lastTouchDist = 0, lastTouchX = 0, lastTouchY = 0;
  el.addEventListener('touchstart', e => {{
    if (e.touches.length === 1) {{ lastTouchX = e.touches[0].clientX; lastTouchY = e.touches[0].clientY; isDragging = true; }}
    if (e.touches.length === 2) {{ lastTouchDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); isDragging = false; }}
    e.preventDefault();
  }}, {{ passive: false }});
  el.addEventListener('touchmove', e => {{
    if (e.touches.length === 1 && isDragging) {{
      const dx = e.touches[0].clientX - lastTouchX, dy = e.touches[0].clientY - lastTouchY;
      spherical.theta -= dx * 0.005;
      spherical.phi    = Math.max(0.05, Math.min(Math.PI * 0.48, spherical.phi + dy * 0.005));
      lastTouchX = e.touches[0].clientX; lastTouchY = e.touches[0].clientY;
      updateCamera();
    }}
    if (e.touches.length === 2) {{
      const dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      spherical.radius = Math.max(8, Math.min(60, spherical.radius - (dist - lastTouchDist) * 0.05));
      lastTouchDist = dist;
      updateCamera();
    }}
    e.preventDefault();
  }}, {{ passive: false }});
}})();

// ─── LIGHTING ──────────────────────────────────────────────────────────────
const ambientLight = new THREE.AmbientLight(0x334466, 0.6);
scene.add(ambientLight);

const sunLight = new THREE.DirectionalLight(0xffffff, 1.1);
sunLight.position.set(-8, 12, 6);
sunLight.castShadow = true;
scene.add(sunLight);

const fillLight = new THREE.DirectionalLight(0x334466, 0.35);
fillLight.position.set(8, 4, -6);
scene.add(fillLight);

// ─── BASE PLATFORM ─────────────────────────────────────────────────────────
const baseGeo  = new THREE.BoxGeometry(TERRAIN_HALF_W * 2 + 0.5, 0.4, TERRAIN_DEPTH * 2 + 0.5);
const baseMat  = new THREE.MeshLambertMaterial({{ color: 0x1e293b }});
const baseMesh = new THREE.Mesh(baseGeo, baseMat);
baseMesh.position.y = -0.2;
scene.add(baseMesh);

const baseEdges = new THREE.EdgesGeometry(baseGeo);
const baseLines = new THREE.LineSegments(baseEdges, new THREE.LineBasicMaterial({{ color: 0x475569, transparent: true, opacity: 0.5 }}));
baseLines.position.y = -0.2;
scene.add(baseLines);

// ─── TERRAIN GEOMETRY ──────────────────────────────────────────────────────
// We build two separate meshes: calls (right/+X) and puts (left/-X)
// Each is a PlaneGeometry rotated flat with vertices displaced by OI height

// ─── SHADER MATERIAL (per-fragment color — fixes snow cap bleeding) ────────
// Color is computed in the fragment shader from the actual interpolated Y world
// position, not from vertex colors. This prevents white peak color from bleeding
// down steep triangle faces into dark valleys.
const terrainVertexShader = `
  varying vec3 vWorldPos;
  varying vec3 vNormal;
  void main() {{
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vWorldPos = worldPos.xyz;
    vNormal   = normalMatrix * normal;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }}
`;

const terrainFragmentShader = `
  uniform float uMaxHeight;
  uniform float uYP95;      // Y world position of snow cap threshold
  uniform float uGamma;     // color curve gamma — lower = more vivid at mid heights
  uniform int   uSide;      // 0 = put (red), 1 = call (green)

  // Sun light direction (matches scene DirectionalLight at -8, 12, 6)
  uniform vec3  uSunDir;
  uniform vec3  uSunColor;
  uniform float uAmbient;

  varying vec3 vWorldPos;
  varying vec3 vNormal;

  void main() {{
    // Height fraction 0-1 based on actual fragment Y position.
    // Side-specific gamma: puts use a stronger curve (lower gamma) so mid-range
    // OI terrain reaches vivid orange-red instead of sitting in dark crimson.
    float tRaw = clamp(vWorldPos.y / uMaxHeight, 0.0, 1.0);
    float t    = pow(tRaw, uGamma);

    // Slate base color
    vec3 slate = vec3(0.059, 0.090, 0.165);

    vec3 peakColor;
    if (uSide == 1) {{
      // Call: slate → bright lime green
      peakColor = vec3(0.10, 0.66, 0.10);
    }} else {{
      // Put: slate → deep crimson (data-honest — sparse OI stays dark, peaks go bright)
      peakColor = vec3(0.98, 0.16, 0.12);
    }}

    vec3 baseColor = mix(slate, peakColor, t);

    // Snow cap: blend toward white above the 70% height threshold (uYP95)
    float snowT = clamp((vWorldPos.y - uYP95) / max(uMaxHeight - uYP95, 0.001), 0.0, 1.0);
    vec3 color = mix(baseColor, vec3(1.0), snowT);

    // Lambertian diffuse shading using sun direction
    vec3  n        = normalize(vNormal);
    float diffuse  = max(dot(n, normalize(uSunDir)), 0.0);
    vec3  lighting = uAmbient * vec3(1.0) + diffuse * uSunColor;

    gl_FragColor = vec4(color * lighting, 1.0);
  }}
`;

function buildTerrainMesh(side) {{
  const SCOLS = N_STRIKES;
  const DROWS = N_EXPS;

  // Full width = TERRAIN_HALF_W * 2 so both halves share same X coordinate space
  const geo = new THREE.PlaneGeometry(
    TERRAIN_HALF_W * 2,
    TERRAIN_DEPTH,
    SCOLS - 1,
    DROWS - 1
  );
  geo.rotateX(-Math.PI / 2);

  const positions = geo.attributes.position;

  for (let r = 0; r < DROWS; r++) {{
    for (let c = 0; c < SCOLS; c++) {{
      const vertIdx    = r * SCOLS + c;
      const dte        = DATA.expirations[r];
      const depthFrac  = dteToDepthFrac(dte);
      const strikeFrac = c / (SCOLS - 1);

      // X: identical for both sides — same strike at same X position
      const worldX = -TERRAIN_HALF_W + strikeFrac * TERRAIN_HALF_W * 2;

      // Z: calls fan into +Z, puts fan into -Z — both start at Z=0 (0 DTE)
      const worldZ = side === 'call'
        ?  depthFrac * TERRAIN_DEPTH
        : -depthFrac * TERRAIN_DEPTH;

      // OI: same strike index c for both sides — no mirroring needed
      const oi     = smoothedOI(c, r, side);
      const height = oiToHeight(oi); // returns world Y directly (0 to MAX_HEIGHT*2)

      positions.setXYZ(vertIdx, worldX, height, worldZ);
    }}
  }}

  geo.computeVertexNormals();

  // Find the actual peak Y in the geometry — use this as the shader's color ceiling
  // so the gradient always stretches from floor to the real tallest peak,
  // regardless of OI distribution. This fixes puts looking dark when most OI is modest.
  const positions2 = geo.attributes.position;
  let actualMaxY = 0.001; // small floor to avoid divide-by-zero
  for (let i = 0; i < positions2.count; i++) {{
    const y = positions2.getY(i);
    if (y > actualMaxY) actualMaxY = y;
  }}
  console.log('[SHADER] ' + side + ' actual peak Y=' + actualMaxY.toFixed(3) + ' (theoretical MAX_HEIGHT=' + MAX_HEIGHT.toFixed(3) + ')');

  // Snow cap starts at MAX_HEIGHT (tier 2 boundary), absolute ceiling is MAX_HEIGHT * 2
  const snowCapY = MAX_HEIGHT;       // tier 2 boundary — snow starts here
  const sideP75  = SHARED_P95;      // unused but kept for logging

  const mat = new THREE.ShaderMaterial({{
    vertexShader:   terrainVertexShader,
    fragmentShader: terrainFragmentShader,
    uniforms: {{
      uMaxHeight: {{ value: MAX_HEIGHT * 2 }},  // absolute ceiling spans both tiers
      uYP95:      {{ value: snowCapY }},          // = MAX_HEIGHT, snow starts here
      uGamma:     {{ value: side === 'call' ? 0.45 : 0.45 }},
      uSide:      {{ value: side === 'call' ? 1 : 0 }},
      uSunDir:    {{ value: new THREE.Vector3(-8, 12, 6).normalize() }},
      uSunColor:  {{ value: new THREE.Vector3(1.1, 1.1, 1.1) }},
      uAmbient:   {{ value: 0.45 }},
    }},
    side: THREE.DoubleSide,
  }});

  console.log('[SHADER] ' + side + ' — actualMaxY=' + actualMaxY.toFixed(3) + ' snowCapY=' + snowCapY.toFixed(3));

  return new THREE.Mesh(geo, mat);
}}

const callMesh = buildTerrainMesh('call');
const putMesh  = buildTerrainMesh('put');
callMesh.receiveShadow = true;
putMesh.receiveShadow  = true;
scene.add(callMesh);
scene.add(putMesh);

// ─── FLOOR GRID ────────────────────────────────────────────────────────────
// Grid spans full terrain: X = strike axis (-HW to +HW), Z = DTE axis (-DEPTH to +DEPTH)
const gridHelper = new THREE.GridHelper(
  Math.max(TERRAIN_HALF_W * 2, TERRAIN_DEPTH * 2),
  20, 0x1e3a5f, 0x1e3a5f
);
gridHelper.position.y = 0.01;
scene.add(gridHelper);

// ─── CONTOUR LINES ─────────────────────────────────────────────────────────
// For each labeled strike, trace a line across all DTE rows on BOTH sides

const strikeMin    = parseFloat(DATA.strikes[0]);
const strikeMax    = parseFloat(DATA.strikes[DATA.strikes.length - 1]);
const currentPrice = DATA.current_price;
const contourStrikes = [];

// Generate labeled strikes every ~$40 within range
let step = 40;
let start = Math.ceil(strikeMin / step) * step;
for (let s = start; s <= strikeMax; s += step) {{
  contourStrikes.push(s);
}}
// Always include current price
if (!contourStrikes.includes(currentPrice)) {{
  contourStrikes.push(currentPrice);
}}

const labelGroup = new THREE.Group();
scene.add(labelGroup);

contourStrikes.forEach(targetStrike => {{
  const isCurrentPrice = Math.abs(targetStrike - currentPrice) < 1;
  const color   = isCurrentPrice ? 0xf59e0b : 0x5eead4;
  const opacity = isCurrentPrice ? 0.95 : 0.65;

  ['call', 'put'].forEach(side => {{
    const points = [];
    const strikeFrac = (targetStrike - strikeMin) / (strikeMax - strikeMin);
    const colFloat   = strikeFrac * (N_STRIKES - 1);
    const colLo      = Math.floor(colFloat);
    const colHi      = Math.min(colLo + 1, N_STRIKES - 1);
    const colT       = colFloat - colLo;
    const worldX     = -TERRAIN_HALF_W + strikeFrac * TERRAIN_HALF_W * 2;

    DATA.expirations.forEach((dte, r) => {{
      const depthFrac = dteToDepthFrac(dte);
      // Same strike index for both sides — no mirroring
      const oi     = smoothedOI(colLo, r, side) * (1-colT) + smoothedOI(colHi, r, side) * colT;
      const height = oiToHeight(oi) + 0.05;
      const worldZ = side === 'call'
        ?  depthFrac * TERRAIN_DEPTH
        : -depthFrac * TERRAIN_DEPTH;
      points.push(new THREE.Vector3(worldX, height, worldZ));
    }});

    if (points.length < 2) return;
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({{ color, transparent: true, opacity }})
    );

    // Place label at OUTER edge of contour (last point = furthest DTE = back edge)
    // Current price: single center label at Z=0 (0 DTE seam), call side only
    let labelPt;
    let addLabel = true;
    if (isCurrentPrice) {{
      labelPt = points[0].clone();
      // Only one current price label — call side only
      if (side !== 'call') addLabel = false;
    }} else {{
      labelPt = points[points.length - 1].clone();
    }}
    scene.add(line);

    if (addLabel) {{
      const cssClass = isCurrentPrice ? 'price-label current' : 'price-label';
      const label = makeLabel('$' + Math.round(targetStrike), labelPt, cssClass);
      scene.add(label);
    }}
  }});
}});

// ─── CENTER LINE (0 DTE divider) ───────────────────────────────────────────
// At Z=0, runs full strike width (X axis)
const centerPoints = [
  new THREE.Vector3(-TERRAIN_HALF_W, 0, 0),
  new THREE.Vector3( TERRAIN_HALF_W, 0, 0),
];
const centerLine = new THREE.Line(
  new THREE.BufferGeometry().setFromPoints(centerPoints),
  new THREE.LineBasicMaterial({{ color: 0xffffff, transparent: true, opacity: 0.25 }})
);
scene.add(centerLine);

// ─── EXPIRATION RIDGE LINES ────────────────────────────────────────────────
// For each expiration, draw a line across the full X width of the terrain
// following the terrain surface height at that DTE slice.
// This lets the viewer visually trace any expiration across both call and put sides.

DATA.expirations.forEach((dte, r) => {{
  const depthFrac = dteToDepthFrac(dte);
  const isMajor   = (dte === 2 || dte === DATA.expirations[DATA.expirations.length-1] || r % 2 === 0);
  const opacity   = isMajor ? 0.35 : 0.18;
  const color     = 0x94a3b8; // slate-400 — neutral, not competing with contours

  ['call', 'put'].forEach(side => {{
    const points = [];
    const worldZ = side === 'call'
      ?  depthFrac * TERRAIN_DEPTH
      : -depthFrac * TERRAIN_DEPTH;

    // Sample height across all strikes at this DTE
    for (let c = 0; c < N_STRIKES; c++) {{
      const strikeFrac = c / (N_STRIKES - 1);
      const worldX     = -TERRAIN_HALF_W + strikeFrac * TERRAIN_HALF_W * 2;
      const oi     = smoothedOI(c, r, side);
      const height = oiToHeight(oi) + 0.03;
      points.push(new THREE.Vector3(worldX, height, worldZ));
    }}

    const ridgeLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({{ color, transparent: true, opacity }})
    );

    // DTE labels on BOTH X edges of base plate, Y=0
    // High-strike edge (+X) and low-strike edge (-X)
    // Both get labels so at least one set is always visible regardless of rotation
    [TERRAIN_HALF_W + 0.3, -TERRAIN_HALF_W - 0.3].forEach(labelX => {{
      const labelPt = new THREE.Vector3(labelX, 0, worldZ);
      const label = makeLabel(dte + 'd', labelPt, 'dte-label');
      scene.add(label);
    }});

    scene.add(ridgeLine);
  }});
}});

// ─── CSS2D LABEL SYSTEM ────────────────────────────────────────────────────
const css2dRenderer = new THREE.CSS2DRenderer();
css2dRenderer.setSize(container.clientWidth, container.clientHeight);
css2dRenderer.domElement.style.position = 'absolute';
css2dRenderer.domElement.style.top = '0';
css2dRenderer.domElement.style.left = '0';
css2dRenderer.domElement.style.pointerEvents = 'none';
container.appendChild(css2dRenderer.domElement);

// Helper: create a CSS2DObject label at a given 3D position
function makeLabel(text, position, cssClass) {{
  const div = document.createElement('div');
  div.className = cssClass || 'price-label';
  div.textContent = text;
  const label = new THREE.CSS2DObject(div);
  label.position.copy(position);
  return label;
}}

// ─── RESIZE HANDLER ────────────────────────────────────────────────────────
window.addEventListener('resize', () => {{
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
  css2dRenderer.setSize(container.clientWidth, container.clientHeight);
}});

// ─── RENDER LOOP ───────────────────────────────────────────────────────────
function animate() {{
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
  css2dRenderer.render(scene, camera);
}}
animate();
</script>
</body>
</html>"""

    return html


def main():
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AMD'
    print(f"[START] Building 3D relief model for {ticker}...")

    data = fetch_options_data(ticker)
    html = render_html(data)

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.html',
        prefix=f'relief3d_{ticker}_',
        delete=False, encoding='utf-8'
    ) as f:
        f.write(html)
        path = f.name

    print(f"[DONE] Relief model written to: {path}")
    print(f"[DONE] Opening in browser... (drag to rotate, scroll to zoom)")
    webbrowser.open(f'file://{path}')


if __name__ == '__main__':
    main()
