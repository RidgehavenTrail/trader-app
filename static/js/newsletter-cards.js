// newsletter-cards.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    let NEWSLETTER_TRADES = [];
    let NEWSLETTER_ISSUE = null;
    let newsletterEditions = [];

    // Live state is loaded by loadNewsletterState() (defined below); no
    // hand-authored trade/issue data remains in this file.

    // --- Derived-display helpers (schema fields -> layout, per newsletter-schema.md) ---

    // Card/header label. Pairs use `basket`, options use `legs`, everything
    // else falls back to a plain ticker. campaign_title (when present) is a
    // human mnemonic, not a replacement for the underlying instrument label.
    function getLegsLabel(t) {
        if (t.basket) return t.basket.map(b => b.ticker).join(' / ');
        if (t.legs) {
            const expiry = t.legs[0].expiry ? t.legs[0].expiry.slice(5).replace('-', '/') : '';
            return t.legs.map(l => `${l.strike}${l.type[0].toUpperCase()}`).join('/') + (expiry ? ` ${expiry}` : '');
        }
        return t.underlying || '--';
    }

    // --- Card/dive identity line (section D card specs, resolves A.2) ---
    // Three trade shapes, each with its own Line 2: basket -> composition +
    // "Pair"; options (has `legs`) -> underlying + structure (Call/Put Spread,
    // never campaign_title-or-strikes); outright (no basket, no legs) ->
    // bare underlying + direction word, colored via the existing P&L
    // green/red tokens (B.4 / section D "Outright card").
    function getBasketCompositionLabel(basket) {
        const longs = basket.filter(b => b.side === 'long').map(b => b.ticker).join('+');
        const shorts = basket.filter(b => b.side === 'short').map(b => b.ticker).join('+');
        return shorts ? `${longs}/${shorts}` : longs;
    }

    // Full descriptive label from structure_label: "bear_call_spread" ->
    // "Bear Call Spread". Shown on BOTH the card and the detail panel (user
    // override of section D's original card-terseness rule — the directional
    // Bear/Bull word helps frame what the trade is at a glance).
    function getStructureDisplay(t) {
        const label = t.structure_label || '';
        if (label) return label.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        return (t.structure || '').replace(/_/g, ' ');
    }

    // Forex pairs store as a bare 6-letter code (USDJPY); display with a slash.
    // Plain equity/future tickers display as-is.
    function formatOutrightTicker(t) {
        const u = t.underlying || '';
        if (t.asset_class === 'forex' && /^[A-Z]{6}$/.test(u)) {
            return u.slice(0, 3) + '/' + u.slice(3);
        }
        return u || '--';
    }

    function getCardIdentityHTML(t) {
        if (t.basket) {
            return `<span class="font-bold">${esc(getBasketCompositionLabel(t.basket))}</span>` +
                   `<span class="text-xs text-slate-400 font-normal ml-1">Pair</span>`;
        }
        if (t.legs) {
            return `<span class="font-bold">${esc(t.underlying || '--')}</span>` +
                   `<span class="text-xs text-slate-400 font-normal ml-1">${esc(getStructureDisplay(t))}</span>`;
        }
        const dirWord = t.direction === 'long' ? 'Long' : t.direction === 'short' ? 'Short' : '';
        const dirColor = t.direction === 'long' ? 'text-emerald-400' : t.direction === 'short' ? 'text-red-400' : '';
        return `<span class="font-bold">${esc(formatOutrightTicker(t))}</span>` +
               (dirWord ? `<span class="text-xs font-bold ${dirColor} ml-1">${dirWord}</span>` : '');
    }

    // Formats an entry/stop/targets[] level object as a bare number, or a
    // "level–level_high" range when level_high is stated (B.1 frontend impact).
    function fmtLevel(obj) {
        if (!obj || obj.level === null || obj.level === undefined) return '--';
        return (obj.level_high !== null && obj.level_high !== undefined)
            ? `${obj.level}–${obj.level_high}`
            : `${obj.level}`;
    }

    // "2026-06-18" -> "Jun 18"; "2026-06" (month only) -> "Jun". Bare/null -> ''.
    function formatExpiry(exp) {
        if (!exp) return '';
        const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        const p = exp.split('-');
        const mon = MON[parseInt(p[1], 10) - 1] || '';
        return p[2] ? `${mon} ${parseInt(p[2], 10)}` : mon;
    }

    // reference_values chips, FILTERING OUT chart-derivable stats (C.5/C.6): moving
    // averages and spot/close prices are already on the Chart tab, so they're
    // redundant here — keep only trade-specific numbers the chart can't show (z-scores,
    // betas, IV, skew, credit/debit references). Fix (2026-07-11): the old regex only
    // matched `dma_x`/`x_dma` naming and missed `igv_50dma`-style keys (digits directly
    // before "dma", no separator) — a real moving-average field slipped through as a
    // "trade-specific" chip. Broadened to a plain `dma` substring match, which catches
    // every naming variant seen so far.
    function refValueChips(rv) {
        return Object.entries(rv || {})
            .filter(([k]) => !/(dma|close$|^spot|_spot)/i.test(k));
    }

    // Renders filtered reference-value entries as a chip grid, column count matched
    // to the actual chip count (2026-07-11 fix) — previously hardcoded grid-cols-3
    // left a visibly empty, unlabeled cell whenever fewer than 3 chips survived the
    // filter (e.g. IGV/SOXX: only 1-2 chips after fixing the dma-filter above).
    function refValueChipsBlock(rv) {
        const entries = refValueChips(rv);
        if (!entries.length) return '';
        const cols = Math.min(entries.length, 3);
        const chips = entries.map(([k, v]) =>
            `<div class="bg-slate-800/50 rounded-lg p-2 border border-slate-700 text-center">
                <p class="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">${esc(k.replace(/_/g, ' '))}</p>
                <p class="text-xs font-mono text-slate-200">${esc(v)}</p>
            </div>`).join('');
        return `<div class="grid gap-2 mt-1" style="grid-template-columns: repeat(${cols}, minmax(0, 1fr));">${chips}</div>`;
    }

    // Package-membership banner (item G, 2026-07-11): a funded multi-underlying
    // options package (e.g. QQQ/CRM/HUBS downside convexity) is stored as one
    // trade object PER underlying, all sharing `package_id`. This surfaces that
    // linkage in the detail panel — the package slug + clickable sibling legs
    // (each shows its own status, since package legs close independently).
    // Empty string for the vast majority of trades (package_id null).
    function packageSiblingsHTML(t) {
        if (!t.package_id) return '';
        const siblings = NEWSLETTER_TRADES.filter(x => x.package_id === t.package_id && x.id !== t.id);
        const links = siblings.map(s => {
            const label = esc(s.underlying || s.id);
            const st = esc(getStatusMeta(s).label || s.status || '');
            return `<button onclick="showNewsletterDive('${s.id}')" class="text-cyan-300 hover:text-cyan-200 underline underline-offset-2">${label}</button> <span class="text-slate-500 text-[10px]">${st}</span>`;
        }).join('<span class="text-slate-600 mx-1">·</span>');
        const sibRow = siblings.length
            ? `<div class="flex flex-wrap items-center gap-1 mt-1 text-xs">${links}</div>`
            : `<p class="text-slate-500 text-[11px] mt-0.5 italic">other package legs not in the current set</p>`;
        return `<div class="p-3 bg-cyan-900/20 rounded-lg border border-cyan-500/30 mb-2">
                    <p class="text-[10px] font-bold text-cyan-300 uppercase tracking-widest">Part of Package</p>
                    <p class="text-slate-400 text-[11px] mt-0.5 font-mono">${esc(t.package_id)}</p>
                    ${sibRow}
                </div>`;
    }

    // Detail-panel "Trade Structure" block: the trade's OWN newsletter-specified
    // legs + break-even + reference stats (static) — distinct from live options-chain
    // market data, which has no endpoint for newsletter trades. For a non-options
    // trade (outright/pairs) it states that plainly but STILL shows the trade's stats
    // (C.4: pairs z-scores/betas were previously invisible).
    function renderOptionsStructureHTML(t) {
        const chipsBlock = refValueChipsBlock(t.reference_values);
        const pkgBlock = packageSiblingsHTML(t);
        if (!t.legs || !t.legs.length) {
            // Pairs/basket: list each component (side/ticker/weight + per-component
            // note) — parallel to how options list legs, so basket notes have a home.
            if (t.structure === 'pairs' && t.basket && t.basket.length) {
                const rows = t.basket.map(b => {
                    const sideColor = b.side === 'long' ? 'text-emerald-400' : 'text-red-400';
                    // The note WRAPS rather than clipping (user, 2026-09-01): it was
                    // `truncate`, so a basket component's reason got an ellipsis at the
                    // pane's width and the half that explains the leg was unreadable.
                    // `min-w-0` is what actually lets it wrap — a flex item's default
                    // min-width:auto refuses to shrink below its content, so removing
                    // `truncate` alone would push the row wide instead of breaking it.
                    // Baseline alignment keeps the first line level with LONG/SHORT
                    // while later lines run underneath.
                    const note = b.note ? `<span class="text-slate-500 text-xs min-w-0 break-words">${esc(b.note)}</span>` : '';
                    const weight = b.weight != null ? `<span class="text-slate-500 text-xs ml-auto shrink-0">${b.weight}</span>` : '';
                    return `<div class="flex items-baseline gap-2 text-sm font-mono">
                                <span class="${sideColor} font-bold w-12 shrink-0">${esc((b.side || '').toUpperCase())}</span>
                                <span class="text-slate-100 font-bold shrink-0">${esc(b.ticker)}</span>
                                ${note}${weight}
                            </div>`;
                }).join('');
                return `${pkgBlock}<div class="p-4 bg-slate-800/50 rounded-lg border border-slate-700 flex flex-col gap-2">
                            <p class="text-xs font-bold text-slate-300">Basket / Pair</p>
                            <div class="flex flex-col gap-1">${rows}</div>
                            ${chipsBlock}
                            ${targetRowsHTML(t)}
                        </div>`;
            }
            const desc = `Outright ${esc(t.asset_class || '')} position`.trim();
            return `${pkgBlock}<div class="p-4 bg-slate-800/50 rounded-lg border border-slate-700 flex flex-col gap-2">
                        <p class="text-slate-500 text-sm italic">${desc} — no options structure.</p>
                        ${chipsBlock}
                        ${targetRowsHTML(t)}
                    </div>`;
        }
        const legRows = t.legs.map(l => {
            const act = (l.action || '').toUpperCase();
            const actColor = act === 'SELL' ? 'text-red-400' : 'text-emerald-400';
            const typ = l.type ? l.type[0].toUpperCase() : '';
            return `<div class="flex items-center gap-2 text-sm font-mono">
                        <span class="${actColor} font-bold w-11 shrink-0">${act}</span>
                        <span class="text-slate-100 font-bold">${l.strike}${typ}</span>
                        <span class="text-slate-500 text-xs shrink-0">${formatExpiry(l.expiry)}</span>
                        ${l.note ? `<span class="text-slate-500 text-xs truncate">${esc(l.note)}</span>` : ''}
                    </div>`;
        }).join('');
        // Break-even (C.2) — Python-derived from legs + credit/debit; shown when known.
        const be = (t.break_even != null)
            ? `<p class="text-xs text-slate-400 mt-1">Break-even <span class="font-mono text-slate-200">${t.break_even}</span></p>`
            : '';
        return `${pkgBlock}<div class="p-4 bg-slate-800/50 rounded-lg border border-slate-700 flex flex-col gap-2">
                    <p class="text-xs font-bold text-slate-300">${esc(getStructureDisplay(t))}</p>
                    <div class="flex flex-col gap-1">${legRows}</div>
                    ${be}
                    ${chipsBlock}
                    ${targetRowsHTML(t)}
                </div>`;
    }

    // A targets[] entry with a numeric level (or an expiration_worthless credit spread,
    // whose "target" is 0). Not every targets[] entry is a real profit target — see below.
    function numericTargets(t) {
        return (t.targets || []).filter(
            x => x && (x.level != null || x.label === 'expiration_worthless'));
    }

    // Split targets[] into PROFIT targets vs position-management GUIDANCE (user,
    // 2026-07-12). The newsletter files underlying-price/management levels into
    // targets[] — GLD 395/372 "T1 380 / T2 372" (underlying gold prices) and KRE
    // "reassess 80 / monetization_zone 83–85" — which aren't premium profit objectives.
    // The LABEL can't be trusted (GLD calls them T1/T2), so the split is by UNIT: Python
    // (derive_target_basis) tags an options target basis:"underlying" when its level is a
    // real underlying price (>= the strikes) rather than a premium; the frontend just
    // reads that tag. Non-options targets share the entry's unit (underlying/ratio) — all
    // are real targets. Guidance routes to the Trigger/Invalidation section (see
    // showNewsletterDive).
    function isProfitTarget(t, tg) {
        if (t && t.structure === 'options') return !(tg && tg.basis === 'underlying');
        return true;
    }

    // Targets sub-block folded INTO the Trade Structure box (item N fix, 2026-07-12) —
    // lists every PROFIT target (not just targets[0]); management-guidance levels are
    // routed to the Trigger/Invalidation section instead (see showNewsletterDive). The
    // compact strip/level rows intentionally show only the nearest target
    // (targetDisplay -> targets[0]) to stay lean, so a multi-target trade's later targets
    // (e.g. the Space Trade's T2 6.0–6.25 trim zone) were invisible everywhere. ONLY
    // renders with 2+ profit targets (a single one already shows in the compact level
    // row). Returns a divider-topped sub-section (no box of its own — it lives inside the
    // structure box); empty string otherwise.
    function targetRowsHTML(t) {
        const tgts = numericTargets(t).filter(tg => isProfitTarget(t, tg));
        if (tgts.length < 2) return '';   // multi-target only; a single target already shows in the level row
        const rows = tgts.map(tg => {
            const lvl = tg.level != null ? fmtLevel(tg) : '0';
            // Labels vary from short (T1/T2) to descriptive (monetization_zone) — humanize
            // the underscore and DON'T fix the width: a w-10 column clipped the long ones
            // into unreadable overlap (user, 2026-07-12). The number is shrink-0 so it
            // never clips; the note takes the remaining width and wraps.
            const label = tg.label ? esc(tg.label.replace(/_/g, ' ')) : '';
            const note = tg.note ? `<span class="text-slate-500 text-xs">${esc(tg.note)}</span>` : '';
            return `<div class="flex items-baseline gap-2 text-sm font-mono">
                        <span class="text-slate-100 font-bold shrink-0">${lvl}</span>
                        ${label ? `<span class="text-emerald-400 text-xs shrink-0">${label}</span>` : ''}
                        ${note}
                    </div>`;
        }).join('');
        return `<div class="flex flex-col gap-1 mt-1 pt-2 border-t border-slate-700/50">
                    <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Targets</p>
                    ${rows}
                </div>`;
    }

    // Status label: New is not a schema status — it's `planned` trades on
    // their very first appearance (first_seen === last_mentioned). Once a
    // planned trade survives into a second issue without triggering, it
    // reverts to Watching. `abandoned`/`deleted` trades are filtered out
    // entirely before this ever runs (silence = drop, per the schema).
    function getStatusMeta(t) {
        // Two DECOUPLED axes (user 2026-07-10):
        //  • `tone`  = the trade's actual LIFECYCLE state — drives card COLOR, the
        //    price-line (Entry/Tgt-Stop/P&L) and opacity.
        //  • `label` = the BADGE. "New" takes PRIORITY: a trade on its first appearance
        //    wears the New badge even when already entered (open), so a new+entered trade
        //    shows a New badge on an Active(violet)-toned card.
        const stale = t.status === 'open' && !!t.stale_flag;
        // Unresolved: a planned trade dropped by silence this issue (still in `discarded`),
        // surfaced for its transition week. Sits just after the live cluster (order 1.5) —
        // near where it was last seen — so the drop reads as continuity, not a vanish.
        if (t.status === 'unresolved') return { label: 'Unresolved', tone: 'Unresolved', dot: 'status-dot-watching', order: 1.5, stale: false };
        if (t.status === 'closed') return { label: 'Closed', tone: 'Closed', dot: 'status-dot-resolved', order: 2, stale };
        if (t.status === 'open' || t.status === 'planned') {
            const tone = t.status === 'open' ? 'Active' : 'Watching';
            if (t.first_seen === t.last_mentioned) return { label: 'New', tone, dot: 'status-dot-new', order: 0, stale };
            return t.status === 'open'
                ? { label: 'Active', tone, dot: 'status-dot-active', order: 1, stale }
                : { label: 'Watching', tone, dot: 'status-dot-watching', order: 0, stale };
        }
        return { label: t.status, tone: 'Watching', dot: 'status-dot-watching', order: 3, stale: false };
    }

    // 5-dot conviction strength row. Observation/indicator trades carry a text
    // label (observation_only/watchlist) instead of a numeric scale — the label is
    // the sole indicator marker now (the `role` field was removed, schema §6).
    function renderConvictionDotsHTML(conviction) {
        if (!conviction || conviction.scale == null) {
            if (!conviction || !conviction.label) return '';
            return `<span class="conviction-label-only">${conviction.label.replace('_', ' ')}</span>`;
        }
        const max = conviction.max_scale || 5;
        let dots = '';
        for (let i = 1; i <= max; i++) {
            dots += `<span class="conviction-dot${i <= conviction.scale ? ' filled' : ''}"></span>`;
        }
        return `<div class="conviction-dots">${dots}</div>`;
    }

    // Closed-trade P&L display (C.1). Prefers the deterministic risk-based
    // pnl_pct that Python attaches at close-time for defined-risk spreads
    // (DOCU -> +11.4%). Falls back to the raw $ credit/debit captured when risk
    // couldn't be derived — e.g. a spread opened before the first imported issue,
    // whose entry economics were never captured (GLD 425/450 -> -$2.70). The
    // old code only appended '%' when pnl.unit === 'pct', so $/share credits
    // rendered as a bare, ambiguous number; the $ fallback branch fixes that.
    function closedPnlDisplay(t) {
        const hist = t.status_history || [];
        const last = hist[hist.length - 1] || {};
        const pct = (t.pnl_pct != null) ? t.pnl_pct
                  : (last.pnl_pct != null) ? last.pnl_pct : null;
        if (pct != null) {
            return { text: `${pct >= 0 ? '+' : '-'}${Math.abs(pct)}%`, positive: pct >= 0 };
        }
        const pnl = last.pnl || null;
        if (!pnl || pnl.value == null) return { text: '--', positive: true };
        const v = pnl.value;
        const body = pnl.unit === 'pct' ? `${Math.abs(v)}%` : `$${Math.abs(v).toFixed(2)}`;
        return { text: `${v >= 0 ? '+' : '-'}${body}`, positive: v >= 0 };
    }

    // Composite PAIRS ratio from per-name CLOSING marks: Σ(long exit_price) / Σ(short
    // exit_price), computed STRAIGHT UP from raw prices (C.16). `weight` is beta-neutral
    // sizing, NOT a ratio input, so it's ignored here. Returns a rounded ratio, or null
    // unless every basket leg carries an exit_price (a %-only close has none -> falls to
    // '--' per C.15). e.g. (159.92+84.87+53.55)/86.96 = 3.43.
    function pairExitRatio(t) {
        const basket = t.basket;
        if (!Array.isArray(basket) || !basket.length) return null;
        let longs = 0, shorts = 0;
        for (const b of basket) {
            if (b.exit_price == null) return null;   // need ALL marks to form the ratio
            if (b.side === 'long') longs += b.exit_price;
            else if (b.side === 'short') shorts += b.exit_price;
        }
        if (!shorts) return null;
        return Math.round(longs / shorts * 100) / 100;
    }

    // Closing price for a closed trade, read from status_history OR tranches (C.8) —
    // one source so the exit displays consistently regardless of where it's stored.
    // For a PAIRS trade the exit "level" is the composite ratio computed from the
    // per-name closing marks (C.16), preferred when those marks are present.
    function closingExit(t) {
        const ratio = pairExitRatio(t);
        if (ratio != null) return ratio;
        if (t.exit_price != null) return t.exit_price;   // top-level (plumbing fix, mirrors closingEntry)
        for (const tr of (t.tranches || [])) {
            if (tr.status === 'closed' && tr.exit_price != null) return tr.exit_price;
        }
        const hist = t.status_history || [];
        for (let i = hist.length - 1; i >= 0; i--) {
            if (hist[i].exit_price != null) return hist[i].exit_price;
        }
        return null;
    }

    // Closing ENTRY for a closed round-trip: the fill cost (debit/credit) when
    // stated; else a tranche's entry_price; else the stated entry.level — the
    // planned/trigger level the position was taken at (fix, 2026-07-11). The
    // entry.level fallback mirrors activeEntryText() and matters for trades whose
    // "entry" IS a level rather than a separate fill cost — notably a PAIR, whose
    // entry ratio lives in entry.level (e.g. IWM/QQQ entry ratio 0.412 stated the
    // prior week) and never gets a distinct entry_price. Without it, a closed pair
    // shows Entry '--' even though the ratio is right there in the data. entry_price
    // still wins when present, so an options spread whose fill cost genuinely differs
    // from a trigger level is unaffected. Only truly entry-less closes (a
    // back-computed pre-window close with no stated level) still show --.
    function closingEntry(t) {
        if (t.entry_price != null) return t.entry_price;
        for (const tr of (t.tranches || [])) {
            if (tr.entry_price != null) return tr.entry_price;
        }
        if (t.entry && t.entry.level != null) return t.entry.level;
        return null;
    }

    // Target for display — NUMERIC only, never prose (user, 2026-07-09). A real price
    // level shows as-is. An expiration_worthless credit spread renders as 0 (max profit
    // = the spread going to zero — a number, not a label). A purely qualitative
    // "target" (e.g. SMH "continued outperformance") is NOT a target — it's guidance
    // that lives in status_history — so show no Tgt at all.
    function targetDisplay(t) {
        // The first genuine PROFIT target — never an options underlying-price guidance
        // level (basis:"underlying"), which would show a nonsensical price here (same
        // unit-mismatch as the stop). isProfitTarget keeps non-options targets as-is.
        const tgt = (t.targets || []).find(x => x && isProfitTarget(t, x)
            && (x.level != null || x.label === 'expiration_worthless'));
        if (!tgt) return null;
        if (tgt.level != null) return { text: fmtLevel(tgt), isLabel: false };
        if (tgt.label === 'expiration_worthless') return { text: '0', isLabel: false };
        return null;
    }

    // Entry/Tgt-Stop/P&L row, by status. DETAIL panel (levelsRowHTML): new/watching
    // -> Entry only; active -> Entry+Tgt+Stop (Entry LEADS, C.14); closed -> Entry+Exit+P&L
    // with '--' for any level the letter didn't state (C.15) — never derived, never
    // dropped (P&L still tracks). The compact STRIP version (levelsInlineHTML) stays
    // leaner: active -> Tgt+Stop, closed -> P&L (+ entry→exit only when both known).
    // P&L color branches by pnl sign (fixes the old hardcoded-green bug).
    // One metric as a label-above-value column (detail panel). Columns are laid out
    // side-by-side in a single row (below) so Tgt/Stop and P&L/Exit don't waste
    // vertical space stacking four lines deep.
    function metricCol(label, valueHTML) {
        return `<div class="flex flex-col items-center">
                    <p class="text-[10px] text-slate-500 uppercase tracking-widest">${label}</p>
                    <p class="text-sm">${valueHTML}</p>
                </div>`;
    }

    // The "entry" to show on an ACTIVE card: the actual fill cost (entry_price) when
    // known — an options credit/debit or an outright fill — else the trigger/limit level
    // (entry.level), else a tranche fill, else '--'. fmtLevel alone reads only entry.level,
    // which is NULL on a market-entered options spread whose cost lives in entry_price
    // (the GLD bear put spread showed a blank Entry for exactly this).
    function activeEntryText(t) {
        if (t.entry_price != null) return `${t.entry_price}`;
        if (t.entry && t.entry.level != null) return fmtLevel(t.entry);
        for (const tr of (t.tranches || [])) if (tr.entry_price != null) return `${tr.entry_price}`;
        return '--';
    }

    function levelsRowHTML(t, meta) {
        const cols = [];
        if (meta.tone === 'Closed') {
            // Closed round-trip at a glance: Entry -> Exit -> P&L (user 2026-07-10).
            // Entry/Exit slots are ALWAYS present; a level the letter never stated
            // renders '--' (C.15) — never derived, never dropped (P&L still tracks).
            const entry = closingEntry(t);
            cols.push(metricCol('Entry', `<span class="font-mono text-slate-300">${entry != null ? entry : '--'}</span>`));
            const exit = closingExit(t);
            cols.push(metricCol('Exit', `<span class="font-mono text-slate-300">${exit != null ? exit : '--'}</span>`));
            const { text, positive } = closedPnlDisplay(t);
            cols.push(metricCol('P&amp;L', `<span class="font-mono ${positive ? 'text-emerald-400' : 'text-red-400'}">${text}</span>`));
        } else if (meta.tone === 'Active') {
            // Entry LEADS on an active trade (user 2026-07-10, C.14): Entry -> Tgt -> Stop.
            // Prefer the fill cost (entry_price) over the trigger level so a market-entered
            // options spread shows its debit/credit, not a blank (C.14 fix, 2026-07-11).
            cols.push(metricCol('Entry', `<span class="font-mono text-slate-200">${activeEntryText(t)}</span>`));
            const td = targetDisplay(t);
            if (td) cols.push(metricCol('Tgt', `<span class="${td.isLabel ? 'text-emerald-300 italic' : 'font-mono text-emerald-400'}">${td.text}</span>`));
            // An options stop tagged basis:"underlying" (Python) is an underlying price,
            // a different unit than the premium Entry/Tgt — it reads as nonsensical here,
            // so it's shown in the Trigger/Invalidation detail instead (user, 2026-07-12).
            if (!(t.stop && t.stop.basis === 'underlying')) cols.push(metricCol('Stop', `<span class="font-mono text-red-400">${fmtLevel(t.stop)}</span>`));
        } else {
            cols.push(metricCol('Entry', `<span class="font-mono text-slate-200">${fmtLevel(t.entry)}</span>`));
        }
        return `<div class="flex items-start gap-4">${cols.join('')}</div>`;
    }

    // Strip-card mini version of the same row (single line, compact).
    function levelsInlineHTML(t, meta) {
        if (meta.tone === 'Closed') {
            const { text, positive } = closedPnlDisplay(t);
            const entry = closingEntry(t), exit = closingExit(t);
            const rt = (entry != null && exit != null)
                ? `<span class="font-mono text-slate-400">${entry}→${exit}</span><span class="text-slate-700">·</span>`
                : '';
            return `${rt}<span class="text-slate-500">P&amp;L</span><span class="${positive ? 'text-emerald-400' : 'text-red-400'}">${text}</span>`;
        }
        if (meta.tone === 'Active') {
            const td = targetDisplay(t);
            const tgt = td
                ? `<span class="text-slate-500">Tgt</span><span class="${td.isLabel ? 'text-emerald-300 italic' : 'text-emerald-400'}">${td.text}</span>`
                : '';
            // An options underlying-price stop (basis:"underlying") is omitted here — it
            // lives in the Trigger/Invalidation detail (user, 2026-07-12). Fall back to
            // Entry when there's no target so the line isn't empty.
            if (t.stop && t.stop.basis === 'underlying') {
                return tgt || `<span class="text-slate-500">Entry</span><span class="text-slate-300">${activeEntryText(t)}</span>`;
            }
            const stop = `<span class="text-slate-500">Stop</span><span class="text-red-400">${fmtLevel(t.stop)}</span>`;
            return tgt ? `${tgt}<span class="text-slate-700">·</span>${stop}` : stop;
        }
        return `<span class="text-slate-500">Entry</span><span class="text-slate-300">${fmtLevel(t.entry)}</span>`;
    }

    // §6: a trade is an observation-only INDICATOR (a market read, not a takeable
    // position) iff conviction.label is observation_only/watchlist — routed to the
    // digest dropdown, never the plays strip.
    function isIndicator(t) {
        const lbl = t && t.conviction && t.conviction.label;
        return lbl === 'observation_only' || lbl === 'watchlist';
    }

    // Renders the Newsletter Plays strip from NEWSLETTER_TRADES. Order:
    // New/Watching -> Active -> Closed (left to right), matching the
    // settled layout rule. `abandoned`/`deleted` trades never reach this —
    // they're excluded up front, same as silence should drop them live.
    // An OPEN trade with NO entry basis anywhere — no stated entry level and no fill
    // price on the trade or any tranche. Un-scoreable (no basis to compute a P&L at
    // close) and incomplete on the card, so its DATA text mutes (C.16). Applied
    // UNIFORMLY, INCLUDING pre_existing holds (the SMH core): a pre-window entry is
    // just as absent a basis as a narrated in-window re-entry, so both mute (user
    // 2026-07-10 — chose the uniform scoreability rule over a tracking-window carve-out).
    function lacksEntryBasis(t) {
        if (t.status !== 'open') return false;
        if (t.entry && t.entry.level != null) return false;
        if (t.entry_price != null) return false;
        for (const tr of (t.tranches || [])) if (tr.entry_price != null) return false;
        return true;
    }

    // Structure word for a BARE discard stub, which carries no basket/legs to read
    // structure off (only id/strategy_id/tickers/underlying). The one reliable signal
    // is the strategy_id shape: a pair's key is `{long}-vs-{short}` (§8a) — the sole
    // structure whose id contains `-vs-`; tickers.length>1 corroborates. A single-name
    // stub can't be told apart as outright vs options (no legs), so return '' and show
    // NO structure word rather than assert a wrong "Pair" (fixes a dropped outright like
    // USDJPY being mislabeled a Pair on the un-enrichable fallback path; user 2026-07-13).
    function unresolvedStubKind(t) {
        const isPair = /-vs-/.test(t.strategy_id || '') || (Array.isArray(t.tickers) && t.tickers.length > 1);
        return isPair ? 'Pair' : '';
    }

    // Compact card for an `unresolved` discard stub (tickers + reason only). Amber
    // to read as "attention / needs your judgment" — distinct from live violet/slate
    // and closed emerald. Surfaces the drop reason inline so continuity is immediate;
    // click opens the minimal detail panel (showNewsletterDive handles the stub shape).
    function renderUnresolvedCardHTML(t) {
        const title = (t.tickers && t.tickers.length) ? t.tickers.join(' / ') : (t.strategy_id || '--');
        const kind = unresolvedStubKind(t);
        const reason = t.reason || 'Dropped by silence this issue — see last week’s edition for the full setup.';
        return `
            <div class="glass-panel p-2.5 rounded-lg cursor-pointer hover:bg-slate-800 transition border-l-4 border-l-amber-500 shadow-lg flex flex-col gap-1 shrink-0" style="min-width:190px; max-width:220px;" onclick="showNewsletterDive('${t.id}')">
                <div class="flex justify-between items-center">
                    <span class="text-[9px] font-bold text-amber-400 uppercase tracking-widest flex items-center gap-1"><span class="w-1 h-1 rounded-full bg-amber-400"></span>Unresolved</span>
                </div>
                <div class="flex flex-col gap-1">
                    <span class="text-sm font-bold">${esc(title)}${kind ? `<span class="text-xs text-slate-400 font-normal ml-1">${kind}</span>` : ''}</span>
                    <p class="text-[10px] text-slate-400 leading-snug line-clamp-3">${esc(reason)}</p>
                </div>
            </div>`;
    }

    function renderNewsletterStrip() {
        const container = document.getElementById('newsletter-container');
        // A closed trade belongs to the issue it closed IN. Show a close only when its
        // close-issue (last_mentioned) matches the issue currently on the dashboard, so
        // a PRIOR week's closes don't linger here. They stay in the store (scoreboard)
        // and remain viewable by pulling up that week's edition — they're just not part
        // of THIS week's board. Open/planned trades always show.
        const issueDate = NEWSLETTER_ISSUE && NEWSLETTER_ISSUE.issue_date;
        const visible = NEWSLETTER_TRADES.filter(t => {
            if (t.status === 'abandoned' || t.status === 'deleted') return false;
            // Observation-only / watchlist INDICATORS are market reads, not positions —
            // they render in the digest dropdown (§6), not as plays-strip cards.
            if (isIndicator(t)) return false;
            // A pulled-up PAST edition is that week's frozen, self-scoped file — show
            // it as-is. Only the LIVE store board scopes closes to the current issue.
            if (t.status === 'closed' && !viewingPastStem) return t.last_mentioned === issueDate;
            return true;
        });
        visible.sort((a, b) => getStatusMeta(a).order - getStatusMeta(b).order);

        // Recorded before the empty-state early return below, so a collapsed bar
        // reports "0 plays" rather than silently keeping the last non-zero count.
        container.dataset.count = visible.length;
        syncNewsletterBar();

        if (!visible.length) {
            container.innerHTML = `<div class="flex items-center h-full text-slate-500 text-xs italic px-3">
                No newsletter plays yet — use the Import icon in the digest strip to bring in an issue.</div>`;
            return;
        }

        container.innerHTML = visible.map(t => {
            const meta = getStatusMeta(t);
            // An unresolved trade renders as its full last-week card (conviction + entry),
            // just amber — so it reads as continuity, not a placeholder. Fall back to the
            // compact stub card ONLY if it's a bare discard stub (no status_history — the
            // reliable full-object vs stub discriminator; a full OUTRIGHT has no basket/legs
            // either, so those can't be used to detect a stub).
            if (t.status === 'unresolved' && !Array.isArray(t.status_history)) return renderUnresolvedCardHTML(t);
            // Card COLOR/opacity follow the lifecycle TONE (decoupled from the badge), so a
            // New badge can sit on a violet Active card (user 2026-07-10). The badge text
            // color stays with the badge LABEL.
            const borderClass = meta.tone === 'Active' ? 'border-l-violet'
                : meta.tone === 'Closed' ? 'border-l-emerald-500'
                : meta.tone === 'Unresolved' ? 'border-l-amber-500' : 'border-l-slate-400';
            // A Closed card mutes wholesale (opacity on the whole card). An OPEN trade
            // with no entry basis KEEPS its Active identity — the violet border AND the
            // "Active" badge stay bright — but mutes its data (title + levels): the data
            // is incomplete, the position isn't (user 2026-07-10, C.16).
            const cardMute = meta.tone === 'Closed' ? 'opacity-60' : '';
            const dataMute = lacksEntryBasis(t) ? 'opacity-50' : '';
            const dotColorClass = meta.label === 'Active' ? 'text-violet-300'
                : meta.label === 'Closed' ? 'text-emerald-400'
                : meta.label === 'Unresolved' ? 'text-amber-400' : 'text-slate-400';
            return `
                <div class="glass-panel p-2.5 rounded-lg cursor-pointer hover:bg-slate-800 transition border-l-4 ${borderClass} shadow-lg flex flex-col gap-1 shrink-0 ${cardMute}" style="min-width:190px; max-width:220px;" onclick="showNewsletterDive('${t.id}')">
                    <div class="flex justify-between items-center">
                        <span class="text-[9px] font-bold ${dotColorClass} uppercase tracking-widest flex items-center gap-1"><span class="w-1 h-1 rounded-full ${meta.dot}"></span>${meta.label}${meta.stale ? '<span class="stale-badge ml-1">Stale</span>' : ''}</span>
                        ${renderConvictionDotsHTML(t.conviction)}
                    </div>
                    <div class="flex flex-col gap-1 ${dataMute}">
                        <div class="flex justify-between items-baseline">
                            <span class="text-sm ${meta.label === 'Closed' ? 'line-through decoration-slate-500' : ''}">${getCardIdentityHTML(t)}</span>
                        </div>
                        <div class="text-[10px] font-mono flex items-center gap-1.5">
                            ${levelsInlineHTML(t, meta)}
                        </div>
                    </div>
                </div>`;
        }).join('');
    }

    // --- Collapsible plays bar ------------------------------------------------
    // The detail panel underneath is flex-1, so every pixel this strip gives up goes
    // straight to it — which is the whole reason to collapse rather than hide: the
    // plays are still one click away, and the panel gets the 86px.
    // Same localStorage grammar as persistCollapse() uses for the sidebar sections
    // ('1' open / '0' closed), but written by hand because that helper drives a
    // <details> element's .open and this is a div.
    const NL_BAR_KEY = 'newsletterBarOpen';

    function syncNewsletterBar() {
        const strip = document.getElementById('newsletter-strip');
        const el = document.getElementById('newsletter-count');
        if (!strip || !el) return;
        // Before the first render there is no count yet, and a collapsed bar reading
        // "0 plays" during load would be a claim, not a blank. Say nothing until the
        // strip has actually counted.
        const raw = (document.getElementById('newsletter-container') || {}).dataset?.count;
        const n = raw === undefined ? null : +raw;
        el.textContent = n === null ? '' : n === 1 ? '1 play' : `${n} plays`;
        const open = !strip.classList.contains('collapsed');
        const btn = document.getElementById('newsletter-bar-toggle');
        if (btn) btn.setAttribute('aria-expanded', String(open));
    }

    function toggleNewsletterBar(force) {
        const strip = document.getElementById('newsletter-strip');
        if (!strip) return;
        const collapse = force === undefined ? !strip.classList.contains('collapsed') : !force;
        strip.classList.toggle('collapsed', collapse);
        localStorage.setItem(NL_BAR_KEY, collapse ? '0' : '1');
        syncNewsletterBar();
    }

    // Restore before first paint of the cards. Defaults to OPEN when unset, matching
    // every other collapsible section in the dashboard.
    (function initNewsletterBar() {
        const strip = document.getElementById('newsletter-strip');
        if (!strip) return;
        if (localStorage.getItem(NL_BAR_KEY) === '0') strip.classList.add('collapsed');
        syncNewsletterBar();
    })();

    // Per-view state: which entity is active, and the chart instance (so we
    // don't recreate it on every tab click — only when the entity changes).
