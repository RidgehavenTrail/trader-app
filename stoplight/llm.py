"""
OpenRouter inference client for the stoplight extractors (Phase D).

The ONLY place the extraction factors touch inference. Anthropic-direct paths
(macro briefing, actionable synthesis) are untouched — this is OpenRouter-native
so the AutoRouter cost/quality experiment runs here (see the
stoplight-inference-openrouter memory).

Model config — two knobs, env-overridable, so switching arms needs no code:
  STAGE1_MODEL  the regulatory-sweep DETECTOR (cheap, high-volume). Default
                openrouter/auto-beta — the AUTOROUTER chooses a live model per
                task and fails over automatically. (A pinned
                deepseek/deepseek-v4-flash:free default was introduced WITHOUT
                authorization and 404'd once that slug went dead; a pinned model
                can't route around itself — the whole point of STAGE1 being the
                router. Restored 2026-07-20.)
  STAGE2_MODEL  classification / earnings extraction (quality-critical). Default
                anthropic/claude-sonnet-5 at low reasoning effort ("Sonnet Low")
                — kept as the PROVEN config; the flakiness of alternatives is not
                worth trading for on the quality-critical stage.

Every call:
  - requests usage accounting ({"usage": {"include": true}}) so the response
    carries real cost + the actually-routed model (auto-beta reports its pick);
  - is logged to the llm_calls ledger with cost/route/schema-validity AND the
    verbatim raw_response (so a comparison shows exactly what each model said);
  - parses JSON PROSE-TOLERANTLY (web-search replies come back as prose + JSON +
    citations; we pull the JSON block out rather than demand a pure-JSON body).

COST CONTROLS (added after the 2026-07-19 $5.37 overrun — root cause: native
agentic web search pulled 150k-600k INPUT tokens/call, x3 via retries):
  - Web search FORCES the Exa engine ({"engine":"exa","max_results":3}) — bounded
    result snippets, NOT native agentic full-page fetches. This is the big lever.
  - Output capped (max_tokens) — the payloads are tiny JSON.
  - NO retry/fallback storm on web-search calls: a web-search extraction gets
    ONE attempt. If it fails schema, the prior primitive is kept and the factor
    is flagged — we never re-run an expensive search 3x. (Non-search calls keep
    the retry+Sonnet-fallback path — they're cheap.)
"""
import json
import os
import re
import statistics

import requests

from . import store

_URL = "https://openrouter.ai/api/v1/chat/completions"
FALLBACK_MODEL = "anthropic/claude-sonnet-5"
MAX_OUTPUT_TOKENS = 4000   # raised 1200->2500->4000. 2500 cut off reasoning-heavy
                           # extractions BEFORE the JSON (MSFT/META capex: empty
                           # content, exactly 2500 completion tokens spent thinking).
                           # A CEILING not a target — clean calls still finish in
                           # ~250-700 tokens; only the tangled ones use the headroom.
                           # Exa bounds input, so the per-call ceiling stays ~$0.05.
EXA_MAX_RESULTS = 3

STAGE1_MODEL = os.getenv("STOPLIGHT_STAGE1_MODEL", "openrouter/auto-beta")
STAGE2_MODEL = os.getenv("STOPLIGHT_STAGE2_MODEL", "anthropic/claude-sonnet-5")

# Reasoning effort for extraction calls (module-level so a per-set test can
# override it). "low" is the default (matches the newsletter setting; enough for
# pull-a-number extraction, and it stops the MSFT unbounded-reasoning wall).
REASONING_EFFORT = os.getenv("STOPLIGHT_REASONING_EFFORT", "low")


