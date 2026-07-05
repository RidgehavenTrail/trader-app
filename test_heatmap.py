"""
Options open interest heatmap — standalone test script.
Fetches real options chain data via yfinance and renders a self-contained
HTML file with the butterfly heatmap (puts left, calls right).

Usage:
    python3 test_heatmap.py AMD
    python3 test_heatmap.py AAPL
    python3 test_heatmap.py SPY
"""

import sys
import json
import webbrowser
import tempfile
import os
from datetime import datetime, date

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)


def fetch_options_data(ticker_symbol):
    """
    Fetches the full options chain for all expirations up to 90 days out.
    Returns a dict ready to pass into the heatmap renderer.
    """
    stock = yf.Ticker(ticker_symbol)
    current_price = None

    try:
        hist = stock.history(period="2d")
        if not hist.empty:
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

    # Filter to expirations within 90 days
    valid_exps = []
    for exp in expirations:
        exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
        dte = (exp_date - today).days
        if 0 <= dte <= 90:
            valid_exps.append((dte, exp))

    if not valid_exps:
        print("No expirations found within 90 days.")
        sys.exit(1)

    print(f"[DATA] Found {len(valid_exps)} expirations within 90 days: "
          f"{[f'{dte}d' for dte, _ in valid_exps]}")

    # Collect all strikes across all expirations
    all_strikes = set()
    chain_data = {}

    for dte, exp in valid_exps:
        try:
            chain = stock.option_chain(exp)
            puts = chain.puts[['strike', 'openInterest']].copy()
            calls = chain.calls[['strike', 'openInterest']].copy()

            # Raw DataFrame diagnostic
            print(f"[RAW] {exp} calls columns: {list(chain.calls.columns)}")
            print(f"[RAW] {exp} calls first row: {chain.calls.iloc[0].to_dict()}")
            print(f"[RAW] {exp} calls strike col first 3: {chain.calls['strike'].values[:3]}")

            for strike in puts['strike'].values:
                all_strikes.add(str(float(strike)))
            for strike in calls['strike'].values:
                all_strikes.add(str(float(strike)))

            # Use zip over column arrays directly — avoids DataFrame index
            # leaking into keys when using iterrows()
            chain_data[dte] = {
                'puts': {
                    str(float(strike)): int(oi)
                    for strike, oi in zip(
                        puts['strike'].values,
                        puts['openInterest'].values
                    )
                },
                'calls': {
                    str(float(strike)): int(oi)
                    for strike, oi in zip(
                        calls['strike'].values,
                        calls['openInterest'].values
                    )
                }
            }

            # Diagnostic — print first 3 call entries to verify strike values
            sample = list(chain_data[dte]['calls'].items())[:3]
            print(f"[DIAG] {exp} ({dte} DTE) sample call keys: {sample}")
            print(f"[DATA] {exp} ({dte} DTE): "
                  f"{len(puts)} put strikes, {len(calls)} call strikes")
        except Exception as e:
            print(f"[WARN] Could not fetch chain for {exp}: {e}")

    # Apply strike filter:
    # 1. Start with ±30% of current price
    # 2. If that yields fewer than 20 strikes, expand to show all
    # 3. Additionally remove strikes with zero OI across ALL expirations
    # Filter strikes by minimum OI threshold rather than price range.
    # This handles the weekly/monthly asymmetry — deep ITM strikes ($5-$100)
    # exist in the chain but have near-zero OI and should be excluded.
    # Only include a strike if at least one expiration has OI >= min_oi.
    # Also apply a ±30% price range as a secondary cap to exclude truly
    # irrelevant strikes even if they somehow have OI.
    sorted_strikes = sorted(all_strikes, key=lambda s: float(s))
    lower = current_price * 0.70
    upper = current_price * 1.30
    min_oi = 100  # minimum OI at any expiration to include a strike

    print(f"[FILTER] Price=${current_price:.2f}, range=${lower:.0f}-${upper:.0f}, min_oi={min_oi}")

    def max_oi_for_strike(strike):
        """Return the highest OI for this strike across all expirations."""
        best = 0
        for data in chain_data.values():
            best = max(best, data['calls'].get(strike, 0))
            best = max(best, data['puts'].get(strike, 0))
        return best

    filtered = [
        s for s in sorted_strikes
        if lower <= float(s) <= upper
        and max_oi_for_strike(s) >= min_oi
    ]

    # If too few strikes survive, progressively relax the min_oi threshold
    for fallback_oi in [50, 10, 1]:
        if len(filtered) >= 20:
            break
        filtered = [
            s for s in sorted_strikes
            if lower <= float(s) <= upper
            and max_oi_for_strike(s) >= fallback_oi
        ]
        if len(filtered) >= 20:
            print(f"[FILTER] Relaxed min_oi to {fallback_oi} — {len(filtered)} strikes")

    # Final fallback — show all strikes in price range
    if len(filtered) < 10:
        filtered = [s for s in sorted_strikes if lower <= float(s) <= upper]
        print(f"[FILTER] Final fallback — showing all {len(filtered)} strikes in range")

    print(f"[FILTER] Result: {len(filtered)} strikes "
          f"(${float(filtered[0]):.0f}–${float(filtered[-1]):.0f})"
          if filtered else "[FILTER] No strikes survived filter")

    # Diagnostic — print non-zero OI at filtered strikes for later expirations
    for dte, data in sorted(chain_data.items()):
        if dte <= 8:
            continue
        call_hits = [(s, data['calls'].get(s, 0)) for s in filtered
                     if data['calls'].get(s, 0) > 0]
        put_hits  = [(s, data['puts'].get(s, 0)) for s in filtered
                     if data['puts'].get(s, 0) > 0]
        print(f"[OI CHECK] DTE {dte}: "
              f"{len(call_hits)} call strikes with OI, "
              f"{len(put_hits)} put strikes with OI")
        if call_hits:
            print(f"  Top 5 calls: {sorted(call_hits, key=lambda x: -x[1])[:5]}")
        if put_hits:
            print(f"  Top 5 puts:  {sorted(put_hits, key=lambda x: -x[1])[:5]}")

    # Find peak OI for summary tiles
    max_call_oi = 0
    max_call_strike = None
    max_call_dte = None
    max_put_oi = 0
    max_put_strike = None
    max_put_dte = None

    for dte, data in chain_data.items():
        for strike, oi in data['calls'].items():
            if strike in filtered and oi > max_call_oi:
                max_call_oi = oi
                max_call_strike = strike
                max_call_dte = dte
        for strike, oi in data['puts'].items():
            if strike in filtered and oi > max_put_oi:
                max_put_oi = oi
                max_put_strike = strike
                max_put_dte = dte

    print(f"[DATA] Peak call OI: ${float(max_call_strike) if max_call_strike else 0:.0f} at {max_call_dte} DTE "
          f"({max_call_oi:,})")
    print(f"[DATA] Peak put OI:  ${float(max_put_strike) if max_put_strike else 0:.0f} at {max_put_dte} DTE "
          f"({max_put_oi:,})")

    return {
        'ticker': ticker_symbol,
        'current_price': current_price,
        'strikes': filtered,
        'expirations': sorted([dte for dte, _ in valid_exps]),
        'chain': {str(dte): data for dte, data in chain_data.items()},
        'max_call_oi': max_call_oi,
        'max_put_oi': max_put_oi,
        'peak_call': {'strike': max_call_strike, 'dte': max_call_dte,
                      'oi': max_call_oi},
        'peak_put': {'strike': max_put_strike, 'dte': max_put_dte,
                     'oi': max_put_oi},
        'exp_count': len(valid_exps),
        'debug': {
            'valid_exps': [(dte, exp) for dte, exp in valid_exps],
            'chain_keys': sorted([int(k) for k in
                                  {str(dte): None
                                   for dte, _ in valid_exps}.keys()]),
        }
    }


