// actionable.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    let dynamicContextData = {};
    let lastActionableSnapshot = '';

    async function fetchActionableMoves() {
        try {
            const res = await fetch(`${API_BASE}/get_actionable_moves`);
            const actionableData = await res.json();
            dynamicContextData = actionableData;

            const container = document.getElementById('actionable-container');
            const tickers = Object.keys(actionableData);
            const snapshot = JSON.stringify(actionableData);

            // Skip full DOM rebuild if data hasn't changed — preserves scroll position
            if (snapshot === lastActionableSnapshot) return;
            lastActionableSnapshot = snapshot;
            const scrollLeft = container.scrollLeft;

            if (tickers.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center h-full text-slate-500 text-xs italic text-center p-2 min-w-full">
                        No stocks have exceeded their 1σ expected move yet.<br>Monitoring active lists...
                    </div>`;
                return;
            }

            // Multi-condition cards: sort/priority is Turtle > 2x volume >
            // 1-sigma; a card's rank is the highest-priority condition in its
            // set, and all fired conditions render as badges (turtle-volume-
            // indicators.md). PRIORITY ids match the engine's condition tags.
            const PRIORITY = { 'turtle-trade': 3, '2x-volume': 2, '1-sigma': 1 };
            const priorityRank = (conds) => (conds || []).reduce((m, c) => Math.max(m, PRIORITY[c] || 0), 0);
            const badgeFor = (cond, meta) => {
                if (cond === '2x-volume') {
                    const r = meta && meta['2x-volume'] && meta['2x-volume'].ratio;
                    return { text: r ? `${r}x vol` : '2x vol', cls: 'bg-amber-500/20 text-amber-300' };
                }
                if (cond === 'turtle-trade') {
                    const dir = meta && meta['turtle-trade'] && meta['turtle-trade'].direction;
                    const arrow = dir === 'short' ? ' ↓' : (dir === 'long' ? ' ↑' : '');
                    return { text: 'Turtle' + arrow, cls: 'bg-violet-500/20 text-violet-300' };
                }
                if (cond === '1-sigma')     return { text: '1σ',      cls: 'bg-slate-600/40 text-slate-300' };
                return { text: cond, cls: 'bg-slate-600/40 text-slate-300' };
            };

            // Bubble the highest-priority conditions to the front; Array.sort is
            // stable, so cards of equal rank keep their existing (insertion) order.
            const ordered = tickers.slice().sort((a, b) =>
                priorityRank(actionableData[b].conditions) - priorityRank(actionableData[a].conditions)
            );

            container.innerHTML = ordered.map(ticker => {
                const data = actionableData[ticker];
                const isPositive = data.price_change > 0;
                const borderColor = isPositive ? 'border-l-emerald-500' : 'border-l-red-500';
                const priceColor = isPositive ? 'text-emerald-400' : 'text-red-400';
                const sign = isPositive ? '+' : '';
                const conds = data.conditions || [];
                // Cards carrying a volume/Turtle condition get a subtle ring so
                // they stand out above plain 1-sigma-only cards.
                const highlight = priorityRank(conds) >= 2 ? ' ring-1 ring-amber-400/50' : '';
                const badges = conds.map(c => {
                    const b = badgeFor(c, data.condition_meta);
                    return `<span class="text-[9px] font-semibold px-1.5 py-0.5 rounded ${b.cls}">${esc(b.text)}</span>`;
                }).join('');
                const badgeRow = badges ? `<div class="flex flex-wrap gap-1 mt-0.5">${badges}</div>` : '';
                // A bound carried from the prior session's last live book (options do not
                // quote pre-market) is marked, so the number is not read as live.
                const emCarried = data.em_source === 'prior_close';
                const emMark = emCarried
                    ? `<span class="text-slate-500" title="Prior-session close mark — options do not quote pre-market">*</span>`
                    : '';
                const emText = (data.expected_move != null) ? `±${data.expected_move}%${emMark}` : '';
                return `
                    <div class="glass-panel group relative rounded-xl cursor-pointer hover:bg-slate-800 transition border-l-4 ${borderColor}${highlight} shadow-lg flex flex-col gap-0.5" onclick="updateContext('${ticker}')" ondragstart="return false">
                        <button class="dismiss-btn absolute top-0.5 right-1 invisible group-hover:visible text-slate-500 hover:text-red-400 text-xs leading-none" title="Dismiss card" onclick="event.stopPropagation(); dismissActionable('${esc(ticker)}')">✕</button>
                        <div class="flex justify-between items-baseline pr-4">
                            <span class="text-base font-bold">${ticker}</span>
                            <span class="text-base font-bold ${priceColor}">${sign}${data.price_change}%</span>
                        </div>
                        <div class="flex justify-between items-baseline">
                            <span class="text-xs font-mono text-slate-300">${data.price}</span>
                            <span class="text-xs text-slate-400">${emText}</span>
                        </div>
                        ${badgeRow}
                        <p class="text-[10px] text-slate-400 line-clamp-2">${data.why || 'Scanning latest headlines...'}</p>
                    </div>
                `;
            }).join('');
            container.scrollLeft = scrollLeft;
        } catch (err) {
            console.error("Error fetching actionable moves:", err);
        }
    }

    // Remove a single actionable card (user dismiss — e.g. an --as-of-date test
    // card). POSTs to the engine, then forces a re-render by clearing the snapshot.
    async function dismissActionable(ticker) {
        try {
            await fetch(`${API_BASE}/dismiss_actionable`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker })
            });
            lastActionableSnapshot = '';   // bypass the no-change dedup so it re-renders
            fetchActionableMoves();
        } catch (err) {
            console.error('dismiss failed', err);
        }
    }

    // --- DRAG-TO-SCROLL + WHEEL-TO-HORIZONTAL, shared by any horizontal card
    // strip. Ported verbatim from trader_dashboard.html for #actionable-container;
    // generalized (A.5) so #newsletter-container gets the same interaction — it
    // previously only had native CSS overflow-x-scroll, which doesn't respond to
    // a plain vertical mouse-wheel roll (only trackpad swipe / shift+wheel /
    // manual scrollbar drag). Per CLAUDE.md's Known Pitfalls: uses window-level
    // capture-phase pointer events, and card children have pointer-events:none
    // (see CSS) so pointerdown always resolves to the outer card div's onclick —
    // the pointerdown event does not bubble correctly from child elements to the
    // container in Chrome. Do not change this approach; it was hard-won after
    // extensive debugging on the original strip and applies identically here.
    const TRIGGER_DEFS = [
        { id: '1-sigma', label: '1σ Move' },
        { id: '2x-volume', label: '2x Volume' },
        { id: 'turtle-trade', label: 'Turtle Trade' }
    ];

    function renderTriggers(view, hitList) {
        const container = document.getElementById(view + '-triggers');
        if (!container) return;
        const hits = hitList || [];
        container.innerHTML = TRIGGER_DEFS.map(t => {
            const hit = hits.includes(t.id);
            return '<div class="trigger-row ' + (hit ? 'hit' : 'not-hit') + '">' +
                       '<span class="trigger-dot' + (hit ? ' hit' : '') + '">' + (hit ? '✓' : '') + '</span>' +
                       t.label +
                   '</div>';
        }).join('');
    }

    // --- Newsletter trade data — real .claude/rules/newsletter-schema.md shape,
    // now fetched live from the ingestion store (watchtower_engine.py :5001) via
    // loadNewsletterState() rather than hand-authored. NEWSLETTER_TRADES is the
    // store's live working set + closed archive (discarded stubs omitted);
    // NEWSLETTER_ISSUE is the most recent issue envelope; newsletterEditions is
    // the Past Editions list. All start empty and populate on load / after an
    // import. The render functions below already consume this exact shape.