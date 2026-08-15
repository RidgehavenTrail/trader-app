// newsletter-dive.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    function renderQuoteChip(el, price, pct, label) {
        if (!el) return;
        if (price == null) { el.className = 'hidden'; el.innerText = ''; return; }
        let color, sign;
        if (pct == null || pct === 0) { color = 'text-slate-300'; sign = ''; }
        else if (pct > 0) { color = 'text-emerald-400'; sign = '+'; }
        else { color = 'text-red-400'; sign = ''; } // negatives already carry '-'
        const pctText = pct == null ? '' : ` ${sign}${pct}%`;
        el.className = `text-sm font-mono ${color}`;
        el.innerHTML = `${label != null ? label : price}${pctText}`;
    }

    async function loadTradeQuote(t) {
        const seq = _ndDiveSeq;                                  // stale-guard token (see showNewsletterDive)
        const el = document.getElementById('nd-quote');         // header: structure price
        const uel = document.getElementById('nd-underlying');   // tab row: underlying equity (options)
        el.className = 'hidden text-sm font-mono'; el.innerText = '';
        uel.className = 'hidden text-sm font-mono'; uel.innerText = '';
        // planned/open are the live actionable states; `unresolved` is included so an
        // enriched unresolved trade (carries its full basket/legs) still answers
        // "where's it at now?" — the ratio/price context that judges whether it
        // quietly triggered. Bare stubs never reach here (renderUnresolvedDive). closed
        // stays excluded (no live quote needed on a realized trade).
        if (!t || (t.status !== 'planned' && t.status !== 'open' && t.status !== 'unresolved')) return;
        el.className = 'text-sm font-mono text-slate-500'; el.innerText = '…';
        try {
            const q = await fetch(`${API_BASE}/get_trade_quote?id=${encodeURIComponent(t.id)}`).then(r => r.json());
            if (seq !== _ndDiveSeq) return;                      // a newer dive opened mid-fetch — don't paint
            // Header: the trading structure's own price (spread mark / underlying / ratio).
            renderQuoteChip(el, q && q.current_price, q && q.day_change_pct,
                (q && q.is_ratio) ? `${q.current_price} ratio` : undefined);
            // Tab-row far-right: underlying equity price — options trades only (the
            // backend returns underlying_price only for those). Prefixed with the ticker
            // so it reads as the equity, not the spread, and it survives leg expiry.
            if (q && q.underlying_price != null) {
                renderQuoteChip(uel, q.underlying_price, q.underlying_day_pct,
                    `${t.underlying} ${q.underlying_price}`);
            }
        } catch (err) {
            el.className = 'hidden'; uel.className = 'hidden';
        }
    }

    // --- Newsletter thesis deep-dive ---
    // Bumped on every dive open. loadTradeQuote() captures it and bails if a newer
    // dive has opened before its async fetch resolves — otherwise a prior trade's
    // late quote can paint onto the now-current panel (e.g. onto an unresolved stub,
    // whose view intentionally shows no quote).
    let _ndDiveSeq = 0;
    function showNewsletterDive(id) {
        const t = NEWSLETTER_TRADES.find(x => x.id === id) || NEWSLETTER_TRADES[0];
        if (!t) return; // empty store — nothing to dive into
        _ndDiveSeq++;
        const meta = getStatusMeta(t);
        showOnlyPanel('newsletter-dive');   // shared list in core.js — see DETAIL_PANELS
        // Restore the tab bar (an unresolved-stub dive hides it; a normal trade always shows it).
        document.getElementById('nd-tabs').style.display = '';

        // Unresolved trade dives as its full last-week self (conviction/entry/thesis/dates),
        // amber, with a one-line note prepended to the thesis below. Fall back to the minimal
        // stub panel ONLY for a bare discard stub (no status_history — see the card guard;
        // basket/legs can't detect a stub since a full outright has neither).
        if (t.status === 'unresolved' && !Array.isArray(t.status_history)) { renderUnresolvedDive(t, meta); return; }

        document.getElementById('nd-legs').innerHTML = getCardIdentityHTML(t);
        document.getElementById('nd-ratio').innerText = t.campaign_title || '';
        loadTradeQuote(t);
        document.getElementById('nd-status').innerText = meta.label;
        document.getElementById('nd-stale-badge').classList.toggle('hidden', !meta.stale);
        document.getElementById('nd-conviction').innerHTML = renderConvictionDotsHTML(t.conviction);
        document.getElementById('nd-levels').innerHTML = levelsRowHTML(t, meta);
        document.getElementById('nd-structure').innerHTML = renderOptionsStructureHTML(t);

        // thesis is a {rationale, positioning} object (schema-tightening §6). rationale
        // is the current writeup; positioning is a DATED HISTORY [{as_of, text}] (C.13) —
        // render newest-first, the latest read prominent and prior reads as dimmer,
        // indented history rows. Tolerates a legacy plain-string positioning (one
        // undated entry), a plain-string thesis, and null.
        const thesisEl = document.getElementById('nd-thesis');
        const th = t.thesis;
        if (th && typeof th === 'object') {
            const rationale = th.rationale || 'No thesis text captured for this issue.';
            const plist = Array.isArray(th.positioning) ? th.positioning
                : (th.positioning ? [{ as_of: null, text: th.positioning }] : []);
            const positioning = plist.slice().reverse().map((e, i) => {
                const asof = e.as_of ? `<span class="text-slate-600"> · as of ${esc(e.as_of)}</span>` : '';
                return i === 0
                    ? `<p class="mt-2 text-slate-400 text-xs"><span class="uppercase tracking-wide text-slate-500">Positioning · </span>${esc(e.text)}${asof}</p>`
                    : `<p class="mt-1 ml-3 text-slate-500 text-xs"><span class="text-slate-600">↳ </span>${esc(e.text)}${asof}</p>`;
            }).join('');
            thesisEl.innerHTML = `<p>${esc(rationale)}</p>${positioning}`;
        } else {
            thesisEl.innerText = th || 'No thesis text captured for this issue.';
        }
        // Unresolved: a one-line amber note atop last week's thesis — just what happened
        // (no update in the letter, but a name was still discussed), nothing about the rules.
        // Source: the live board's enriched `unresolved_reason`, else (Past Editions view) the
        // frozen object's own last `unresolved` status_history note — so both paths show it.
        if (t.status === 'unresolved') {
            const shNote = (t.status_history || []).slice().reverse().find(h => h.status === 'unresolved');
            const noteTxt = t.unresolved_reason || t.reason || (shNote && shNote.note);
            if (noteTxt) {
                thesisEl.innerHTML =
                    `<p class="mb-2 pl-2 border-l-2 border-amber-500/60 text-amber-300/90 text-xs">${esc(noteTxt)}</p>`
                    + thesisEl.innerHTML;
            }
        }

        // Trigger / invalidation notes: entry.note / stop.note, unconditionally
        // (not gated on tranches — see the HTML comment above nd-trigger-notes-section).
        // Plus any management-GUIDANCE levels (reassess/monetize) the newsletter filed
        // into targets[] — they belong here, with the entry/trigger info, not in Targets
        // (user, 2026-07-12); the split is isProfitTarget() above.
        const triggerNotes = [];
        if (t.entry && t.entry.note) triggerNotes.push(`<div><span class="text-slate-500">Entry —</span> ${esc(t.entry.note)}</div>`);
        numericTargets(t).filter(tg => !isProfitTarget(t, tg)).forEach(tg => {
            const lbl = esc((tg.label || 'guidance').replace(/_/g, ' '));
            const lvl = tg.level != null ? fmtLevel(tg) : '';
            const note = tg.note ? ` ${esc(tg.note)}` : '';
            triggerNotes.push(`<div><span class="text-slate-500 capitalize">${lbl} —</span> <span class="font-mono text-slate-300">${lvl}</span>${note}</div>`);
        });
        // Stop / invalidation. An options underlying-price stop (basis:"underlying") is
        // omitted from the premium level row, so show its LEVEL here (plus any note) —
        // otherwise KRE's 71.5–72, whose note doesn't restate the number, would vanish.
        // Non-options stops (pairs ratio, note-only) keep the plain note line.
        if (t.stop && t.stop.basis === 'underlying' && t.stop.level != null) {
            const sn = t.stop.note ? ` <span class="text-slate-400">· ${esc(t.stop.note)}</span>` : '';
            triggerNotes.push(`<div><span class="text-slate-500">Stop/Invalidation —</span> <span class="font-mono text-slate-300">${fmtLevel(t.stop)}</span> <span class="text-slate-500">(underlying)</span>${sn}</div>`);
        } else if (t.stop && t.stop.note) {
            triggerNotes.push(`<div><span class="text-slate-500">Stop/Invalidation —</span> ${esc(t.stop.note)}</div>`);
        }
        document.getElementById('nd-trigger-notes-section').classList.toggle('hidden', triggerNotes.length === 0);
        document.getElementById('nd-trigger-notes').innerHTML = triggerNotes.join('');

        const datesEl = document.getElementById('nd-dates');
        datesEl.innerHTML = (t.key_dates && t.key_dates.length)
            ? t.key_dates.map(k => `<div class="flex items-center gap-2">
                    <span class="${k.passed ? 'text-emerald-400' : 'text-slate-500'}">${k.passed ? '✓' : '○'}</span>
                    <span class="font-mono text-xs text-slate-400">${k.date}</span>
                    <span>${k.event}</span>
                </div>`).join('')
            : '<p class="text-slate-500 italic">No catalyst dates flagged for this trade.</p>';

        const histEl = document.getElementById('nd-status-history');
        histEl.innerHTML = (t.status_history || []).map(h => {
            const pnlText = h.pnl ? ` — ${h.pnl.value >= 0 ? '+' : ''}${h.pnl.value}${h.pnl.unit === 'pct' ? '%' : ''}` : '';
            // Show the note too — it carries the audit trail (risk-parameter changes,
            // close reasoning) and, going forward, qualitative target guidance routed
            // here (e.g. SMH "continued outperformance") instead of a fake target.
            const noteText = h.note ? `<span class="block text-xs text-slate-400 ml-4 mt-0.5">${esc(h.note)}</span>` : '';
            return `<p class="text-slate-300 text-sm"><span class="font-mono text-xs text-slate-500">${h.date}</span> — ${h.status}${pnlText}${noteText}</p>`;
        }).join('');

        // Tranches (A.8): scaled-entry / planned-add levels captured from the
        // newsletter (e.g. HG copper's $6.15 add). Previously extracted but read
        // by no code, so invisible in the UI. Hide the whole block when empty.
        const tranches = t.tranches || [];
        const tranchesSection = document.getElementById('nd-tranches-section');
        tranchesSection.classList.toggle('hidden', tranches.length === 0);
        if (tranches.length) {
            // Tranches are typed entities (§8d): {size?, entry_price?, entry_date?,
            // status, exit_price?, exit_date?, pnl?, note?}. The scale-in plan context
            // (trigger conditions like "add on ratio close >3.22") now renders
            // unconditionally via #nd-trigger-notes above, so it's not duplicated here.
            const trNote = tr => tr.note ? ` <span class="text-slate-500">— ${esc(tr.note)}</span>` : '';
            document.getElementById('nd-tranches').innerHTML = tranches.map(tr => {
                // Planned (unfilled) scaled add (C.3) — entry_price is the TRIGGER
                // level, not a fill; render it distinctly as a planned add.
                if (tr.status === 'planned') {
                    return `<div class="flex items-start gap-1.5"><span class="text-amber-400/60 shrink-0">▹</span>
                        <span class="text-slate-400">planned add${tr.entry_price != null ? ` @ <span class="font-mono text-amber-300/80">${tr.entry_price}</span>` : ''}${trNote(tr)}</span></div>`;
                }
                const bits = [];
                if (tr.entry_price != null) bits.push(`<span class="font-mono text-amber-300">${tr.entry_price}</span>`);
                if (tr.size != null) bits.push(`<span class="text-xs text-slate-400">${tr.size}×</span>`);
                if (tr.status) bits.push(`<span class="text-xs text-slate-500">${esc(tr.status)}</span>`);
                if (tr.status === 'closed' && tr.exit_price != null) {
                    let exit = `→ <span class="font-mono text-slate-300">${tr.exit_price}</span>`;
                    if (tr.pnl && tr.pnl.value != null) {
                        const pos = tr.pnl.value >= 0;
                        exit += ` <span class="${pos ? 'text-emerald-400' : 'text-red-400'}">${pos ? '+' : ''}${tr.pnl.value}${tr.pnl.unit === 'pct' ? '%' : ''}</span>`;
                    }
                    bits.push(exit);
                }
                return `<div class="flex items-start gap-1.5"><span class="text-amber-400 shrink-0">▸</span><span>${bits.join(' · ')}${trNote(tr)}</span></div>`;
            }).join('');
        }

        // Carry per-leg {ticker, side} through to the chart layer so the pair
        // ratio can sum long vs short legs correctly (A.6) — the old bare-ticker
        // array (t.basket.map(b => b.ticker)) discarded side and let loadChart
        // pair legs by array position.
        viewState.nd.entity = {
            asset_class: t.asset_class,
            ticker: t.underlying,
            basketLegs: t.basket ? t.basket.map(b => ({ ticker: b.ticker, side: b.side })) : null,
            // A ratio-triggered outright (e.g. MAGS long on the SOXX/MAGS 50DMA break, §
            // derive_ratio_trigger) charts the RATIO instead of the single stock — the card
            // stays outright, only the detail chart/header change.
            ratioTrigger: t.ratio_trigger || null
        };
        viewState.nd.loadedFor = null;
        // Gate the Options TAB (real live-chain-style content, meaningless for a
        // basket) on trade STRUCTURE, not asset_class alone: under the tightened
        // schema a pairs trade is asset_class 'equity' (`pair` was dropped as an
        // asset_class), but a basket has no single options chain — so feed a
        // synthetic 'pair' to keep the Options TAB hidden via the shared equity-only
        // check. Options structures and single-name equity outrights keep their
        // real 'equity' chain; futures/forex outrights stay hidden as before.
        const ndGatingClass = (t.structure === 'pairs') ? 'pair' : t.asset_class;
        setTabsForAssetClass('nd', ndGatingClass);
        // Do NOT call setOptionsDataVisibility('nd', ...) here (fix, 2026-07-11).
        // That function pre-dates the C.4 rewrite of renderOptionsStructureHTML(),
        // which now always renders real content for THIS quadrant — options legs,
        // basket composition, or a plain-outright statement — never truly blank.
        // Calling it with ndGatingClass (which is 'pair' for baskets) set
        // visibility:hidden on the whole quadrant, silently undoing the C.4 fix:
        // the box still reserved its full height in layout (visibility:hidden, not
        // display:none) but rendered nothing visible — confirmed live on the
        // IGV/SOXX pair, whose basket-composition chips were fully populated in the
        // DOM but invisible on screen. The 'dd' (ticker Actionable-Moves) quadrant
        // is unrelated and still correctly gated below — it shows literal live
        // options-chain fields (ATM strike/IV/etc.) that genuinely don't exist for
        // non-equity tickers.
        document.getElementById('nd-options-data').style.visibility = 'visible';
        resetToNarrativeTab('nd');
    }

    // Minimal detail panel for an `unresolved` discard stub. Populates the header +
    // the Thesis/Key-Dates/Status-History column with the drop context, blanks the
    // trade-specific sections, and hides the Chart/Options tabs (a bare stub has no
    // chart or option chain). Keeps the panel intentional instead of half-empty.
    function renderUnresolvedDive(t, meta) {
        const title = (t.tickers && t.tickers.length) ? t.tickers.join(' / ') : (t.strategy_id || '--');
        const reason = t.reason || 'Dropped by silence this issue.';
        const kind = unresolvedStubKind(t);
        document.getElementById('nd-legs').innerHTML = `${esc(title)} <span class="text-sm text-slate-400 font-normal">${kind ? kind + ' · ' : ''}unresolved</span>`;
        document.getElementById('nd-ratio').innerText = '';
        // Clear any quote chips left by a previously-viewed trade — a stub has no live quote.
        document.getElementById('nd-quote').className = 'hidden text-sm font-mono';
        document.getElementById('nd-underlying').className = 'hidden text-sm font-mono';
        document.getElementById('nd-status').innerText = meta.label;
        document.getElementById('nd-stale-badge').classList.add('hidden');
        document.getElementById('nd-conviction').innerHTML = '';
        document.getElementById('nd-levels').innerHTML = '<span class="text-slate-500">—</span>';
        document.getElementById('nd-structure').innerHTML = '';
        document.getElementById('nd-options-data').style.visibility = 'hidden';
        document.getElementById('nd-thesis').innerHTML =
            `<p><span class="text-amber-400 font-semibold">Dropped as unresolved</span> — the trade got no entry/exit/stop update this issue, but a constituent ticker was still discussed, so it wasn't marked abandoned. It stays in the archive for your judgment; it may have quietly triggered or simply been dropped.</p>` +
            `<p class="mt-2 text-slate-400 text-xs">${esc(reason)}</p>` +
            `<p class="mt-2 text-slate-500 text-xs italic">Open last week’s issue from Past Editions to see the full setup.</p>`;
        document.getElementById('nd-trigger-notes-section').classList.add('hidden');
        document.getElementById('nd-dates').innerHTML =
            '<p class="text-slate-500 italic">No catalyst dates — this is a dropped-trade record.</p>';
        document.getElementById('nd-status-history').innerHTML =
            `<p class="text-slate-300 text-sm"><span class="font-mono text-xs text-slate-500">${esc(t.dropped_on || '')}</span> — unresolved` +
            `<span class="block text-xs text-slate-400 ml-4 mt-0.5">${esc(reason)}</span></p>`;
        document.getElementById('nd-tranches-section').classList.add('hidden');
        document.getElementById('nd-tabs').style.display = 'none';
        resetToNarrativeTab('nd');
    }
