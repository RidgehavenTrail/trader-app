"""
Options open interest 3D impulse model — lollipop visualization.
Each OI data point rendered as a vertical line stem + sphere top.
No smoothing — raw OI values mapped directly to height.
OI < 100 contracts filtered out entirely.

Same butterfly layout and coordinate system as v1 (test_heatmap_3d.py)
for direct visual comparison.

Usage:
    python test_heatmap_3d_impulse.py AMD
    python test_heatmap_3d_impulse.py AAPL
    python test_heatmap_3d_impulse.py SPY
"""

import sys
import json
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
    Identical to v1 — strike keys as str(float(strike)), .values arrays throughout.
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

    # Peak OI summary for tiles
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
<title>{ticker} Options Impulse Model</title>

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
    <span class="subtitle">Open interest impulse model · {n_exps} expirations · {n_strikes} strikes · drag to rotate · scroll to zoom</span>
  </div>
  <div class="legend">
    <span><span class="legend-swatch" style="background:#84cc16;"></span>Calls</span>
    <span><span class="legend-swatch" style="background:#fb923c;"></span>Puts</span>
    <span><span style="display:inline-block;width:20px;height:2px;background:#f59e0b;vertical-align:middle;margin-right:4px;"></span>${curr_price:,.2f}</span>
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
const TERRAIN_HALF_W = 10;
const TERRAIN_DEPTH  = 8;
const MAX_HEIGHT     = TERRAIN_HALF_W * 2 * 0.22; // 4.4 world units — same as v1
const OI_FLOOR       = 100; // impulses below this are not rendered

// Shared p95 scale computed from combined call+put pool (same two-tier rules as v1)
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
  const p95   = all[Math.floor(all.length * 0.95)] || 1;
  const maxOI = p95 * 2;
  console.log('[OI] samples:', all.length, '| p95:', p95, '| tier2 cap:', maxOI);
  return {{ SHARED_P95: p95, SHARED_MAX_OI: maxOI }};
}})();

// Same DTE compressed scale as v1
function dteToDepthFrac(dte) {{
  if (dte <= 14) return (dte / 14) * 0.42;
  if (dte <= 42) return 0.42 + ((dte - 14) / 28) * 0.33;
  return Math.min(1.0, 0.75 + ((dte - 42) / 48) * 0.25);
}}

// Same two-tier height mapping as v1 — returns absolute world Y
function oiToHeight(oi) {{
  const adjusted = oi - OI_FLOOR;
  if (adjusted <= 0) return 0;
  if (adjusted <= SHARED_P95) {{
    return (adjusted / SHARED_P95) * MAX_HEIGHT;
  }} else {{
    const tier2Frac = Math.min((adjusted - SHARED_P95) / (SHARED_MAX_OI - SHARED_P95), 1.0);
    return MAX_HEIGHT + tier2Frac * MAX_HEIGHT;
  }}
}}

// Color for a given height: slate → peak color → white (snow cap above MAX_HEIGHT)
function heightToColor(worldY, side) {{
  const tRaw  = Math.min(worldY / (MAX_HEIGHT * 2), 1.0);
  const t     = Math.pow(tRaw, 0.45); // gamma curve — same as v1 shader

  const slate = [0.059, 0.090, 0.165];
  const peak  = side === 'call' ? [0.10, 0.66, 0.10] : [0.98, 0.16, 0.12];

  // Blend slate → peak
  let r = slate[0] + (peak[0] - slate[0]) * t;
  let g = slate[1] + (peak[1] - slate[1]) * t;
  let b = slate[2] + (peak[2] - slate[2]) * t;

  // Snow cap: blend toward white above MAX_HEIGHT (tier 2 boundary)
  const snowT = Math.max(0, Math.min((worldY - MAX_HEIGHT) / MAX_HEIGHT, 1.0));
  r += (1.0 - r) * snowT;
  g += (1.0 - g) * snowT;
  b += (1.0 - b) * snowT;

  return new THREE.Color(r, g, b);
}}

// ─── THREE.JS SETUP ────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const renderer  = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setClearColor(0x0f172a, 1);
container.appendChild(renderer.domElement);

const scene  = new THREE.Scene();
scene.fog    = new THREE.FogExp2(0x0f172a, 0.018);

const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 200);

// ─── ORBIT CONTROLS (inline) ───────────────────────────────────────────────
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
scene.add(new THREE.AmbientLight(0x334466, 0.7));
const sunLight = new THREE.DirectionalLight(0xffffff, 1.0);
sunLight.position.set(-8, 12, 6);
scene.add(sunLight);

// ─── BASE PLATFORM ─────────────────────────────────────────────────────────
const baseGeo  = new THREE.BoxGeometry(TERRAIN_HALF_W * 2 + 0.5, 0.4, TERRAIN_DEPTH * 2 + 0.5);
const baseMesh = new THREE.Mesh(baseGeo, new THREE.MeshLambertMaterial({{ color: 0x1e293b }}));
baseMesh.position.y = -0.2;
scene.add(baseMesh);
const baseLines = new THREE.LineSegments(
  new THREE.EdgesGeometry(baseGeo),
  new THREE.LineBasicMaterial({{ color: 0x475569, transparent: true, opacity: 0.5 }})
);
baseLines.position.y = -0.2;
scene.add(baseLines);