def _json_from_text(text):
    """Prose-tolerant JSON extraction: strip ```json fences, else grab the first
    balanced {...} block. Web-search replies wrap the JSON in prose + citations."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        end = None
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        candidate = text[start:end] if end else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _key():
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), ".env"))
        except ImportError:
            pass
        key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return key


def _post(model, messages, web_search, timeout, max_results=EXA_MAX_RESULTS):
    body = {
        "model": model,
        "messages": messages,
        "usage": {"include": True},          # cost + routed model in the response
        "max_tokens": MAX_OUTPUT_TOKENS,
        # Extraction is pull-a-number-from-search, NOT a reasoning task. Unbounded
        # thinking walled MSFT capex (empty content at maxed tokens — it thought
        # itself into the ceiling before emitting JSON). Cap reasoning so the model
        # converges and actually writes the answer. (OpenRouter reasoning param,
        # verified 2026-07-19; "low" ~= 20% of max_tokens for thinking.)
        "reasoning": {"effort": REASONING_EFFORT},
    }
    if web_search:
        # Force bounded Exa (snippets), NOT native agentic search (full-page
        # fetches were the token bomb). No json_object mode with search — the
        # plugin overrides it and we parse prose-tolerantly instead. max_results
        # is per-factor: a multi-source composite (silicon payback) needs more
        # candidate pages than a single-number pull.
        body["plugins"] = [{"id": "web", "engine": "exa", "max_results": max_results}]
    else:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(_URL, headers={"Authorization": f"Bearer {_key()}",
                                     "Content-Type": "application/json"},
                      json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _parse(resp):
    choice = resp["choices"][0]["message"]["content"]
    usage = resp.get("usage") or {}
    return {
        "content": choice,
        "model_routed": resp.get("model"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost_usd": usage.get("cost"),
    }


def extract_json(extractor, stage, messages, model, validate,
                 web_search=False, timeout=120, max_results=EXA_MAX_RESULTS):
    """Run an extraction call, log it (with the verbatim raw_response), and
    return (validated_data, meta).

    `validate(dict) -> (ok, cleaned_or_reason)`. Output is parsed prose-tolerantly
    (web-search replies wrap JSON in prose + citations).

    RETRY POLICY is cost-aware:
      - web_search=True  -> ONE attempt only. A web search is expensive; if it
        fails schema we do NOT re-run it — the caller keeps the prior primitive
        and flags the factor. (This is the fix for the 3x-search overrun.)
      - web_search=False -> cheap, so keep the resilient path: retry once on the
        same model, then fall back to Sonnet.
    Raises ValueError if no attempt validates (caller catches, keeps prior value).
    """
    if web_search:
        attempts = [(model, "single")]
    else:
        attempts = [(model, "primary"), (model, "retry"), (FALLBACK_MODEL, "fallback")]

    last_reason = None
    spent = 0.0
    for used_model, note in attempts:
        resp = _post(used_model, messages, web_search, timeout, max_results)
        p = _parse(resp)
        spent += p["cost_usd"] or 0
        data = _json_from_text(p["content"])
        if data is None:
            ok, cleaned = False, "no parseable JSON in response"
        else:
            ok, cleaned = validate(data)
        store.record_llm_call(
            extractor, stage, used_model, p["model_routed"],
            p["prompt_tokens"], p["completion_tokens"], p["cost_usd"],
            schema_valid=ok, note=None if ok else f"{note}:{cleaned}",
            raw_response=p["content"])
        if ok:
            return cleaned, p
        last_reason = cleaned
    # A schema failure still SPENT — the search + inference ran, only the answer was
    # rejected. Carry the amount on the exception so the caller can bill it; without
    # this a rejected leg reports $0 and the run's total under-states real spend
    # (observed 2026-07-29: a VRT leg cost $0.0164 and was logged as $0).
    err = ValueError(f"{extractor}/{stage}: failed schema (last: {last_reason})")
    err.cost_usd = round(spent, 6)
    raise err


def extract_sampled(extractor, stage, messages, model, validate, web_search=False,
                    max_results=EXA_MAX_RESULTS, timeout=120, samples=1,
                    median_field="value_b"):
    """Adaptive sample-and-median for LOW-CONFIDENCE sources (general engine
    feature). Always runs once. If the validated result carries
    low_confidence=True AND samples>1, it takes up to `samples` total samples and
    returns the MEDIAN of median_field, with the spread + provenance attached
    under `_sampled`. A HIGH-confidence first result returns immediately (cost-
    adaptive — hard sources never pay for extra calls). Individual extra-sample
    failures are skipped; the first (already validated) result always anchors.

    The softness signal is the validator's `low_confidence` flag — e.g. a
    seats-x-price estimate whose seat count was NOT from an official disclosure.
    Median (not mean) so one bad low-quality source can't drag the aggregate."""
    data, meta = extract_json(extractor, stage, messages, model, validate,
                              web_search=web_search, timeout=timeout,
                              max_results=max_results)
    if samples <= 1 or not data.get("low_confidence") or median_field not in data:
        return data, meta

    vals = [data[median_field]]
    provs = [data.get("seat_source") or data.get("source") or data.get("url")]
    cost = meta.get("cost_usd") or 0
    for _ in range(samples - 1):
        try:
            d2, m2 = extract_json(extractor, stage, messages, model, validate,
                                  web_search=web_search, timeout=timeout,
                                  max_results=max_results)
        except ValueError:
            continue                     # a failed extra sample is skipped, not fatal
        cost += m2.get("cost_usd") or 0
        # A high-confidence sample (an AUTHORITATIVE disclosure) beats a median
        # of estimates outright — take it and stop, don't keep sampling/blending.
        if not d2.get("low_confidence"):
            out = dict(d2)
            out["_sampled"] = {"resolved": "authoritative_after_estimates",
                               "prior_estimates": vals}
            m2 = dict(m2)
            m2["cost_usd"] = cost
            return out, m2
        if median_field in d2:
            vals.append(d2[median_field])
            provs.append(d2.get("seat_source") or d2.get("source") or d2.get("url"))

    med = round(statistics.median(vals), 1)
    out = dict(data)
    out[median_field] = med
    out["_sampled"] = {"n": len(vals), "values": vals,
                       "spread": [min(vals), max(vals)], "provenance": provs}
    meta = dict(meta)
    meta["cost_usd"] = cost
    return out, meta
