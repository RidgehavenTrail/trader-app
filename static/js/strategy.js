// strategy.js — Rocket Strategy sidebar section (classic script, global scope).
// Do not add import/export; every function here must stay global, same as the
// other static/js modules (see .claude/rules/newsletter-tracker.md).
//
// Renders GET /get_strategy_dial into #strategy-section. Dumb renderer: the state,
// the latch, the portfolios and the proximity flag are ALL computed server-side in
// engine/strategy.py. This file formats and paints.
//
// SCOPE (user, 2026-08-10): the left panel shows the dial STATE, the allocation,
// and each holding's own strategy state. Nothing numeric — rate, the change over the
// lookback, distance to a flip, the latch counter — lives here; that is detail-panel
// content.
// The payload still carries those fields, unused here, ready for that panel.

    // Remember open/closed across reloads (shared helper in core.js), same grammar as
    // Live Macro and AI Bubble. Added 2026-08-12: this section was the only one of the
    // three NOT registered, so it fell back to a hardcoded `open` in the markup and
    // re-expanded on every reload no matter what the user had done. The markup default
    // is now closed — Live Macro is the only section that starts expanded — and this
    // makes the user's own choice stick.
    persistCollapse('strategy-section', 'strategySectionOpen');

    // 60s — driven by the day-move percentages, not the dial. The dial itself moves
    // once a business day and is cached 6h server-side; the quotes ride a separate
    // 60s cache, so this poll is cheap and keeps the pills current intraday.
    const STR_POLL_MS = 60000;

    let strSel  = null;   // selected holding's ticker — drives the block below the dial
    let strLast = null;   // last payload, so a pill click re-renders without a fetch

    function strHexToRgba(hex, a) {
        const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
        if (!m) return `rgba(148,163,184,${a})`;
        return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})`;
    }

    function strTintPill(el, color) {
        el.style.color = color;
        el.style.background = strHexToRgba(color, 0.12);
        el.style.borderColor = strHexToRgba(color, 0.30);
    }

    // Ticker pill. Colored per INSTRUMENT (h.color from the server) so a name looks
    // the same in every column. Clickable ahead of the strategy detail panel.
    //
    // Live pills are larger and carry today's move: text = identity, border =
    // direction, background = identity tint. When the move is unavailable (quote
    // outage, or a symbol yfinance did not return) the pill falls back to an
    // identity-colored border and simply omits the percentage — never a fake 0.00%.
    function strTickerPillHTML(h, isAlt) {
        if (isAlt) {
            return `<span class="str-tpill" style="color:${h.color};` +
                   `border-color:${strHexToRgba(h.color, 0.45)}" ` +
                   `onclick="openStrategyTicker('${esc(h.ticker)}')" ` +
                   `title="${esc(h.ticker)}">${esc(h.ticker)}</span>`;
        }
        const p = h.day_pct;
        const has = (p !== null && p !== undefined && isFinite(p));
        const dir = has ? (p >= 0 ? '#4ade80' : '#f87171') : strHexToRgba(h.color, 0.38);
        // RED TEXT IS LIGHTER THAN ITS BORDER (user, 2026-08-12) — the Live Macro VIX
        // pill's scheme: text-red-300 on a red-500/30 border. Green is deliberately
        // unchanged; only the red was failing, measuring 4.70-4.82 against the pill fill
        // while green sat at 7.2-7.7. #fca5a5 lifts it to ~7.0 without touching a colour
        // that already worked. The BORDER stays #f87171 on purpose: keeping it more
        // saturated than the text is what makes this read as the VIX treatment rather
        // than as a washed-out red.
        const pct = has
            ? `<span class="str-tp-pct" style="color:${p >= 0 ? '#4ade80' : '#fca5a5'}">` +
              `${p >= 0 ? '+' : '−'}${Math.abs(p).toFixed(2)}%</span>`
            : '';
        // Selection is marked by a caret to the LEFT of the pill (see strColumnHTML),
        // not on the pill itself — nothing here varies with what is selected.
        return `<span class="str-tpill str-tpill-lg" style="color:${h.color};` +
               `background:${strHexToRgba(h.color, 0.14)};border-color:${dir}" ` +
               `onclick="openStrategyTicker('${esc(h.ticker)}')" ` +
               `title="${esc(h.ticker)}${has ? ` · ${p >= 0 ? '+' : ''}${p}% today` : ''}">` +
               `${esc(h.ticker)}${pct}</span>`;
    }

    // One portfolio = one column, one holding = one row inside it. On the LIVE
    // column each row also carries that holding's own strategy state, so the panel
    // states each name once rather than listing the book twice.
    function strColumnHTML(label, color, holdings, isAlt) {
        const rows = holdings.map(h => {
            if (isAlt) {
                // The caret slot is emitted on ALTERNATE rows too (2026-08-15). Selection
                // can now land in a column the dial has not allocated, and without a slot
                // here the only visible effect of selecting one was the caret vanishing
                // from the live column — the selection worked and looked like nothing had
                // happened. Kept to the caret alone: the weight and state label stay off
                // the alternates, which are deliberately the dimmed, minimal columns.
                const carA = h.ticker === strSel ? '&#9654;' : '';
                return `<div class="str-hold"><span class="str-sel-caret">${carA}</span>` +
                       `${strTickerPillHTML(h, true)}</div>`;
            }
            const st = h.state || {};
            const cls = st.wired ? 'str-st' : 'str-st-off';
            // The caret slot is emitted on EVERY live row, empty when unselected, so the
            // 10px is always reserved and the column never shifts as selection moves.
            const car = h.ticker === strSel ? '&#9654;' : '';
            return `<div class="str-hold"><span class="str-sel-caret">${car}</span>` +
                   `${strTickerPillHTML(h, false)}` +
                   `<span class="str-wt">${h.weight}%</span>` +
                   `<span class="${cls}">${esc(st.label || '—')}</span></div>`;
        }).join('');
        return `<div class="${isAlt ? 'str-col-alt' : 'str-col-live'}">` +
               `<div class="str-col-hd"${isAlt ? '' : ` style="color:${color}"`}>` +
               `${esc(label)}</div>${rows}</div>`;
    }

    // Ticker pill click — SELECTS that holding into the block below the dial. The
    // left panel shows one holding at a time (user, 2026-08-10). Re-renders off the
    // cached payload, so selecting is instant and costs no fetch.
    //
    // THE DETAIL PANEL IS NO LONGER "FUTURE" (2026-08-15). This comment used to read "the
    // hook the future strategy DETAIL panel should hang off; today it only drives the
    // left-panel selection" — accurate when written, and it outlived its own resolution the
    // moment strategy-dive.js landed. A pill click now does both: selects into the sidebar
    // block AND opens the panel.
    function openStrategyTicker(ticker) {
        strSel = ticker;
        if (strLast) renderStrategyDial(strLast);
        if (typeof showStrategyDive === 'function') showStrategyDive(ticker);
    }

    // Find a vehicle anywhere in the book — the live column OR a dimmed alternate.
    // LIVE FIRST on purpose: a ticker can appear in two columns (QQQ is in both hold and
    // tightening) and the live copy is the one the server filled `state` on, so the richer
    // record wins. This is what lets a pill in a column the dial has not selected be
    // selected and hold focus; it used to be looked up in the live column alone, so
    // selecting XLE off a tightening dial was reset by the very next poll.
    function strFindHolding(d, ticker) {
        if (!d || !ticker) return null;
        return (d.holdings || []).find(h => h.ticker === ticker)
            || (d.alternates || []).reduce(
                   (acc, a) => acc || (a.holdings || []).find(h => h.ticker === ticker),
                   null)
            || null;
    }

    // Strategy state for a vehicle the dial has NOT allocated.
    //
    // The dial payload builds state for the live column only, and that stays true: each
    // build walks ~26 years of history, so with QQQ/MO/PM/GC/XLE all wired an eager
    // payload would block a cold engine on five of them before the dial could paint. An
    // alternate's state is therefore fetched ON SELECTION and cached here — the panel
    // costs nothing for vehicles you are not looking at.
    const STR_STATE_TTL_MS = 15 * 60 * 1000;
    const _strState     = {};   // ticker -> {at, payload}   payload null = nothing to show
    const _strStateWait = {};   // ticker -> true while a fetch is in flight

    function strStateFor(h) {
        // DISPLAY IS DECOUPLED FROM ALLOCATION (user, 2026-08-20): a holding with no
        // `strategy` (an open allocation decision, e.g. MO) still asks the endpoint,
        // which answers has_strategy:false for genuinely unwired names and that
        // negative is cached. The rotation's own mechanics never read this.
        if (!h || !h.ticker) return null;
        // The live column's state short-circuits ONLY when it carries a real
        // strategy read. A no_strategy marker is the engine reporting the HOLDING
        // has no allocation -- which says nothing about whether the TICKER has a
        // registered strategy to display, so fall through to the endpoint (MO: the
        // rotation sleeve says "hold", the Rocket block shows the baseline).
        if (h.state && !h.state.no_strategy) return h.state;

        const hit = _strState[h.ticker];
        if (hit && (Date.now() - hit.at) < STR_STATE_TTL_MS) return hit.payload;

        if (!_strStateWait[h.ticker]) {
            _strStateWait[h.ticker] = true;
            fetch(`${API_BASE}/get_ticker_strategy/${encodeURIComponent(h.ticker)}`)
                .then(r => r.json())
                // CACHE THE NEGATIVE TOO. A vehicle whose build failed would otherwise be
                // re-fetched on every poll, turning a broken strategy into a request loop.
                .then(p => { _strState[h.ticker] =
                                 { at: Date.now(),
                                   payload: (p && p.ok && p.has_strategy) ? p : null }; })
                .catch(() => { _strState[h.ticker] = { at: Date.now(), payload: null }; })
                .finally(() => {
                    _strStateWait[h.ticker] = false;
                    if (strLast) renderStrategyDial(strLast);   // repaint with what landed
                });
        }
        // Serve the stale payload while a refresh is in flight rather than blanking the
        // block; on a first fetch there is nothing yet and this pass renders without it.
        return hit ? hit.payload : null;
    }

    // Label / value / footnote as three SIBLINGS, not a nested pair — .str-v is
    // fixed-width, so every footnote in the block starts at the same x.
    // `v` and `sub` are HTML: callers esc() anything dynamic.
    function strRow(k, v, sub, color) {
        const c = color ? ` style="color:${color}"` : '';
        return `<div class="str-row"><span class="str-k">${esc(k)}</span>` +
               `<span class="str-v"${c}>${v}</span>` +
               (sub ? `<span class="str-sub">${sub}</span>` : '') +
               `</div>`;
    }

    function strPct(v) {
        if (v === null || v === undefined || !isFinite(v)) return '—';
        const cls = v >= 0 ? 'str-up' : 'str-dn';
        return `<span class="${cls}">${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%</span>`;
    }

    // State color = POSTURE, in three tiers (user, 2026-08-10 — chose this over a
    // richer "what ends the position" scheme as doing too much):
    //   holding -> the TICKER's own color, so State reads as part of that instrument
    //              rather than introducing a new token
    //   exiting -> orange: an exit is already triggered and is just waiting on its
    //              condition. Orange (#fb923c, the stoplight's .sl-o) NOT amber —
    //              amber already means WARNING on Era and pending on the dial latch.
    //   flat    -> slate: visibly not a position.
    // Keyed off state_tier, never off a state NAME: the renderer must not learn any
    // strategy-specific vocabulary (see engine/qqq_system.py's CONTRACT).
    // Keyed on the CONTRACT's state_tier, never on state names — that is what lets a
    // different strategy show its own vocabulary with no change to this file.
    function strStateColor(tier, tickerColor) {
        if (tier === 'flat')    return '#64748b';
        if (tier === 'exiting') return '#fb923c';
        return tickerColor;     // holding
    }

    // Uncolored percentage — gap and depth are descriptive, not outcomes, so they
    // do not earn green/red (user, 2026-08-10). Reserving those two colors for
    // actual gains and losses is what keeps them meaningful elsewhere in the block.
    function strPctPlain(v) {
        if (v === null || v === undefined || !isFinite(v)) return '—';
        return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%`;
    }

    // The selected holding's block. Era / 200 SMA / gap / depth are REAL and generic
    // — computed identically for every name. The strategy rows are QQQ-only and
    // still invented; the prototype badge marks exactly that boundary.
    function renderStrategyStock(h) {
        const box = document.getElementById('str-stock');
        if (!box) return;
        if (!h) { box.innerHTML = ''; return; }

        // strStateFor returns the live column's own `state` untouched, and only reaches
        // for the endpoint when the selected vehicle is an alternate.
        const st = strStateFor(h) || h.state || {};
        // A strategy renders when the ENDPOINT knows one, whether or not the holding
        // allocates to it (h.strategy) -- MO displays its baseline while the
        // rotation sleeve decision stays open.
        const hasStrategy = st.ok && !st.no_strategy && st.state !== undefined;
        // Era: the STRATEGY's own reading wins for the name it governs. It walks the
        // full unadjusted history the system actually trades on, where the generic
        // technicals use a 5-year window — they can differ by a bar, and only one
        // number can be on screen. The authoritative one is the strategy's.
        const era = (hasStrategy ? st.era : h.era) || '—';
        const eraDays = hasStrategy ? st.era_days : h.era_days;
        // golden renders in GOLD (user, 2026-08-10) — the same #d4af37 token the GC
        // pill uses. WARNING amber, dark red. (The ERA is dark; only the CROSS that
        // starts it is a death cross — user, 2026-08-27.)
        // st.era_color first: a strategy may DECLARE its era's color (MO's retired Carry
        // wears MO's own brown) -- the renderer still learns no vocabulary.
        const eraColor = (hasStrategy && st.era_color)
                       || { golden: '#d4af37', WARNING: '#fbbf24', dark: '#f87171' }[era]
                       || '#64748b';

        // Era carries how long the name has been in it, in trading days — same unit
        // as the dial's own counter, so the two read together. A capped count means
        // the era predates the history window and the number is a floor.
        const eraSub = eraDays
            ? `${(!hasStrategy && h.era_days_capped) ? '>' : ''}${eraDays} td`
            : null;
        let rows = strRow('Era', esc(era), eraSub, eraColor);

        if (hasStrategy) {
            // The open position's P&L rides as State's FOOTNOTE rather than taking a
            // row of its own (user, 2026-08-10): it is a property of the state, not a
            // peer fact, and it still carries gain/loss color there.
            // PHASE GOES IN THE FOOTNOTE COLUMN, AND ONLY WHEN FLAT (user, 2026-08-15).
            // Two rules, both his:
            //   ACTIVE state -> no phase at all. "50MA dip" already names what is on; the
            //   cycle position adds nothing a reader needs there.
            //   CASH -> the phase explains it, because Cash reads identically whether the
            //   gate is holding the slot, B1 has yet to fire, or B1 is done.
            // It rides the THIRD span, never the value cell. `.str-v` is fixed at 66px, so
            // anything appended there wraps and costs the block a line — which is what made
            // the section look sloppy on the first attempt.
            // The two are mutually exclusive by construction: a flat system has no P&L, so
            // the footnote is free exactly when the phase needs it.
            rows += strRow('State', esc(st.state),
                           (st.pnl_pct === null || st.pnl_pct === undefined)
                               ? (st.state_tier === 'flat' && st.phase ? esc(st.phase) : null)
                               : strPct(st.pnl_pct),
                           strStateColor(st.state_tier, h.color));
            // THE PRICE THAT WOULD OPEN A POSITION — shown only while FLAT, because that is
            // the only time it is the next thing to happen. Colored in the instrument's own
            // hue at 55% so it reads as belonging to this name but is visibly NOT the solid
            // tone a held position wears: a target, not a fill.
            // A strategy may rest MORE THAN ONE bid at once (the tobacco ruleset keeps a
            // deep bid under its regime bid every day), so `triggers` is the ladder and
            // gets a row each, nearest first. `trigger` stays the single-value contract
            // QQQ and XLE fill; it is used only when no ladder is published, so neither
            // strategy changed and neither renders a level twice.
            if (st.state_tier === 'flat' && Array.isArray(st.triggers) && st.triggers.length) {
                st.triggers.forEach((t, i) => {
                    // The nearest rung wears the instrument's hue; the ones behind it fade,
                    // so the ladder reads in the order it would fill rather than as several
                    // equally-imminent orders.
                    rows += strRow('entry @', t.level.toFixed(2), esc(t.label || 'resting bid'),
                                   strHexToRgba(h.color, i === 0 ? 0.55 : 0.3));
                });
            } else if (st.state_tier === 'flat'
                && st.trigger !== null && st.trigger !== undefined) {
                rows += strRow('entry @', st.trigger.toFixed(2),
                               esc(st.trigger_basis || 'trigger'),
                               strHexToRgba(h.color, 0.55));
            }
            // Days held sit in parentheses after the entry DATE — the date is what
            // they qualify. Both rows are skipped when flat, and `target` is null on
            // the strategy's timer-based sleeves, which have no price target.
            if (st.entry_price !== null && st.entry_price !== undefined) {
                const held = (st.days_held === null || st.days_held === undefined)
                    ? '' : ` (${st.days_held} td)`;
                rows += strRow('entry', st.entry_price.toFixed(2),
                               esc(`${st.entry_date || '—'}${held}`));
            }
            if (st.target !== null && st.target !== undefined) {
                rows += strRow('target', st.target.toFixed(2),
                               st.target_mult ? `fill ×${st.target_mult}` : 'target');
            }
        } else if (_strStateWait[h.ticker]) {
            // A DECLARED strategy whose first read is still running. Without this branch
            // the block fell through to "no strategy" for the ~minute the build takes —
            // asserting the vehicle has no rule at the exact moment it is proving it has
            // one. The state is unknown here, not absent, and the row says so.
            rows += strRow('State', '<span class="str-st-off">building…</span>',
                           'first read walks ~26 years');
        } else {
            rows += strRow('State', '<span class="str-st-off">no strategy</span>',
                           'held · monthly rebal');
        }

        // 200 SMA row dropped (user, 2026-08-10) — never-sell-below is a rule he
        // already knows, and the exiting State covers the case where it binds.
        rows += strRow('gap', strPctPlain(h.gap_pct), '50/200 MA');
        rows += strRow('depth', strPctPlain(h.depth_pct), 'vs 50 SMA');
        // THE EXIT THAT GOVERNS THE OPEN POSITION: between depth and Era P&L, the slot
        // the standing carry order used to hold. Carry went out with MO's all-dip
        // baseline on 2026-08-25 and no live strategy emits `carry_level` any more; the
        // row it left is now the one that says where the position ends.
        // Which level that is depends on the sleeve and the ADAPTER decides — a trend
        // position runs to a new 252-day low, a bid sleeve to the 200. Nothing is
        // learned here: the label and the note both arrive named.
        // The note is the module's own sentence, so the level carries its own
        // justification the way the carry spread used to.
        if (hasStrategy && st.exit_level !== null && st.exit_level !== undefined) {
            rows += strRow(esc(st.exit_level_label || 'exit'),
                           st.exit_level.toFixed(2), esc(st.exit_note || ''),
                           strHexToRgba(h.color, 0.55));
        }
        // WHERE THE STATE ENDS — distinct from where the position exits, and during a
        // trend run it is the only level of the two that exists. Breaking it ends the
        // state and hands the book to a 200 retest; it is not a fill, which is why it
        // renders muted rather than in the ticker's colour like a live order.
        if (hasStrategy && st.state_end_level !== null && st.state_end_level !== undefined) {
            // Muted by COLOUR, not by size (user, 2026-08-26: too hard to read). It went
            // in wearing .str-st-off, which is 9px italic — that class is for the words
            // "no strategy", not for a price you are meant to read off the panel. Slate
            // at the row's normal mono size keeps it visibly not-a-live-order while
            // staying legible next to the levels above it.
            rows += strRow(esc(st.state_end_label || 'state'),
                           st.state_end_level.toFixed(2),
                           esc(st.state_end_note || ''), '#94a3b8');
        }
        // Era P&L last, by request. DEFINITION (user, 2026-08-10): the COMPOUNDED
        // return of everything the strategy did inside the current era — halo, then
        // B1, then any false-warning breakout — PLUS the open position marked to
        // market, PLUS idle cash earning the T-bill rate between trades. Geometric,
        // not additive, and the idle stretches compound in rather than counting as
        // flat: prod(1 + daily_ret) - 1 across the era, where daily_ret is the
        // position's return when held and the ^IRX daily rate when flat — exactly
        // what qqq_full_system.py's series() already builds as `dly`.
        // The era runs from the golden cross to the death cross.
        // A strategy may DECLARE what its era P&L is measured from; the tobacco ruleset
        // does, and MO's retired baseline did too (it re-based the clock to the carry
        // exit). The two cross labels stay as the fallback for strategies that say
        // nothing — QQQ and XLE still take that path.
        rows += strRow('Era P&L',
                       hasStrategy ? strPct(st.era_pnl_pct)
                                   : '<span class="str-st-off">—</span>',
                       hasStrategy ? esc(st.era_pnl_basis
                                         || (era === 'dark' ? 'since death cross'
                                                             : 'since golden cross'))
                                   : null);

        box.innerHTML =
            `<div class="str-blk-hd">` +
            `<span class="str-blk-nm" style="color:${h.color}">${esc(h.ticker)}</span>` +
            `<span class="str-state" style="color:${h.color}">` +
            `${h.price === null ? '—' : h.price.toFixed(2)}</span>` +
            `<span class="str-sub">${strPct(h.day_pct)}</span>` +
            // Prototype badge retired 2026-08-10 — these rows are live now. A stale
            // badge takes its place: shown only when the last state build FAILED and
            // we are serving the previous good payload.
            (st.stale ? `<span class="str-badge str-badge-warn">stale</span>` : '') +
            `</div>` + rows;
    }

    function renderStrategyDial(d) {
        const pill  = document.getElementById('str-dial-pill');
        const state = document.getElementById('str-dial-state');
        if (!pill || !state) return;               // section not on this page

        if (!d || !d.ok) {
            pill.textContent = 'DIAL —';
            state.textContent = '—';
            state.style.color = '#64748b';
            document.getElementById('str-alloc').innerHTML =
                `<div class="str-st-off">dial unavailable</div>`;
            return;
        }

        // Summary pill: color carries the STATE, the amber ring (str-near) carries
        // proximity to a threshold. Never conflate the two — the user's rule is that
        // the main color must always convey the actual state (2026-08-10).
        pill.textContent = `DIAL ${d.label.toUpperCase()}`;
        strTintPill(pill, d.color);
        pill.classList.toggle('str-near', !!d.near);
        pill.title = (d.near ? `${d.nearest_pp.toFixed(2)}pp from a threshold — judgment period`
                             : `${d.nearest_pp.toFixed(2)}pp from the nearest threshold`)
                   // The lookback and the series' name come from the payload — they are
                   // strategy, and naming them here would put them back in the repo.
                   + `\n${d.lookback_months}mo change ${d.chg >= 0 ? '+' : '−'}${Math.abs(d.chg).toFixed(2)}pp`
                   + ` · ${d.rate_label} ${d.rate.toFixed(2)}% as of ${d.asof}`
                   + (d.stale ? '\nSTALE — last good pull, FRED refresh failed' : '');

        // Second pill carries the live holdings, so a collapsed section still answers
        // "what am I holding" without expanding.
        const hp = document.getElementById('str-hold-pill');
        if (hp) {
            hp.textContent = d.holdings.map(h => h.ticker).join('·');
            strTintPill(hp, d.color);
        }

        state.textContent = d.label.toUpperCase();
        state.style.color = d.color;

        // Trading days in this state, next to the state itself. Calendar days go in
        // the tooltip — 89 td reads very differently from 127 days and both are true.
        const days = document.getElementById('str-dial-days');
        if (days) {
            days.textContent = d.days_in_state ? `${d.days_in_state} td` : '';
            days.title = d.cal_days_in_state
                ? `${d.days_in_state} trading days (${d.cal_days_in_state} calendar) in ${d.label}`
                : '';
        }

        document.getElementById('str-dial-latched').textContent =
            (d.stale ? 'stale · ' : '') + (d.latched_on ? `latched ${d.latched_on}` : '');

        // Default selection: the holding that actually has a strategy, else the
        // largest weight. Re-validated every render so a regime flip (which swaps
        // the whole book) cannot leave a stale ticker selected.
        strLast = d;
        // Validated across the WHOLE book now, so a deliberately-selected alternate
        // survives the poll. The DEFAULT is unchanged — still the live column's rule
        // holding — so nothing auto-selects a vehicle the dial has not allocated.
        if (!strFindHolding(d, strSel)) {
            const withRule = d.holdings.find(h => h.strategy);
            strSel = (withRule || d.holdings[0] || {}).ticker || null;
        }

        // Live column first, then the alternates in the server's rate-direction order.
        document.getElementById('str-alloc').innerHTML =
            strColumnHTML(d.label, d.color, d.holdings, false) +
            d.alternates.map(a => strColumnHTML(a.label, a.color, a.holdings, true)).join('');

        renderStrategyStock(strFindHolding(d, strSel));
    }

    function fetchStrategyDial() {
        fetch(`${API_BASE}/get_strategy_dial`)
            .then(r => r.json())
            .then(renderStrategyDial)
            .catch(e => console.error('[strategy] dial fetch failed:', e));
    }