def render_html(data):
    """Renders a self-contained HTML file with the options heatmap."""

    data_json = json.dumps(data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{data['ticker']} Options Heatmap</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f172a;
    color: #f8fafc;
    padding: 24px;
    min-height: 100vh;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }}
  .ticker {{
    font-size: 22px;
    font-weight: 500;
    color: #f8fafc;
  }}
  .subtitle {{
    font-size: 13px;
    color: #94a3b8;
    margin-left: 10px;
  }}
  .legend {{
    display: flex;
    gap: 20px;
    font-size: 12px;
    color: #94a3b8;
    align-items: center;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .legend-ramp {{
    display: flex;
    gap: 2px;
  }}
  .legend-swatch {{
    width: 8px;
    height: 12px;
    border-radius: 1px;
  }}
  .canvas-wrap {{
    background: #0f172a;
    border-radius: var(--border-radius-lg);
    padding: 8px;
    margin-bottom: 8px;
    border: 1px solid rgba(71,85,105,0.4);
    width: 100%;
    box-sizing: border-box;
  }}
  canvas {{ display: block; }}
  .axis-labels {{
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #64748b;
    padding: 4px 48px 0;
    margin-bottom: 16px;
  }}
  .axis-center {{
    font-weight: 500;
    color: #94a3b8;
  }}
  .tiles {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }}
  .tile {{
    background: #1e293b;
    border-radius: 8px;
    padding: 10px 12px;
    text-align: center;
    border: 1px solid rgba(71,85,105,0.3);
  }}
  .tile-label {{
    font-size: 10px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }}
  .tile-value {{
    font-size: 13px;
    font-weight: 500;
    color: #f1f5f9;
  }}
  .tile-value.call {{ color: #84cc16; }}
  .tile-value.put  {{ color: #fb923c; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <span class="ticker">{data['ticker']}</span>
    <span class="subtitle">Open interest heatmap · {data['exp_count']} expirations · up to 90 DTE</span>
  </div>
  <div class="legend">
    <div class="legend-item">
      <div class="legend-ramp">
        <div class="legend-swatch" style="background:rgba(22,163,74,0.08)"></div>
        <div class="legend-swatch" style="background:#16a34a"></div>
        <div class="legend-swatch" style="background:#84cc16"></div>
      </div>
      Calls (low → high OI)
    </div>
    <div class="legend-item">
      <div class="legend-ramp">
        <div class="legend-swatch" style="background:rgba(220,38,38,0.08)"></div>
        <div class="legend-swatch" style="background:#dc2626"></div>
        <div class="legend-swatch" style="background:#fb923c"></div>
      </div>
      Puts (low → high OI)
    </div>
    <div class="legend-item">
      <span style="display:inline-block;width:24px;height:2px;background:#f59e0b;vertical-align:middle;margin-right:4px;"></span>
      Current price
    </div>
  </div>
</div>

<div class="canvas-wrap">
  <canvas id="heatmap"></canvas>
</div>

<div class="axis-labels">
  <span>← Puts (90 DTE)</span>
  <span>← Puts (42 DTE)</span>
  <span>← Puts (14 DTE)</span>
  <span class="axis-center">0 DTE</span>
  <span>Calls (14 DTE) →</span>
  <span>Calls (42 DTE) →</span>
  <span>Calls (90 DTE) →</span>
</div>

<div class="tiles">
  <div class="tile">
    <div class="tile-label">Current price</div>
    <div class="tile-value">${data['current_price']:,.2f}</div>
  </div>
  <div class="tile">
    <div class="tile-label">Peak call OI</div>
    <div class="tile-value call">
      ${float(data['peak_call']['strike']):.0f} · {data['peak_call']['dte']} DTE
      <br><span style="font-size:11px;color:#84cc16;">{data['peak_call']['oi']:,}</span>
    </div>
  </div>
  <div class="tile">
    <div class="tile-label">Peak put OI</div>
    <div class="tile-value put">
      ${float(data['peak_put']['strike']):.0f} · {data['peak_put']['dte']} DTE
      <br><span style="font-size:11px;color:#fb923c;">{data['peak_put']['oi']:,}</span>
    </div>
  </div>
  <div class="tile">
    <div class="tile-label">Strikes shown</div>
    <div class="tile-value">{len(data['strikes'])}</div>
  </div>
</div>

<script>
const DATA = {data_json};

// Targeted diagnostic — verify JS can find known OI values
// Based on Python output: DTE 58 should have calls['380.0'] = 20999
const testDTE = DATA.expirations.find(d => d >= 55);
if (testDTE) {{
  const testChain = DATA.chain[String(testDTE)];
  console.log(`[JS LOOKUP] DTE ${{testDTE}} chain exists:`, !!testChain);
  if (testChain) {{
    console.log(`[JS LOOKUP] DTE ${{testDTE}} call keys sample:`, 
      Object.keys(testChain.calls).slice(0, 5));
    console.log(`[JS LOOKUP] DTE ${{testDTE}} calls['380.0']:`, testChain.calls['380.0']);
    console.log(`[JS LOOKUP] DTE ${{testDTE}} total non-zero calls:`,
      Object.values(testChain.calls).filter(v => v > 0).length);
  }}
}}

// Also verify strikes array contains '380.0'
console.log('[JS LOOKUP] strikes contains 380.0:', DATA.strikes.includes('380.0'));
console.log('[JS LOOKUP] strikes[0] type:', typeof DATA.strikes[0]);
console.log('[JS LOOKUP] strikes sample:', DATA.strikes.slice(0, 3));

const canvas = document.getElementById('heatmap');
const dpr = window.devicePixelRatio || 1;
const W = window.innerWidth - 48;
const H = 500;
canvas.style.width = W + 'px';
canvas.style.height = H + 'px';
canvas.width = W * dpr;
canvas.height = H * dpr;
console.log('[HEATMAP] Canvas W:', W);
const ctx = canvas.getContext('2d');
ctx.scale(dpr, dpr);

ctx.fillStyle = '#0f172a';
ctx.fillRect(0, 0, W, H);

const YPAD_LEFT = 52;
const YPAD_RIGHT = 8;
const XPAD_TOP = 10;
const XPAD_BOTTOM = 24;
const plotW = W - YPAD_LEFT - YPAD_RIGHT;
const plotH = H - XPAD_TOP - XPAD_BOTTOM;

const strikes = DATA.strikes;
const expirations = DATA.expirations;
const currentPrice = DATA.current_price;

// Center of the PLOT area (not canvas), accounting for Y axis padding
// Put half-width and call half-width must both fit within plotW/2
const halfW = plotW / 2;
const center = YPAD_LEFT + halfW;

// Compressed time scale — 3 zones
// Zone 1: 0-14 DTE = 42% of half-width
// Zone 2: 14-42 DTE = 33% of half-width  
// Zone 3: 42-90 DTE = 25% of half-width
function dteToFrac(dte) {{
  const w1 = 0.42, w2 = 0.33, w3 = 0.25;
  if (dte <= 0) return 0;
  if (dte <= 14) return (dte / 14) * w1;
  if (dte <= 42) return w1 + ((dte - 14) / 28) * w2;
  return Math.min(1.0, w1 + w2 + ((dte - 42) / 48) * w3);
}}

// Pre-compute column boundaries for each expiration
// Each column owns the space from the midpoint to the previous expiration
// to the midpoint to the next expiration — no overlaps, no gaps
function computeColBounds(exps) {{
  const bounds = [];
  for (let i = 0; i < exps.length; i++) {{
    const dte = exps[i];
    const prevDte = i > 0 ? exps[i - 1] : 0;
    const nextDte = i < exps.length - 1 ? exps[i + 1] : Math.min(dte + (dte - prevDte), 90);
    const leftFrac  = dteToFrac((dte + prevDte) / 2);
    const rightFrac = dteToFrac((dte + nextDte) / 2);
    bounds.push({{ dte, leftFrac, rightFrac }});
  }}
  return bounds;
}}

const colBounds = computeColBounds(expirations);

function strikeToY(strike) {{
  const sv = parseFloat(strike);
  const minS = parseFloat(strikes[0]);
  const maxS = parseFloat(strikes[strikes.length - 1]);
  const frac = (sv - minS) / (maxS - minS);
  return XPAD_TOP + (1 - frac) * plotH;
}}

// Cell height — use actual strike spacing in pixels, minimum 5px
const gaps = [];
for (let i = 1; i < strikes.length; i++) {{
  gaps.push(strikeToY(strikes[i - 1]) - strikeToY(strikes[i]));
}}
const medianGap = gaps.length > 0 ? gaps.sort((a,b) => a-b)[Math.floor(gaps.length/2)] : 8;
const cellH = Math.max(medianGap, 5);

// Color scaling — log scale for skewed OI distributions
const allOI = [];
expirations.forEach(dte => {{
  const d = DATA.chain[String(dte)];
  if (!d) return;
  strikes.forEach(s => {{
    const c = d.calls[s] || 0;
    const p = d.puts[s] || 0;
    if (c > 0) allOI.push(c);
    if (p > 0) allOI.push(p);
  }});
}});
allOI.sort((a, b) => a - b);
const p95idx = Math.floor(allOI.length * 0.95);
const maxOI = allOI.length > 0 ? Math.max(allOI[p95idx] || 1, 1) : 1;
console.log('[HEATMAP] OI range: min=' + allOI[0] + ' p95=' + maxOI + ' max=' + allOI[allOI.length-1]);

function tFromOI(oi) {{
  if (oi <= 0) return 0;
  // Log scale: spreads gradient across heavily skewed distributions
  return Math.min(Math.log1p(oi) / Math.log1p(maxOI), 1.0);
}}

function oiToCallColor(oi) {{
  const t = tFromOI(oi);
  if (t === 0) return 'rgba(22,163,74,0.03)';
  const r = Math.round(20 * (1 - t));
  const g = Math.round(60 + (210 - 60) * t);
  const b = Math.round(20 * (1 - t));
  return `rgba(${{r}},${{g}},${{b}},${{0.08 + t * 0.92}})`;
}}

function oiToPutColor(oi) {{
  const t = tFromOI(oi);
  if (t === 0) return 'rgba(220,38,38,0.03)';
  const r = Math.round(180 + (251 - 180) * t);
  const g = Math.round(38 * (1 - t) + 50 * t * 0.3);
  const b = Math.round(38 * (1 - t));
  return `rgba(${{r}},${{g}},${{b}},${{0.08 + t * 0.92}})`;
}}

// Draw cells — one column per expiration, no overlaps
// Use strike INDEX for Y positioning (not strike value) to ensure
// cells tile perfectly with no gaps regardless of strike spacing
colBounds.forEach(({{ dte, leftFrac, rightFrac }}) => {{
  const d = DATA.chain[String(dte)];
  if (!d) return;

  const callX = Math.round(center + leftFrac * halfW);
  const callW = Math.max(Math.round((rightFrac - leftFrac) * halfW) - 1, 1);
  const putX  = Math.round(center - rightFrac * halfW);
  const putW  = Math.max(Math.round((rightFrac - leftFrac) * halfW) - 1, 1);
  const rowH  = Math.max(Math.floor(plotH / strikes.length), 1);

  // Count how many cells will actually be drawn for this expiration
  let callsDrawn = 0, putsDrawn = 0;
  strikes.forEach((strike, si) => {{
    const callOI = d.calls[strike] || 0;
    const putOI  = d.puts[strike]  || 0;
    if (callOI > 0) callsDrawn++;
    if (putOI > 0) putsDrawn++;
  }});
  console.log(`[DRAW] DTE ${{dte}}: callX=${{callX}} callW=${{callW}} putX=${{putX}} putW=${{putW}} rowH=${{rowH}} callsDrawn=${{callsDrawn}} putsDrawn=${{putsDrawn}}`);

  strikes.forEach((strike, si) => {{
    // Y from top: si=0 is highest strike (strikes array sorted ascending,
    // so reverse the index for top-to-bottom display)
    const ri = strikes.length - 1 - si;
    const y = XPAD_TOP + Math.round((ri / strikes.length) * plotH);
    const rowH = Math.max(Math.floor(plotH / strikes.length), 1);

    // Try both float and integer key formats since yfinance can return either
    const callOI = d.calls[strike] || d.calls[Math.round(strike)] || 0;
    const putOI  = d.puts[strike]  || d.puts[Math.round(strike)]  || 0;

    if (callOI > 0) {{
      ctx.fillStyle = oiToCallColor(callOI);
      ctx.fillRect(callX, y, callW, rowH);
    }}
    if (putOI > 0) {{
      ctx.fillStyle = oiToPutColor(putOI);
      ctx.fillRect(putX, y, putW, rowH);
    }}
  }});
}});

// Horizontal grid lines at labeled strikes
ctx.strokeStyle = 'rgba(255,255,255,0.04)';
ctx.lineWidth = 0.5;
const labelEvery = Math.max(1, Math.floor(strikes.length / 18));
strikes.forEach((s, i) => {{
  if (i % labelEvery === 0) {{
    const y = strikeToY(s);
    ctx.beginPath();
    ctx.moveTo(YPAD_LEFT, y);
    ctx.lineTo(YPAD_LEFT + plotW, y);
    ctx.stroke();
  }}
}});

// Zone boundary lines at 14 DTE and 42 DTE
ctx.setLineDash([3, 4]);
ctx.strokeStyle = 'rgba(255,255,255,0.1)';
[14, 42].forEach(dte => {{
  const frac = dteToFrac(dte);
  [center + frac * halfW, center - frac * halfW].forEach(x => {{
    ctx.beginPath();
    ctx.moveTo(x, XPAD_TOP);
    ctx.lineTo(x, XPAD_TOP + plotH);
    ctx.stroke();
  }});
}});
ctx.setLineDash([]);

// Current price line
const priceY = strikeToY(currentPrice);
ctx.strokeStyle = '#f59e0b';
ctx.lineWidth = 1.5;
ctx.beginPath();
ctx.moveTo(YPAD_LEFT, priceY);
ctx.lineTo(YPAD_LEFT + plotW, priceY);
ctx.stroke();

// Y axis — strike labels
ctx.font = '11px monospace';
ctx.textAlign = 'right';
const strikeStep = strikes.length > 1 ? parseFloat(strikes[1]) - parseFloat(strikes[0]) : 5;
strikes.forEach((s, i) => {{
  if (i % labelEvery === 0) {{
    const sv = parseFloat(s);
    const y = strikeToY(s);
    const isNearPrice = Math.abs(sv - currentPrice) < strikeStep * 0.6;
    ctx.fillStyle = isNearPrice ? '#f59e0b' : 'rgba(255,255,255,0.35)';
    ctx.fillText('$' + sv.toFixed(0), YPAD_LEFT - 4, y + 4);
  }}
}});

// Center line
ctx.strokeStyle = 'rgba(255,255,255,0.15)';
ctx.lineWidth = 1;
ctx.beginPath();
ctx.moveTo(center, XPAD_TOP);
ctx.lineTo(center, XPAD_TOP + plotH);
ctx.stroke();

// X axis — DTE labels
ctx.fillStyle = 'rgba(255,255,255,0.4)';
ctx.font = '10px sans-serif';
ctx.textAlign = 'center';
colBounds.forEach(({{ dte, leftFrac, rightFrac }}) => {{
  const frac = (leftFrac + rightFrac) / 2;
  const label = dte + 'd';
  ctx.fillText(label, center + frac * halfW, XPAD_TOP + plotH + 15);
  ctx.fillText(label, center - frac * halfW, XPAD_TOP + plotH + 15);
}});
ctx.fillStyle = 'rgba(255,255,255,0.7)';
ctx.font = '500 11px sans-serif';
ctx.fillText('0', center, XPAD_TOP + plotH + 15);

console.log('[HEATMAP] Rendered', strikes.length, 'strikes x', expirations.length, 'expirations. cellH=' + cellH.toFixed(1) + 'px');
</script>
</body>
</html>"""

    return html


def main():
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AMD'
    print(f"[START] Fetching options chain for {ticker}...")

    data = fetch_options_data(ticker)
    html = render_html(data)

    # Write to a temp file and open in browser
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.html',
        prefix=f'heatmap_{ticker}_',
        delete=False, encoding='utf-8'
    ) as f:
        f.write(html)
        path = f.name

    print(f"[DONE] Heatmap written to: {path}")
    print(f"[DONE] Opening in browser...")
    webbrowser.open(f'file://{path}')


if __name__ == '__main__':
    main()
