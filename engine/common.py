"""
Shared engine utilities — extracted from engine/newsletter.py (phase-2 split,
2026-07-19). Imports nothing from watchtower_engine or any blueprint, so any
module can depend on it without circularity.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Promoted here in split phase 3 (2026-07-21): BOTH the macro blueprint's
# macro_loop and the engine's fetch_loop need market_state(), so it cannot live
# in either one without creating a circular import.
ET = ZoneInfo("America/New_York")


def market_state():
    """
    Returns the current operating mode based on ET time and weekday:
      'closed'      — midnight→8am ET weekdays; all weekend except Sun→Mon midnight
      'pre_market'  — 8:00am→9:30am ET weekdays
      'open'        — 9:30am→4:00pm ET weekdays
      'after_hours' — 4:00pm→midnight ET weekdays (dashboard static, no triggers)
    Midnight Sunday→Monday is treated as 'closed' until 8am Monday ET.
    """
    now = datetime.now(ET)
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    t = now.time()

    from datetime import time as dtime
    MIDNIGHT     = dtime(0, 0)
    PRE_OPEN     = dtime(8, 0)
    MARKET_OPEN  = dtime(9, 30)
    MARKET_CLOSE = dtime(16, 0)

    # Full weekend days — always closed
    if weekday == 5:  # Saturday
        return "closed"
    if weekday == 6:  # Sunday
        return "closed"

    # Weekdays
    if MIDNIGHT <= t < PRE_OPEN:
        return "closed"
    elif PRE_OPEN <= t < MARKET_OPEN:
        return "pre_market"
    elif MARKET_OPEN <= t < MARKET_CLOSE:
        return "open"
    else:  # 4pm → midnight
        return "after_hours"


# Promoted here in split phase 4 (2026-07-22): both the market blueprint's routes
# and the engine's fetch_loop touch these — fetch_loop READS the ticker list and
# WRITES the market-data snapshot, while the routes read/write both. Same rule as
# market_state(): anything shared between a blueprint and the engine lives here,
# never in the blueprint.
TICKERS_FILE = 'tickers.json'
DATA_FILE = 'market_data.json'


def get_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            with open(TICKERS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return list(set(data))
        except:
            pass
    return ["AAPL", "QQQ", "SPY"]


def save_tickers(tickers):
    with open(TICKERS_FILE, 'w') as f:
        json.dump(list(set(tickers)), f)


def atomic_write_json(path, obj):
    """Write JSON via temp file + os.replace so the destination only ever appears
    complete, never half-written. os.replace is atomic on the same filesystem."""
    tmp = os.path.join(os.path.dirname(path), ".tmp_" + os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
