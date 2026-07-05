"""
save_oi_snapshot.py — Pull AMD (or any ticker) full options chain OI and save to JSON.
Usage: python save_oi_snapshot.py AMD
"""
import sys
import json
import os
from datetime import datetime, date
import yfinance as yf

ticker_symbol = sys.argv[1].upper() if len(sys.argv) > 1 else 'AMD'
stock = yf.Ticker(ticker_symbol)

today = date.today().isoformat()
out = {
    'ticker':       ticker_symbol,
    'snapshot_date': today,
    'snapshot_time': datetime.now().isoformat(),
    'current_price': None,
    'expirations':  [],
    'chain':        {}
}

# Current price
try:
    hist = stock.history(period='2d')
    out['current_price'] = float(hist['Close'].iloc[-1])
    print(f"[SNAP] {ticker_symbol} @ ${out['current_price']:.2f}")
except Exception as e:
    print(f"[WARN] Could not get price: {e}")

# Full chain — every expiration yfinance has
expirations = stock.options
print(f"[SNAP] {len(expirations)} expirations found")

for exp in expirations:
    try:
        chain = stock.option_chain(exp)
        puts  = chain.puts[['strike','openInterest','lastPrice','impliedVolatility']].copy()
        calls = chain.calls[['strike','openInterest','lastPrice','impliedVolatility']].copy()

        out['chain'][exp] = {
            'puts':  {str(float(r.strike)): {
                'oi': int(r.openInterest),
                'last': float(r.lastPrice),
                'iv': float(r.impliedVolatility)
            } for r in puts.itertuples()},
            'calls': {str(float(r.strike)): {
                'oi': int(r.openInterest),
                'last': float(r.lastPrice),
                'iv': float(r.impliedVolatility)
            } for r in calls.itertuples()}
        }
        out['expirations'].append(exp)
        print(f"[SNAP] {exp}: {len(puts)} puts, {len(calls)} calls")
    except Exception as e:
        print(f"[WARN] Skipped {exp}: {e}")

# Save to Trader App directory
out_dir  = r"C:\Users\pguth\OneDrive\Desktop\Trader App"
out_path = os.path.join(out_dir, f"oi_snapshot_{ticker_symbol}_{today}.json")
with open(out_path, 'w') as f:
    json.dump(out, f)

print(f"[DONE] Snapshot saved: {out_path}")
print(f"[DONE] {len(out['expirations'])} expirations, {sum(len(v['puts'])+len(v['calls']) for v in out['chain'].values())} total contracts")
