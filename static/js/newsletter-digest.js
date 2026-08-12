// newsletter-digest.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    let digestOpen = false;
    function toggleDigest() {
        digestOpen = !digestOpen;
        const strip = document.getElementById('digest-strip');
        const caret = document.getElementById('digest-caret');
        // Height is auto-calculated — use scrollHeight so playbooks/analysis
        // sections don't get clipped by a fixed 120px cap.
        strip.style.maxHeight = digestOpen ? strip.scrollHeight + 'px' : '0';
        caret.style.transform = digestOpen ? 'rotate(90deg)' : 'rotate(0deg)';
    }

    // Minimal HTML escaper for untrusted strings (filenames, issue titles)
    // interpolated into innerHTML templates below.
    function digestControlsHTML() {
        return `
            <button onclick="event.stopPropagation(); openImportPicker(this);"
                    class="shrink-0 flex items-center justify-center w-5 h-5 rounded hover:bg-violet-500/20 text-violet-300 hover:text-violet-200 transition-colors"
                    title="Import newsletter">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>
                </svg>
            </button>
            <button onclick="event.stopPropagation(); openPastEditions(this);"
                    class="shrink-0 flex items-center justify-center w-5 h-5 rounded hover:bg-violet-500/20 text-violet-300 hover:text-violet-200 transition-colors"
                    title="Past editions">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>
                </svg>
            </button>`;
    }

    // --- Digest strip: renders an issue envelope (date, themes, trade-count
    // pills in the header; title + analysis_features + playbooks in the expanded
    // body). renderDigestStrip() shows the CURRENT issue (NEWSLETTER_ISSUE) with
    // live pills; viewPastEdition() reuses _renderDigest() in read-only mode for a
    // past extract, WITHOUT touching the Newsletter Plays panel.
    function renderDigestStrip() {
        _renderDigest(NEWSLETTER_ISSUE, NEWSLETTER_TRADES, false);
    }

    function _renderDigest(iss, trades, readOnly) {
        trades = trades || [];

        // Count pills — an ISSUE-ACTIVITY summary (user 2026-07-10), NOT the raw store:
        // excludes indicators, and scopes to THIS issue so a prior week's closes don't
        // inflate the count. "new" = introduced this issue (first_seen === issue_date,
        // entered or not); "closed" = closed THIS issue; active/watching = carried-forward
        // open/planned. On the live view these sit in the header; in read-only past-edition
        // mode they move to the dropdown body (the header shows the read-only badge).
        const iid = iss && iss.issue_date;
        const summ = (trades || []).filter(t => !isIndicator(t) && t.status !== 'abandoned' && t.status !== 'deleted');
        // Counts match the strip's badges: "new" = New-badge set (first appearance, not
        // closed); watching/active = carried-forward planned/open; "closed" scoped to THIS
        // issue (last_mentioned === issue_date) so a prior week's closes don't inflate it.
        const newCount = summ.filter(t => t.status !== 'closed' && t.first_seen === t.last_mentioned).length;
        const watchCount = summ.filter(t => t.status === 'planned' && t.first_seen !== t.last_mentioned).length;
        const activeCount = summ.filter(t => t.status === 'open' && t.first_seen !== t.last_mentioned).length;
        const closedCount = summ.filter(t => t.status === 'closed' && t.last_mentioned === iid).length;
        const pills = [];
        if (newCount) pills.push(`<span class="text-[10px] font-mono text-violet-300 bg-violet-500/10 border border-violet-500/30 rounded-full px-2 py-0.5">${newCount} new</span>`);
        if (watchCount) pills.push(`<span class="text-[10px] font-mono text-slate-300 bg-slate-500/10 border border-slate-500/30 rounded-full px-2 py-0.5">${watchCount} watching</span>`);
        if (activeCount) pills.push(`<span class="text-[10px] font-mono text-sky-300 bg-sky-500/10 border border-sky-500/30 rounded-full px-2 py-0.5">${activeCount} active</span>`);
        if (closedCount) pills.push(`<span class="text-[10px] font-mono text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-full px-2 py-0.5">${closedCount} closed</span>`);

        const dateLabel = iss && iss.issue_date ? esc(iss.issue_date) : '—';
        // Header shows the issue TITLE (a clean headline); the themes (the longer,
        // narrative-ish string) moved to the expanded dropdown body instead
        // (user 2026-07-09 — swapped from the reverse).
        const titleLabel = iss
            ? esc(iss.title || '')
            : 'No issues imported yet — click the import icon to bring one in';
        // Re-rendering the header recreates the caret, so re-apply its open/closed
        // rotation inline rather than losing it.
        const caretRot = digestOpen ? 'rotate(90deg)' : 'rotate(0deg)';

        document.getElementById('digest-header').innerHTML = `
            <div class="flex items-center gap-2 min-w-0">
                <span class="w-2 h-2 rounded-full bg-violet-400 shrink-0"></span>
                ${digestControlsHTML()}
                <span class="text-xs font-bold text-violet-300 uppercase tracking-wider shrink-0">Newsletter · ${dateLabel}</span>
                <span class="text-xs text-slate-200 font-semibold truncate">${titleLabel}</span>
                ${readOnly ? `<button onclick="event.stopPropagation(); returnToCurrentIssue();" class="shrink-0 text-[10px] font-mono text-violet-300 hover:text-violet-100 underline decoration-dotted">← current</button>` : ''}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                ${readOnly
                    ? `<span class="text-[10px] font-mono text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-full px-2 py-0.5">Past edition · read-only</span>`
                    : pills.join('')}
                <span id="digest-caret" class="text-slate-500 text-xs transition-transform" style="transform: ${caretRot}">▶</span>
            </div>`;

        // In read-only past-edition mode the count pills live here in the body (the
        // header shows the "read-only" badge in their place).
        const bodyPills = (readOnly && pills.length)
            ? `<div class="flex flex-wrap items-center gap-2 mb-2">${pills.join('')}</div>`
            : '';
        document.getElementById('digest-body').innerHTML = iss ? (bodyPills + _digestBodyHTML(iss, trades))
            : `<div class="text-slate-500 italic text-xs">Import a newsletter issue to populate the digest.</div>`;

        // Keep the expanded height correct when re-rendering while open.
        if (digestOpen) {
            const strip = document.getElementById('digest-strip');
            strip.style.maxHeight = strip.scrollHeight + 'px';
        }
    }

    // Body: 1) themes (the narrative-ish string, moved here from the header —
    // user 2026-07-09), 2) analysis_features, 3) playbooks (each if present).
    function _digestBodyHTML(iss, trades) {
        let body = iss.themes && iss.themes.length
            ? `<div class="flex flex-col gap-0.5">${iss.themes.map(th =>
                  `<div class="text-slate-300 text-xs flex items-baseline gap-1.5"><span class="text-violet-400/70">·</span>${esc(th)}</div>`
              ).join('')}</div>`
            : '';

        if (iss.analysis_features && iss.analysis_features.length) {
            body += `<div>
                <p class="text-[10px] font-bold text-indigo-300 uppercase tracking-widest mb-1">Analysis</p>
                ${iss.analysis_features.map(af => {
                    let detail = '';
                    if (af.type === 'sector_model' && (af.top_ranked || af.bottom_ranked)) {
                        const top = af.top_ranked ? `<span class="text-emerald-400">▲ ${esc(af.top_ranked.join(', '))}</span>` : '';
                        const bot = af.bottom_ranked ? `<span class="text-red-400">▼ ${esc(af.bottom_ranked.join(', '))}</span>` : '';
                        detail = `<div class="flex gap-3 mt-1 text-[10px] font-mono">${top}${bot}</div>`;
                    }
                    const themeTag = af.linked_theme ? `<span class="text-[10px] font-mono text-violet-400 ml-2">→ ${esc(af.linked_theme)}</span>` : '';
                    return `<div class="bg-slate-800/50 rounded px-3 py-2 border border-slate-700 mb-1">
                        <p class="text-slate-200 text-xs font-medium">${esc(af.title || '')}${themeTag}</p>
                        <p class="text-slate-400 text-[11px] mt-0.5">${esc(af.summary || '')}</p>
                        ${detail}
                    </div>`;
                }).join('')}
            </div>`;
        }

        if (iss.playbooks && iss.playbooks.length) {
            body += `<div>
                <p class="text-[10px] font-bold text-amber-400 uppercase tracking-widest mb-1">Playbooks</p>
                ${iss.playbooks.map(pb => {
                    const cands = pb.candidates || [];
                    const triggered = cands.filter(c => c.status === 'triggered').length;
                    const pending = cands.filter(c => c.status === 'pending').length;
                    return `<div class="bg-slate-800/50 rounded px-3 py-2 border border-slate-700 mb-1">
                        <p class="text-slate-200 text-xs font-medium">${esc(pb.trigger_rule || '')}</p>
                        <div class="flex gap-3 mt-1 text-[10px] font-mono text-slate-400">
                            <span>${cands.length} candidates</span>
                            ${triggered ? `<span class="text-amber-300">${triggered} triggered</span>` : ''}
                            ${pending ? `<span class="text-slate-500">${pending} pending</span>` : ''}
                            <span>Size: ${esc(pb.sizing_per_trigger)} per trigger · Hold: ${esc(pb.hold_sessions)} sessions</span>
                        </div>
                        <div class="flex flex-wrap gap-2 mt-1">
                            ${cands.map(c => {
                                const color = c.status === 'triggered' ? 'text-amber-300' : c.status === 'expired' ? 'text-slate-600 line-through' : 'text-slate-400';
                                return `<span class="text-[10px] font-mono ${color}">${esc(c.entity)} (${esc(c.index)})</span>`;
                            }).join('')}
                        </div>
                    </div>`;
                }).join('')}
            </div>`;
        }
        // §6: observation-only / watchlist INDICATORS render here (a market READ, not a
        // takeable position) — never as plays-strip cards. Title + proxy + thesis +
        // long/short constituents.
        const indicators = (trades || []).filter(isIndicator);
        if (indicators.length) {
            body += `<div>
                <p class="text-[10px] font-bold text-cyan-300 uppercase tracking-widest mb-1">Indicators</p>
                ${indicators.map(ind => {
                    const name = esc(ind.campaign_title || ind.linked_theme || 'Observation basket');
                    const lbl = esc(((ind.conviction && ind.conviction.label) || '').replace(/_/g, ' '));
                    const proxy = ind.indicates ? `<p class="text-slate-400 text-[11px] mt-0.5">Proxy for: ${esc(ind.indicates)}</p>` : '';
                    const rationale = (ind.thesis && ind.thesis.rationale) ? `<p class="text-slate-500 text-[11px] mt-0.5">${esc(ind.thesis.rationale)}</p>` : '';
                    const bk = ind.basket || [];
                    const longs = bk.filter(b => b.side === 'long').map(b => esc(b.ticker));
                    const shorts = bk.filter(b => b.side === 'short').map(b => esc(b.ticker));
                    const constituents = bk.length ? `<div class="flex flex-wrap gap-3 mt-1 text-[10px] font-mono">${longs.length ? `<span class="text-emerald-400">▲ ${longs.join(' ')}</span>` : ''}${shorts.length ? `<span class="text-red-400">▼ ${shorts.join(' ')}</span>` : ''}</div>` : '';
                    // Clickable (user, 2026-07-11): opens the indicator in the detail
                    // panel. Indicators are excluded from the plays STRIP (they're a
                    // market read, not a takeable position), so the digest card is the
                    // only way to re-open one after clicking away — showNewsletterDive
                    // looks up NEWSLETTER_TRADES, which still contains indicators.
                    return `<div class="bg-slate-800/50 hover:bg-slate-700/60 rounded px-3 py-2 border border-slate-700 mb-1 cursor-pointer transition-colors" onclick="event.stopPropagation(); showNewsletterDive('${ind.id}')" title="View this indicator's detail">
                        <p class="text-slate-200 text-xs font-medium">${name}<span class="text-[10px] font-mono text-cyan-400 ml-2">${lbl}</span></p>
                        ${proxy}${rationale}${constituents}
                    </div>`;
                }).join('')}
            </div>`;
        }
        return body;
    }

    // Leave read-only past-edition mode, restore the current issue.
    function returnToCurrentIssue() {
        viewingPastStem = null;
        // Reload the live store — restores NEWSLETTER_TRADES/ISSUE and re-renders the
        // plays strip, digest, and deep-dive back to the current board.
        loadNewsletterState();
    }

    // --- Anchored dropdown used by both the Import picker and Past Editions.
    // Positioned fixed under the clicked button so the right column's
    // overflow-hidden can't clip it. Only one open at a time.
    let openDropdownEl = null;
    function closeNewsletterDropdown() {
        if (openDropdownEl) {
            openDropdownEl.remove();
            openDropdownEl = null;
            document.removeEventListener('click', _onDocClickForDropdown, true);
        }
    }
    function _onDocClickForDropdown(e) {
        if (openDropdownEl && !openDropdownEl.contains(e.target)) closeNewsletterDropdown();
    }
    function anchorDropdown(btn) {
        closeNewsletterDropdown();
        const panel = document.createElement('div');
        panel.className = 'newsletter-dropdown';
        const r = btn.getBoundingClientRect();
        panel.style.top = (r.bottom + 4) + 'px';
        panel.style.left = r.left + 'px';
        document.body.appendChild(panel);
        openDropdownEl = panel;
        // Defer wiring the outside-click close so this same click doesn't trip it.
        setTimeout(() => document.addEventListener('click', _onDocClickForDropdown, true), 0);
        return panel;
    }

    // --- Import picker: lists pending PDFs (imported ones grayed, not hidden),
    // selecting one POSTs /import_newsletter (a billed ~2-3 min low-effort extraction) then
    // refreshes the plays panel + digest from the store.
    async function openImportPicker(btn) {
        const panel = anchorDropdown(btn);
        panel.innerHTML = `<div class="nl-dd-title">Import newsletter</div><div class="nl-dd-msg">Loading…</div>`;
        let data;
        try {
            data = await fetch(`${API_BASE}/list_pending_newsletters`).then(r => r.json());
        } catch (e) {
            panel.innerHTML = `<div class="nl-dd-title">Import newsletter</div><div class="nl-dd-msg">Engine unreachable on :5001.</div>`;
            return;
        }
        if (data.error) {
            panel.innerHTML = `<div class="nl-dd-title">Import newsletter</div><div class="nl-dd-msg">${esc(data.error)}</div>`;
            return;
        }
        const files = data.files || [];
        if (!files.length) {
            panel.innerHTML = `<div class="nl-dd-title">Import newsletter</div><div class="nl-dd-msg">No newsletter PDFs found in NEWSLETTER_PDF_DIR.</div>`;
            return;
        }
        // Display newest-first (most current issue on top — user pref, 2026-07-12).
        // The backend returns oldest-first; reverse for display only.
        files.sort((a, b) => (b.issue_date || b.filename).localeCompare(a.issue_date || a.filename));
        // Ordering safeguard: the merge is order-dependent (each issue reconciles
        // against the prior live set), so a multi-issue catch-up MUST import
        // oldest->newest. With newest-first display, that's bottom-up — warn when
        // 2+ are still pending so the reversed order doesn't cause a backward import.
        const pendingCount = files.filter(f => !f.imported && !f.before_start).length;
        const orderHint = pendingCount >= 2
            ? `<div class="nl-dd-msg" style="color:#fbbf24;font-size:11px;">${pendingCount} pending — import <b>oldest first</b> (lowest active row up).</div>`
            : '';
        panel.innerHTML = `<div class="nl-dd-title">Import newsletter</div>` + orderHint + files.map(f => {
            const label = esc(f.issue_date || f.filename);
            if (f.imported) {
                return `<div class="nl-dd-item nl-dd-done" title="Already imported — delete its extract to re-import">${label}<span class="nl-dd-tag">imported</span></div>`;
            }
            if (f.before_start) {
                return `<div class="nl-dd-item nl-dd-done" title="Before your import start date (NEWSLETTER_START_DATE) — not imported">${label}<span class="nl-dd-tag">before start</span></div>`;
            }
            return `<div class="nl-dd-item" data-fn="${encodeURIComponent(f.filename)}">${label}<span class="nl-dd-sub">${esc(f.filename)}</span></div>`;
        }).join('');
        panel.querySelectorAll('.nl-dd-item:not(.nl-dd-done)').forEach(el => {
            el.addEventListener('click', () => importNewsletter(decodeURIComponent(el.dataset.fn), el));
        });
    }

    async function importNewsletter(filename, el) {
        el.classList.add('nl-dd-busy');
        el.innerHTML = `<span class="nl-dd-spin"></span>Importing… (~2–3 min, one API call)`;
        let res;
        try {
            res = await fetch(`${API_BASE}/import_newsletter`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            }).then(r => r.json());
        } catch (e) {
            el.classList.remove('nl-dd-busy');
            el.innerHTML = `Import failed (network). Click Import again to retry.`;
            return;
        }
        if (res.status === 'ok' || res.status === 'already_imported') {
            closeNewsletterDropdown();
            await loadNewsletterState();
        } else if (res.status === 'before_start') {
            el.classList.remove('nl-dd-busy');
            el.innerHTML = `Before your import start date — not imported.`;
        } else {
            el.classList.remove('nl-dd-busy');
            el.innerHTML = `Import failed. Click Import again to retry.`;
        }
    }

    // --- Past Editions: lists already-extracted issues (newest first); selecting
    // one renders that issue's envelope read-only into the digest area. Uses the
    // editions list already fetched into newsletterEditions by loadNewsletterState().
    function openPastEditions(btn) {
        const panel = anchorDropdown(btn);
        if (!newsletterEditions.length) {
            panel.innerHTML = `<div class="nl-dd-title">Past editions</div><div class="nl-dd-msg">No imported issues yet.</div>`;
            return;
        }
        panel.innerHTML = `<div class="nl-dd-title">Past editions</div>` + newsletterEditions.map(e =>
            `<div class="nl-dd-item" data-stem="${encodeURIComponent(e.stem)}">${esc(e.issue_date || e.stem)}${e.title ? `<span class="nl-dd-sub">${esc(e.title)}</span>` : ''}</div>`
        ).join('');
        panel.querySelectorAll('.nl-dd-item').forEach(el => {
            el.addEventListener('click', () => viewPastEdition(decodeURIComponent(el.dataset.stem)));
        });
    }

    async function viewPastEdition(stem) {
        closeNewsletterDropdown();
        let data;
        try {
            data = await fetch(`${API_BASE}/get_extracted_newsletter?stem=${encodeURIComponent(stem)}`).then(r => r.json());
        } catch (e) { return; }
        if (!data || data.error) return;
        viewingPastStem = stem;
        // Pull up the FROZEN weekly snapshot: the plays strip, digest, and deep-dive
        // all render from that week's file (self-scoped, immutable) instead of the live
        // store. returnToCurrentIssue() reloads the store to restore the live board.
        NEWSLETTER_TRADES = data.trade_updates || [];
        NEWSLETTER_ISSUE = data;
        _renderDigest(data, NEWSLETTER_TRADES, true);
        renderNewsletterStrip();
        const firstPast = NEWSLETTER_TRADES
            .filter(t => t.status !== 'abandoned' && t.status !== 'deleted')
            .sort((a, b) => getStatusMeta(a).order - getStatusMeta(b).order)[0];
        if (firstPast) showNewsletterDive(firstPast.id);
        if (!digestOpen) {
            toggleDigest();
        } else {
            const strip = document.getElementById('digest-strip');
            strip.style.maxHeight = strip.scrollHeight + 'px';
        }
    }

    // --- Load current store state (live + closed archive), the latest issue
    // envelope, and the Past Editions list, then render. Called on page load and
    // after every successful import so the UI reflects the store on disk.
    let viewingPastStem = null;
    async function loadNewsletterState() {
        try {
            const data = await fetch(`${API_BASE}/get_newsletter_state`).then(r => r.json());
            // `unresolved` = discard stubs dropped THIS issue (dropped_on === issue_date),
            // surfaced for their transition week so a freshly-dropped trade doesn't vanish
            // without a trace (user 2026-07-13). Display-only; they still live in `discarded`.
            NEWSLETTER_TRADES = [...(data.live || []), ...(data.archive || []), ...(data.unresolved || [])];
            NEWSLETTER_ISSUE = data.issue || null;
            newsletterEditions = data.editions || [];
        } catch (e) {
            NEWSLETTER_TRADES = [];
            NEWSLETTER_ISSUE = null;
            newsletterEditions = [];
        }
        renderDigestStrip();
        renderNewsletterStrip();
        // Default the thesis deep-dive to the first visible trade, if any.
        const first = NEWSLETTER_TRADES
            .filter(t => t.status !== 'abandoned' && t.status !== 'deleted')
            .sort((a, b) => getStatusMeta(a).order - getStatusMeta(b).order)[0];
        if (first) showNewsletterDive(first.id);
    }