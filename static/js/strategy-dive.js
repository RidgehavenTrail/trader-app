// strategy-dive.js — the Rocket Strategy DETAIL panel (classic script, global scope).
// Do not add import/export; every function here must stay global, same as the other
// static/js modules (see .claude/rules/newsletter-tracker.md).
//
// SPLIT MIRRORS THE NEWSLETTER PAIR: newsletter-cards.js renders the strip and
// newsletter-dive.js owns its panel; strategy.js renders the sidebar and this owns
// the panel. strategy.js's own header scopes itself that way — "nothing numeric …
// lives here; that is detail-panel content" — so this is where the numeric side goes.
//
// WHAT THIS PANEL IS FOR (user, 2026-08-15): seeing a vehicle's strategy state AGAINST
// its price. The sidebar block already states the position in words; the value here is
// the chart with the strategy's own levels drawn on it.
//
// The chart is NOT reimplemented. charts.js is parameterised by view key (`dd`, `nd`)
// and gains a third, `sd` — same fetch, same candles, same SMA 50/200, same 2-year
// buffer for seeding. This file only supplies the entity and the levels to draw.

    let _sdSeq = 0;          // stale-guard: a slow fetch must not paint over a newer open

    // NO hideStrategyDive(). One was written for symmetry and never called: every other
    // panel's opener hides this one through showOnlyPanel(), so a private hide would be a
    // second way to do the same thing and the first to fall out of step. `_sdTicker` went
    // with it — that function was its only reader, so keeping it left a variable written
    // on every open and consulted by nothing.

    // The levels the chart draws, derived from the CONTRACT and nothing else.
    //
    // HOLDING -> where you got in and where it is going. FLAT -> the one price that would
    // put you in. Never both: a trigger while holding is not the next thing to happen, and
    // an entry line with no position is a line from a trade that is over.
    //
    // Colors follow the sidebar's own scheme rather than inventing tokens: the instrument's
    // hue for its entry, green for a target (the one place green already means "gain"), and
    // the instrument's hue at 55% for a trigger — visibly this name, visibly not a fill.
    function sdLevels(st, color) {
        const out = [];
        if (st.state_tier !== 'flat') {
            if (st.entry_price !== null && st.entry_price !== undefined) {
                out.push({ price: st.entry_price, color: color, title: 'entry' });
            }
            if (st.target !== null && st.target !== undefined) {
                out.push({ price: st.target, color: '#4ade80', title: 'target' });
            }
        } else if (st.trigger !== null && st.trigger !== undefined) {
            out.push({ price: st.trigger, color: strHexToRgba(color, 0.55),
                       title: st.trigger_basis || 'entry' });
        }
        return out;
    }

    // The facts strip. Deliberately ONE row of inline items, not a grid of boxes — the
    // sidebar states the same position vertically and a second stacked copy would just be
    // the sidebar again, larger.
    // `color` is the instrument's own hue, and the LEVEL VALUES here are tinted to match
    // the lines drawn on the chart beside them (user, 2026-08-15) — entry in the
    // instrument's colour, target green, the trigger in the dimmed variant. That pairing is
    // what lets you read a level off the strip and find its line without a legend.
    //
    // PANEL ONLY. The sidebar's rows stay as they are: the same treatment was tried there
    // and reads busier, because that block is a narrow stack of many rows rather than one
    // strip sitting directly above the chart it refers to.
    function sdFactsHTML(st, color) {
        const item = (k, v, color) =>
            `<span class="sd-fact"><span class="sd-fact-k">${esc(k)}</span>` +
            `<span class="sd-fact-v"${color ? ` style="color:${color}"` : ''}>${v}</span></span>`;

        const eraColor = { golden: '#d4af37', WARNING: '#fbbf24', death: '#f87171' }[st.era]
                       || '#64748b';
        let out = item('Era', esc(st.era || '—') +
                       (st.era_days ? ` <span class="sd-fact-sub">${st.era_days} td</span>` : ''),
                       eraColor);

        // Phase reads as the qualifier on the state, same rule as the sidebar: it explains
        // a flat system and adds nothing to an active one, which already names itself.
        const phase = (st.state_tier === 'flat' && st.phase)
            ? ` <span class="sd-fact-sub">${esc(st.phase)}</span>` : '';
        out += item('State', esc(st.state || '—') + phase, null);

        if (st.pnl_pct !== null && st.pnl_pct !== undefined) out += item('P&L', strPct(st.pnl_pct));
        if (st.entry_price !== null && st.entry_price !== undefined) {
            const held = (st.days_held === null || st.days_held === undefined)
                ? '' : ` <span class="sd-fact-sub">${st.days_held} td</span>`;
            out += item('Entry', st.entry_price.toFixed(2) + held, color);
        }
        if (st.target !== null && st.target !== undefined) {
            out += item('Target', st.target.toFixed(2), '#4ade80');
        }
        if (st.state_tier === 'flat' && st.trigger !== null && st.trigger !== undefined) {
            out += item('Entry @', st.trigger.toFixed(2) +
                        (st.trigger_basis ? ` <span class="sd-fact-sub">${esc(st.trigger_basis)}</span>` : ''),
                        strHexToRgba(color, 0.55));
        }
        out += item('Era P&L', strPct(st.era_pnl_pct));
        return `<div class="sd-facts-row">${out}</div>`;
    }

    // The facts strip lives in TWO places: the panel header (always on screen, whichever
    // tab is open) and the Strategy tab. Written through one function so they cannot
    // disagree — two innerHTML sites for one fact set is how a stale copy gets left behind.
    function sdSetFacts(html) {
        ['sd-facts-hd', 'sd-facts'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = html;
        });
    }

    // The DIAL tab — the macro half, above the vehicle.
    //
    // Every field here has been shipped in the dial payload since 2026-08-10 and read by
    // nothing: strategy.js's header states outright that the rate, the change over the
    // lookback, the distance to a flip and the latch counter are "detail-panel content" and
    // that "the payload still carries those fields, unused here, ready for that panel."
    // This is that panel. No new endpoint and no new computation — the numbers were already
    // arriving on every poll.
    function renderDialPane() {
        const box = document.getElementById('sd-dial');
        if (!box) return;
        const d = (typeof strLast !== 'undefined') ? strLast : null;
        if (!d || !d.ok) { box.innerHTML = ''; return; }

        const sign = v => (v === null || v === undefined || !isFinite(v))
            ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(3)}`;

        let rows = strRow('Regime', esc(d.label || '—'),
                          d.days_in_state ? `${d.days_in_state} td` : null, d.color);
        if (d.rate !== null && d.rate !== undefined) {
            rows += strRow(esc(d.rate_label || 'rate'), `${d.rate.toFixed(2)}%`,
                           d.lookback_months ? `${d.lookback_months}mo lookback` : null);
        }
        rows += strRow('change', sign(d.chg), 'over the lookback');
        // DISTANCE TO EACH FLIP, signed as the payload defines them: to_tighten is how far
        // the change must RISE, to_ease how far it must FALL. Shown as magnitudes with the
        // direction in the footnote rather than as raw signs, which read as gains/losses.
        if (d.to_tighten !== null && d.to_tighten !== undefined) {
            rows += strRow('to tighten', Math.abs(d.to_tighten).toFixed(3), 'pp the change must rise');
        }
        if (d.to_ease !== null && d.to_ease !== undefined) {
            rows += strRow('to ease', Math.abs(d.to_ease).toFixed(3), 'pp the change must fall');
        }
        if (d.nearest_pp !== null && d.nearest_pp !== undefined) {
            // `near` is the payload's own proximity flag — amber, the same token the sidebar
            // uses for a pending latch, because both mean "a flip is in reach, not made".
            rows += strRow('nearest flip', Math.abs(d.nearest_pp).toFixed(3),
                           d.near ? 'within the near band' : 'pp away',
                           d.near ? '#fbbf24' : null);
        }
        if (d.latch_days) {
            rows += strRow('latch', `${d.latch_days} td`,
                           d.latched_on ? esc(`latched ${d.latched_on}`) : 'to confirm a flip');
        }
        if (d.pending) rows += strRow('pending', esc(String(d.pending)), 'unconfirmed flip', '#fbbf24');
        if (d.asof) rows += strRow('as of', esc(d.asof), d.stale ? 'stale' : null);

        box.innerHTML = `<div class="str-blk-hd"><span class="str-blk-nm" ` +
                        `style="color:${d.color}">Fed dial</span></div>` + rows;
    }

    // Opened from a ticker pill. Reached by TICKER, so it works for a vehicle in a column
    // the dial has not allocated — the same decoupling GET /get_ticker_strategy exists for.
    async function showStrategyDive(ticker) {
        if (!ticker) return;
        const seq = ++_sdSeq;

        if (!document.getElementById('strategy-dive')) return;
        showOnlyPanel('strategy-dive');     // shared list in core.js — see DETAIL_PANELS
        // ENTITY BEFORE THE TAB SWITCH — the order is load-bearing. switchTab('sd','chart')
        // calls loadChart SYNCHRONOUSLY, and loadChart reads viewState.sd.entity and returns
        // early when `loadedFor` already matches it. Setting these afterwards meant clicking
        // from one ticker to the next rendered the PREVIOUS chart and only then armed the
        // reload — which is exactly why leaving the tab and coming back showed the right one.
        //
        // `loadedFor: null` forces a rebuild even when the ticker has NOT changed, because
        // the levels move daily even when the entity does not.
        viewState.sd.entity = { asset_class: 'equity', ticker };
        viewState.sd.levels = [];
        viewState.sd.loadedFor = null;

        // CHART BY DEFAULT (user, 2026-08-15). A pill click is a request to see the name
        // against its price; the facts strip rides in the header, so opening on the chart
        // costs none of that information.
        switchTab('sd', 'chart');

        // The holding gives price/day/color without a second round trip — the dial payload
        // is already in hand and already carries technicals for every column.
        const h = (typeof strLast !== 'undefined' && strLast)
            ? strFindHolding(strLast, ticker) : null;
        const color = (h && h.color) || '#94a3b8';

        document.getElementById('sd-ticker').innerText = ticker;
        document.getElementById('sd-ticker').style.color = color;
        document.getElementById('sd-price').innerText =
            (h && h.price !== null && h.price !== undefined) ? h.price.toFixed(2) : '—';
        document.getElementById('sd-day').innerHTML =
            (h && h.day_pct !== null && h.day_pct !== undefined) ? strPct(h.day_pct) : '';
        document.getElementById('sd-regime').innerText =
            (typeof strLast !== 'undefined' && strLast && strLast.label)
                ? `dial: ${strLast.label}` : '';

        sdSetFacts('<div class="sd-facts-row"><span class="sd-fact">loading…</span></div>');

        renderDialPane();

        let d = null;
        try {
            const r = await fetch(`${API_BASE}/get_ticker_strategy/${encodeURIComponent(ticker)}`);
            d = await r.json();
        } catch (e) { /* fall through to the no-state message */ }

        if (seq !== _sdSeq) return;    // a newer pill was clicked mid-fetch

        if (!d || !d.ok || !d.has_strategy) {
            sdSetFacts('<div class="sd-facts-row"><span class="sd-fact">' +
                '<span class="sd-fact-k">State</span>' +
                '<span class="sd-fact-v str-st-off">no strategy wired</span></span></div>');
            return;
        }

        sdSetFacts(sdFactsHTML(d, color));

        // Redraw with the levels now that the contract has landed. The chart may still be
        // fetching; drawStrategyLevels is idempotent and reapplies on the next render.
        viewState.sd.levels = sdLevels(d, color);
        drawStrategyLevels('sd');
    }
