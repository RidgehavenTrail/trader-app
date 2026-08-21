// stoplight.js — AI Bubble Stoplight sidebar section (classic script, global scope).
// Do not add import/export. Renders GET /get_stoplight into #stoplight-section.
// Visual contract: AI Stoplight/stoplight_mockup.html + STOPLIGHT_DESIGN.md.
// All display flags (is_new / flipped_today / stale_days / header pin) are
// computed SERVER-side by the stoplight blueprint — this file is a dumb renderer.

    const SL_POLL_MS = 300000;   // 5 min — the board changes at most hourly (copper)
    const SL_DOT_CLS = { green: 'sl-g', yellow: 'sl-y', orange: 'sl-o', red: 'sl-r' };
    let _slPrevDrums = null;     // last odometer digit string, for the roll animation
    let _slBoard = null;         // last board payload — the detail panel renders from it
    let _abFactor = null;        // reserved: factor id when opened via a future factor click

    function slDotHTML(f) {
        const cls = (f.built && f.light) ? (SL_DOT_CLS[f.light] || 'sl-x') : 'sl-x';
        return `<span class="sl-dot ${cls}"></span>`;
    }

    // Glyph gutter, LEFT of the dot (design doc): arrows are stoplight-POSITION
    // (down = toward burst); +/- is the corroborator agrees/contradicts glyph.
    function slGlyph(f) {
        const a = f.extras && f.extras.arrow;
        return { down: '↓', up: '↑', plus: '+', minus: '−' }[a] || '';
    }

    function slWeekday(iso) {
        try { return new Date(iso).toLocaleDateString('en-US', { weekday: 'short' }); }
        catch (e) { return ''; }
    }

    function renderStoplightHeader(board) {
        const hdr = document.getElementById('stoplight-hdr');
        const all = board.factors.concat(board.module ? [board.module] : []);
        const h = all.find(f => f.id === board.header_id);
        if (!h || !h.updated_at) { hdr.innerHTML = ''; return; }
        hdr.innerHTML =
            slDotHTML(h) +
            `<span class="sl-hdr-nm">${esc(h.name)}</span>` +
            `<span class="sl-hdr-val">${esc(h.metric || '')}</span>` +
            `<span class="sl-hdr-when">${slWeekday(h.updated_at)}</span>`;
    }

    function renderStoplightRows(board) {
        document.getElementById('stoplight-rows').innerHTML = board.factors.map(f => {
            const cls = ['sl-row'];
            if (f.is_new) cls.push('sl-row-new');
            if (f.flipped_today) cls.push('sl-row-flip');
            const stale = f.stale_days > 0
                ? `<span class="sl-badge-stale">${f.stale_days}d</span>` : '';
            // Live-but-flagged-for-refinement marker (e.g. infra_backlog): a small
            // wrench badge; hover explains it's on the board but being reworked.
            const refine = f.refine
                ? '<span class="sl-badge-refine" title="Live, flagged for refinement">⚒</span>' : '';
            const metric = f.built ? esc(f.metric || '--') : '—';
            // Right rail: 'D' for a daily poller, else the next-catalyst date
            // (e.g. 7/22). Title spells it out on hover.
            const catTip = f.cat === 'D' ? 'Updated daily'
                : (f.cat ? 'Next update ' + esc(f.cat) : '');
            const cat = f.cat
                ? `<span class="sl-cat" title="${catTip}">${esc(f.cat)}</span>` : '';
            const err = f.built && f.error ? ' title="' + esc(f.error) + '"' : '';
            // CLICK OPENS THE FACTOR'S OWN DETAIL (2026-08-21). Only a BUILT factor
            // is clickable: an unbuilt one has no light, no metric and no evidence,
            // so an affordance there would promise a panel with nothing in it.
            // openBubbleDetail already took a factorId — it was reserved for this.
            let click = '', a11y = '';
            if (f.built) {
                cls.push('sl-click');
                click = ` onclick="openBubbleDetail('${esc(f.id)}')"`;
                a11y = ` role="button" tabindex="0" title="${esc(f.name)} — detail"` +
                       ` onkeydown="if(event.key===&quot;Enter&quot;||event.key===&quot; &quot;)` +
                       `{event.preventDefault();openBubbleDetail(&quot;${esc(f.id)}&quot;)}"`;
            }
            return `<div class="${cls.join(' ')}"${err}${click}${a11y}>` +
                `<span class="sl-rk">${f.rank}</span>` +
                `<span class="sl-gl">${slGlyph(f)}</span>` +
                slDotHTML(f) +
                `<span class="sl-nm${f.built ? '' : ' sl-dim'}">${esc(f.name)}</span>` +
                `<span class="sl-mt">${metric}</span>${cat}${refine}${stale}</div>`;
        }).join('');
    }

    // Silicon E odometer: white drums + lime nameplate; the 63-bar % pinned to the
    // corner (or n/63 while the snapshot log warms up). Drums roll on a change.
    function renderSiliconE(m) {
        const el = document.getElementById('stoplight-module');
        if (!m || !m.built || m.value == null) { el.style.display = 'none'; return; }
        el.style.display = '';
        const digits = String(Math.round(m.value));
        const roll = _slPrevDrums !== null && _slPrevDrums !== digits;
        _slPrevDrums = digits;
        const drums = digits.split('').map(d => `<span class="sl-drum">${d}</span>`).join('');
        const ex = m.extras || {};
        let corner = '';
        if (ex.roll_63bar_pct != null) {
            const p = ex.roll_63bar_pct;
            corner = `<span class="sl-corner" style="color:${p >= 0 ? '#84cc16' : '#f87171'}">` +
                     `${p >= 0 ? '+' : ''}${p}%</span>`;
        } else if (ex.warming_up) {
            corner = `<span class="sl-corner" style="color:#64748b">${ex.bars_collected || 0}/63</span>`;
        }
        el.innerHTML = corner +
            `<div class="sl-odo"><div class="sl-drums${roll ? ' sl-roll' : ''}">` +
            `<span class="sl-unit">$</span>${drums}<span class="sl-unit-b">B</span></div>` +
            `<span class="sl-plate">Silicon E</span></div>`;
    }

    async function fetchStoplight() {
        try {
            const res = await fetch(`${API_BASE}/get_stoplight`);
            const board = await res.json();
            _slBoard = board;
            renderStoplightHeader(board);
            renderStoplightRows(board);
            renderSiliconE(board.module);
            if (!document.getElementById('ai-bubble-dive').classList.contains('hidden'))
                renderBubbleOverview();     // keep an open detail panel live
        } catch (err) {
            console.error('Error fetching stoplight board:', err);
        }
    }

    // --- AI Bubble detail panel (modal) --------------------------------------
    // Opened by the section's "detail" button; factorId is accepted now and stored
    // for a FUTURE factor-row click that deep-links into this same panel (v1 always
    // shows the Overview regardless). Tabs mirror the deep-dive pattern (view "ab").
    const AB_THESIS_HTML =
        '<p>The board reads the AI-bubble <strong>reality</strong>, inverted: ' +
        '🟢 = pro-burst, 🔴 = bubble-supportive. It is a reality-check, ' +
        'not narrative confirmation — a light can only be moved by a measured input.</p>' +
        '<p><strong>Core thesis:</strong> demand is durable; an AI bubble unwinds through ' +
        '<strong>price and margin</strong>, not a demand cliff. Under commoditization the prime ' +
        'target is <strong>NVIDIA</strong> (the fattest margin to lose), not the insulated name — ' +
        'substitution flees it both ways (custom silicon and cheap merchant GPU).</p>' +
        '<p><strong>Two-layer read:</strong> pricing power leads (premium share + GPU/token prices ' +
        'show commoditization first), then the composite forward net income of the 5 AI-semis ' +
        '<strong>confirms</strong> — its arrow turning down is the coincident bail signal.</p>';

    // Show the AI-bubble dive in the SHARED deep-dive panel (hide the ticker /
    // newsletter / empty siblings, like updateContext / showNewsletterDive do). It
    // stays until another entity is selected — no close button, matching dd/nd.
    function openBubbleDetail(factorId) {
        _abFactor = factorId || null;
        showOnlyPanel('ai-bubble-dive');    // shared list in core.js — see DETAIL_PANELS
        renderBubbleHead();                 // title header: identity line only
        renderBubbleSubhead();              // band below it: the factor's About box
        switchBubbleTab('overview');
        renderBubbleOverview();
    }

    // WHAT A FACTOR MEASURES, AND WHY IT MATTERS. Rendered as a small box above the
    // calendar, NOT in the header — as header prose it crowded the identity line
    // (user, 2026-08-21). Split into two short fields so the box can label them.
    // Hand-written here for now, DELIBERATELY: the same text also lives in each
    // factor's module docstring, and the right home is a structured `definition`
    // block on the factor itself (with the light thresholds, which live only in
    // docstring prose today). Until that exists this map is the honest shortcut —
    // an id absent from it renders NO box rather than a wrong one.
    const AB_WHY = {
        premium_share: {
            measures: 'Premium models’ revenue ÷ total revenue on OpenRouter.',
            why: 'The commoditization kill-mechanism gauge — if quality stops commanding a ' +
                 'price premium, the capex case for frontier models goes with it.'
        }
    };

    // The note box, painted into the SUB-HEADER band (#ab-subhead) between the title
    // header and the tabs. Three placements were tried before this one and each was
    // wrong for a specific reason worth not repeating: the scrolling pane (could
    // never sit closer than the tab strip's height to the rule, and lifting it past
    // the pane's edge CLIPPED it), the tabs row (outside the pane and unclippable,
    // but not the header meant), and the title header itself (correct band, but it
    // put a ~100px box in the identity row and pushed the header to 114px).
    // Its own band keeps the title header one line and leaves room for the legend
    // strip to join it later. Empties on the board view, and #ab-subhead:not(:empty)
    // means the band takes no height at all then.
    function renderBubbleSubhead() {
        const el = document.getElementById('ab-subhead');
        if (!el) return;
        const f = _abFactor && _slBoard
            ? (_slBoard.factors || []).find(x => x.id === _abFactor) : null;
        const w = f && AB_WHY[f.id];
        el.innerHTML = !w ? '' :
            '<div class="abh-note"><div class="ab-box ab-about">' +
            `<div class="ab-ab-r"><span class="ab-ab-k">Measures</span>${esc(w.measures)}</div>` +
            `<div class="ab-ab-r"><span class="ab-ab-k">Why</span>${esc(w.why)}</div>` +
            '<div class="ab-ab-p">Green = pro-burst on this board, not “all clear.”</div>' +
            '</div></div>';
    }
    const AB_LC = { green: 'g', yellow: 'y', orange: 'o', red: 'r' };

    // The panel header. No factor selected -> the board header, unchanged from what
    // the panel has always shown. A factor selected -> its compact identity line.
    function renderBubbleHead() {
        const el = document.getElementById('ab-head');
        if (!el) return;
        const f = _abFactor && _slBoard
            ? (_slBoard.factors || []).find(x => x.id === _abFactor) : null;
        if (!f) {
            el.innerHTML =
                '<div class="flex items-baseline gap-3">' +
                '<span class="text-[10px] font-bold text-indigo-300 uppercase tracking-widest ' +
                'bg-indigo-500/10 border border-indigo-500/30 rounded-full px-2 py-0.5">AI Bubble</span>' +
                '<h2 class="text-2xl font-bold text-white tracking-tight">Tracker</h2></div>';
            return;
        }
        const c = AB_LC[f.light] || 'y';
        // The glyph is the row's own — slGlyph already normalizes up/down/plus/minus,
        // so the header cannot disagree with the sidebar about which way it points.
        const gl = slGlyph(f);
        // IDENTITY ONLY — what it measures and why now lives in the About box above
        // the sub-header band below it (renderBubbleSubhead); this stays one line.
        // Three children only — identity line, note box, back button — so the row can
        // align them to the TOP. Left flat, the box's height would drag the line and
        // the button to its midpoint.
        return void (el.innerHTML =
            '<div class="abh">' +
              '<div class="abh-id">' +
                `<span class="abh-rank">#${f.rank}</span>` +
                `<span class="abh-name">${esc(f.name)}</span>` +
                `<span class="abh-dot abh-bg-${c}"></span>` +
                `<span class="abh-val abh-${c}">${esc(f.metric || '--')}</span>` +
                `<span class="abh-st">${esc((f.state || '').replace(/_/g, ' '))}</span>` +
                (gl ? `<span class="abh-gl">${gl}</span>` : '') +
              '</div>' +
              '<button class="abh-back" onclick="openBubbleDetail(null)">← Tracker</button>' +
            '</div>');
    }
    function switchBubbleTab(tabName) {
        document.getElementById('ab-tabs').querySelectorAll('.view-tab')
            .forEach(b => b.classList.toggle('active', b.dataset.view === tabName));
        ['overview', 'tbd1', 'charts'].forEach(n => {
            const p = document.getElementById('ab-pane-' + n);
            if (p) p.classList.toggle('hidden', n !== tabName);
        });
        // Charts must be built with the pane VISIBLE — lightweight-charts sizes to
        // the container, and a hidden pane measures 0. So render on activation.
        if (tabName === 'charts') renderBubbleCharts();
    }

    function abEventLabel(id) {
        const parts = id.split('_');
        return parts.length > 1 ? parts[0].toUpperCase() + ' ' + parts.slice(1).join(' ')
                                : parts[0].toUpperCase();
    }
    function abMD(iso) { const p = iso.split('-'); return (+p[1]) + '/' + (+p[2]); }
    // One-word factor refs: first token of each feed id, de-duped (capex_pressure +
    // capex_spigot -> just "capex"). Keeps the calendar column tight.
    function abFactorWords(feeds) {
        return [...new Set((feeds || []).map(f => f.split('_')[0]))].join('·');
    }

    function renderBubbleOverview() {
        const b = _slBoard;
        if (!b) return;

        // Headline tally from the live lights.
        const c = { green: 0, yellow: 0, orange: 0, red: 0 };
        (b.factors || []).forEach(f => { if (f.built && c[f.light] !== undefined) c[f.light]++; });
        const chip = (emoji, n) => n ? `<span class="n">${emoji} ${n}</span>` : '';
        const tally = `<div class="ab-tally">${chip('🟢', c.green)}` +
            `${chip('🟡', c.yellow)}${chip('🟠', c.orange)}${chip('🔴', c.red)}` +
            `<span class="ab-verdict">loaded, not fired</span></div>`;

        // Update banner — factors with new earnings data ready to pull (pending_billed),
        // an in-flight run (update_status.running), or the just-finished result. The
        // Update button is the billed-run authorization (nothing spends without it).
        const factorName = {};
        (b.factors || []).forEach(f => { factorName[f.id] = f.name; });
        const nm = fid => factorName[fid] || fid.replace(/_/g, ' ');
        const pend = b.pending_billed || [];
        const us = b.update_status || {};
        let upd = '';
        if (us.running) {
            upd = '<div class="ab-upd ab-upd-run">⏳ Updating — pulling fresh data…</div>';
        } else if (pend.length) {
            // A row that carries `failures` was ALREADY pulled and came back empty —
            // it stays queued (only a successful pull clears it), so say so loudly
            // rather than let it read as a fresh, untried update.
            const items = pend.map(p => {
                const f = (p.failures || [])[0];
                let row = `<div class="ab-upd-item"><span class="ab-upd-f">${esc(nm(p.factor))}</span>` +
                    `<span class="ab-upd-t">${esc((p.triggers || []).map(abEventLabel).join(', '))}</span></div>`;
                if (f) {
                    // Two different states, two different next actions: 'unavailable'
                    // means the print isn't out yet (WAIT), 'rejected' means the answer
                    // was bad. Spend is sunk either way, so show it, and offer a Clear.
                    const tries = f.attempts > 1 ? ` (${f.attempts} tries)` : '';
                    const spent = f.cost ? ` · billed $${(+f.cost).toFixed(4)}${tries}` : '';
                    const na = f.kind === 'unavailable';
                    const withheld = na && f.why === 'not_disclosed';
                    const per = f.period_end ? ` for the quarter ended ${esc(f.period_end)}` : '';
                    // Three different situations, three different next moves. Waiting
                    // only helps when the SOURCE isn't out; if it is out and the company
                    // simply didn't give the number, re-asking just bills again.
                    const body = withheld
                        ? `source is published${per}, but the company did not disclose the figure — ` +
                          `re-checking will not help. ${esc(f.reason)}`
                        : na
                        ? `not published yet${per} — waiting on the release/transcript`
                        : `returned no usable data — ${esc(f.reason)}`;
                    const args = `'${esc(p.factor)}','${esc(p.event_id || '')}','${esc(p.fire_date)}'`;
                    const parked = p.snoozed_until
                        ? ` <span class="ab-upd-snz">· parked, re-checks ${esc(p.snoozed_until)}</span>`
                        : (withheld ? ''   // don't offer a wait that cannot resolve
                            : `<button class="ab-upd-clear" onclick="snoozeBubbleUpdate(this,${args})"` +
                              `>Check tomorrow</button>`) +
                          `<button class="ab-upd-clear" onclick="dismissBubbleUpdate(this,${args})"` +
                          `>Clear</button>`;
                    row += `<div class="ab-upd-fail">${na ? '⏳' : '⚠'} ${esc(f.source)}: ` +
                        `checked ${esc(f.at)}${spent} · ${body}${parked}</div>`;
                }
                return row;
            }).join('');
            // Snoozed rows are owed but PARKED — they must not drive the headline or
            // the Update button, or "1 update ready" would nag about something the
            // user deliberately deferred (and Update would try to bill it).
            const live = pend.filter(p => !p.snoozed_until);
            const anyFail = live.some(p => (p.failures || []).length);
            const allParked = live.length === 0;
            const head = allParked
                ? `⏳ ${pend.length} parked`
                : `${anyFail ? '⚠' : '⚡'} ${live.length} update${live.length > 1 ? 's' : ''} ` +
                  `${anyFail ? 'pending' : 'ready'}`;
            upd = '<div class="ab-upd' + (anyFail ? ' ab-upd-warn' : '') + '"><div class="ab-upd-hd">' +
                `<span class="ab-upd-ttl">${head}</span>` +
                (allParked ? ''      // nothing firable — don't offer a button that no-ops
                    : '<button class="ab-upd-btn" onclick="runBubbleUpdates(this)">Update</button>') +
                '</div>' + items + '<div class="ab-upd-note">' +
                (allParked ? 'waiting on a later re-check — nothing will be billed until then'
                    : anyFail ? 'a flagged pull already billed once — re-running may return the same'
                              : 'new earnings data — refresh is billed') + '</div></div>';
        } else if (us.last && (us.last.fired || []).some(f => !f.error)) {
            const done = us.last.fired.filter(f => !f.error);
            const cost = done.reduce((a, f) => a + (f.cost || 0), 0);
            const bad = done.filter(f => (f.failed_sources || []).length);
            upd = `<div class="ab-upd ${bad.length ? 'ab-upd-warn' : 'ab-upd-done'}">` +
                `${bad.length ? '⚠' : '✓'} Updated ${esc(done.map(f => nm(f.factor)).join(', '))}` +
                ` · $${cost.toFixed(2)}` +
                (bad.length ? '<div class="ab-upd-fail">⚠ no usable data from ' +
                    esc(bad.map(f => f.failed_sources.join(', ')).join('; ')) +
                    ' — prior value kept</div>' : '') + '</div>';
        }

        // Earnings durability (Silicon E module).
        const m = b.module;
        let dur = '<div class="ab-tbd" style="padding:14px 0">warming up…</div>';
        if (m && m.value != null) {
            const p = m.extras && m.extras.roll_63bar_pct;
            dur = `<div class="ab-dur"><span class="v">$${Math.round(m.value)}B</span>` +
                (p != null ? `<span class="d">${p >= 0 ? '▲' : '▼'} ${p >= 0 ? '+' : ''}${p}% · 63-bar</span>` : '') +
                '</div>';
        }

        // Calendar — date · label · 1-word factor · countdown. This-week rows (through the
        // coming Sunday) get the green box, same as the board's new-data highlight. Weekday
        // is taken from the server date so it matches the ET-based days_out.
        const cats = b.catalysts || [];
        const gd = (b.generated_at || '').slice(0, 10);
        const wd = gd ? new Date(gd + 'T12:00:00Z').getUTCDay() : new Date().getDay(); // 0=Sun
        const daysLeftInWeek = (7 - wd) % 7;
        const cal = cats.length ? cats.map(e => {
            const cd = e.days_out === 0 ? 'today' : e.days_out + 'd';
            const hot = e.days_out <= daysLeftInWeek ? ' this-week' : '';
            return `<div class="ab-cal-row${hot}"><span class="ab-cal-date">${abMD(e.date)}</span>` +
                `<span class="ab-cal-lbl">${esc(abEventLabel(e.event_id))}</span>` +
                `<span class="ab-cal-fac">${esc(abFactorWords(e.feeds))}</span>` +
                `<span class="ab-cal-cd">${cd}</span></div>`;
        }).join('') : '<div class="ab-tbd" style="padding:12px 0">no upcoming catalysts</div>';

        // Two constrained columns (prose ~half left, calendar ~third right); each
        // section boxed like the ticker deep-dive panels.
        document.getElementById('ab-overview-body').innerHTML =
            tally + upd +
            '<div class="ab-cols">' +
                '<div class="ab-col-prose">' +
                    `<div class="ab-sec"><h5>Thesis</h5><div class="ab-box ab-thesis">${AB_THESIS_HTML}</div></div>` +
                    `<div class="ab-sec"><h5>Earnings durability</h5><div class="ab-box">${dur}</div></div>` +
                '</div>' +
                '<div class="ab-col-cal">' +
                    // The factor note is NOT here — it lives in the sub-header band
                    // (renderBubbleSubhead), outside this scrolling pane.
                    `<div class="ab-sec"><h5>Calendar · 90d</h5><div class="ab-box"><div class="ab-cal">${cal}</div></div></div>` +
                '</div>' +
            '</div>';
    }

    // Authorize + fire the due billed pulls, then fast-poll /get_stoplight until the
    // run finishes so the panel shows ⏳ -> ✓ + refreshed lights without waiting for
    // the 5-min cadence. The server-side lock 409s a double click; a fresh page poll
    // reflects update_status.running immediately (set synchronously by the endpoint).
    let _abPollIv = null;
    // Clear one owed row by hand — for a pull that ran and came back empty because the
    // number genuinely is not published (VRT not disclosing orders). Spends nothing;
    // scoped to this event only, so the same event next quarter still queues.
    async function dismissBubbleUpdate(btn, factor, eventId, fireDate) {
        if (btn) { btn.disabled = true; btn.textContent = 'Clearing…'; }
        try {
            await fetch(`${API_BASE}/dismiss_billed_pull`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ factor: factor, event_id: eventId, fire_date: fireDate })
            });
        } catch (e) {
            console.error('dismiss failed', e);
            if (btn) { btn.disabled = false; btn.textContent = 'Clear'; }
            return;
        }
        await fetchStoplight();
    }

    // Park a row until tomorrow — it stays OWED and visible, just not firable (and not
    // billable) until then. For "the transcript isn't out yet, ask me again later".
    async function snoozeBubbleUpdate(btn, factor, eventId, fireDate) {
        if (btn) { btn.disabled = true; btn.textContent = 'Parking…'; }
        try {
            await fetch(`${API_BASE}/snooze_billed_pull`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ factor: factor, event_id: eventId,
                                       fire_date: fireDate, days: 1 })
            });
        } catch (e) {
            console.error('snooze failed', e);
            if (btn) { btn.disabled = false; btn.textContent = 'Check tomorrow'; }
            return;
        }
        await fetchStoplight();
    }

    async function runBubbleUpdates(btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Updating…'; }
        try { await fetch(`${API_BASE}/run_stoplight_updates`, { method: 'POST' }); }
        catch (e) { console.error('stoplight update failed', e); }
        await fetchStoplight();                       // pick up running=true
        if (_abPollIv) clearInterval(_abPollIv);
        let n = 0;
        _abPollIv = setInterval(async () => {
            await fetchStoplight();
            const running = _slBoard && _slBoard.update_status && _slBoard.update_status.running;
            if (!running || ++n > 60) { clearInterval(_abPollIv); _abPollIv = null; }
        }, 3000);
    }


    // --- Charts tab (3rd tab) -------------------------------------------------
    // Renders GET /get_board_charts with lightweight-charts, same house options as
    // charts.js. The payload is fetched ONCE per page load and the charts built
    // once — the engine rebuilds its cache daily, so there is nothing to poll.
    let _chartData = null;      // cached payload
    let _boardCharts = [];      // live chart instances (teardown handles)

    async function renderBubbleCharts() {
        const body = document.getElementById('ab-charts-body');
        if (!body || _boardCharts.length) return;          // already drawn
        if (!_chartData) {
            body.innerHTML = '<div class="ab-tbd" style="padding:14px 0">loading chart data…</div>';
            try {
                const res = await fetch(`${API_BASE}/get_board_charts`);
                _chartData = await res.json();
            } catch (e) {
                console.error('rate charts fetch failed', e);
                body.innerHTML = '<div class="ab-rt-err">chart data unavailable — is the engine running?</div>';
                return;
            }
        }
        drawBoardCharts(body, _chartData);
    }

    function drawBoardCharts(body, payload) {
        _boardCharts.forEach(c => { try { c.remove(); } catch (e) { /* already gone */ } });
        _boardCharts = [];
        body.innerHTML = '';
        // Small multiples: 2 across x 3 down, so all six read without scrolling.
        const grid = document.createElement('div');
        grid.className = 'ab-rt-grid';
        body.appendChild(grid);
        (payload.charts || []).forEach(ch => {
            const sec = document.createElement('div');
            sec.className = 'ab-rt';
            sec.innerHTML =
                `<div class="ab-rt-hd"><span class="ab-rt-ttl">${esc(ch.title)}</span>` +
                `<span class="ab-rt-val">${esc((ch.latest && ch.latest.label) || '')}</span></div>` +
                (ch.subtitle ? `<div class="ab-rt-sub">${esc(ch.subtitle)}</div>` : '');
            grid.appendChild(sec);
            if (ch.error) {                                // one bad series ≠ a broken tab
                const e = document.createElement('div');
                e.className = 'ab-rt-err';
                e.textContent = 'unavailable — ' + ch.error;
                sec.appendChild(e);
                return;
            }
            if (ch.placeholder) {                          // reserved slot, content TBD
                const box = document.createElement('div');
                box.className = 'ab-rt-tbd';
                box.textContent = 'TBD';
                sec.appendChild(box);
                return;
            }
            const holder = document.createElement('div');
            holder.className = 'ab-rt-chart';
            sec.appendChild(holder);
            const chart = buildBoardChart(holder, ch);
            if (chart) _boardCharts.push(chart);
            const leg = chartLegendHTML(ch);
            if (leg) {
                const l = document.createElement('div');
                l.className = 'ab-rt-leg';
                l.innerHTML = leg;
                sec.appendChild(l);
            }
        });
        const foot = document.createElement('div');
        foot.className = 'ab-rt-foot';
        foot.textContent = 'FRED · rebuilt daily'
            + (payload.generated_at ? ' · ' + payload.generated_at.slice(0, 10) : '');
        body.appendChild(foot);
    }

    function buildBoardChart(holder, ch) {
        if (!window.LightweightCharts) return null;
        // LOCKED small-multiple: no pan, no zoom, both edges pinned — the whole
        // history stays framed so the six can be compared at a glance and nothing
        // drifts off-screen from a stray scroll over the panel. Crosshair stays on
        // so hovering still reads a value.
        const chart = LightweightCharts.createChart(holder, {
            autoSize: true,
            handleScroll: false,
            handleScale: false,
            layout: { background: { color: 'transparent' }, textColor: '#94a3b8',
                      fontFamily: 'Inter, sans-serif', fontSize: 10 },
            grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
            timeScale: { borderColor: '#334155', fixLeftEdge: true, fixRightEdge: true,
                         lockVisibleTimeRangeOnResize: true },
            rightPriceScale: { borderColor: '#334155', scaleMargins: { top: 0.14, bottom: 0.14 } },
            leftPriceScale: { visible: false },
            crosshair: { mode: 0 }
        });
        const times = (((ch.series || [])[0] || {}).data || []).map(p => p.time);
        // Recession shading is added FIRST so it paints BEHIND the lines (series
        // draw in add order). It rides its own hidden 0..1 price scale with zero
        // margins, so a value of 1 fills the full pane height as a gray band.
        if ((ch.bands || []).length && times.length) {
            // STEPPED AREA, not a histogram. A histogram draws one discrete bar per
            // data point, so at weekly spacing the shading came out as separate
            // stripes ("raster scan"). An area series with step interpolation is a
            // CONTINUOUS fill — 1 inside a band, 0 outside, vertical transitions —
            // which renders each recession as one solid rectangle at any zoom.
            const STEPS = (window.LightweightCharts.LineType || {}).WithSteps;
            const band = chart.addAreaSeries({
                priceScaleId: 'bands',
                lineType: STEPS === undefined ? 1 : STEPS,
                lineColor: 'rgba(0,0,0,0)',                 // no outline, fill only
                topColor: 'rgba(148,163,184,0.16)',
                bottomColor: 'rgba(148,163,184,0.16)',      // flat, not a gradient
                priceLineVisible: false, lastValueVisible: false,
                crosshairMarkerVisible: false
            });
            const inBand = t => ch.bands.some(b => t >= b.from && t <= b.to);
            band.setData(times.map(t => ({ time: t, value: inBand(t) ? 1 : 0 })));
            chart.priceScale('bands').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
        }
        let main = null;
        if (ch.baseline && (ch.series || []).length === 1) {
            // Split-fill at a baseline: line stays one color, but the region BELOW
            // the baseline fills red (the yield curve's inverted stretch) while the
            // region above stays unfilled. One series, native to lightweight-charts.
            const bl = ch.baseline, s = ch.series[0];
            main = chart.addBaselineSeries({
                baseValue: { type: 'price', price: bl.price || 0 },
                topLineColor: bl.top_line, bottomLineColor: bl.bottom_line,
                topFillColor1: bl.top_fill, topFillColor2: bl.top_fill,
                bottomFillColor1: bl.bottom_fill, bottomFillColor2: bl.bottom_fill,
                lineWidth: 2, priceLineVisible: false, lastValueVisible: false
            });
            main.setData(s.data || []);
        } else {
            (ch.series || []).forEach(s => {
                const ls = chart.addLineSeries({
                    color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false
                });
                ls.setData(s.data || []);
                if (!main) main = ls;
            });
        }
        if (ch.zero_line && main) {                        // the inversion line
            main.createPriceLine({
                price: 0, color: 'rgba(203,213,225,0.45)', lineWidth: 1,
                lineStyle: 0 /* solid, per the reference chart */,
                axisLabelVisible: false, title: ''
            });
        }
        if (ch.y_range && main) {
            // PINNED axis: hand the scale a fixed range instead of letting it
            // autoscale to whatever is in view, and drop the scale margins so the
            // stated min/max ARE the visible edges (margins would pad past them).
            const r = ch.y_range;
            main.applyOptions({
                autoscaleInfoProvider: () => ({ priceRange: { minValue: r.min, maxValue: r.max } })
            });
            chart.priceScale('right').applyOptions({ scaleMargins: { top: 0, bottom: 0 } });
        }
        if (ch.marker_last && main) {
            const pts = (ch.series[0] || {}).data || [];
            const last = pts[pts.length - 1];
            if (last) {
                // Dot ON the last point, but the LABEL as an HTML tag pinned inside
                // the plot. A marker's own text is centered on its bar — and that bar
                // is the right edge, so the text ran off and got clipped. Top-left is
                // dead space here (the pinned -2..5 axis leaves the top empty; the
                // series never exceeds +3.8), so the tag never collides with the line.
                main.setMarkers([{ time: last.time, position: 'inBar',
                                   color: '#f87171', shape: 'circle' }]);
                if (ch.latest && ch.latest.label) {
                    holder.style.position = 'relative';
                    const tag = document.createElement('div');
                    tag.className = 'ab-rt-today';
                    tag.textContent = 'today ' + ch.latest.label;
                    holder.appendChild(tag);
                    // Land the tag's right edge on the END of the plot. The price
                    // axis eats the real right edge, and its width depends on the
                    // label text ("-2.0" vs "5.0"), so measure it rather than guess.
                    // Deferred a frame: the scale has no width until first layout.
                    requestAnimationFrame(() => {
                        try {
                            tag.style.right = (chart.priceScale('right').width() + 5) + 'px';
                        } catch (e) { /* keep the CSS fallback inset */ }
                    });
                }
            }
        }
        chart.timeScale().fitContent();
        return chart;
    }

    function chartLegendHTML(ch) {
        const items = (ch.legend || []).map(l =>
            `<span><i style="background:${esc(l.color)}"></i>${esc(l.label)}</span>`);
        if ((ch.bands || []).length) {
            items.push('<span><i style="background:rgba(148,163,184,0.35)"></i>Recession</span>');
        }
        return items.join('');
    }


    // Collapse-state persistence (design-doc open item, closed 2026-07-19).
    // Shared helper in core.js; defaults to open (markup attribute) when unset.
    persistCollapse('stoplight-section', 'stoplightSectionOpen');

    // Self-initializing (independent of main.js's sync chain — the board has no
    // localStorage/ticker dependency).
    fetchStoplight();
    setInterval(fetchStoplight, SL_POLL_MS);
