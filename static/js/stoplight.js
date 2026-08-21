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
        _abHist = null; _abDay = 0;         // never show the PREVIOUS factor's rail
        showOnlyPanel('ai-bubble-dive');    // shared list in core.js — see DETAIL_PANELS
        renderBubbleHead();                 // title header: identity line only
        renderBubbleSubhead();              // band below it: the factor's About box
        switchBubbleTab('overview');
        renderBubbleOverview();             // paints immediately off the board row...
        if (_abFactor) {                    // ...then again with the rail + the ledger
            _abLedger = null; _abView = null;
            loadFactorHistory(_abFactor);
            loadFactorLedger(_abFactor);
        }
    }

    // WHAT A FACTOR MEASURES, AND WHY IT MATTERS. Rendered as a small box above the
    // calendar, NOT in the header — as header prose it crowded the identity line
    // (user, 2026-08-21). Split into two short fields so the box can label them.
    // Hand-written here for now, DELIBERATELY: the same text also lives in each
    // factor's module docstring, and the right home is a structured `definition`
    // block on the factor itself (with the light thresholds, which live only in
    // docstring prose today). Until that exists this map is the honest shortcut —
    // an id absent from it renders NO box rather than a wrong one.
    // `bands` is ordered pro-burst -> bubble-supportive (green .. red) and is a LIST,
    // never a fixed trio: heavy_haul has four (green/yellow/orange/red), so the
    // renderer must not assume three. `glyph` is omitted when a factor has none —
    // only 5 of 17 carry one. Both are read generically by renderBubbleSubhead, so
    // when a factor finally serves its own `definition` the data source changes and
    // the renderer does not.
    const AB_WHY = {
        premium_share: {
            measures: 'Premium models’ revenue ÷ total revenue on OpenRouter.',
            why: 'The commoditization kill-mechanism gauge — if quality stops commanding a ' +
                 'price premium, the capex case for frontier models goes with it.',
            bands: [
                { light: 'green',  range: '< 35%',    mean: 'commoditized' },
                { light: 'yellow', range: '35 – 50%', mean: 'premium eroding' },
                { light: 'red',    range: '≥ 50%',    mean: 'premium intact' }
            ],
            glyph: [
                { sym: '+', arrow: 'plus',  mean: 'volume AGREES with the money' },
                { sym: '−', arrow: 'minus', mean: 'volume CONTRADICTS it' }
            ],
            // Footnote prose, verbatim from the prototype. HTML, not escaped — it is
            // a literal in this file, never anything a source produced. Like the rest
            // of AB_WHY this belongs on the factor's own `definition`.
            method: 'Revenue = tokens × the <b>80/20</b> in/out blend of listed prices. ' +
                    'Premium = output ≥ <b>50×</b> the day’s commodity floor, re-read every ' +
                    'pull, so price deflation cannot sweep models across the line.'
        }
    };

    // The note box, painted into the SUB-HEADER band (#ab-subhead) between the title
    // header and the tabs. Three placements were tried before this one and each was
    // wrong for a specific reason worth not repeating: the scrolling pane (could
    // never sit closer than the tab strip's height to the rule, and lifting it past
    // the pane's edge CLIPPED it), the tabs row (outside the pane and unclippable,
    // but not the header meant), and the title header itself (correct band, but it
    // put a ~100px box in the identity row and pushed the header to 114px).
    // Its own band keeps the title header one line and leaves room beside the box for
    // the light-scale list (abLegendHTML). Empties on the board view, and
    // #ab-subhead:not(:empty) means the band takes no height at all then.
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
            '</div></div>' + abLegendHTML(f, w);
    }

    // The light scale, right of the About box: a COMPACT VERTICAL LIST — one row per
    // band, so three rows normally and FOUR for heavy_haul. It began as a horizontal
    // strip of side-by-side segments, and the width was simply wrong for this
    // dashboard (user, 2026-08-21): four columns only read at a width the panel does
    // not have, and stretching three short phrases across the band made a key look
    // like a banner. Stacked, it is content-sized and sits BESIDE the About box.
    // The row the factor is CURRENTLY in is lifted and carries the live metric, so the
    // list is the reading explained rather than a static key.
    // Rows are GRID CELLS, not nested row boxes, so the four columns (light / range /
    // meaning / live metric) align across every band whatever the threshold text is —
    // a factor with wider ranges widens the column, it does not ragged the list. The
    // metric cell is emitted EMPTY on inactive rows to hold its place; dropping it
    // would shear the grid. Four cells per band is also what the first-row border
    // reset (:nth-child(-n+4)) counts on.
    // The glyph row is appended only when the factor has one, and its active side is
    // matched off extras.arrow — the same field slGlyph reads for the sidebar, so the
    // legend cannot disagree with the row that opened it.
    function abLegendHTML(f, w) {
        const bands = (w && w.bands) || [];
        if (!bands.length) return '';
        const lc = { green: 'g', yellow: 'y', orange: 'o', red: 'r' };
        const rows = bands.map(b => {
            const c = lc[b.light] || 'y';
            const on = b.light === f.light ? ' on' : '';
            return `<span class="ab-sc-c ab-sc-l${on} abh-${c}">` +
                     `<span class="abh-dot abh-bg-${c}"></span>` +
                     `<span class="ab-sc-n">${esc(b.light)}</span></span>` +
                   `<span class="ab-sc-c ab-sc-r${on}">${esc(b.range)}</span>` +
                   `<span class="ab-sc-c ab-sc-m${on}">${esc(b.mean)}</span>` +
                   `<span class="ab-sc-c ab-sc-v${on}${on ? ' abh-' + c : ''}">` +
                     `${on ? esc(f.metric || '') : ''}</span>`;
        }).join('');
        const arrow = f.extras && f.extras.arrow;
        const gl = (w.glyph || []).length && arrow
            ? '<div class="ab-gl">' + w.glyph.map(g =>
                `<span class="ab-gl-i${g.arrow === arrow ? ' on' : ''}">` +
                `<b class="ab-gl-${g.arrow}">${g.sym}</b>${esc(g.mean)}</span>`).join('') + '</div>'
            : '';
        return `<div class="abh-legend"><div class="ab-scale">${rows}</div>${gl}</div>`;
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

    // --- Featured content: the prototype's EVIDENCE BLOCK ---------------------
    // Shape comes from Euphemus' published prototype ("Stoplight factor detail —
    // compact shell", artifact 0d4c13d9): a day RAIL down the left, a SUBSTRIP of the
    // day's reading with a 10-day sparkline, the evidence VIEW under it, and the
    // nuance as footnote columns at the bottom. The prototype's own summary of the
    // rule: only the evidence block changes shape per factor.
    // The Overview tab has two modes and the switch is the same `_abFactor` the header
    // and sub-header band already branch on. Board view is UNCHANGED — the light
    // tally, the update banner, the thesis and the durability module are board-level,
    // and that is the view they belong to.
    // A factor view drops the tally (user, 2026-08-21): a count of how the other
    // fifteen lights sit is not what you opened one factor to read.
    // It also drops the UPDATE BANNER — the Update button fires every due pull on the
    // board, not this factor's, so inside a single-factor view it would read as
    // "update THIS" while billing the rest. The banner stays on the board view, where
    // its scope is the truth.
    // The calendar stays (user), board-wide and content-sized on the far right.
    let _abHist = null;      // { factor, days:[newest-first] } for the OPEN factor only
    let _abDay = 0;          // index into _abHist.days; 0 = today's reading
    let _abLedger = null;    // { factor, has_ledger, days:[newest-first by DATE] }
    let _abView = null;      // 'ledger' | 'lenses' | null (generic) — sticky per open

    // History is fetched on panel open, not carried on the board payload — see the
    // comment on /get_factor_history. A factor with no rows yet (silicon_e is 14 days
    // old, some are 33) still renders: the rail simply has fewer days.
    async function loadFactorHistory(fid) {
        _abHist = null; _abDay = 0;
        try {
            const r = await fetch(`${API_BASE}/get_factor_history?factor=${encodeURIComponent(fid)}&days=30`);
            const j = await r.json();
            // A slow fetch that lands after the user has clicked ANOTHER factor must
            // not paint this one's history under that one's header.
            if (_abFactor !== fid) return;
            _abHist = (j && j.days) ? j : null;
        } catch (e) { console.error('factor history failed', e); _abHist = null; }
        if (_abFactor === fid) renderBubbleOverview();
    }

    // The per-model evidence, when the factor has any. Fetched alongside the history
    // and cached server-side per day, so clicking down the rail costs nothing.
    // has_ledger:false is the NORMAL answer for 15 of 16 factors and is not an error —
    // it is what suppresses the view switcher rather than showing a dead button.
    async function loadFactorLedger(fid) {
        _abLedger = null;
        try {
            const r = await fetch(`${API_BASE}/get_factor_ledger?factor=${encodeURIComponent(fid)}&days=10`);
            const j = await r.json();
            if (_abFactor !== fid) return;          // a later click won the race
            _abLedger = (j && j.has_ledger) ? j : null;
            if (_abLedger && !_abView) _abView = 'ledger';
        } catch (e) { console.error('factor ledger failed', e); _abLedger = null; }
        if (_abFactor === fid) renderBubbleOverview();
    }

    function abSetView(v) { _abView = v; renderBubbleOverview(); }

    // Rail click. Re-renders the whole Overview body rather than patching the detail:
    // the substrip, the sparkline marker and the evidence all key off the same index,
    // and three partial updates is three chances for them to disagree.
    function abPickDay(i) {
        _abDay = i;
        renderBubbleOverview();
    }

    function abHumanKey(k) { return k.replace(/_/g, ' '); }

    // Values come straight off the factor's extras, which are per-factor and untyped.
    // Formatting is by JS TYPE only — no per-factor knowledge here, deliberately, so a
    // factor the map has never seen still renders. Lists become chips because the ones
    // we have (premium_models) are sets of identifiers, not sentences.
    function abEvValue(v) {
        if (v == null) return '<span class="ab-ev-n">—</span>';
        if (Array.isArray(v)) return v.length
            ? '<span class="ab-ev-chips">' + v.map(x =>
                `<span class="ab-ev-chip">${esc(String(x))}</span>`).join('') + '</span>'
            : '<span class="ab-ev-n">none</span>';
        if (typeof v === 'boolean') return v ? 'yes' : 'no';
        if (typeof v === 'object') return `<span class="ab-ev-chip">${esc(JSON.stringify(v))}</span>`;
        return esc(String(v));
    }

    // 10-day sparkline over the snapshot values. Drawn from the SAME rows the rail
    // lists, so the marked point and the highlighted rail row cannot disagree.
    // A flat series (every value equal) would divide by zero on the y-scale, so it is
    // pinned to the mid-line instead of collapsing onto the baseline.
    const AB_SPARK_N = 10;   // how many observations the strip shows, not a unit of time
    function abSparkSVG(days, sel, light) {
        const pts = days.slice(0, AB_SPARK_N).filter(d => typeof d.value === 'number').reverse();
        if (pts.length < 2) return null;
        const W = 150, H = 24, PAD = 3;
        const vs = pts.map(d => d.value);
        const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo;
        const x = i => PAD + i * ((W - 2 * PAD) / (pts.length - 1));
        const y = v => span ? (H - PAD) - ((v - lo) / span) * (H - 2 * PAD) : H / 2;
        const line = pts.map((d, i) => `${x(i).toFixed(1)},${y(d.value).toFixed(1)}`).join(' ');
        // sel indexes the NEWEST-FIRST list; the polyline runs oldest-first.
        const si = pts.length - 1 - sel;
        const mark = (si >= 0 && si < pts.length)
            ? `<circle cx="${x(si).toFixed(1)}" cy="${y(pts[si].value).toFixed(1)}" r="2.5" ` +
              `class="ab-spk-pt abh-fill-${light}"/>` : '';
        // The count comes back with the SVG so the label cannot claim a span the line
        // does not draw — a factor with six days of history says 6, not 10.
        return { n: pts.length, svg:
            `<svg class="ab-spk" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" ` +
            `aria-label="last ${pts.length} readings">` +
            `<polyline points="${line}" fill="none" class="ab-spk-l"/>${mark}</svg>` };
    }

    // The rail is "history at this factor's cadence" — today that is DAYS for every
    // factor, because the snapshot log records one row per ET date whatever the factor's
    // own cadence is. A quarterly factor therefore shows ninety identical days rather
    // than the reported periods it should. Nothing here hard-codes a count (the caller
    // passes whatever it fetched); collapsing days to periods is the change that turns
    // this into the general thing, and it belongs in the STORE, not the renderer.
    const AB_DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    function abRailHTML(days, sel) {
        if (!days.length) return '<div class="ab-rail-e">no history yet</div>';
        return days.map((d, i) => {
            const c = AB_LC[d.light] || 'y';
            // The weekday is shown, not just derived, because for at least one factor
            // it is load-bearing: premium_share reads RED on Saturdays — commodity
            // coding traffic drops, so premium's revenue share rises mechanically — and
            // its highlight is state-change, which makes that flip a calendar artifact
            // wearing a signal's colour. Naming the day is what lets you see it. The
            // UTC noon parse keeps the name off the local timezone, which would slide a
            // date across midnight and mislabel exactly the weekend rows that matter.
            const wd = new Date(d.date + 'T12:00:00Z').getUTCDay();
            const we = (wd === 0 || wd === 6) ? ' we' : '';
            return `<button class="ab-day" onclick="abPickDay(${i})"` +
                   `${i === sel ? ' aria-current="true"' : ''}>` +
                   `<span class="abh-dot abh-bg-${c}"></span>` +
                   `<span class="d">${esc(d.date.slice(5))}</span>` +
                   `<span class="wd${we}">${AB_DOW[wd]}</span>` +
                   `<span class="v">${esc(d.metric || (d.value != null ? String(d.value) : ''))}</span>` +
                   '</button>';
        }).join('');
    }

    // Dollars-per-day run to seven figures; the table has one column for them and the
    // lens rows have half of one. Compact is the only thing that fits, and the exact
    // figure is never the point — the SHARE beside it is.
    function abUSD(v) {
        if (v == null) return '—';
        const a = Math.abs(v);
        if (a >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
        if (a >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
        if (a >= 1e3) return '$' + Math.round(v / 1e3) + 'k';
        return '$' + Math.round(v);
    }

    // LEDGER — the full priced table for one day: who earned what, at what price, on
    // which side of the premium line. This is the view that shows the light being
    // computed rather than asserted.
    function abLedgerHTML(day) {
        const rows = day.by_rev || [];
        if (!rows.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this day</div>';
        const top = Math.max(...rows.map(m => m.rev)) || 1;
        const body = rows.map(m =>
            '<tr>' +
              `<td class="rk">${m.r}</td>` +
              '<td class="l"><div class="mdl">' +
                `<div class="nm2">${esc(m.name)}</div><div class="sl">${esc(m.slug)}</div>` +
              '</div></td>' +
              `<td>${m.out ? '$' + m.out.toFixed(2) : '—'}</td>` +
              // Order is pct - bar - dollars (Euphemus' prototype). The share leads
              // because it is what the light is computed from; the bar reads left-to-
              // right off it, and the dollar figure lands at the column's right edge
              // where the eye scans a money column.
              '<td class="l"><div class="revcell">' +
                `<span class="pct">${m.revs.toFixed(1)}%</span>` +
                `<span class="bar"><i class="${m.prem ? 'p' : 'c'}" ` +
                  `style="width:${Math.max(2, Math.round(m.rev / top * 100))}%"></i></span>` +
                `<span class="amt">${abUSD(m.rev)}</span>` +
              '</div></td>' +
              `<td>${m.ts.toFixed(2)}%</td>` +
              `<td class="l"><span class="tier ${m.prem ? 'p' : 'c'}">` +
                `${m.prem ? 'premium' : 'commodity'}</span></td>` +
            '</tr>').join('');
        return '<div class="ab-scroller"><table class="ab-ledger">' +
            '<thead><tr><th class="l" colspan="2">Model</th><th>Out $/M</th>' +
            '<th class="l">Est. revenue / day</th><th>Tokens</th><th class="l">Tier</th></tr></thead>' +
            `<tbody>${body}</tbody></table></div>`;
    }

    // TWO LENSES — the same day read twice: top 10 by money, top 10 by volume. The
    // factor's whole +/- glyph is whether those two agree, so putting them side by side
    // is the glyph shown rather than stated. A model on BOTH lists is marked, and the
    // count of those is the line that has been falling.
    function abLensesHTML(day, oldest) {
        const rev = day.by_rev || [], tok = day.by_tok || [];
        if (!rev.length || !tok.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this day</div>';
        const inRev = new Set(rev.map(m => m.slug)), inTok = new Set(tok.map(m => m.slug));
        const row = (m, both, fig) =>
            `<div class="ab-lrow${both ? ' both' : ''}">` +
              `<span class="rk">${m.r}</span>` +
              `<span class="link${both ? '' : ' off'}">↔</span>` +
              `<span class="nm2">${esc(m.name)}</span>` +
              `<span class="fig">${fig}</span></div>`;
        // Each lens LEADS with the figure it is sorted by, in that lens's own accent —
        // gold for dollars on the money side, steel for token share on the volume side
        // — then quotes the other figure muted behind it. So the coloured number is
        // always the ranking key, and the pair still lets you see what a model earns
        // against what it serves. Long names ellipsise; the figures do not shrink
        // (user: a cut-off model name is acceptable, a cut-off number is not).
        const money = rev.map(m => row(m, inTok.has(m.slug),
            `<b>${abUSD(m.rev)}</b> <span class="alt">${m.revs.toFixed(1)}%</span>`)).join('');
        const vol = tok.map(m => row(m, inRev.has(m.slug),
            `<b>${m.ts.toFixed(2)}%</b> <span class="alt">${abUSD(m.rev)}</span>`)).join('');
        // The trend line is the point of the overlap count, so it is shown against the
        // oldest day the ledger carries rather than on its own.
        // The sentence is the point — the count alone reads as a stat, and this number
        // is the thesis. The trailing comparison is what makes it a TREND rather than a
        // reading: 4 down to 1 over ten days is the money and the volume separating.
        const then = oldest && oldest.date !== day.date
            ? ` <span class="ago">was <b>${oldest.overlap}</b> on ${esc(abMD(oldest.date))}</span>` : '';
        return '<div class="ab-lenses">' +
            '<div class="ab-lens money"><div class="lens-hd"><div class="t">Where the money is</div>' +
              '<div class="s">top 10 by estimated revenue</div></div>' + money + '</div>' +
            '<div class="ab-lens vol"><div class="lens-hd"><div class="t">Where the volume is</div>' +
              '<div class="s">top 10 by tokens served</div></div>' + vol + '</div>' +
            '</div>' +
            `<div class="ab-overlapbar"><b>${day.overlap}</b> of ${rev.length} models appear in ` +
            'both lists — the rest earn without volume, or serve volume without earning.' +
            `${then}</div>`;
    }

    function abFeaturedHTML(f) {
        // The rail's rows ARE the history; the live board row is only the newest of
        // them. Reading the selected day out of the history (rather than special-casing
        // index 0 to the board row) keeps one code path for "what am I looking at".
        const days = (_abHist && _abHist.days) || [];
        const sel = Math.min(_abDay, Math.max(days.length - 1, 0));
        const d = days[sel] || { date: f.asof, light: f.light, metric: f.metric,
                                 state: f.state, extras: f.extras, value: f.value };
        const prior = days[sel + 1] || null;
        const today = sel === 0;

        // The ledger is keyed by the day the DATA is for, the rail by the day the
        // snapshot was taken — premium_share's 08-21 snapshot carries asof 08-20. Match
        // on asof so a rail click lands on the ledger row it is actually about.
        const led = (_abLedger && _abLedger.days) || [];
        const ledDay = led.find(x => x.date === (d.asof || d.date)) || null;
        // A PAST ledger day is a RECONSTRUCTION, not the record. ledger() re-prices old
        // token volumes with TODAY's price list, and this factor's premium line is a
        // multiple of a floor that deflates fast — so a floor move sweeps whole models
        // across the line and the recomputed share can miss the recorded one badly
        // (2026-08-13: recorded 27.1%, recomputed 45.9% — different BANDS, green vs
        // yellow). Today's day agrees by construction; older ones need not.
        // The pane is therefore made self-consistent on the LEDGER's own numbers — the
        // table, the strip and the reading all come from one computation — and the
        // recorded value is named beside it rather than quietly overwritten. The rail
        // keeps showing what the board actually recorded, because that is the history.
        // `basis` is the server's own answer and is authoritative: 'recorded' means the
        // day was captured at the prices its light was decided on, 'reconstructed'
        // means it was re-derived later. The numeric fallback covers a payload served
        // before the ledgers table existed, where the disagreement is all we have.
        const recon = ledDay && (ledDay.basis
            ? ledDay.basis === 'reconstructed'
            : (d.value != null && Math.abs(ledDay.share - d.value) >= 0.05))
            ? d : null;
        const rd = ledDay
            ? { metric: ledDay.share.toFixed(1) + '%', light: ledDay.light }
            : d;
        const c = AB_LC[rd.light] || 'y';

        // --- evidence header: label, what day is on screen, view switcher ---------
        // The switcher renders only when a factor HAS more than one view. 15 of 16 have
        // none — a per-item ledger is something a factor either keeps or does not — and
        // an always-visible switcher over a single view is chrome that promises a
        // second one. `views` is a LIST for the same reason `bands` is: a factor that
        // grows a ledger gets the switcher with no change here.
        const views = ledDay
            ? [{ key: 'ledger', label: 'Ledger' }, { key: 'lenses', label: 'Two lenses' }]
            : [];
        const view = _abView || (views.length ? views[0].key : null);
        const vsw = views.length > 1
            ? '<span class="ab-vsw">' + views.map(v =>
                `<button class="ab-vbtn" aria-pressed="${v.key === view}" ` +
                `onclick="abSetView('${v.key}')">${esc(v.label)}</button>`).join('') +
              '</span>'
            : '';
        const evHd =
            '<div class="ab-ev-hd"><span class="lbl">Evidence</span>' +
            `<span class="meta">${esc(d.date || '')}${today ? '' : ' · historical'}` +
            `${d.asof && d.asof !== d.date ? ' · as of ' + esc(d.asof) : ''}` +
            `${ledDay ? ' · ' + ledDay.n_models + ' models' : ''}` +
            `${recon ? ' · <span class="ab-recon">re-priced today' +
                       (recon.metric ? ' · recorded ' + esc(recon.metric) : '') +
                       '</span>' : ''}</span>` + vsw + '</div>';

        // --- substrip: the day's reading, the one before it, its headline figures and
        // the shape of the run. The scalar extras ride here rather than in the view
        // below, as the prototype has them (Comm tokens / Prem line / Est rev / Prev):
        // they are the numbers you read AT the reading, not evidence for it.
        const ex = d.extras || {};
        const skip = { source: 1, arrow: 1 };
        // When a ledger day is on screen its figures WIN over the snapshot's. The two
        // are computed at different moments — the snapshot froze that day's floor, the
        // ledger re-derives it from today's price list — so premium_share's stored
        // line (8.11) and its recomputed one (7.97) can differ by a few cents. Sourcing
        // the strip from the ledger keeps the line quoted above the table identical to
        // the line the table's own tiers were cut on, which is the same rule the legend
        // follows: nothing on screen may disagree with the thing it explains.
        const fig = ledDay
            ? [['comm tokens', ledDay.comm_tok + '%'],
               ['prem line', '$' + ledDay.line],
               ['est rev', abUSD(ledDay.total_rev)]]
            : Object.keys(ex)
                .filter(k => !skip[k] && ex[k] != null && typeof ex[k] !== 'object')
                .slice(0, 4).map(k => [abHumanKey(k), String(ex[k])]);
        // Prev follows the SAME computation as Reading. Mixing them — a re-priced
        // reading against a recorded previous — would invent a day-over-day move that
        // neither series actually shows.
        const ledPrev = ledDay ? led[led.indexOf(ledDay) + 1] : null;
        const prevTx = ledDay
            ? (ledPrev ? ledPrev.share.toFixed(1) + '%' : '—')
            : (prior ? (prior.metric || '—') : '—');
        const spark = abSparkSVG(days, sel, c);
        const substrip =
            '<div class="ab-substrip">' +
              `<span><span class="k">Reading</span> <b class="abh-${c}">${esc(rd.metric || '—')}</b></span>` +
              fig.map(([k, v]) => `<span><span class="k">${esc(k)}</span> <b>${esc(v)}</b></span>`).join('') +
              `<span><span class="k">Prev</span> <b>${esc(prevTx)}</b></span>` +
              (spark ? `<span class="sp"><span class="k">${spark.n}d</span>${spark.svg}</span>` : '') +
            '</div>';

        // --- the view itself. A factor with a ledger gets the real thing; the rest get
        // the generic grid of whatever the substrip did NOT already show — the arrays
        // (premium_models, basket constituents) and any scalars past the first four.
        // Keys render raw-but-despaced on purpose: a real label and unit per key belongs
        // in the `definition` promotion, and inventing prettier names here would put a
        // second, drifting copy of that vocabulary in the frontend.
        const shown = new Set(fig.map(([k]) => k));
        const rest = Object.keys(ex).filter(k => !skip[k] && !shown.has(abHumanKey(k)));
        const generic = rest.length
            ? '<div class="ab-ev"><div class="ab-ev-g">' +
              rest.map(k => `<div class="ab-ev-k">${esc(abHumanKey(k))}</div>` +
                            `<div class="ab-ev-v">${abEvValue(ex[k])}</div>`).join('') +
              '</div></div>'
            : '<div class="ab-ev"><div class="ab-tbd">every figure this reading carried is on ' +
              'the line above</div></div>';
        const viewHTML = !ledDay ? generic
            : view === 'lenses' ? abLensesHTML(ledDay, led[led.length - 1])
            : abLedgerHTML(ledDay);

        const body =
            '<div class="ab-evid">' +
              `<nav class="ab-rail" aria-label="Reading history">${abRailHTML(days, sel)}</nav>` +
              `<section class="ab-detail">${substrip}${viewHTML}</section>` +
            '</div>';

        // --- footnotes: the nuance, at the bottom, in columns ---------------------
        // The prototype's third column is the GLYPH key. It is not repeated here: the
        // legend in the sub-header band already carries it, and two copies on one
        // screen is worse than either placement. Whether it belongs up there or down
        // here is the open call (user, 2026-08-21).
        const w = AB_WHY[f.id] || {};
        const src = (d.extras && d.extras.source) || (f.extras && f.extras.source) || '';
        const prov = [
            src ? esc(src) : '',
            f.cadence ? `<span>cadence</span> ${esc(f.cadence)}` : '',
            f.highlight ? `<span>highlight</span> ${esc(f.highlight)}` : '',
            f.updated_at ? `<span>updated</span> ${esc(String(f.updated_at).replace('T', ' ').slice(0, 16))}` : '',
            `<span>fails</span> ${f.consecutive_failures || 0}`,
            f.stale_days ? `<span>stale</span> ${f.stale_days}d` : ''
        ].filter(Boolean).join(' · ');
        // An errored factor says so in the footnotes, not quietly in a log: the number
        // on screen is then the last good one, not a current one.
        const err = f.error
            ? `<div class="ab-fc"><span class="k">Error</span><div class="b ab-fc-err">⚠ ${esc(f.error)}</div></div>`
            : '';
        const method = w.method
            ? `<div class="ab-fc"><span class="k">Method</span><div class="b">${w.method}</div></div>`
            : '';
        const foot = '<div class="ab-foot">' + method +
            `<div class="ab-fc"><span class="k">Provenance</span><div class="prov">${prov}</div></div>` +
            err + '</div>';

        return `<div class="ab-frame">${evHd}${body}${foot}</div>`;
    }

    function renderBubbleOverview() {
        const b = _slBoard;
        if (!b) return;

        // A factor is selected -> the board-level tally / banner / thesis are not what
        // this view is for. Everything below still runs for the BOARD view only.
        const _f = _abFactor ? (b.factors || []).find(x => x.id === _abFactor) : null;

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

        // The calendar column is identical in both modes — same board-wide 90d list,
        // same content-sized column on the far right. Only the LEFT column changes.
        const calCol =
            '<div class="ab-col-cal">' +
                // The factor note is NOT here — it lives in the sub-header band
                // (renderBubbleSubhead), outside this scrolling pane.
                `<div class="ab-sec"><h5>Calendar · 90d</h5><div class="ab-box"><div class="ab-cal">${cal}</div></div></div>` +
            '</div>';

        // FACTOR VIEW — no tally, no update banner, and the featured column takes all
        // the width up to the calendar (.ab-col-feat is flex:1, where the board's
        // .ab-col-prose is a constrained half; prose wants a measure, a reading does
        // not, and the extras lists need the room).
        if (_f) {
            document.getElementById('ab-overview-body').innerHTML =
                '<div class="ab-cols">' +
                    `<div class="ab-col-feat">${abFeaturedHTML(_f)}</div>` + calCol +
                '</div>';
            return;
        }

        // BOARD VIEW — unchanged. Two constrained columns (prose ~half left, calendar
        // ~third right); each section boxed like the ticker deep-dive panels.
        document.getElementById('ab-overview-body').innerHTML =
            tally + upd +
            '<div class="ab-cols">' +
                '<div class="ab-col-prose">' +
                    `<div class="ab-sec"><h5>Thesis</h5><div class="ab-box ab-thesis">${AB_THESIS_HTML}</div></div>` +
                    `<div class="ab-sec"><h5>Earnings durability</h5><div class="ab-box">${dur}</div></div>` +
                '</div>' + calCol +
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
