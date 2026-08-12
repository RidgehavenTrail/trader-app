"""
OpenRouter fetchers — data endpoints (this file) and, in Phase D, the
extractor inference client.

- rankings_daily: GET /api/v1/datasets/rankings-daily — REQUIRES the free
  OPENROUTER_API_KEY (the public no-key pull returns only the Top 12, which
  undercounts the commodity long tail — spec says the key is required, not
  optional). Returns ~30 days of {date, model_permaslug, total_tokens} rows:
  top-50 per day + an "other" aggregate. total_tokens arrives as a STRING.
- model_prices: GET /api/v1/models — public. pricing.prompt/completion are
  $/token STRINGS (multiply by 1e6 for $/M).

JOIN NOTE (verified live 2026-07-19): rankings permaslugs match the models
endpoint's `canonical_slug` (43/51), except `:free` variants (strip the
suffix to identify; their revenue is genuinely $0), non-chat models (e.g.
embeddings — not in /models), and the "other" row. Callers handle those.
"""
import os

import requests

_BASE = "https://openrouter.ai/api/v1"


def _key():
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))), ".env"))
        except ImportError:
            pass
        key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set (.env or environment)")
    return key


def rankings_daily(timeout=30):
    """All available daily rows, each {date, model_permaslug, total_tokens:int}."""
    r = requests.get(f"{_BASE}/datasets/rankings-daily",
                     headers={"Authorization": f"Bearer {_key()}"}, timeout=timeout)
    r.raise_for_status()
    rows = r.json()["data"]
    for row in rows:
        row["total_tokens"] = int(row["total_tokens"])
    return rows


def model_prices(timeout=30):
    """{canonical_slug: {prompt_per_m, completion_per_m, id, name}} — chat models."""
    r = requests.get(f"{_BASE}/models", timeout=timeout)
    r.raise_for_status()
    out = {}
    for m in r.json()["data"]:
        slug = m.get("canonical_slug") or m["id"]
        try:
            out[slug] = {
                "prompt_per_m": float(m["pricing"]["prompt"]) * 1e6,
                "completion_per_m": float(m["pricing"]["completion"]) * 1e6,
                "id": m["id"],
                "name": m.get("name"),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out
