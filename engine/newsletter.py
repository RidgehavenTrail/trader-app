"""
Newsletter ingestion + trade-quote routes — extracted from watchtower_engine.py
(2026-07-13 engine split, phase 1). Self-contained Flask Blueprint: imports nothing
from watchtower_engine, so there is no circular import. The engine registers it via
app.register_blueprint(bp). See .claude/rules/newsletter-ingestion.md.
"""
import os
import json
import re
import math
from datetime import datetime, date
import yfinance as yf
from flask import Blueprint, request, jsonify
import newsletter_ingest

bp = Blueprint('newsletter', __name__)

NEWSLETTER_PDF_DIR = os.getenv("NEWSLETTER_PDF_DIR")
NEWSLETTER_EXTRACTED_DIR = os.getenv("NEWSLETTER_EXTRACTED_DIR") or (
    os.path.join(NEWSLETTER_PDF_DIR, "extracted") if NEWSLETTER_PDF_DIR else None)
# Optional floor date (YYYY-MM-DD): issues dated/mtime'd before this are grayed
# out in the Import picker AND rejected server-side if POSTed anyway. Exists to
# let the user start the live-set store from an arbitrary week without the
# backward-import corruption risk (an older issue reconciled against a store
# whose `live` set already reflects later issues) — see newsletter-ingestion.md.
NEWSLETTER_START_DATE = os.getenv("NEWSLETTER_START_DATE")


def _newsletter_issue_date(filename):
    """Best-effort issue date from a filename: a YYYY-MM-DD anywhere, else a
    leading YYMMDD (e.g. '260525' -> 2026-05-25), else None (caller falls back to
    file mtime). Do not require a naming convention."""
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"\s*(\d{2})(\d{2})(\d{2})(?!\d)", filename)
    if m:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _newsletter_sort_date(filename, full_path):
    """Date string used for both display ordering and the NEWSLETTER_START_DATE
    threshold, so the two always agree on what date a file represents: parsed
    issue date if present, else file mtime."""
    issue_date = _newsletter_issue_date(filename)
    if issue_date:
        return issue_date
    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        mtime = 0
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


# _atomic_write_json moved to engine/common.py (phase-2 split, 2026-07-19) —
# shared with the stoplight package.
from engine.common import atomic_write_json as _atomic_write_json


@bp.route('/list_pending_newsletters', methods=['GET'])
def list_pending_newsletters():
    """List PDFs in NEWSLETTER_PDF_DIR, date-sorted, each flagged with whether a
    same-stem extract already exists in NEWSLETTER_EXTRACTED_DIR (already-imported
    -> grayed out, not hidden, so re-import stays trivial), and whether it falls
    before NEWSLETTER_START_DATE (also grayed out, separately labeled)."""
    if not NEWSLETTER_PDF_DIR or not os.path.isdir(NEWSLETTER_PDF_DIR):
        return jsonify({"error": "NEWSLETTER_PDF_DIR not set or missing", "files": []})
    files = []
    for fn in os.listdir(NEWSLETTER_PDF_DIR):
        if not fn.lower().endswith(".pdf"):
            continue
        stem = os.path.splitext(fn)[0]
        issue_date = _newsletter_issue_date(fn)
        sort_date = _newsletter_sort_date(fn, os.path.join(NEWSLETTER_PDF_DIR, fn))
        imported = bool(NEWSLETTER_EXTRACTED_DIR and
                        os.path.isfile(os.path.join(NEWSLETTER_EXTRACTED_DIR, stem + ".json")))
        before_start = bool(NEWSLETTER_START_DATE and sort_date < NEWSLETTER_START_DATE)
        files.append({"filename": fn, "issue_date": issue_date, "imported": imported,
                      "before_start": before_start, "_sort": sort_date})
    files.sort(key=lambda x: x["_sort"])
    for f in files:
        f.pop("_sort", None)
    return jsonify({"files": files})