// ─── FLOOR GRID ────────────────────────────────────────────────────────────
const gridHelper = new THREE.GridHelper(
  Math.max(TERRAIN_HALF_W * 2, TERRAIN_DEPTH * 2), 20, 0x1e3a5f, 0x1e3a5f
);
gridHelper.position.y = 0.01;
scene.add(gridHelper);

// ─── CURRENT PRICE LINE (amber, runs full depth at Z=0) ────────────────────
const strikeMin  = parseFloat(DATA.strikes[0]);
const strikeMax  = parseFloat(DATA.strikes[DATA.strikes.length - 1]);
const currentPrice = DATA.current_price;
const priceFrac  = (currentPrice - strikeMin) / (strikeMax - strikeMin);
const priceX     = -TERRAIN_HALF_W + priceFrac * TERRAIN_HALF_W * 2;

scene.add(new THREE.Line(
  new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(priceX, 0.02, -TERRAIN_DEPTH),
    new THREE.Vector3(priceX, 0.02,  TERRAIN_DEPTH),
  ]),
  new THREE.LineBasicMaterial({{ color: 0xf59e0b, transparent: true, opacity: 0.9 }})
));

// ─── CSS2D SETUP ───────────────────────────────────────────────────────────
const css2dRenderer = new THREE.CSS2DRenderer();
css2dRenderer.setSize(container.clientWidth, container.clientHeight);
css2dRenderer.domElement.style.position = 'absolute';
css2dRenderer.domElement.style.top  = '0';
css2dRenderer.domElement.style.left = '0';
css2dRenderer.domElement.style.pointerEvents = 'none';
container.appendChild(css2dRenderer.domElement);

function makeLabel(text, position, cssClass) {{
  const div = document.createElement('div');
  div.className = cssClass || 'price-label';
  div.textContent = text;
  const label = new THREE.CSS2DObject(div);
  label.position.copy(position);
  return label;
}}

// Current price label at center seam (Z=0)
scene.add(makeLabel('$' + Math.round(currentPrice), new THREE.Vector3(priceX, 0.1, 0), 'price-label current'));

// ─── DTE LABELS on base plate edges ────────────────────────────────────────
DATA.expirations.forEach(dte => {{
  const depthFrac = dteToDepthFrac(dte);
  ['call', 'put'].forEach(side => {{
    const worldZ = side === 'call' ?  depthFrac * TERRAIN_DEPTH : -depthFrac * TERRAIN_DEPTH;
    [TERRAIN_HALF_W + 0.3, -TERRAIN_HALF_W - 0.3].forEach(labelX => {{
      scene.add(makeLabel(dte + 'd', new THREE.Vector3(labelX, 0, worldZ), 'dte-label'));
    }});
  }});
}});

// ─── IMPULSE RENDERING ─────────────────────────────────────────────────────
// Each OI data point (strike × DTE × side) with OI >= OI_FLOOR gets:
//   - A Line stem from Y=0 to Y=height
//   - A SphereGeometry lollipop top at Y=height
// No smoothing — raw OI values only.
// Color encodes height (same gradient + snow cap logic as v1 shader).

const SPHERE_RADIUS = 0.12; // uniform size regardless of OI
const sphereGeo = new THREE.SphereGeometry(SPHERE_RADIUS, 8, 6); // shared geometry

let stemCount = 0;

DATA.expirations.forEach(dte => {{
  const d = DATA.chain[String(dte)];
  if (!d) return;
  const depthFrac = dteToDepthFrac(dte);

  ['call', 'put'].forEach(side => {{
    const oiMap  = side === 'call' ? d.calls : d.puts;
    const worldZ = side === 'call' ?  depthFrac * TERRAIN_DEPTH : -depthFrac * TERRAIN_DEPTH;

    DATA.strikes.forEach((s, si) => {{
      const oi = oiMap[s] || 0;
      if (oi < OI_FLOOR) return; // skip sub-floor impulses entirely

      const strikeFrac = si / (DATA.strikes.length - 1);
      const worldX     = -TERRAIN_HALF_W + strikeFrac * TERRAIN_HALF_W * 2;
      const worldY     = oiToHeight(oi);
      if (worldY <= 0) return;

      const color = heightToColor(worldY, side);

      // Stem: Line from base to top
      const stemGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(worldX, 0.01, worldZ),
        new THREE.Vector3(worldX, worldY, worldZ),
      ]);
      scene.add(new THREE.Line(stemGeo, new THREE.LineBasicMaterial({{
        color, transparent: true, opacity: 0.75
      }})));

      // Lollipop top: sphere at tip
      const sphere = new THREE.Mesh(sphereGeo, new THREE.MeshLambertMaterial({{ color }}));
      sphere.position.set(worldX, worldY, worldZ);
      scene.add(sphere);

      stemCount++;
    }});
  }});
}});

console.log('[IMPULSE] Rendered', stemCount, 'stems');

// ─── RESIZE ────────────────────────────────────────────────────────────────
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
    print(f"[START] Building impulse model for {ticker}...")

    data = fetch_options_data(ticker)
    html = render_html(data)

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.html',
        prefix=f'impulse_{ticker}_',
        delete=False, encoding='utf-8'
    ) as f:
        f.write(html)
        path = f.name

    print(f"[DONE] Impulse model written to: {path}")
    print(f"[DONE] Opening in browser...")
    webbrowser.open(f'file://{path}')


if __name__ == '__main__':
    main()
