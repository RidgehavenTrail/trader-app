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
        // Never show the PREVIOUS factor's rail — or its LEDGER. The ledger reset used
        // to happen below, AFTER the immediate paint, which was invisible while
        // premium_share was the only factor holding one: the stale value was always
        // either null or its own. With a second ledger factor the first paint reads the
        // outgoing factor's days through the incoming factor's vocabulary, and a
        // silicon payback day has no `share` to quote. Cleared before anything renders.
        _abHist = null; _abDay = 0; _abLedger = null; _abView = null;
        showOnlyPanel('ai-bubble-dive');    // shared list in core.js — see DETAIL_PANELS
        renderBubbleHead();                 // title header: identity line only
        renderBubbleSubhead();              // band below it: the factor's About box
        switchBubbleTab('overview');
        renderBubbleOverview();             // paints immediately off the board row...
        if (_abFactor) {                    // ...then again with the rail + the ledger
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
            // The band edges as NUMBERS, for the sparkline's dashed gridlines (the
            // prototype's 35/50 lines). Hand-written like the rest of AB_WHY —
            // per-factor content is allowed to be per-factor (user, 2026-08-21); the
            // definition promotion only moves where this data lives, not this shape.
            edges: [35, 50],
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
        },
        silicon_payback: {
            measures: 'AI services revenue / industry GPU spend — can the silicon pay for itself?',
            // Deliberately says nothing about which way the ratio is currently moving.
            // A direction written into a static definition goes stale the first print
            // that contradicts it, and the sparkline and the Two-sides bar both compute
            // the live one — so this says what to WATCH and lets them say what happened.
            why: 'Tests whether the demand is real. If what the market pays for AI can cover ' +
                 'the chips bought to serve it, the spending has something underneath it. Watch ' +
                 'the direction more than the level — a build-out earns less than it costs at ' +
                 'the start, so what matters is whether that gap is closing.',
            bands: [
                { light: 'green',  range: '< 0.20',      mean: 'spend unrecovered' },
                { light: 'yellow', range: '0.20 – 0.50', mean: 'partial recovery' },
                { light: 'red',    range: '> 0.50',      mean: 'chips self-funding' }
            ],
            edges: [0.2, 0.5],
            // No glyph pair: this factor has no second series to agree or disagree with the
            // way premium_share's token share does, and a glyph key here would promise a
            // mark the board never draws.
            method: 'Numerator = OpenAI + Anthropic + Copilot + Gemini — <b>services, not ' +
                    'rails</b> (AMZN excluded; it sells rails). Denominator = NVDA data-centre ' +
                    'revenue <b>×4</b> for a run rate, never TTM, <b>/ 0.73</b> for NVIDIA’s share ' +
                    'of the market. Custom silicon (TPU, Trainium, MTIA) is never counted ' +
                    'directly — nothing here measures it. It enters only through that ' +
                    '<b>0.73</b>, which is NVIDIA’s share of a market defined to include it, so ' +
                    'the rest of the market is <b>implied by grossing up, not added up</b>. ' +
                    '<b>Silicon only</b> — power, shells and ' +
                    'networking sit on top, so red means “chips pay for themselves,” not ' +
                    '“healthy.” And it is a <b>floor</b>: third-party consumption on Azure ' +
                    'OpenAI / Bedrock / Vertex is real demand this cannot see, so the error runs ' +
                    'toward less-green.'
        },
        memory_canary: {
            // Glanceable, and kept that way (user, 2026-08-29): the About box has to say
            // what the factor measures in a couple of seconds. WHICH estimates and why
            // is real, but it is footnote detail — it lives under Horizon below.
            measures: 'Of the last 5 forward-EPS revisions by SELL-SIDE ANALYSTS, pooled '
                    + 'across Micron and SK Hynix, how many were DOWNWARD.',
            // Says nothing about which way the estimates are currently going — that is
            // what the rail, the sparkline and the pips are for, and a direction written
            // into a definition is a direction that has stopped being measured.
            // Two sentences, and deliberately: the About box answers WHY THIS FACTOR, and
            // the basket rationale that used to close it (why these two names, why not HBM
            // alone) moved down to the Method footnote — it is detail you read once, not
            // header (user, 2026-08-29).
            why: 'The memory-glut sub-mechanism, and the earliest place a build-out shows. '
               + 'Memory is bought ahead of the racks it goes into and is the one AI input '
               + 'with a public estimate stream, so it cracks in analyst revisions before it '
               + 'cracks anywhere you can see.',
            // Ordered by the METRIC, like the other two — which is what makes this
            // factor's inversion visible rather than hidden: MORE downgrades is the
            // pro-burst end, so red sits at the bottom of this scale.
            bands: [
                { light: 'red',    range: '0 – 1 down', mean: 'estimates holding' },
                { light: 'yellow', range: '2 – 3 down', mean: 'cracking, partial' },
                { light: 'green',  range: '4 – 5 down', mean: 'estimates cracking' }
            ],
            // Band EDGES, for the sparkline's dashed gridlines. The reading is an integer
            // 0–5, so the lines fall between the integers a band separates.
            edges: [1.5, 3.5],
            // No glyph pair: nothing corroborates this factor the way premium_share's
            // token share corroborates its money share, and a key here would promise a
            // mark the board never draws.
            // THREE TOPICS, not one column of prose: the note had grown to cover the
            // basket, the horizon rule and the counting mechanics at once, and none of
            // them was findable in it (user, 2026-08-29). `.ab-foot` is an auto-fit grid,
            // so these flow into columns and wrap on their own.
            method: [
                { k: 'Basket', b:
                    'Memory-market HEALTH, not HBM alone: DDR5 strength is itself '
                  + 'AI-caused — diverted capacity starved commodity DRAM — so a crack '
                  + 'that counts is <b>HBM and DDR5 rolling together</b>. Hence two names: '
                  + '<b>Micron</b> for the commodity line, <b>SK Hynix</b> (56% of HBM) for '
                  + 'the AI one.' },
                { k: 'Horizon', b:
                    'Two estimates per name, not four: the <b>next quarter</b> — the '
                  + 'upcoming one reports within weeks and is largely priced — and the '
                  + '<b>fiscal year that reports 6+ months out</b>. The test is the REPORT '
                  + 'date, not the period end, because the report is where an estimate is '
                  + 'tested: a period that closed yesterday but prints next month is still '
                  + 'forward-looking. The two names run different fiscal calendars, so at '
                  + 'one horizon this can select different LABELS for them — which is the '
                  + 'point of selecting by date. Readings before <b>2026-08-29</b> summed '
                  + 'all four periods: same bands, different denominator, and the substrip '
                  + 'names which rule each day was counted under.' },
                { k: 'Counting', b:
                    'Counts come from yfinance <b>eps_revisions</b> — the direction of '
                  + 'sell-side EPS ESTIMATE changes. Not rating actions, and not company '
                  + 'guidance, which <i>triggers</i> revisions rather than being one. They '
                  + 'arrive per forecast period, so one analyst revising a whole model '
                  + 'counts twice — a “revision” here is an <b>analyst-period</b>, not an '
                  + 'analyst. The feed publishes 7-day and 30-day <b>totals</b> rather than '
                  + 'a dated list, so “the last 5” is <b>approximated</b> from the '
                  + 'down-share of the narrower window that holds at least 5 revisions, '
                  + '×5 and rounded. Pooling is by <b>count</b> and unweighted: a name '
                  + 'that files more revisions carries more of the light.' },
                { k: 'The clock', b:
                    'The feed’s “last 7 days” is not a rolling window — it is a '
                  + 'field the vendor refreshes in steps. Measured over this factor’s own '
                  + 'log, <b>42 daily rows held ten distinct observations</b>, the longest '
                  + 'unchanged for 13 days, and two vendor frames alternate. The reading '
                  + 'now carries the date it was <b>OBSERVED</b> rather than the date we '
                  + 'looked: <b>Observed</b> above is how long the current numbers have '
                  + 'stood, and the log keeps one row per observation instead of one per '
                  + 'poll. Distinct from <b>stale</b> in the provenance line, which counts '
                  + 'days since the last poll and reads 0 here every day — a fresh poll '
                  + 'and a fresh reading are different claims.' }
            ]
        },
        regulatory: {
            measures: 'How many US states have a state-level action IN FORCE against '
                    + 'the free ride on ratepayers.',
            why: 'The earnings-durability drag. Data-center economics assume somebody '
               + 'else pays for the grid they need; a state that makes the load pay, or '
               + 'stops it connecting, prices that assumption. Not a timing signal — '
               + 'what it drags on is how durable the earnings are.',
            bands: [
                { light: 'red',    range: '< 10 states',  mean: 'free ride on' },
                { light: 'yellow', range: '10 – 20 states', mean: 'movement starting' },
                { light: 'green',  range: '20+ states',   mean: 'nowhere to run' }
            ],
            edges: [9.5, 19.5],
            glyph: [
                { sym: '↓', arrow: 'down', mean: 'MORE projects blocked locally' },
                { sym: '↑', arrow: 'up',   mean: 'fewer blocked' }
            ],
            method: [
                { k: 'What counts', b:
                    'Four tests, all required. <b>In force</b> — signed, issued or '
                  + 'adopted, with an effective date; passed-but-unsigned does not count '
                  + '(New York’s Responsible Data Center Development Act), nor does an '
                  + 'open docket. <b>Any branch</b> — statute, executive order, or a '
                  + 'commission rule of general application. <b>State-wide</b> — binds '
                  + 'every utility in the state. <b>About large-load power</b> — cost '
                  + 'allocation, rate class, interconnection or permitting; a tax measure '
                  + 'and a study mandate both fail. A TEMPORARY action counts while it is '
                  + 'in force, and retires on its own expiry date without a billed run.' },
                { k: 'What it costs', b:
                    'The state-wide test excludes the two most consequential measures in '
                  + 'the country: <b>AEP Ohio</b>’s tariff and Virginia’s '
                  + '<b>Dominion GS-5</b> class, because each binds one utility — and '
                  + 'Dominion is about two thirds of Virginia. That is a real cost, taken '
                  + 'deliberately: a light that counted one utility as a state would say '
                  + 'the map was covered when it is not. Both are in <b>Excluded</b>, '
                  + 'where an exclusion can be checked rather than mistaken for an '
                  + 'oversight. Before <b>2026-08-29</b> the roster was three unaudited '
                  + 'names and the rule read “statutes only”; audited, it was right '
                  + 'about one of them.' },
                { k: 'The arrow', b:
                    'A Data Center Watch count of projects stopped by local opposition, '
                  + 'as a DIRECTION only — it never changes the colour. It compares two '
                  + 'observations and <b>refuses when they are not comparable</b>: a '
                  + 'blocked-only count against a blocked-or-delayed one, a restatement '
                  + 'of the same period, or a running total against a single quarter. '
                  + 'When it refuses it says why rather than showing nothing. That rule '
                  + 'exists because the only arrow this factor has ever fired, on '
                  + '<b>2026-08-18</b>, was an artefact of exactly that: “Q1 2026 '
                  + 'outright cancellations, at least 20” set against a seeded '
                  + '“blocked per quarter, 75”. Every figure now carries the basis '
                  + 'and the period it was measured on, so a mismatch is visible instead '
                  + 'of silent.' }
            ]
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
            // No default set here any more: 'ledger' is premium_share's first view, not
            // every factor's, and abFeaturedHTML already falls back to whichever view
            // the factor lists first.
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
    function abSparkSVG(days, sel, light, edges) {
        const pts = days.slice(0, AB_SPARK_N).filter(d => typeof d.value === 'number').reverse();
        if (pts.length < 2) return null;
        const W = 150, H = 24, PAD = 3;
        const vs = pts.map(d => d.value);
        // Band edges join the scale as well as the drawing: an edge outside the data's
        // own range must pull the scale open rather than draw off-canvas — the whole
        // point of the 35 line is seeing how far ABOVE it the series is riding.
        const es = (edges || []).filter(e => Number.isFinite(e));
        const lo = Math.min(...vs, ...es), hi = Math.max(...vs, ...es), span = hi - lo;
        const x = i => PAD + i * ((W - 2 * PAD) / (pts.length - 1));
        const y = v => span ? (H - PAD) - ((v - lo) / span) * (H - 2 * PAD) : H / 2;
        const line = pts.map((d, i) => `${x(i).toFixed(1)},${y(d.value).toFixed(1)}`).join(' ');
        // sel indexes the NEWEST-FIRST list; the polyline runs oldest-first.
        const si = pts.length - 1 - sel;
        // Prototype treatment (Euphemus): the WHOLE spark — line, area, dot — carries
        // the selected day's light via currentColor off the abh-* class on the svg, so
        // clicking down the rail retints the strip to the day you are reading. The
        // area is the line closed to the baseline at 10% opacity; the dot's dark ring
        // is what keeps it legible on top of that fill.
        const grid = es.map(e =>
            `<line x1="0" y1="${y(e).toFixed(1)}" x2="${W}" y2="${y(e).toFixed(1)}" ` +
            `class="ab-spk-gl"/>`).join('');
        const area = `<polygon points="${line} ${x(pts.length - 1).toFixed(1)},${H} ` +
                     `${x(0).toFixed(1)},${H}" fill="currentColor" opacity=".10"/>`;
        const mark = (si >= 0 && si < pts.length)
            ? `<circle cx="${x(si).toFixed(1)}" cy="${y(pts[si].value).toFixed(1)}" r="2.6" ` +
              `fill="currentColor" stroke="#0f172a" stroke-width="1.4"/>` : '';
        // The count comes back with the SVG so the label cannot claim a span the line
        // does not draw — a factor with six days of history says 6, not 10. It counts
        // READINGS, not days: an asof-keyed factor's rows are one per OBSERVATION, so
        // memory_canary's ten points span six weeks and silicon_payback's seven are
        // quarterly prints. "10d" was the assumption that the rail is a calendar.
        // Gridlines draw FIRST so the line and fill sit on top of them.
        return { n: pts.length, svg:
            `<svg class="ab-spk abh-${light}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" ` +
            `aria-label="last ${pts.length} readings">` +
            `${grid}${area}<polyline points="${line}" fill="none" class="ab-spk-l"/>${mark}</svg>` };
    }

    // The rail is "history at this factor's cadence" — today that is DAYS for every
    // factor, because the snapshot log records one row per ET date whatever the factor's
    // own cadence is. A quarterly factor therefore shows ninety identical days rather
    // than the reported periods it should. Nothing here hard-codes a count (the caller
    // passes whatever it fetched); collapsing days to periods is the change that turns
    // this into the general thing, and it belongs in the STORE, not the renderer.
    const AB_DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    // `backed` — the Set of data-dates the factor's LEDGER covers, or null when the
    // factor has no ledger (or it hasn't loaded yet). A rail day outside it still has
    // its recorded reading, but clicking it opens a panel with no evidence behind it —
    // so its colour is MUTED (user, 2026-08-21): the light stays visible as history,
    // it just stops advertising a depth that is not there. For the 15 no-ledger
    // factors backed is null and nothing mutes — every day there backs itself.
    function abRailHTML(days, sel, backed) {
        if (!days.length) return '<div class="ab-rail-e">no history yet</div>';
        return days.map((d, i) => {
            const c = AB_LC[d.light] || 'y';
            const dim = backed && !backed.has(d.asof || d.date) ? ' dim' : '';
            // The weekday is shown, not just derived, because for at least one factor
            // it is load-bearing: premium_share reads RED on Saturdays — commodity
            // coding traffic drops, so premium's revenue share rises mechanically — and
            // its highlight is state-change, which makes that flip a calendar artifact
            // wearing a signal's colour. Naming the day is what lets you see it. The
            // UTC noon parse keeps the name off the local timezone, which would slide a
            // date across midnight and mislabel exactly the weekend rows that matter.
            const wd = new Date(d.date + 'T12:00:00Z').getUTCDay();
            const we = (wd === 0 || wd === 6) ? ' we' : '';
            return `<button class="ab-day${dim}" onclick="abPickDay(${i})"` +
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

    // Figures that ARRIVE in billions stay in billions: abUSD compacts raw dollars, and
    // pushing $487.7B through it loses the tenth the denominator is quoted to.
    function abB(v) { return v == null ? '—' : '$' + Number(v).toFixed(1) + 'B'; }

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

    // THE FRACTION, DRAWN. Two pies whose AREAS are the two sides, so the reading is the
    // picture rather than a caption on it: radius scales as sqrt(value), which makes the
    // small pie's area exactly the ratio of the big one's. At 0.25 that is a half-radius
    // circle, and "a quarter of the spend is covered" is legible before a number is read.
    //
    // Area is a weak channel for judging exact magnitude, so every slice carries its own
    // percentage and the summary lists below repeat the dollars. The pies carry the SHAPE
    // of the answer; the digits carry its precision.
    //
    // COLOUR, AND WHY THE TWO SIDES ARE COLOURED DIFFERENTLY. Hue is doing a job on the
    // left and no job at all on the right, so it is spent on the left only:
    //   * the numerator is FOUR DIFFERENT COMPANIES -- identity, which is what
    //     categorical colour is for. These four steps validate as a set against this
    //     panel's own surface (#0f172a), all pairs, worst normal-vision dE 19.3 against a
    //     floor of 15. The worst CVD pair (yellow/green, dE 6.9) sits in the band that is
    //     legal ONLY with secondary encoding -- hence the per-slice labels, the 2px
    //     surface gaps between slices, and the swatched legend below. Do not drop those.
    //   * the denominator has NO identities to separate: it is one measured quantity and
    //     one remainder the share implies. That is a difference of EPISTEMIC STATUS, and
    //     texture encodes it honestly where a second hue would invent a second entity.
    //     It stays in the board's silicon steel, one step brighter for contrast.
    // A fifth saturated hue was tried and abandoned: no step in the palette clears the
    // normal-vision floor against all four numerator hues (orange collides with yellow at
    // 10.6, violet with blue at 9.8, aqua with green at 11.9). Faceting -- two separate
    // circles, separately captioned -- is the sanctioned answer, and is what this is.
    // The hues are the USER'S, chosen by brand association (2026-08-28): OpenAI slate,
    // Anthropic burnt orange, Copilot pink, Gemini iceberg blue, NVIDIA its own green.
    // Each was STEPPED -- not replaced -- until the set separated: the first cut of slate
    // and iceberg blue were both blue-greys and failed at dE 5.7 normal-vision against a
    // floor of 15, so the slate went deeper and the ice went paler until the pair sat
    // apart on LIGHTNESS, the sturdiest channel there is. As shipped the set clears both
    // separation gates on this panel's surface, all pairs: normal-vision worst 17.3, CVD
    // worst 9.8. It sits outside the reference palette's lightness band and chroma floor,
    // which is what asking for a slate and an ice-blue MEANS -- low chroma is the colour,
    // not a defect -- and contrast against the surface passes on every one.
    //
    // (Briefly reverted to the board's own validated four on 2026-08-28 and put straight
    // back: that revert was a misread of a request to recover an earlier VIEW, not a
    // request to change colour. The set it fell back to, if ever wanted, was
    // ['#3987e5', '#008300', '#c98500', '#d55181'] + steel '#7d94b0'.)
    const AB_PIE_HUES = ['#6b7f94', '#c4623c', '#f28fb8', '#a8dced'];  // fixed per entity
    const AB_PIE_NVDA = '#76b900';       // NVIDIA's own green
    // The remainder is nobody's colour. It is the one thing on the panel that no source
    // published, so it wears no company hue and no solid fill at all -- a neutral hatch,
    // which is also the only textured mark on the board and therefore unmistakable.
    const AB_PIE_GHOST = '#8b98a8';
    const AB_PIE_SURFACE = '#0f172a';    // the 2px gap between slices IS the surface

    // Label ink per slice, by measured contrast rather than a lightness guess: NVIDIA's
    // green and the iceberg blue both take DARK text, the slate takes light, and picking
    // one ink for all of them would lose a label on some slice whichever way it went.
    function abInkOn(hex) {
        const c = [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16) / 255)
            .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
        const L = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
        return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? '#0b1220' : '#f8fafc';
    }

    // One pie, labelled. Slices start at twelve o'clock and run clockwise. A lone 100%
    // slice is drawn as a CIRCLE: a 360 degree arc has identical start and end points and
    // collapses to nothing, which is the classic way a pie renderer draws an empty pane.
    function abPie(cx, cy, r, slices, total) {
        if (!total) return '';
        let a0 = -Math.PI / 2, arcs = '', labels = '';
        const out = [];               // slices too thin to hold their own label
        slices.forEach(function (s) {
            const frac = s.value / total, a1 = a0 + frac * Math.PI * 2;
            const P = a => (cx + r * Math.cos(a)).toFixed(2) + ',' + (cy + r * Math.sin(a)).toFixed(2);
            arcs += slices.length === 1
                ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${s.fill}"${s.extra || ''}>` +
                  `<title>${esc(s.title)}</title></circle>`
                : `<path d="M${cx},${cy} L${P(a0)} A${r},${r} 0 ${(a1 - a0) > Math.PI ? 1 : 0},1 ${P(a1)} Z" ` +
                  `fill="${s.fill}" stroke="${AB_PIE_SURFACE}" stroke-width="2"${s.extra || ''}>` +
                  `<title>${esc(s.title)}</title></path>`;
            // A label goes INSIDE only while the slice can actually HOLD it. Measured,
            // not guessed at a percentage threshold: the arc the label would sit on is
            // frac x 2*pi*r*0.62, and a "10%" glyph run is about 18px wide. A fixed
            // "inside above 10%" rule spills the label across its own slice edge on the
            // smaller pie and holds it comfortably on the larger one -- the same
            // percentage is a different amount of room in each circle.
            const mid = (a0 + a1) / 2, pct = Math.round(frac * 100);
            const txt = frac * 100 < 1 ? '<1%' : pct + '%';
            if (frac * 2 * Math.PI * r * 0.62 >= txt.length * 6.2 + 6) {
                labels += `<text x="${(cx + r * 0.62 * Math.cos(mid)).toFixed(1)}" ` +
                          `y="${(cy + r * 0.62 * Math.sin(mid) + 3.5).toFixed(1)}" ` +
                          `class="ab-pie-in" fill="${abInkOn(s.ink || s.fill)}">${txt}</text>`;
            } else if (frac > 0) {
                // Parked for a de-collision pass: two thin slices next to each other put
                // their leaders within a few px of one another, and the labels that exist
                // precisely to identify the smallest slices are the ones that would end
                // up on top of each other.
                out.push({ mid: mid, txt: txt, y: cy + (r + 13) * Math.sin(mid),
                           right: Math.cos(mid) >= 0 });
            }
            a0 = a1;
        });
        // Push stacked outside labels apart along Y, in place, keeping their order. The
        // leader still starts on the slice's own edge, so a nudged label stays visibly
        // tied to the wedge it names.
        ['left', 'right'].forEach(function (side) {
            const col = out.filter(o => (side === 'right') === o.right).sort((a, b) => a.y - b.y);
            for (let i = 1; i < col.length; i++) {
                if (col[i].y - col[i - 1].y < 12) col[i].y = col[i - 1].y + 12;
            }
        });
        out.forEach(function (o) {
            const x1 = cx + (r + 3) * Math.cos(o.mid), y1 = cy + (r + 3) * Math.sin(o.mid);
            const x2 = cx + (r + 13) * Math.cos(o.mid);
            labels += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" ` +
                      `y2="${o.y.toFixed(1)}" class="ab-pie-lead"/>` +
                      `<text x="${(x2 + (o.right ? 3 : -3)).toFixed(1)}" y="${(o.y + 3).toFixed(1)}" ` +
                      `class="ab-pie-out" text-anchor="${o.right ? 'start' : 'end'}">${o.txt}</text>`;
        });
        return arcs + labels;
    }

    function abFractionPieSVG(day) {
        const parts = day.num_parts || [];
        // The denominator is NOT a sum of measured parts -- it is NVIDIA's own run rate
        // grossed up by its share, so the only honest two slices are the measured one and
        // the remainder that grossing up IMPLIES. Derived here from fields every recorded
        // row already carries, so it draws for periods captured before this view existed.
        const nvda = (day.dc_qtr_b || 0) * 4;
        const rest = Math.max(0, (day.den_b || 0) - nvda);
        if (!parts.length || !day.den_b) return '';

        const R = 62, r = R * Math.sqrt((day.num_b || 0) / day.den_b);
        const W = 340, H = 196, cy = 84, cx1 = 86, cx2 = 254;
        const numSlices = parts.map((m, i) => ({
            value: m.value_b, fill: AB_PIE_HUES[i % AB_PIE_HUES.length],
            title: `${m.name} - ${abB(m.value_b)} (${m.share.toFixed(1)}%)`
        }));
        const denSlices = [
            { value: nvda, fill: AB_PIE_NVDA,
              title: `NVIDIA - ${abB(nvda)} (${Math.round((day.accel_share || 0) * 100)}%), measured` },
            // `ink` because the fill is a pattern, and a pattern reference cannot be
            // measured for contrast -- the hatch's own colour is what the label sits over.
            { value: rest, fill: 'url(#abHatch)', ink: AB_PIE_GHOST,
              title: `Everyone else - ${abB(rest)}, implied by the share, not measured` }
        ].filter(s => s.value > 0);

        const cap = (x, t, v) =>
            `<text x="${x}" y="${cy + R + 26}" class="ab-pie-c">${esc(t)}</text>` +
            `<text x="${x}" y="${cy + R + 41}" class="ab-pie-v">${esc(v)}</text>`;

        // THE READING, AT READING SIZE. The pies show the SHAPE of the answer and the
        // lists show its parts, but the one number the panel exists to report was only
        // ever available at 11px in the substrip. It sits top-right of the band, in the
        // sans rather than the panel's mono: a hero figure takes proportional digits,
        // because tabular ones give every digit the width of a zero and read loose at
        // display size. One per view -- the substrip's copy is a stat-strip entry, not a
        // second hero competing with this.
        const band = ((AB_WHY.silicon_payback || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">reading</span>' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.ratio.toFixed(2)}</span>` +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `${band.range ? `<span class="r">band ${esc(band.range)}</span>` : ''}` +
            '</div>';

        // Hero FIRST in the flow, so it lands upper-LEFT of the band (user, 2026-08-28)
        // and the eye takes the answer before the arithmetic that produced it.
        return '<div class="ab-pies">' + hero +
          `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Services revenue ` +
          `${abB(day.num_b)} against industry GPU spend ${abB(day.den_b)}, drawn to area: ` +
          `the smaller circle is ${Math.round((day.ratio || 0) * 100)} percent of the larger">` +
            '<defs><pattern id="abHatch" width="5" height="5" patternUnits="userSpaceOnUse" ' +
              'patternTransform="rotate(45)">' +
              `<rect width="5" height="5" fill="rgba(139,152,168,.16)"/>` +
              `<line x1="0" y1="0" x2="0" y2="5" stroke="${AB_PIE_GHOST}" stroke-width="1.5"/>` +
            '</pattern></defs>' +
            abPie(cx1, cy, r, numSlices, day.num_b) +
            abPie(cx2, cy, R, denSlices, day.den_b) +
            `<text x="${(cx1 + cx2) / 2}" y="${cy + 9}" class="ab-pie-op">/</text>` +
            cap(cx1, 'services revenue', abB(day.num_b)) +
            cap(cx2, 'industry GPU spend', abB(day.den_b)) +
          '</svg></div>';
    }

    // TWO SIDES - the primary view. The pies lead and the lists legend them: every row
    // carries the swatch of its own slice, so identity is never colour alone and the
    // dollars sit in text ink rather than wearing the series hue.
    function abSidesHTML(day, oldest) {
        const parts = day.num_parts || [];
        if (!parts.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this period</div>';
        const row = (sw, name, fig, alt) =>
            '<div class="ab-lrow">' +
              (sw ? `<span class="ab-sw" style="background:${sw}"></span>`
                  : '<span class="ab-sw ab-sw-h"></span>') +
              `<span class="nm2">${esc(name)}</span>` +
              `<span class="fig"><b>${fig}</b>` +
              `${alt ? ` <span class="alt">${esc(alt)}</span>` : ''}</span></div>`;
        const left = parts.map((m, i) =>
            row(AB_PIE_HUES[i % AB_PIE_HUES.length], m.name, abB(m.value_b),
                m.share.toFixed(1) + '%')).join('');
        const nvda = (day.dc_qtr_b || 0) * 4;
        const rest = Math.max(0, (day.den_b || 0) - nvda);
        const pct = x => day.den_b ? (x / day.den_b * 100).toFixed(1) + '%' : '';
        const right = row(AB_PIE_NVDA, 'NVIDIA', abB(nvda), pct(nvda)) +
            (rest > 0 ? row(null, 'Everyone else - implied', abB(rest), pct(rest)) : '');
        // Only against a period the ledger actually holds. On the first print there is
        // nothing to compare to, and the sentence then says the reading alone rather than
        // inventing a move.
        const moved = oldest && oldest.date !== day.date;
        const dir = !moved ? ''
            : day.ratio > oldest.ratio ? ' - converging, which cuts against the thesis'
            : day.ratio < oldest.ratio ? ' - widening, which supports it'
            : ' - flat';
        const then = moved
            ? ` <span class="ago">was <b>${oldest.ratio.toFixed(2)}</b> on ${esc(abMD(oldest.date))}</span>` : '';
        return abFractionPieSVG(day) +
            '<div class="ab-lenses ab-sides">' +
            '<div class="ab-lens money"><div class="lens-hd"><div class="t">What the services earn</div>' +
              `<div class="s">${parts.length} lines &middot; ${abB(day.num_b)} run rate</div></div>` +
              left + '</div>' +
            '<div class="ab-lens vol"><div class="lens-hd"><div class="t">What the silicon cost</div>' +
              `<div class="s">${esc(day.quarter || 'latest quarter')}</div></div>` + right + '</div>' +
            '</div>' +
            `<div class="ab-overlapbar"><b>${Math.round(day.ratio * 100)}&cent;</b> of every dollar of ` +
            `industry GPU spend is matched by services revenue${dir}.${then}</div>`;
    }

    // SOURCES - where every input came from and when it was pulled, which is the only way
    // to judge whether a reading is stale or thin. Six sourced inputs; the x4 and the
    // division are DERIVATIONS, not sources, and are named at the foot rather than given
    // rows that would imply somebody published them.
    function abSourcesHTML(day, method) {
        const parts = day.num_parts || [], build = day.den_build || [];
        if (!parts.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this period</div>';
        const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; } };
        const dc = build[0] || {}, sh = build[build.length - 1] || {};
        // Age against the DAY, not against today: a period recorded in July should not
        // look staler every time the panel is opened.
        const ageOf = d => {
            if (!d || !day.date) return null;
            const ms = Date.parse(day.date + 'T00:00:00Z') - Date.parse(d + 'T00:00:00Z');
            return isNaN(ms) ? null : Math.round(ms / 86400000);
        };
        const rows = [].concat(
            parts.map((m, i) => ({ sw: AB_PIE_HUES[i % AB_PIE_HUES.length], name: m.name,
                                   val: abB(m.value_b), src: m, side: 'services' })),
            [{ sw: AB_PIE_NVDA, name: 'NVDA data-centre revenue', val: abB(day.dc_qtr_b),
               src: dc, side: 'silicon' },
             { sw: AB_PIE_NVDA, name: 'NVDA share of the market',
               val: (day.accel_share != null ? day.accel_share.toFixed(2) : '—'),
               src: sh, side: 'silicon' }]);
        const body = rows.map(r => {
            const s = r.src || {};
            // PUBLISHED is the staleness signal; PULLED only says when we last looked.
            // Keeping both is the whole point: a pull dated today off a years-old
            // market-sizing press release looks identical to one off this week's
            // research if only the pull date is shown.
            const pAge = ageOf(s.published_at);
            const pub = s.published_at
                ? `${esc(s.published_at)}<span class="age">${pAge === null ? '' :
                    pAge <= 0 ? '' : ' &middot; ' + pAge + 'd old'}</span>`
                // Muted, not red: the earnings-fed legs pin a named quarter instead and
                // are not expected to carry one. Red is reserved for a MISSING PULL date,
                // which is the figure nobody can age-check at all.
                : '<span class="sl">not stated</span>';
            const age = ageOf(s.refreshed_at);
            const when = s.refreshed_at
                ? `${esc(s.refreshed_at)}<span class="age">${age === null ? '' :
                    age <= 0 ? ' same day' : ' &middot; ' + age + 'd before'}</span>`
                : '<span class="ab-fc-err">not recorded</span>';
            const who = s.source
                ? esc(s.source)
                : (s.url ? esc(host(s.url)) : '<span class="ab-fc-err">unattributed</span>');
            return '<tr>' +
              `<td class="rk"><span class="ab-sw" style="background:${r.sw}"></span></td>` +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(r.name)}` +
                `${s.soft ? '<span class="tier c" style="margin-left:7px">estimated</span>' : ''}</div>` +
                `<div class="sl">${who}</div></div></td>` +
              `<td class="l"><div class="revcell"><span class="amt">${r.val}</span></div></td>` +
              `<td class="l"><span class="pulled">${pub}</span></td>` +
              `<td class="l"><span class="pulled">${when}</span></td>` +
              `<td class="l">${s.url ? `<a class="ab-src-a" href="${esc(s.url)}" target="_blank" ` +
                `rel="noopener noreferrer">open</a>` : '<span class="sl">&mdash;</span>'}</td>` +
            '</tr>';
        }).join('');
        return '<div class="ab-scroller"><table class="ab-ledger ab-sources">' +
            '<thead><tr><th class="l" colspan="2">Input</th><th class="l">Value</th>' +
            '<th class="l">Published</th><th class="l">Pulled</th>' +
            '<th class="l">Link</th></tr></thead>' +
            `<tbody>${body}</tbody></table>` +
            // The short note first, because it is about THIS TABLE — it says why two of
            // the arithmetic's steps have no row. The full method follows it: same
            // subject, one level out, and the natural place to keep reading.
            '<div class="ab-srcfoot">The run rate and the gross-up are <b>derivations, not ' +
            'sources</b>: the quarter above is multiplied by 4 and divided by the share, ' +
            'so neither has a publisher or a date of its own.</div>' +
            (method ? `<div class="ab-srcmethod"><span class="k">Method</span>` +
                      `<div class="b">${method}</div></div>` : '') +
            '</div>';
    }

    // FIVE PIPS — the reading drawn as the thing it literally says: how many of the last
    // five revisions went DOWN. A count of five has no distribution worth a chart, so the
    // honest picture is the count itself against its own denominator — filled pips are the
    // downgrades, hollow ones the rest of the five. They take the day's light through
    // currentColor, the same way the sparkline does, so a rail click retints them.
    //
    // TWO SVGs, NOT ONE (2026-08-29). This was a single drawing scaled as a unit, and a
    // unit can only be pinned to one edge: capped at 520px it left the slack on the
    // right of a wider pane, and uncapping it would have scaled the whole band up with
    // the row (a 900px row is a 225px-tall picture). So the pips own the left, the bird
    // owns the right, and the flex gap between them absorbs whatever the row has spare.
    // Both are rendered at the same HEIGHT and let their widths follow, which is what
    // keeps the two coordinate spaces on one scale — y=46 is the same pixel in each, so
    // the lamp still lines up with the pips it is pointed at.
    const AB_PIP_CY = 46;
    function abPipsSVG(down, of, lc) {
        const W = 300, H = 140, R = 20, GAP = 58, X0 = 28;
        let pips = '';
        for (let i = 0; i < of; i++) {
            pips += i < down
                ? `<circle cx="${X0 + i * GAP}" cy="${AB_PIP_CY}" r="${R}" fill="currentColor"/>`
                : `<circle cx="${X0 + i * GAP}" cy="${AB_PIP_CY}" r="${R - 1}" fill="none" ` +
                  `stroke="#334155" stroke-width="2"/>`;
        }
        return `<svg class="abh-${lc} ab-pips" viewBox="0 0 ${W} ${H}" role="img" ` +
            `aria-label="${down} of the last ${of} pooled revisions were downward">` +
            pips +
            `<text x="${X0 + (of - 1) * GAP / 2}" y="104" class="ab-pie-c">${down} of the ` +
            `last ${of} pooled revisions went down</text></svg>`;
    }

    // THE CANARY, AND ITS LAMP. Decorative and marked so: the pips carry the reading and
    // its label, and a screen reader has no use for the bird.
    //
    // It is DELIBERATELY not data — hardcoded canary yellow whatever the light says,
    // because a bird that turned red on a red day would read as a sixth pip. What it is
    // for is the mnemonic: the factor's name and its job in one mark, above a table of
    // revision counts (user, 2026-08-29 — "the optics are not the point").
    //
    // Draw order is body -> face -> helmet, and the helmet sits ABOVE the eye and beak
    // rather than over them; the first cut put the brim across both and the bird lost its
    // face. Size and position are the two constants at the top, so moving or resizing it
    // never means re-numbering the paths. The beam dies inside this box rather than
    // reaching the pips, since the gap between them is now elastic and nothing can be
    // drawn across it.
    function abCanarySVG() {
        const W = 240, H = 140, BS = 1.05, BX = -242.8, BY = 5.05;
        const LAMP_X = 108, FADE_X = 6;
        const beam =
            '<defs><linearGradient id="abBeam" gradientUnits="userSpaceOnUse" ' +
              `x1="${LAMP_X}" y1="0" x2="${FADE_X}" y2="0">` +
              '<stop offset="0" stop-color="#ffe9ab" stop-opacity=".44"/>' +
              '<stop offset=".55" stop-color="#f0a020" stop-opacity=".20"/>' +
              '<stop offset="1" stop-color="#f0a020" stop-opacity="0"/>' +
            '</linearGradient></defs>' +
            `<polygon points="${LAMP_X},${AB_PIP_CY} ${FADE_X},14 ${FADE_X},82" ` +
              'fill="url(#abBeam)"/>' +
            `<polygon points="${LAMP_X},${AB_PIP_CY} ${FADE_X},28 ${FADE_X},66" ` +
              'fill="url(#abBeam)"/>';
        return `<svg class="ab-canary" viewBox="0 0 ${W} ${H}" aria-hidden="true" ` +
            'focusable="false">' + beam +
            `<g transform="translate(${BX},${BY}) scale(${BS})">` +
              '<path d="M416 74 C 436 62 444 56 452 48 C 448 64 440 74 430 82 Z" fill="#d9a028"/>' +
              '<path d="M418 88 C 440 82 450 76 456 70 C 448 86 436 94 422 98 Z" fill="#e5ae2e"/>' +
              '<ellipse cx="386" cy="90" rx="40" ry="34" fill="#f0c23a"/>' +
              '<ellipse cx="378" cy="98" rx="28" ry="25" fill="#f7d971"/>' +
              '<path d="M400 76 C 380 86 374 108 384 122 C 400 128 416 118 422 102 ' +
                'C 424 88 416 78 400 76 Z" fill="#dea62b"/>' +
              '<circle cx="366" cy="56" r="27" fill="#f0c23a"/>' +
              '<circle cx="376" cy="66" r="17" fill="#f7d971"/>' +
              '<path d="M332 63 L 354 56 L 354 70 Z" fill="#e8863c"/>' +
              '<path d="M332 63 L 354 63 L 354 70 Z" fill="#cf6f2c"/>' +
              '<circle cx="356" cy="55" r="4.2" fill="#3f2d13"/>' +
              '<circle cx="357.5" cy="53.5" r="1.5" fill="#ffffff"/>' +
              '<path d="M338 42 A 28 28 0 0 1 394 42 Z" fill="#b8462a"/>' +
              '<path d="M352 19 A 28 28 0 0 1 368 17 L 365 42 L 353 42 Z" ' +
                'fill="#c9573a" opacity=".7"/>' +
              '<ellipse cx="366" cy="43" rx="36" ry="6" fill="#a03c22"/>' +
              '<ellipse cx="366" cy="41" rx="36" ry="5.5" fill="#c14e2e"/>' +
              '<circle cx="334" cy="39" r="9" fill="#8f3520"/>' +
              '<circle cx="334" cy="39" r="6" fill="#e8b64a"/>' +
              '<circle cx="334" cy="39" r="3.6" fill="#fff2c6"/>' +
            '</g></svg>';
    }

    // REVISIONS — the primary view: who filed the revisions this reading is made of.
    // The basket is two names by definition, so this is not a top-N of a longer list; it
    // is the COMPLETE evidence, which is what lets it carry the two columns a pooled
    // figure hides. ALONE is what each name would read on its own, WEIGHT is how much of
    // the pool it supplies, and together they answer whether the pooled light is actually
    // pooled or one name's read wearing both names' label.
    function abRevisionsHTML(day, oldest) {
        const names = day.names || [];
        if (!names.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this day</div>';
        const c = AB_LC[day.light] || 'y';
        const band = ((AB_WHY.memory_canary || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">reading</span>' +
              `<span class="v abh-${c}">${day.downs}/5</span>` +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `${band.range ? `<span class="r">band ${esc(band.range)}</span>` : ''}` +
            '</div>';
        // The down SHARE is what the light is computed from, so it gets the bar; the raw
        // pair beside it keeps the COUNT visible, because a share of three revisions and
        // a share of twenty are not the same evidence.
        const bar = pct => '<span class="bar"><i class="p" style="width:' +
            Math.max(2, Math.min(100, Math.round(pct))) + '%"></i></span>';
        const body = names.map(n => {
            const nc = AB_LC[n.alone_light] || 'y';
            return '<tr>' +
              '<td class="l" colspan="2"><div class="mdl">' +
                `<div class="nm2">${esc(n.name)}</div><div class="sl">${esc(n.role)}` +
                // Per NAME, not only in the strip: the two fiscal calendars can put the
                // same horizon under different labels, and when they do this row is the
                // only place on the panel that shows it.
                `${(n.periods || []).length ? ' · ' + esc(n.periods.join(' · ')) : ''}` +
                '</div></div></td>' +
              `<td>${n.up}</td><td>${n.down}</td>` +
              '<td class="l"><div class="revcell">' +
                `<span class="pct">${n.share.toFixed(1)}%</span>${bar(n.share)}` +
                `<span class="amt">${n.down}/${n.total}</span></div></td>` +
              `<td class="l"><span class="tier c">${Math.round(n.weight)}% of pool</span></td>` +
              `<td class="abh-${nc}">${n.alone}/5</td>` +
            '</tr>';
        }).join('');
        const sum = '<tr class="sum">' +
            '<td class="l" colspan="2"><div class="mdl"><div class="nm2">Pooled</div>' +
              '<div class="sl">both names, unweighted</div></div></td>' +
            `<td>${day.pool_up}</td><td>${day.pool_down}</td>` +
            '<td class="l"><div class="revcell">' +
              `<span class="pct">${day.share.toFixed(1)}%</span>${bar(day.share)}` +
              `<span class="amt">${day.pool_down}/${day.pool_total}</span></div></td>` +
            `<td class="l"><span class="tier p">${esc(day.window)} window</span></td>` +
            `<td class="abh-${c}">${day.downs}/5</td></tr>`;
        // The sentence is the point, as it is on the other two factors: a number alone
        // reads as a stat, and what this one says is whether the basket did its job on
        // this day. Computed, never asserted — which name leads changes over the history
        // (MU filed 106 of 114 revisions in July; SK Hynix files 20 of 23 now).
        const lead = names.slice().sort((a, b) => b.weight - a.weight)[0];
        const spread = names.length > 1 ? Math.abs(names[0].weight - names[1].weight) : 0;
        const owns = lead && lead.weight >= 65
            ? `<b>${esc(lead.name)}</b> files ${lead.total} of the ${day.pool_total} revisions ` +
              `in this window, so the pooled reading is ${Math.round(lead.weight)}% its own.`
            : `The two names are within ${Math.round(spread)} points of each other on count, ` +
              'so the pool reads both.';
        const then = oldest && oldest.date !== day.date
            ? ` <span class="ago">was <b>${oldest.downs}/5</b> on ${esc(abMD(oldest.date))}</span>` : '';
        return '<div class="ab-pies">' + hero +
            '<div class="ab-band">' + abPipsSVG(day.downs, 5, c) + abCanarySVG() + '</div>' +
            '</div>' +
            '<div class="ab-scroller"><table class="ab-ledger">' +
            '<thead><tr><th class="l" colspan="2">Name</th><th>Up</th><th>Down</th>' +
            '<th class="l">Down share</th><th class="l">Weight</th><th>Alone</th></tr></thead>' +
            `<tbody>${body}${sum}</tbody></table></div>` +
            `<div class="ab-overlapbar">${owns}${then}</div>`;
    }

    // BOTH WINDOWS — the same day read on each of the two windows the feed publishes.
    // The rule takes the 7-day count whenever it holds five revisions and falls back to
    // the 30-day one when it does not, so the reading can change band on WHICH WINDOW
    // QUALIFIED rather than on anything an analyst did. Showing both is showing that.
    // Gold marks the window the light was taken on and steel the counterfactual — the
    // same job the pair does on premium_share's lenses: separating the numbers that are
    // load-bearing from the ones quoted beside them.
    function abWindowsHTML(day, oldest) {
        const wins = day.windows || [];
        if (!wins.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this day</div>';
        const row = (k, fig, on) => `<div class="ab-lrow${on ? ' both' : ''}">` +
            `<span class="nm2">${esc(k)}</span><span class="fig">${fig}</span></div>`;
        const lens = w => {
            const lc = AB_LC[w.light] || 'y';
            const sub = w.used ? 'the reading is taken here'
                : (w.thin ? 'thinner than 5 revisions' : 'not used');
            return `<div class="ab-lens ${w.used ? 'money' : 'vol'}">` +
              '<div class="lens-hd"><div class="t">' +
                esc(w.label.charAt(0).toUpperCase() + w.label.slice(1)) + '</div>' +
                `<div class="s">${w.total} revisions &middot; ${sub}</div></div>` +
              row('Downward', `<b>${w.down}</b>`) +
              row('Upward', `<b>${w.up}</b>`) +
              row('Down share', `<b>${w.share.toFixed(1)}%</b>`) +
              row('Rounds to', `<b class="abh-${lc}">${w.downs}/5</b> ` +
                              `<span class="alt">${esc(w.light)}</span>`, w.used) +
            '</div>';
        };
        const sel = wins.find(w => w.used) || wins[0];
        const other = wins.find(w => w !== sel);
        // The lens HEADING names the window the feed's own way ("last 7 days"); the
        // sentence needs it as an adjective, and "the last 30 days window" does not read.
        const shortL = w => (w.key === '7d' ? '7-day' : '30-day');
        const why = sel.key === '7d' ? 'because it holds at least 5 revisions'
                                     : 'because the 7-day window held fewer than 5';
        const msg = !other
            ? `Read on the ${shortL(sel)} window.`
            : other.light === sel.light
                ? `Both windows land on <b>${esc(sel.light)}</b>, so this reading does not ` +
                  'depend on which one qualified.'
                : `The rule takes the <b>${shortL(sel)}</b> window ${why}; the ` +
                  `${shortL(other)} window would read <b>${other.downs}/5</b> — ` +
                  `${esc(other.light)}.`;
        const then = oldest && oldest.date !== day.date
            ? ` <span class="ago">was <b>${oldest.downs}/5</b> on ${esc(abMD(oldest.date))}</span>` : '';
        return '<div class="ab-lenses">' + wins.map(lens).join('') + '</div>' +
            `<div class="ab-overlapbar">${msg}${then}</div>`;
    }

    // WHICH STATES, DRAWN — the question this factor answers is how much of the map is
    // covered, so the map is the picture. Outlines are pre-projected at build time
    // (`static/js/us-map.js`, generated by scratchpad/gen_us_map.py from MIT-licensed
    // Census-derived TopoJSON), which keeps the runtime to fills: no projection maths,
    // no library, no dependency. Alaska and Hawaii are inset bottom-left at their own
    // scales, Alaska at a size you can actually read (user, 2026-08-29).
    //
    // COLOUR CARRIES THE INSTRUMENT, not the light. Two reasons it can: the band colour
    // is already spoken for on this board, and WHICH BRANCH ACTED is the fact this
    // factor was rebuilt to see — the rule it replaced could only count statutes. The
    // three hues were picked by running the dataviz validator against this panel's own
    // surface (#0f172a), all pairs, and they pass every check: lightness band, chroma
    // floor, CVD separation (worst ΔE 8.2 deutan, above the 8.0 target), normal-vision
    // separation (worst 18.5 against a floor of 15) and contrast. Do not substitute by
    // eye — blue/violet pairs that look fine read as ΔE 0.5 apart under deuteranopia.
    // None of the three can be mistaken for red, yellow or green.
    const AB_INSTRUMENT = {
        statute:         { hue: '#6366f1', label: 'statute' },
        executive_order: { hue: '#ec4899', label: 'executive order' },
        commission_rule: { hue: '#0e9fbf', label: 'commission rule' }
    };
    const AB_MAP_EMPTY = '#182235';       // a state with nothing in force
    const AB_MAP_LINE  = '#334155';

    function abUSMapSVG(actions) {
        if (typeof US_MAP === 'undefined') return '';
        // A state can hold more than one instrument (Texas has SB 6 and the governor's
        // audit order). The FILL takes the earliest one in force — the standing rule
        // rather than the newest headline — and a dot marks that there is more than
        // one, because a single fill cannot say "two" and inventing a blended hue would
        // say something false. The roster table below names both.
        const by = {};
        (actions || []).filter(a => a.in_force).forEach(a => {
            (by[a.state] = by[a.state] || []).push(a);
        });
        const shapes = Object.keys(US_MAP.paths).map(name => {
            const list = (by[name] || []).slice()
                .sort((x, y) => (x.effective_date || '').localeCompare(y.effective_date || ''));
            const hue = list.length
                ? (AB_INSTRUMENT[list[0].instrument_type] || {}).hue || AB_MAP_EMPTY
                : AB_MAP_EMPTY;
            const title = list.length
                ? `${name} — ` + list.map(a => `${a.citation} (${(AB_INSTRUMENT[a.instrument_type]
                    || {}).label || a.instrument_type})`).join('; ')
                : `${name} — nothing in force`;
            return `<path d="${US_MAP.paths[name]}" fill="${hue}" stroke="${AB_MAP_LINE}" ` +
                   `stroke-width="0.6"><title>${esc(title)}</title></path>`;
        }).join('');
        // The multi-instrument dot, placed on the shape's own bounding-box centre so it
        // needs no extra data. Ringed in the surface colour so it reads on any fill.
        const dots = Object.keys(by).filter(n => by[n].length > 1 && US_MAP.paths[n])
            .map(n => {
                const nums = US_MAP.paths[n].match(/-?\d+\.?\d*/g).map(Number);
                const xs = nums.filter((_, i) => i % 2 === 0);
                const ys = nums.filter((_, i) => i % 2 === 1);
                const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
                const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
                return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3.4" ` +
                       `fill="#f8fafc" stroke="#0f172a" stroke-width="1.2"><title>` +
                       `${esc(n)} — ${by[n].length} instruments in force</title></circle>`;
            }).join('');
        return `<svg viewBox="0 0 ${US_MAP.w} ${US_MAP.h}" role="img" ` +
            `aria-label="US map: ${Object.keys(by).length} states with an action in ` +
            `force, shaded by which branch acted">${shapes}${dots}</svg>`;
    }

    // Identity is never colour alone: the legend names each hue, and every state on the
    // map appears in the roster table underneath with its instrument spelled out.
    function abMapLegendHTML(byBranch) {
        const on = Object.keys(AB_INSTRUMENT).filter(k => (byBranch || {})[k]);
        if (!on.length) return '';
        return '<div class="ab-maplegend">' + on.map(k =>
            `<span><i style="background:${AB_INSTRUMENT[k].hue}"></i>` +
            `${esc(AB_INSTRUMENT[k].label)} <b>${byBranch[k]}</b></span>`).join('') +
            '<span><i class="ab-sw-h" style="border-radius:2px"></i>nothing in force</span>' +
            '</div>';
    }

    // ROSTER — the primary view: every action the light counts, oldest first, so the
    // column reads as the movement arriving rather than as an alphabetical list. The
    // INSTRUMENT column is the point of the 2026-08-29 rebuild and earns its width: the
    // rule it replaced could only see statutes, and two of these are executive orders.
    function abRosterHTML(day) {
        const rows = (day.actions || []).filter(a => a.in_force);
        if (!rows.length) return '<div class="ab-tbd" style="padding:12px 13px">no roster for this reading</div>';
        const c = AB_LC[day.light] || 'y';
        const band = ((AB_WHY.regulatory || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">reading</span>' +
              `<span class="v abh-${c}">${day.value}</span>` +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `${band.range ? `<span class="r">band ${esc(band.range)}</span>` : ''}` +
            '</div>';
        const BR = { statute: 'statute', executive_order: 'executive order',
                     commission_rule: 'commission rule' };
        const body = rows.map(a =>
            '<tr>' +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(a.state)}` +
                `${a.temporary ? '<span class="tier c" style="margin-left:7px">temporary</span>' : ''}` +
                `</div><div class="sl">${esc(a.citation || '')}</div></div></td>` +
              `<td class="l"><span class="tier ${a.instrument_type === 'statute' ? 'c' : 'p'}">` +
                `${esc(BR[a.instrument_type] || a.instrument_type)}</span></td>` +
              `<td class="l"><span class="pulled">${esc(a.effective_date || '—')}</span></td>` +
              `<td>${a.threshold_mw != null ? a.threshold_mw + ' MW' : '—'}</td>` +
              `<td class="l">${a.url ? `<a class="ab-src-a" href="${esc(a.url)}" ` +
                `target="_blank" rel="noopener noreferrer">source</a>`
                : '<span class="sl">&mdash;</span>'}</td>` +
            '</tr>').join('');
        // Gold marks the instruments the OLD rule could not see. Hue doing a job: the
        // whole reason this factor was rebuilt is that two of these were invisible.
        const nb = day.by_branch || {};
        const mix = Object.keys(nb).map(k => `${nb[k]} ${BR[k] || k}${nb[k] > 1 ? 's' : ''}`)
            .join(' · ');
        const toGo = (day.yellow_at || 10) - day.value;
        return '<div class="ab-pies">' + hero + abUSMapSVG(day.actions) + '</div>' +
            abMapLegendHTML(day.by_branch) +
            '<div class="ab-scroller"><table class="ab-ledger">' +
            '<thead><tr><th class="l">State</th><th class="l">Instrument</th>' +
            '<th class="l">In force</th><th>Threshold</th><th class="l">Link</th></tr></thead>' +
            `<tbody>${body}</tbody></table></div>` +
            `<div class="ab-overlapbar"><b>${day.n_actions}</b> actions across ` +
            `<b>${day.value}</b> states — ${esc(mix)}. ` +
            (toGo > 0 ? `<b>${toGo}</b> more states and this turns yellow.`
                      : 'Past the yellow line.') + '</div>';
    }

    // EXCLUDED — looked at and rejected, with the reason. This half of the evidence is
    // arguably the more useful one: an exclusion that leaves no trace cannot be told
    // apart from an oversight, and two of these were COUNTED as states until the roster
    // was audited on 2026-08-29.
    function abExcludedHTML(day) {
        const rows = day.excluded || [];
        if (!rows.length) return '<div class="ab-tbd" style="padding:12px 13px">nothing recorded as excluded</div>';
        const body = rows.map(e =>
            '<tr>' +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(e.state)}` +
                `${e.was_counted ? '<span class="tier p" style="margin-left:7px">was counted</span>' : ''}` +
                `</div><div class="sl">${esc(e.citation || '')}</div></div></td>` +
              `<td class="l"><span class="ab-why">${esc(e.reason || '')}</span></td>` +
            '</tr>').join('');
        const wc = rows.filter(e => e.was_counted).length;
        return '<div class="ab-scroller"><table class="ab-ledger">' +
            '<thead><tr><th class="l">Measure</th><th class="l">Why it does not count</th>' +
            '</tr></thead>' + `<tbody>${body}</tbody></table></div>` +
            '<div class="ab-overlapbar">' +
            (wc ? `<b>${wc}</b> of these were counted as states until the roster was ` +
                  'audited on 2026-08-29.'
                : 'None of these has ever been counted.') +
            '</div>';
    }

    // THE EVIDENCE VOCABULARY — one entry per factor that keeps a ledger.
    //
    // The chrome above this line knows none of it: the rail, the substrip, the sparkline,
    // the header and the footnotes already run for all 16 factors with no per-factor
    // code. What a factor's EVIDENCE looks like is per-factor by nature (a premium ledger
    // is a priced model table; a payback ledger is the arithmetic of a ratio; a
    // regulatory one would be a case list) and no single renderer serves them — so this
    // is where a factor's own words live, and adding the next one is filling an entry
    // here rather than touching the panel.
    //
    // `tol` is the only entry that is not display: it is how far a re-derived reading may
    // sit from the recorded one before the pane says so, and it has to be per-factor
    // because the units are — 0.05 is a rounding difference on a percentage and most of
    // a band on a ratio that lives between 0.2 and 0.5.
    const AB_VIEWS = {
        premium_share: {
            views:   [{ key: 'ledger', label: 'Ledger' }, { key: 'lenses', label: 'Two lenses' }],
            value:   d => d.share,
            reading: d => d.share.toFixed(1) + '%',
            light:   d => d.light,
            tol:     0.05,
            count:   d => d.n_models + ' models',
            figures: d => [['comm tokens', d.comm_tok + '%'],
                           ['prem line', '$' + d.line],
                           ['est rev', abUSD(d.total_rev)]],
            render:  (key, day, all) => key === 'lenses'
                ? abLensesHTML(day, all[all.length - 1]) : abLedgerHTML(day)
        },
        silicon_payback: {
            // Two sides LEADS (user, 2026-08-28): the pies are what this factor is for,
            // and the first view in the list is the one the panel opens on.
            views:   [{ key: 'sides', label: 'Two sides' }, { key: 'sources', label: 'Sources' }],
            // Method rides in the shared FOOTNOTES, under whichever view is open --
            // reverted 2026-08-28. Claiming it (`method: 'sources'`) moves it inside the
            // Sources view instead; the mechanism is kept because it works, but the
            // footnote is where this factor's prose belongs: it is read under the pies
            // as often as under the table.
            value:   d => d.ratio,
            reading: d => d.ratio.toFixed(2),
            light:   d => d.light,
            tol:     0.005,
            count:   d => ((d.num_parts || []).length + 2) + ' inputs',
            figures: d => [['services', abB(d.num_b)],
                           ['silicon', abB(d.den_b)],
                           ['nvda share', Math.round(d.accel_share * 100) + '%']],
            render:  (key, day, all) => key === 'sources'
                ? abSourcesHTML(day) : abSidesHTML(day, all[all.length - 1])
        },
        memory_canary: {
            // Revisions LEADS: what this factor answers is who is cutting, and the window
            // it was read on is the check you run on that answer.
            views:   [{ key: 'revisions', label: 'Revisions' },
                      { key: 'windows',   label: 'Both windows' }],
            value:   d => d.downs,
            reading: d => d.downs + '/5 dn',
            light:   d => d.light,
            // Half a step. The reading is an INTEGER 0–5, so anything that would round
            // differently is a whole band from being a rounding difference — but this
            // ledger reads the day's own snapshot instead of re-deriving it, so the two
            // cannot drift in the first place.
            tol:     0.5,
            count:   d => d.pool_total + ' revisions',
            // ESTIMATES rides in the strip because it is the day's BASIS, not a detail:
            // '+1q · +1y' and 'all four' are different denominators, and a rail day from
            // before 2026-08-29 must not be read as if it were on today's rule.
            // OBSERVED rides in the strip because the reading's own freshness is not
            // the poll's: this factor polls daily and OBSERVES episodically -- 42
            // snapshot days held ten observations. `stale` in the provenance line
            // counts days since we LOOKED and reads 0 here daily; this counts days
            // since the numbers last MOVED.
            figures: d => [['observed', d.age_days == null ? '—'
                             : (d.age_days === 0 ? 'today' : d.age_days + 'd ago')],
                           ['estimates', d.estimates || 'all four'],
                           ['window', d.window],
                           ['down', String(d.pool_down)]],
            render:  (key, day, all) => key === 'windows'
                ? abWindowsHTML(day, all[all.length - 1])
                : abRevisionsHTML(day, all[all.length - 1])
        },
        regulatory: {
            views:   [{ key: 'roster',   label: 'Roster' },
                      { key: 'excluded', label: 'Excluded' }],
            value:   d => d.value,
            reading: d => d.metric,
            light:   d => d.light,
            // The reading is a COUNT of states, so anything that would round
            // differently is a whole state, not a rounding difference.
            tol:     0.5,
            count:   d => d.n_actions + ' actions',
            figures: d => [['statute', String((d.by_branch || {}).statute || 0)],
                           ['executive', String((d.by_branch || {}).executive_order || 0)],
                           ['commission', String((d.by_branch || {}).commission_rule || 0)],
                           ['excluded', String((d.excluded || []).length)]],
            render:  (key, day) => key === 'excluded'
                ? abExcludedHTML(day) : abRosterHTML(day)
        }
    };

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
        // A ledger day is only usable with a vocabulary to read it by (AB_VIEWS). A
        // factor whose builder grows a ledger() before its entry is written still gets
        // the generic view rather than a pane of undefineds.
        const v = AB_VIEWS[f.id] || null;
        const ledDay = (v && led.find(x => x.date === (d.asof || d.date))) || null;
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
            : (d.value != null && Math.abs(v.value(ledDay) - d.value) >= v.tol))
            ? d : null;
        const rd = ledDay
            ? { metric: v.reading(ledDay), light: v.light(ledDay) }
            : d;
        const c = AB_LC[rd.light] || 'y';
        // The SPARK tints by the day's RECORDED light, not the ledger's re-priced one.
        // The strip plots the recorded series and the rail dot just clicked is the
        // recorded light — on 08-15 recorded red (54.3) re-prices yellow (49.7), and a
        // red click turning the graph yellow read as broken (user, 2026-08-21; they
        // liked the tint and asked for it to be consistent). The Reading keeps the
        // re-priced light: 49.7 painted red would mislabel the number actually shown.
        const sc = AB_LC[d.light] || 'y';

        // --- evidence header: label, what day is on screen, view switcher ---------
        // The switcher renders only when a factor HAS more than one view. 15 of 16 have
        // none — a per-item ledger is something a factor either keeps or does not — and
        // an always-visible switcher over a single view is chrome that promises a
        // second one. `views` is a LIST for the same reason `bands` is: a factor that
        // grows a ledger gets the switcher with no change here.
        const views = ledDay ? v.views : [];
        // _abView is sticky across factors, and the keys are not shared vocabulary —
        // premium_share has 'lenses', silicon_payback has 'sides'. Validate the sticky
        // choice against THIS factor's views so switching factors lands on its first
        // view rather than on a key it has never heard of.
        const view = (views.some(x => x.key === _abView) ? _abView
                      : (views[0] || {}).key) || null;
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
            `${ledDay ? ' · ' + esc(v.count(ledDay)) : ''}` +
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
            ? v.figures(ledDay)
            : Object.keys(ex)
                .filter(k => !skip[k] && ex[k] != null && typeof ex[k] !== 'object')
                .slice(0, 4).map(k => [abHumanKey(k), String(ex[k])]);
        // Prev follows the SAME computation as Reading. Mixing them — a re-priced
        // reading against a recorded previous — would invent a day-over-day move that
        // neither series actually shows.
        const ledPrev = ledDay ? led[led.indexOf(ledDay) + 1] : null;
        const prevTx = ledDay
            ? (ledPrev ? v.reading(ledPrev) : '—')
            : (prior ? (prior.metric || '—') : '—');
        const spark = abSparkSVG(days, sel, sc, (AB_WHY[f.id] || {}).edges);
        const substrip =
            '<div class="ab-substrip">' +
              `<span><span class="k">Reading</span> <b class="abh-${c}">${esc(rd.metric || '—')}</b></span>` +
              fig.map(([k, v]) => `<span><span class="k">${esc(k)}</span> <b>${esc(v)}</b></span>`).join('') +
              `<span><span class="k">Prev</span> <b>${esc(prevTx)}</b></span>` +
              (spark ? '<span class="sp"><span class="k">' + spark.n +
                       ' readings</span>' + spark.svg + '</span>' : '') +
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
        const viewHTML = !ledDay ? generic : v.render(view, ledDay, led);

        const body =
            '<div class="ab-evid">' +
              `<nav class="ab-rail" aria-label="Reading history">` +
              `${abRailHTML(days, sel, led.length ? new Set(led.map(x => x.date)) : null)}</nav>` +
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
        // Method normally rides in the footnotes, under whichever view is open. A factor
        // may CLAIM it instead (`AB_VIEWS[...].method` naming one of its own views), and
        // then the footnote stands down: silicon payback's belongs beside the inputs it
        // describes, in Sources, rather than under the pies it does not. The chrome still
        // knows nothing factor-specific — it asks the vocabulary and does as it is told.
        // `method` is EITHER one prose block or a LIST of {k, b} topics. The list exists
        // because a factor's note can cover several distinct subjects, and one 200-word
        // column is not readable at a glance (user, 2026-08-29). A factor that supplies a
        // string still gets exactly what it got before: one column headed Method. The
        // body is raw HTML in both shapes — it is a literal in this file, never anything
        // a source produced — while the heading is escaped like any other label.
        const method = (w.method && !(v && v.method))
            ? (Array.isArray(w.method) ? w.method : [{ k: 'Method', b: w.method }])
                .map(m => `<div class="ab-fc"><span class="k">${esc(m.k)}</span>` +
                          `<div class="b">${m.b}</div></div>`).join('')
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
                // ASOF beside the value (user, 2026-08-27). Every builder already
                // publishes the REAL print date — `_build_dial` even labels it "the real
                // print date, not the month label" — and none of it reached the screen.
                // That is how a header read 3.71% all day against a live 3.70%: the
                // number was faithfully rendered, its date was not, and the two charts
                // in the same row were a print apart with nothing to say so.
                // A monthly series makes this worse, not better: its x-axis tick says
                // 2026-08-01 whatever day the value is from.
                // AFTER the value, not before it: `.ab-rt-val` already owns the
                // margin-left:auto that pushes the right-hand group over, and a second
                // auto margin would split the free space and strand the date mid-header.
                `<span class="ab-rt-val">${esc((ch.latest && ch.latest.label) || '')}</span>` +
                (ch.asof ? `<span class="ab-rt-asof">${esc(ch.asof)}</span>` : '') + '</div>' +
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