@bp.route('/import_newsletter', methods=['POST'])
def import_newsletter():
    """Import one pending PDF: extract text -> extraction prompt -> merge into the
    store -> atomic write. The per-issue extract file is written LAST and is the
    sole 'already imported' completion signal, so a partial/failed run leaves no
    marker and the item stays importable. No error detail is surfaced to the UI —
    the user just retries by clicking Import again (their explicit call)."""
    body = request.get_json(silent=True) or {}
    filename = body.get("filename")
    if not filename or os.path.basename(filename) != filename:  # reject traversal
        return jsonify({"status": "error"}), 400
    if not NEWSLETTER_PDF_DIR or not NEWSLETTER_EXTRACTED_DIR:
        return jsonify({"status": "error"}), 500
    pdf_path = os.path.join(NEWSLETTER_PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        return jsonify({"status": "error"}), 404
    if NEWSLETTER_START_DATE and _newsletter_sort_date(filename, pdf_path) < NEWSLETTER_START_DATE:
        # Defensive, not just cosmetic: reconciling an issue older than the
        # store's current live set is the backward-import corruption case (an
        # older issue's silence-abandons logic gets applied to trades that
        # didn't exist yet as of its date). The picker already hides this
        # behind a grayed-out entry; this rejects it even if POSTed directly.
        return jsonify({"status": "before_start"}), 400

    stem = os.path.splitext(filename)[0]
    os.makedirs(NEWSLETTER_EXTRACTED_DIR, exist_ok=True)
    marker = os.path.join(NEWSLETTER_EXTRACTED_DIR, stem + ".json")
    if os.path.isfile(marker):
        return jsonify({"status": "already_imported"})

    store_path = os.path.join(NEWSLETTER_EXTRACTED_DIR, "_store.json")
    # Effort: default LOW (the validated import-queue convention — ~½ the cost of
    # high, primitives stable at any effort). Optional body override for experiments.
    effort = (body.get("effort") or "low").strip().lower()
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        effort = "low"
    try:
        if os.path.isfile(store_path):
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
            mode = "dashboard incremental (merging onto existing store)"
        else:
            store = newsletter_ingest.new_store()
            mode = "dashboard cold start (fresh store)"
        text = newsletter_ingest.extract_pdf_text(pdf_path)
        # Shared instrumented path: same telemetry the CLI captures (thinking log,
        # run_archive receipts, cost_experiment_log row) — previously the endpoint
        # discarded all of it. Writes store + marker atomically inside.
        result = newsletter_ingest.ingest_issue_recorded(
            text, store, NEWSLETTER_EXTRACTED_DIR, stem, filename, mode, effort=effort)
        data, counts, usage = result["data"], result["counts"], result["usage"]
    except Exception as e:
        print(f"[NEWSLETTER IMPORT] {filename} failed: {type(e).__name__}: {e}")
        return jsonify({"status": "error"})
    print(f"[NEWSLETTER IMPORT] {filename}: {data.get('issue_date')} effort={effort} "
          f"live={counts['live']} +{counts['archived_now']}archived "
          f"+{counts['discarded_now']}discarded +{counts.get('lapsed_now', 0)}lapsed "
          f"out={usage.get('output_tokens')} cost=${result['cost_usd']:.4f} "
          f"({result['elapsed_s']:.0f}s)")
    return jsonify({"status": "ok", "issue_date": data.get("issue_date"),
                    "trades": len(data.get("trade_updates", [])), "counts": counts,
                    "effort": effort, "cost_usd": result["cost_usd"],
                    "elapsed_s": result["elapsed_s"],
                    "tokens": {"input": usage.get("input_tokens"),
                               "output": usage.get("output_tokens"),
                               "thinking": usage.get("thinking_tokens"),
                               "final": usage.get("final_tokens")}})


def _list_extracted_issues():
    """(stem, data) for every real per-issue extract in NEWSLETTER_EXTRACTED_DIR,
    newest issue_date first. Skips _store.json and any in-flight temp file, and
    silently skips anything unreadable — this is a read path, never the completion
    signal, so a bad file must not break the listing."""
    out = []
    if not NEWSLETTER_EXTRACTED_DIR or not os.path.isdir(NEWSLETTER_EXTRACTED_DIR):
        return out
    for fn in os.listdir(NEWSLETTER_EXTRACTED_DIR):
        if not fn.endswith(".json") or fn == "_store.json" or fn.startswith(".tmp"):
            continue
        try:
            with open(os.path.join(NEWSLETTER_EXTRACTED_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        out.append((os.path.splitext(fn)[0], data))
    out.sort(key=lambda sd: sd[1].get("issue_date") or "", reverse=True)
    return out


@bp.route('/get_newsletter_state', methods=['GET'])
def get_newsletter_state():
    """Read-only current state for the Newsletter Plays panel + digest strip.
    No model call — just reads _store.json and the extract files off disk.
    Returns the live working set + closed archive (the strip renders both), the
    most recent issue envelope for the digest, and the list of past editions for
    the Past Editions dropdown. Also returns `unresolved`: the discard stubs that
    went `unresolved` in the CURRENT issue only (`dropped_on == issue_date`), so a
    freshly-dropped trade lingers on the board for its transition week — visual
    continuity + the drop reason in place — then falls off once a newer issue is
    imported (user, 2026-07-13). Display-only; the lifecycle/discard rules are
    unchanged (the stub still lives in `discarded`). Other discard statuses
    (`abandoned`/`lapsed`) stay omitted. Degrades gracefully when empty."""
    live, archive, discarded = [], [], []
    if NEWSLETTER_EXTRACTED_DIR:
        store_path = os.path.join(NEWSLETTER_EXTRACTED_DIR, "_store.json")
        if os.path.isfile(store_path):
            try:
                with open(store_path, encoding="utf-8") as f:
                    store = json.load(f)
                live = store.get("live", [])
                archive = store.get("archive", [])
                discarded = store.get("discarded", [])
            except (OSError, ValueError):
                pass
    extracted = _list_extracted_issues()
    editions = [{"stem": stem, "issue_date": d.get("issue_date"), "title": d.get("title")}
                for stem, d in extracted]
    issue = extracted[0][1] if extracted else None
    issue_date = issue.get("issue_date") if issue else None
    # Unresolved trades dropped THIS issue: surface them for their transition week,
    # rendered as their FULL last-week trade object (conviction/entry/thesis intact,
    # styled amber by the frontend) rather than the bare discard stub — visual
    # continuity, not a stripped placeholder (user, 2026-07-13). Enrich each stub from
    # the most recent PRIOR edition that carried the full trade; keep the drop `reason`
    # as `unresolved_reason` for the one-line note the frontend puts atop the thesis.
    unresolved = []
    for s in discarded:
        if s.get("status") != "unresolved" or s.get("dropped_on") != issue_date:
            continue
        full = None
        for _stem, d in extracted[1:]:            # prior editions, newest first
            full = next((t for t in d.get("trade_updates", []) if t.get("id") == s.get("id")), None)
            if full:
                break
        if full:
            enriched = dict(full)
            enriched["status"] = "unresolved"
            enriched["dropped_on"] = s.get("dropped_on")
            enriched["unresolved_reason"] = s.get("reason")
            unresolved.append(enriched)
        else:
            unresolved.append(s)                  # fallback: bare stub (frontend renders compact)
    return jsonify({"live": live, "archive": archive, "unresolved": unresolved,
                    "issue": issue, "editions": editions})


@bp.route('/get_extracted_newsletter', methods=['GET'])
def get_extracted_newsletter():
    """Return one past issue's full extract (envelope + that week's trade_updates)
    for the read-only Past Editions view. `stem` must be a bare filename stem
    (traversal rejected); _store.json is not a browsable edition."""
    stem = request.args.get("stem", "")
    if not stem or stem == "_store" or os.path.basename(stem) != stem:
        return jsonify({"error": "bad stem"}), 400
    if not NEWSLETTER_EXTRACTED_DIR:
        return jsonify({"error": "not configured"}), 500
    path = os.path.join(NEWSLETTER_EXTRACTED_DIR, stem + ".json")
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    try:
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except (OSError, ValueError):
        return jsonify({"error": "unreadable"}), 500


# --- Live trade quote (newsletter-ingestion.md section E) ---------------------
# Current price + own day-over-day % move for ONE newsletter trade's detail-panel
# header. The % is the instrument's OWN raw price move (watchlist/Actionable-Moves
# convention), NOT the position's directional P&L — a short trade does not flip the
# sign. Python owns this deterministic math (same principle as C.1), never the model.

def _last_two_closes(symbol):
    """(prev_close, current_close) for a yfinance symbol over its last few daily
    bars, or None if unavailable. Uses a short 5d window — only the last two
    valid closes are needed for a day-over-day move."""
    try:
        hist = yf.Ticker(symbol).history(period="5d")
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    closes = [float(c) for c in hist["Close"].dropna().tolist()]
    if len(closes) < 2:
        return None
    return closes[-2], closes[-1]


def _pct(cur, prev):
    return round((cur - prev) / prev * 100, 2) if prev else None


def _quote_outright(t):
    """Outright equity/future/forex: current price + day % of the underlying.
    Forex needs the =X fetch suffix (A.7); futures' bare root (HG vs HG=F) is the
    still-open CL1!/CL=F symbol item, so a bare future may return no data — handled
    as 'unavailable', not an error."""
    underlying = t.get("underlying")
    if not underlying:
        return {"unavailable": "no_underlying"}
    asset_class = t.get("asset_class")
    if asset_class == "forex":
        symbol = f"{underlying}=X"
    elif asset_class == "future":
        # A bare futures root silently mis-resolves on yfinance (e.g. "HG" -> an
        # unrelated equity at ~$34 instead of copper at ~$6). root+"=F" is the
        # correct fetchable symbol (HG=F verified). Only translate a CLEAN root
        # (letters only); an exotic display-name (e.g. "CL1!") wouldn't map by a
        # naive suffix, so it falls back to unavailable rather than a wrong price.
        if not re.fullmatch(r"[A-Za-z]{1,4}", underlying):
            return {"unavailable": "future_symbol_unmapped"}
        symbol = f"{underlying}=F"
    else:
        symbol = underlying
    pair = _last_two_closes(symbol)
    if not pair:
        return {"unavailable": "no_data"}
    prev, cur = pair
    return {"current_price": round(cur, 4), "day_change_pct": _pct(cur, prev)}


def _quote_pair(t):
    """Pairs/basket: current ratio = sum(long closes) / sum(short closes) (raw
    prices, no weighting — same construction as the chart, A.6), with day % of the
    RATIO (today's ratio vs yesterday's), not each leg's individual day change."""
    basket = t.get("basket") or []
    longs = [b["ticker"] for b in basket if b.get("side") == "long"]
    shorts = [b["ticker"] for b in basket if b.get("side") == "short"]
    if not longs or not shorts:
        return {"unavailable": "no_split"}
    prev_long = cur_long = prev_short = cur_short = 0.0
    for tk in longs:
        pair = _last_two_closes(tk)
        if not pair:
            return {"unavailable": "no_data"}
        prev_long += pair[0]; cur_long += pair[1]
    for tk in shorts:
        pair = _last_two_closes(tk)
        if not pair:
            return {"unavailable": "no_data"}
        prev_short += pair[0]; cur_short += pair[1]
    if not cur_short or not prev_short:
        return {"unavailable": "no_data"}
    cur_ratio, prev_ratio = cur_long / cur_short, prev_long / prev_short
    return {"current_price": round(cur_ratio, 4), "day_change_pct": _pct(cur_ratio, prev_ratio),
            "is_ratio": True}


def _quote_options_spread(t):
    """Options structure: current spread mark from live per-leg bid/ask
    (mark = (bid+ask)/2), signed by leg action (buy +, sell -). Day % approximated
    from each leg's own `change` field (yesterday's mark ~= lastPrice - change).
    yfinance's option_chain() only returns currently-listed (non-expired) expiries,
    so a trade whose legs have already expired returns 'chain_expired' — expected
    for anything near/after its expiry (all June-expiry trades vs a July 'today')."""
    underlying = t.get("underlying")
    legs = t.get("legs") or []
    if not underlying or not legs:
        return {"unavailable": "no_legs"}
    tk = yf.Ticker(underlying)
    try:
        listed = set(tk.options or [])
    except Exception:
        return {"unavailable": "no_chain"}
    mark = prev_mark = 0.0
    for leg in legs:
        exp = leg.get("expiry")
        if not exp or len(exp) != 10 or exp not in listed:  # month-only or expired
            return {"unavailable": "chain_expired"}
        try:
            chain = tk.option_chain(exp)
        except Exception:
            return {"unavailable": "chain_expired"}
        table = chain.calls if leg.get("type") == "call" else chain.puts
        rows = table[table["strike"] == leg.get("strike")]
        if rows.empty:
            return {"unavailable": "strike_not_found"}
        row = rows.iloc[0]
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        last = float(row.get("lastPrice") or 0)
        leg_mark = (bid + ask) / 2 if (bid or ask) else last
        leg_prev = last - float(row.get("change") or 0)
        sign = 1 if leg.get("action") == "buy" else -1
        mark += sign * leg_mark
        prev_mark += sign * leg_prev
    # Report the spread's net mark magnitude; sign of the day move is what matters
    # for the header, so compare against the prior mark on the same convention.
    day_pct = round((mark - prev_mark) / abs(prev_mark) * 100, 2) if prev_mark else None
    return {"current_price": round(mark, 2), "day_change_pct": day_pct}


def _quote_ratio_trigger(t):
    """Outright trade whose ENTRY keys off a pair RATIO (ratio_trigger, 2026-07-13, e.g.
    a MAGS long that enters when SOXX/MAGS breaks its 50DMA). Header shows the live
    numerator/denominator ratio (is_ratio), and the trade's OWN underlying price rides the
    tab-row far-right (like an options underlying) — the ratio decides the entry, the
    underlying is the position actually taken. The CARD stays the outright it is; this only
    feeds the detail header."""
    rt = t.get("ratio_trigger") or {}
    num, den = rt.get("numerator"), rt.get("denominator")
    if not num or not den:
        return {"unavailable": "no_ratio"}
    np_, dp = _last_two_closes(num), _last_two_closes(den)
    if not np_ or not dp or not dp[0] or not dp[1]:
        return {"unavailable": "no_data"}
    cur_ratio, prev_ratio = np_[1] / dp[1], np_[0] / dp[0]
    result = {"current_price": round(cur_ratio, 4),
              "day_change_pct": _pct(cur_ratio, prev_ratio), "is_ratio": True}
    und = _quote_outright(t)                             # the position's own underlying price
    if isinstance(und, dict) and und.get("current_price") is not None:
        result["underlying_price"] = und["current_price"]
        result["underlying_day_pct"] = und.get("day_change_pct")
    return result


@bp.route('/get_trade_quote', methods=['GET'])
def get_trade_quote():
    """Live current-price / day-change for one newsletter trade (section E).
    Only planned/open trades (the store's `live` set) carry a meaningful 'today's
    price'; a closed trade is not looked up (it's in `archive` and shows realized
    P&L instead). Returns {current_price, day_change_pct} or {unavailable: reason}."""
    trade_id = request.args.get("id", "")
    if not trade_id:
        return jsonify({"unavailable": "no_id"}), 400
    if not NEWSLETTER_EXTRACTED_DIR:
        return jsonify({"unavailable": "not_configured"}), 500
    store_path = os.path.join(NEWSLETTER_EXTRACTED_DIR, "_store.json")
    trade = None
    if os.path.isfile(store_path):
        try:
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
            trade = next((x for x in store.get("live", []) if x.get("id") == trade_id), None)
        except (OSError, ValueError):
            pass
    if trade is None:
        # Not in `live`: an enriched `unresolved` trade (e.g. a dropped pair) is only a
        # stub in the store, but keeps its full basket/legs in a PRIOR edition. Find it
        # there so the detail panel can still answer "where's it at now?" (the ratio /
        # current price), matching every other play card (user, 2026-07-13). `closed`
        # trades are never quoted (the frontend gate excludes them), so in practice this
        # fallback only fires for `unresolved`.
        for _stem, _data in _list_extracted_issues():
            trade = next((x for x in _data.get("trade_updates", []) if x.get("id") == trade_id), None)
            if trade:
                break
    if trade is None:
        return jsonify({"unavailable": "not_found"}), 404
    try:
        # HEADER quote = the TRADING STRUCTURE's own current value (user, 2026-07-09):
        # basket -> ratio, options -> spread mark, outright -> underlying price. For an
        # OPTIONS trade we ALSO attach the underlying equity price (`underlying_price`)
        # for the tab-row far-right chip — there the underlying is NOT redundant with
        # the (spread) card tag, and unlike the spread mark it stays live after the legs
        # expire. Outright/basket get no separate underlying chip (header already shows
        # the relevant number).
        if trade.get("basket"):
            result = _quote_pair(trade)
        elif trade.get("legs"):
            result = _quote_options_spread(trade)          # header: spread mark (may be expired)
            if not isinstance(result, dict):
                result = {}
            und = _quote_outright(trade)                    # tab row: underlying equity price
            if isinstance(und, dict) and und.get("current_price") is not None:
                result["underlying_price"] = und["current_price"]
                result["underlying_day_pct"] = und.get("day_change_pct")
        elif trade.get("ratio_trigger"):
            result = _quote_ratio_trigger(trade)            # header: pair ratio + underlying (far right)
        else:
            result = _quote_outright(trade)
    except Exception as e:
        print(f"[TRADE QUOTE] {trade_id} failed: {type(e).__name__}: {e}")
        return jsonify({"unavailable": "error"})
    return jsonify(result)
