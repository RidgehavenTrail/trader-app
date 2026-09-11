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
            // A factor flagging its OWN inputs (heavy_haul: a constituent with no price past
            // the carry limit). Server-computed like stale_days; the light still stands, so
            // this is an amber note beside it, not an error state on the row.
            const alert = f.data_alert
                ? `<span class="sl-badge-stale" title="${esc(f.data_alert)}">gap</span>` : '';
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
                `<span class="sl-mt">${metric}</span>` +
                `${cat}${refine}${stale}${alert}</div>`;
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
            // Board charts ride this poll rather than carrying a timer of their own. The
            // pictures move at most once a day; the Fed dial's header moves every poll.
            if (++_chartsTick % SL_CHARTS_EVERY === 0) refreshBoardCharts();
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
        },
        heavy_haul: {
            // Glanceable (user, 2026-08-29). WHICH sixteen, and why equal weight, is the
            // real content — and it is footnote detail, under Basket and Weighting below.
            measures: 'Sixteen freight names that physically move the buildout, equal-weighted, '
                    + 'against their own 50 and 200-bar trend.',
            // Says nothing about which way freight is currently going. The rail, the
            // sparkline and the constituent table all compute the live direction; a
            // direction written into a static definition is asserted, not observed —
            // the session-48 lesson, in the one place on this factor it could recur.
            why: 'Freight is the buildout’s physical leg. Data centres are poured, trucked '
               + 'and railed into place long before they compute, so a freight tape that is '
               + 'still humming says the physical build has not been called off — and one '
               + 'rolling over says it has, whatever the capex slides still promise.',
            // INVERTED, like the board's other supply-side reads: green is freight rolling
            // over (pro-burst), red is humming. The ranges are LADDER STATES, not cuts on
            // one axis — see `edges`.
            bands: [
                { light: 'green',  range: 'below the 200',        mean: 'freight rolling over' },
                { light: 'yellow', range: 'above, both true',     mean: 'distribution top' },
                { light: 'orange', range: 'above, one true',      mean: 'weakening' },
                { light: 'red',    range: 'above, neither',       mean: 'humming' }
            ],
            // ONE edge, and the omission is the honest answer rather than a gap. The
            // sparkline plots this factor's metric, distance from the 200-bar MA, and the
            // only band boundary that lives on that axis is zero — the 200 breach that
            // turns the light green. Yellow, orange and red do not divide on distance from
            // the 200 at all; they divide on the 50 and on bars since the high. A gridline
            // drawn for them would be a line the series cannot cross.
            edges: [0],
            // No glyph pair: nothing here agrees or disagrees with a second series the way
            // premium_share's token share does, and a key would promise a mark never drawn.
            method: [
                { k: 'Basket', b: 'Sixteen names that PHYSICALLY move the buildout — '
                    + '<b>LTL</b> (less-than-truckload: many small shipments consolidated onto '
                    + 'one trailer, the freight that moves a build-out’s parts rather than its '
                    + 'bulk), truckload, flatbed, intermodal, the three US Class I rails, and utility '
                    + 'fleet. Airlines, parcel and general forwarders are excluded on purpose: '
                    + 'they measure consumer travel and e-commerce, not freight.' },
                { k: 'Weighting', b: 'Equal weight, reset quarterly on the third Friday of '
                    + 'Mar/Jun/Sep/Dec (XTN’s schedule), chain-linked from a fixed base of '
                    + '<b>100</b> at 2021-08-02 — fixed, because rebasing at the fetch '
                    + 'window made the level an artefact of the lookback. Equal <b>and not '
                    + 'cap</b>: three rails are about <b>73%</b> of this basket’s market '
                    + 'cap and are the whole investable rail universe, so cap weight would make '
                    + 'this a rail proxy. Measured 2026-08-01, cap weight read <b>+1.64% above</b> '
                    + 'its 50 while 13 of 16 names sat below their own. Equal weight is the '
                    + 'breadth detector; see Composition.' },
                { k: 'The ladder', b: 'Four states, and the hysteresis is the point. <b>Green '
                    + 'dominates</b>: any close below the 200-bar MA, and nothing else is read. '
                    + 'Above it, two conditions — below the 50-bar MA, and no new 52-week '
                    + 'CLOSE high for <b>63</b> bars (copper’s gate) — give yellow on '
                    + 'both, orange on one, red on neither. Orange is the worker: a brief breach '
                    + 'that recovers cannot snap straight back to red. The 63-bar gate is '
                    + 'SELF-EXECUTING, so its date is knowable ahead and is recomputed every '
                    + 'pass rather than pinned — a new high resets it.' }
            ]
        },
        infra_backlog: {
            measures: 'VRT’s book-to-bill — new orders BOOKED divided by what it BILLED '
                    + 'in the same period.',
            // Says nothing about which way orders are currently going, and nothing about
            // the number being old: the first is the sparkline's job and the second is a
            // live figure the evidence view computes. A staleness written into a static
            // definition would still be sitting here the quarter VRT starts publishing
            // again.
            why: 'The most LEADING read on the capex complex. Orders are signed before '
               + 'guidance is given and long before concrete is poured, so this turns '
               + 'first — the power and cooling gear a data centre cannot open without '
               + 'is ordered while the capex slides still say everything is fine.',
            bands: [
                { light: 'green',  range: '< 0.9 twice',  mean: 'orders evaporating' },
                { light: 'yellow', range: '0.9 – 1.0',    mean: 'softening' },
                { light: 'red',    range: '> 1.0',        mean: 'orders flooding' }
            ],
            edges: [0.9, 1.0],
            glyph: [
                { sym: '+', arrow: 'plus',  mean: 'GEV’s unsold capacity AGREES' },
                { sym: '−', arrow: 'minus', mean: 'GEV’s unsold capacity CONTRADICTS' }
            ],
            method: [
                { k: 'The number', b: 'Book-to-bill is a dimensionless FLOW ratio — orders '
                    + 'in over billings out, both from the same release and the same basis. '
                    + 'Taken as management STATES it, else computed orders ÷ revenue, and '
                    + '<b>never</b> derived from the change in backlog: scan-sourced backlog '
                    + 'figures are routinely not comparable (RPO against backlog against '
                    + 'different report dates), and that path once implied a <b>0.25×</b> '
                    + 'immediately after a 2.9×. The validator rejects the banned path rather '
                    + 'than trusting the number that comes out of it.' },
                { k: 'The cap', b: 'VRT does not disclose orders every quarter — management '
                    + 'has said so outright. While the leg is flagged undisclosed a RED is '
                    + 'held at yellow, because a carried strong print must not keep asserting '
                    + 'maximum bubble-support after the company has stopped publishing the '
                    + 'metric. Deliberately a <b>cap and not a downgrade</b>: silence is soft '
                    + 'evidence, enough to withdraw the strongest claim and never enough to '
                    + 'manufacture a pro-burst one, so it can reach yellow and never green.' },
                { k: 'Why green needs two', b: 'Book-to-bill is lumpy, so one print under '
                    + '<b>0.9</b> is a data point and two consecutive are a turn. The bar is '
                    + 'set there because VRT’s backlog is only about <b>0.9 years</b> of '
                    + 'revenue — no cushion, so it needs a ratio above 1 just to hold ground. '
                    + 'A green cannot be faked by share loss: for the ratio to fall from 2.9× '
                    + 'to under 0.9, orders have to drop about <b>70%</b>.' },
                { k: 'The glyph', b: 'GEV’s remaining UNSOLD generating capacity, in GW — a '
                    + 'stock, not a flow, and a corroborator only: the light is VRT’s. The '
                    + 'model emits the stated figure and <b>this code</b> resolves the '
                    + 'direction, never the model — shrinking unsold capacity means demand is '
                    + 'strong and agrees with red (+); growing means slots are reopening and '
                    + 'contradicts it (−); inside a <b>±5 GW</b> deadband, or with only one '
                    + 'print on the record, no glyph. Read the TIMING: a − beside today’s red '
                    + 'is GEV latency, while a + returning AFTER VRT greens is the real '
                    + 'sector-wide confirmation.' }
            ]
        },
        capex_pressure: {
            measures: 'Capex as a share of operating cash flow, per company, over the '
                    + 'trailing four quarters — can each hyperscaler pay for its own build?',
            // Deliberately silent on which way the ratios are currently going: the arrow,
            // the sparkline and the Direction view all compute that live, and a direction
            // written into a static definition goes stale the first print that contradicts
            // it. Same rule that kept the trend out of silicon_payback's copy.
            why: 'The point at which the build stops being paid for out of the business. '
               + 'Under 100% a company is funding its data centres from the cash they and '
               + 'the rest of its operations throw off; over it, the difference comes from '
               + 'the balance sheet.',
            // INVERTED, like the board's other supply-side reads: green is the pro-burst
            // end. Five per-company lights, then a MAJORITY, with tie-breaks that defer
            // toward red (see The majority, below).
            bands: [
                { light: 'green',  range: '> 100%',    mean: 'funded off the balance sheet' },
                { light: 'yellow', range: '75 – 100%', mean: 'burning too much' },
                { light: 'red',    range: '< 75%',     mean: 'self-funding' }
            ],
            edges: [75, 100],
            glyph: [
                { sym: '↓', arrow: 'down', mean: 'ratios RISING — burning more' },
                { sym: '↑', arrow: 'up',   mean: 'ratios FALLING — pulling back' }
            ],
            method: [
                { k: 'The basket', b: 'MSFT, GOOGL, AMZN, META and ORCL, <b>unweighted</b> '
                    + '— five individual lights and then a majority. Dollar-weighting would '
                    + 'shrink ORCL from canary to rounding error, and ORCL is the name this '
                    + 'factor was built to watch.' },
                { k: 'The window', b: 'Trailing <b>four contiguous quarters</b>, so the '
                    + 'season is complete and a Q4-heavy capex pattern cannot masquerade as '
                    + 'a trend. The arrow compares it with the <b>same four quarters a year '
                    + 'earlier</b> — one basis for every name, always.' },
                { k: 'Over the gate', b: 'Above <b>100%</b> the difference comes from '
                    + 'debt, cash reserves or someone else’s money, and that is a decision a '
                    + 'board has to keep re-making every quarter — which is what makes this '
                    + 'the pro-burst end of the scale. Under <b>75%</b> the build sits '
                    + 'comfortably inside what operations throw off; the band between is the '
                    + 'one worth watching.' },
                { k: 'The majority', b: 'Five lights can deadlock, and the tie-breaks defer '
                    + 'toward red: a green/red tie cancels to <b>yellow</b>, and two '
                    + 'adjoining tiers defer <b>up</b> (2 red + 2 yellow reads red). The '
                    + 'pane names the rule whenever one actually fired.' },
                { k: 'The numbers', b: 'Taken from <b>SEC XBRL</b> as filed, not from a '
                    + 'vendor window, and kept: 315 quarters and counting. Most arrive as '
                    + 'discrete 3-month facts; Q4 is differenced out of the year-to-date '
                    + 'ones, because no 10-Q reports it. Cross-checked against yfinance on '
                    + 'the 30 overlapping quarters — <b>25 agree, 0 differ</b>, and the '
                    + 'other five are periods the vendor left empty.' }
            ]
        },
        capex_spigot: {
            measures: 'Hyperscaler forward capex GUIDANCE against the prior year, '
                    + 'basket aggregate — is the money still flowing?',
            why: 'The demand side of the buildout, taken from what the spenders say they '
               + 'will spend. Guidance is a promise made on a call and revised on the '
               + 'next one, so it turns before the cash does — a cut here is the moment '
               + 'the build is called off out loud.',
            // INVERTED: green is the CUT. Confirming half of the capex pair.
            bands: [
                { light: 'green',  range: '< −10%',      mean: 'guidance cut' },
                { light: 'yellow', range: '−10 to +10%', mean: 'flat / decelerating' },
                { light: 'red',    range: '> +10%',      mean: 'spigot wide open' }
            ],
            edges: [-10, 10],
            // NO GLYPH PAIR, and that is a decision rather than an omission: the measure
            // is already a RATE, so its direction is in the number. An arrow here would
            // be a second derivative. Contrast capex_pressure, a LEVEL, which earns one.
            method: [
                { k: 'The pair', b: 'The CONFIRMING half. Capex pressure greens first, as '
                    + 'names breach 100% of their own cash flow; the spigot greens after, '
                    + 'when that forces the guidance down. Given the lag a green here is '
                    + '<b>confirmation, not warning</b> — the warning is a layer up, in '
                    + 'pressure and infra backlog.' },
                { k: 'The weighting', b: '<b>Dollar-weighted</b>: sum of guidance divided '
                    + 'by sum of prior, so the biggest spender moves the light most. That '
                    + 'is deliberately the opposite of capex pressure, which is unweighted '
                    + 'so ORCL stays a canary. Here a dollar is a dollar whoever spends it.' },
                { k: 'The prior', b: 'DERIVED from SEC filings every pass — capex plus '
                    + '<b>finance-lease principal payments</b>, which is what these '
                    + 'companies mean by "including finance leases". It used to be five '
                    + 'pinned constants, and measured against the filings they were never '
                    + 'on one basis: two were pure GAAP, one included leases, one was '
                    + 'neither, and AMZN’s was its GUIDANCE figure rather than an '
                    + 'actual — <b>$6.8B</b> under its own filed number, understated in the '
                    + 'direction that inflates this reading. Now one convention, '
                    + 'self-updating as each year closes.' },
                { k: 'What is soft', b: 'Only the FORWARD number is model-pulled, because '
                    + 'only it is genuinely soft. Each company is asked separately and the '
                    + 'aggregate is assembled in Python; a company that does not guide is '
                    + 'left OUT of the sum rather than counted as a zero, which would read '
                    + 'as a cut it never made.' }
            ]
        },
        // --- The eight that were left. None of these emits an arrow, so none carries a
        // glyph pair: a key here would promise a mark the board never draws.
        yield_curve: {
            measures: 'The 10-year Treasury yield minus the 3-month, and whether that '
                    + 'spread has already been inverted and come back.',
            why: 'The definitional anchor — is the window open? Inversion preceded six of '
               + 'the last seven recessions, but the inversion is not the trigger: the '
               + 'recession lands six to eighteen months after the spread crosses back '
               + 'to normal.',
            bands: [
                { light: 'green',  range: 'positive, after an inversion', mean: 'window open' },
                { light: 'yellow', range: 'inverted now',                 mean: 'clock loading' },
                { light: 'red',    range: 'positive, never inverted',     mean: 'nothing armed' }
            ],
            // Zero is the only line on this axis: it is where inversion begins and ends.
            // The green/red split is not a level at all — it is whether an inversion sits
            // BEHIND the current positive reading, which no gridline can show.
            edges: [0],
            method: [
                { k: 'Sequence, not level', b: 'A positive spread means opposite things '
                    + 'before and after an inversion, so this factor is a state machine, '
                    + 'not a threshold. Green is the <b>crossover</b> window and carries '
                    + 'months-since in its reading; the historical recessions landed in '
                    + 'the <b>6–18 month</b> band after it.' },
                { k: 'The lookback', b: 'Three years. An inversion older than that belongs '
                    + 'to a previous cycle and no longer arms anything.' },
                { k: 'Source', b: 'FRED <b>DGS10</b> and <b>DGS3MO</b>, daily and free.' }
            ]
        },
        concentration: {
            measures: 'Semiconductor weight in the S&P 500 — at its RUNNING PEAK, not '
                    + 'today’s print.',
            why: 'The magnitude of what is inflated. This is a pre-burst instrument, so '
               + 'what matters is not where concentration sits now but the height the '
               + 'unwind would start from — and a peak, once made, does not un-happen.',
            bands: [
                { light: 'green',  range: '> 20%',    mean: 'peak concentration' },
                { light: 'yellow', range: '15 – 20%', mean: 'elevated' },
                { light: 'red',    range: '< 15%',    mean: 'unremarkable' }
            ],
            edges: [15, 20],
            method: [
                { k: 'Peak, not print', b: 'The LIGHT reads the running maximum over the '
                    + 'log; the sparkline plots the CURRENT daily weight, so the two do '
                    + 'not track — today can fall while the light holds. Red is '
                    + 'structurally unreachable by design: a peak cannot come back down.' },
                { k: 'The basis', b: '<b>Float-adjusted</b> index weights from the SSGA SPY '
                    + 'daily holdings file. A raw-cap basis reads about <b>1.09&times;</b> '
                    + 'lower and is kept in the record as reference only — never mixed into '
                    + 'the running max, which would corrupt the peak with two conventions.' },
                { k: 'The 2000 shape', b: 'Top-10 weight reached <b>25%</b> then against '
                    + '<b>38%</b> now — but 2000 was a wide large-cap mania and today is an '
                    + 'ultra-narrow handful, and 2000 <b>spiked</b> where today has '
                    + '<b>ground</b> up over years. Sharpest tell: then the biggest names '
                    + 'carried the HIGHEST multiples (Cisco 130×), so it was multiple-driven; '
                    + 'today they carry the lowest, so it is earnings-driven.' },
                { k: 'Why 2007 is blank', b: '<b>2008 was a credit bubble, not a '
                    + 'concentration one.</b> Equity breadth sat at <b>0.339</b> against a '
                    + '0.353 median — near normal — while the risk built in mortgages and the '
                    + 'banks holding them. That shape is read by <b>market credit</b> (the '
                    + 'spark) and <b>leverage</b> (how violent the unwind), never here. Today '
                    + 'is argued to be a hybrid, so read all three together.' },
                { k: 'The backfill', b: 'Rows for 2026-04-15 to 07-17 are RECONSTRUCTED — '
                    + 'each name’s float weight scaled back by its price ratio. Validated '
                    + 'twice: the reconstruction’s latest value matched the live file to '
                    + '<b>0.01pp</b>, and the peak lands on the same date as the raw-basis '
                    + 'peak.' }
            ]
        },
        rate_path: {
            measures: 'The 2-year yield minus fed funds — the pivot — and how far it has '
                    + 'moved in six months.',
            why: 'Whether the market is repricing toward TIGHTENING, which is the cause a '
               + 'burst needs, or toward cuts, which is the reaction to one. Reading the '
               + 'pivot rather than the Fed’s own words gets the market’s answer before '
               + 'the committee gives theirs.',
            // TWO bands, not three, and that is the factor rather than an omission: it
            // fires on either of two conditions or it does not fire.
            bands: [
                { light: 'green', range: '6mo move ≥ +0.50, or pivot < 0',
                  mean: 'tightening, or pricing cuts' },
                { light: 'red',   range: 'otherwise', mean: 'status quo' }
            ],
            edges: [0, 0.5],
            method: [
                { k: 'Two ways to green', b: 'A floored six-month move of <b>+0.50</b> or '
                    + 'more (repricing toward tightening), OR a raw pivot below <b>zero</b> '
                    + '(the market pricing cuts outright). Either is pro-burst; the reasons '
                    + 'differ and both are named in the reading.' },
                { k: 'Why floored', b: 'The six-month comparison floors the earlier pivot at '
                    + 'zero, so a <b>fading inversion</b> cannot be read as fresh '
                    + 'tightening. Without it, a move from −1.0 to −0.5 would score +0.5 and '
                    + 'fire a signal that is the opposite of what happened.' },
                { k: 'Strength', b: 'Amplitude is a watch, not a threshold: <b>+0.5</b> puts '
                    + 'it on, <b>+1.0</b> and up is 2022-grade. Post-1994 the pivot averages '
                    + 'about +0.31 and has ranged −1.5 to +2.2.' }
            ]
        },
        leverage: {
            measures: 'FINRA customer margin debt divided by free credit balances — '
                    + 'borrowing against the cash cushion behind it.',
            why: 'How violent the unwind would be, not whether it has started. This is a '
               + 'LOADED gauge: it says the tank is full, and a full tank tells you the '
               + 'size of the fire without telling you when it lights.',
            bands: [
                { light: 'green',  range: '> 2.0×',     mean: 'leverage maxed — primed' },
                { light: 'yellow', range: '1.5 – 2.0×', mean: 'elevated' },
                { light: 'red',    range: '< 1.5×',     mean: 'cushioned' }
            ],
            edges: [1.5, 2.0],
            method: [
                { k: 'The 2.0 line', b: 'ANCHORED, not chosen: the average of the two peaks '
                    + 'that matter — <b>1.85×</b> at the dot-com top and <b>2.19×</b> in the '
                    + '2021 mania. Red is near-moot by design; at a record ratio the bubble '
                    + 'pops long before leverage bleeds back to 1.5.' },
                { k: 'What it misses', b: 'FINRA covers CUSTOMER margin only — no prime '
                    + 'brokerage, no repo, no total-return swaps, so an Archegos is '
                    + 'invisible here. It therefore <b>understates</b> system leverage, '
                    + 'which is the safe direction for a burst board to err in.' },
                { k: 'Which half moves', b: 'The numerator does the work: margin debt has '
                    + 'gone <b>$936B → $1.50T</b> while free credit stayed roughly flat.' }
            ]
        },
        market_credit: {
            measures: 'The ICE BofA US high-yield option-adjusted spread, in basis points '
                    + '— and whether a widening has HELD.',
            why: 'The spark. Everything else on this board describes how much fuel is '
               + 'stacked; credit is where a bubble actually catches, because it is the '
               + 'price at which the marginal borrower can still roll.',
            bands: [
                { light: 'green',  range: '> 500bps, held 10 prints', mean: 'stress that stuck' },
                { light: 'yellow', range: '400 – 500bps',             mean: 'widening, unconfirmed' },
                { light: 'red',    range: '< 400bps',                 mean: 'firewall holding' }
            ],
            edges: [400, 500],
            method: [
                { k: 'The hold clause', b: 'LOAD-BEARING. Green needs every one of the last '
                    + '<b>10</b> prints above 500bps — a two-week hold — so a one-day spike '
                    + 'reads yellow. Two historical false alarms healed within weeks, and '
                    + 'April 2025’s <b>461bps</b> spike correctly never fired.' },
                { k: 'Red is not safe', b: 'Red means no stress NOW, which is a different '
                    + 'claim. Spreads hit record tights immediately before the 2007 blowout.' },
                { k: 'It gaps', b: 'The move from tights to 600+ took WEEKS in 2008 and in '
                    + '2020. This does not drift into position; expect the reading to jump.' }
            ]
        },
        copper: {
            measures: 'Copper against its own 200-bar trend, and how long since it last '
                    + 'made a 52-week closing high.',
            why: 'The real economy’s pulse, and the one industrial read on this board that '
               + 'is not about AI at all. Copper turning while the buildout still hums is '
               + 'the tell that demand is narrowing to one story.',
            bands: [
                { light: 'green',  range: 'below the 200',        mean: 'rolling over' },
                { light: 'yellow', range: 'above, no high in 63',  mean: 'stalling' },
                { light: 'red',    range: 'above, high inside 63', mean: 'humming' }
            ],
            edges: [0],
            method: [
                { k: 'Deliberately aggressive', b: 'The user’s own rule, and explicitly '
                    + '<b>not backtested</b>. Green dominates on any breach of the 200, with '
                    + 'no persistence clause by choice: copper has not closed below its 200 '
                    + 'once in 2026, so a green would break a ten-month streak and is a real '
                    + 'event rather than noise.' },
                { k: 'The gate', b: '<b>63 trading bars</b> — a quarter of trading, not '
                    + 'calendar days. Self-executing, so the date is knowable ahead and is '
                    + 'recomputed every pass; any new high resets it.' },
                { k: 'No price line', b: 'There is no absolute level here on purpose — a '
                    + 'copper price has no fixed meaning across decades. The tariff premium '
                    + 'in the COMEX front month distorts the LEVEL, not the trend.' }
            ]
        },
        inflation: {
            measures: 'Core PCE, year over year — the Fed’s own targeted gauge.',
            why: 'What keeps the Fed trapped. Every other factor here assumes a rescue is '
               + 'possible; this is the one that says whether it is. Hot inflation removes '
               + 'the option to cut into a falling market.',
            bands: [
                { light: 'green',  range: '> 3.5%',   mean: 'Fed trapped' },
                { light: 'yellow', range: '2 – 3.5%', mean: 'elevated, manageable' },
                { light: 'red',    range: '≤ 2%',     mean: 'rescue available' }
            ],
            edges: [2.0, 3.5],
            method: [
                { k: 'Core PCE, not CPI', b: 'Core PCE runs roughly <b>0.3–0.5pp below</b> '
                    + 'CPI. Never read a CPI print against these lines — it would sit a '
                    + 'third of a band too high.' },
                { k: 'Level only', b: 'No direction, no lookback, by design. The question is '
                    + 'whether the Fed’s hands are tied today, and that is a level.' },
                { k: 'The blind spot', b: 'Accepted, not solved: a demand-COLLAPSE '
                    + 'disinflation to 2% would colour red here while meaning the opposite. '
                    + 'The demand factors — copper, heavy haul — green at the same time in '
                    + 'that scenario and catch it. Never read ≤2% as all-clear.' }
            ]
        },
        net_liquidity: {
            measures: 'Fed balance sheet less the Treasury General Account less reverse '
                    + 'repo — and its 13-week change.',
            why: 'The tide the whole market floats on, and the softest leg here. It moves '
               + 'slowly and explains a lot after the fact, which is exactly why it is '
               + 'read as a sustained direction rather than a level.',
            bands: [
                { light: 'green',  range: '13wk < −$0.2T, held', mean: 'draining' },
                { light: 'yellow', range: 'within ±$0.2T',       mean: 'flat' },
                { light: 'red',    range: '13wk > +$0.2T, held', mean: 'expanding' }
            ],
            edges: [-0.2, 0.2],
            method: [
                { k: 'The sustain clause', b: 'LOAD-BEARING. The 13-week move must agree '
                    + 'with the 6-month trend, because <b>TGA swings of $200–400B a '
                    + 'quarter</b> dominate the series. Never flip this light on one '
                    + 'Treasury-account move.' },
                { k: 'The band', b: 'Calibrated, not picked: the last three years’ 13-week '
                    + 'changes have a standard deviation of <b>$0.176T</b>, so ±$0.2T is '
                    + 'one sigma of noise. A 2018-onward window was rejected — the COVID '
                    + 'explosion inflates it.' },
                { k: 'The unit trap', b: 'WALCL and the TGA are in <b>millions</b>, reverse '
                    + 'repo is in <b>billions</b>. Mixing them once produced a −$749T '
                    + 'reading; the alignment is asserted in the builder.' }
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
        const vb = AB_VIEWS[f.id];
        let badge = '';
        try { badge = (vb && vb.badge) ? vb.badge(f) : ''; } catch (e) { badge = ''; }
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
                // An optional second reading, for a factor whose light is decided by
                // something other than the number on the row. Vocabulary lives in
                // AB_VIEWS with the rest of the per-factor language; a factor without
                // a `badge` renders exactly as before.
                (badge ? `<span class="abh-st">${badge}</span>` : '') +
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
    function abMD(iso) { if (!iso) return '—'; const p = String(iso).split('-'); return (+p[1]) + '/' + (+p[2]); }
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
    // THE ROLLING RECORD of what the factor looked at and did not count. It carries
    // forward across sweeps (extractors/run.py `_merge_excluded`), so this table answers
    // "why is the latest news not in the count" with a DATE against each answer — and a
    // measure that has stopped recurring shows as an old date rather than disappearing.
    //
    // Two kinds, and the distinction is the point: an AUDITED exclusion fails one of the
    // four tests in regulatory.py, while `unproven` only means the gate could not prove
    // statewide scope from the evidence THIS pull returned. The second is a statement
    // about the pull, so it wears a chip — an over-strict gate must not read as a
    // considered judgment, because that error runs in the bubble-supportive direction.
    // Entries from before the record carried dates (the 2026-08-29 row) render with an
    // em-dash rather than breaking.
    function abExcludedHTML(day) {
        const rows = day.excluded || [];
        if (!rows.length) return '<div class="ab-tbd" style="padding:12px 13px">nothing recorded as excluded</div>';
        const seen = e => (e.last_seen || e.first_seen) ? abMD(e.last_seen || e.first_seen) : '—';
        const body = rows.map(e =>
            '<tr>' +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(e.state)}` +
                `${e.now_counted ? '<span class="tier c" style="margin-left:7px">now counted</span>'
                 : e.was_counted ? '<span class="tier p" style="margin-left:7px">was counted</span>' : ''}` +
                `${e.kind === 'unproven' ? '<span class="tier c" style="margin-left:7px">unproven</span>' : ''}` +
                `</div><div class="sl">${esc(e.citation || '')}</div></div></td>` +
              `<td class="l"><span class="ab-why">${esc(e.reason || '')}</span></td>` +
              `<td class="r"><span class="sl">${seen(e)}</span></td>` +
            '</tr>').join('');
        const wc = rows.filter(e => e.was_counted).length;
        const up = rows.filter(e => e.kind === 'unproven' && !e.now_counted).length;
        return '<div class="ab-scroller"><table class="ab-ledger">' +
            '<thead><tr><th class="l">Measure</th><th class="l">Why it does not count</th>' +
            '<th class="r">Last seen</th></tr></thead>' + `<tbody>${body}</tbody></table></div>` +
            '<div class="ab-overlapbar">' +
            (wc ? `<b>${wc}</b> of these were counted as states until the roster was ` +
                  'audited on 2026-08-29. '
                : 'None of these has ever been counted. ') +
            (up ? `<b>${up}</b> await proof of state-wide scope, not a judgment that they fail it.`
                : 'Every entry here fails one of the four tests outright.') +
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
    // --- INFRA BACKLOG (factor #6) ---------------------------------------------
    // The band hues are the BOARD's own light colours here, and that is correct rather
    // than a reuse of reserved status colour: this scale IS the light scale. The bands
    // are where the number turns each light, so painting them anything else would put a
    // second colour language on top of the one the panel already speaks.
    const AB_IB_BAND = { green: '#4ade80', yellow: '#fbbf24', red: '#f87171' };

    // Where the reading sits on the book-to-bill scale, and what the light does with
    // it. Drawn because the board row says "yellow · 2.9x" and those two look like a
    // contradiction until you can see the cap: the NUMBER is red, and the light is
    // held down a step because the company stopped publishing the number.
    function abInfraScaleSVG(day) {
        const btb = day.btb, hi = Math.max(1.3, btb * 1.14);
        const W = 680, H = 92, PL = 10, PR = 10, Y = 34, BH = 22;
        const X = v => PL + (v / hi) * (W - PL - PR);
        const seg = (a, b, light) =>
            `<rect x="${X(a).toFixed(1)}" y="${Y}" width="${(X(b) - X(a)).toFixed(1)}" ` +
            `height="${BH}" fill="${AB_IB_BAND[light]}" fill-opacity=".18" ` +
            `stroke="${AB_IB_BAND[light]}" stroke-opacity=".45" stroke-width="1"/>`;
        const tick = (v, label) =>
            `<line x1="${X(v).toFixed(1)}" y1="${Y - 5}" x2="${X(v).toFixed(1)}" ` +
            `y2="${Y + BH + 5}" class="ib-tick"/>` +
            `<text x="${X(v).toFixed(1)}" y="${Y + BH + 16}" class="ib-tk">${label}</text>`;
        // The reading's marker wears the light the NUMBER earns, not the light the board
        // shows. That is the point of the picture: the two differ, and a marker painted
        // the capped colour would quietly agree with the cap instead of showing it.
        const mx = X(btb);
        const marker =
            `<line x1="${mx.toFixed(1)}" y1="${Y - 13}" x2="${mx.toFixed(1)}" ` +
            `y2="${Y + BH + 2}" stroke="${AB_IB_BAND[day.raw_light] || '#e2e8f0'}" ` +
            'stroke-width="2"/>' +
            `<text x="${mx.toFixed(1)}" y="${Y - 18}" class="ib-now" ` +
            `fill="${AB_IB_BAND[day.raw_light] || '#e2e8f0'}">${btb.toFixed(1)}&#215;</text>`;
        // A band is named only while it can HOLD its name — the measured rule the pies
        // use, not a percentage threshold. The yellow band is 0.1 wide on a scale that
        // runs past 3, so at a 2.9 reading it is ~20px against a ~34px word: the label
        // would sit across its neighbours and paint the wrong band's colour over them.
        // The 0.9 and 1.0 ticks carry that boundary instead, which is what ticks are for.
        const labels = [[0, day.yellow_at, 'green'], [day.yellow_at, day.red_above, 'yellow'],
                        [day.red_above, hi, 'red']]
            .map(([a, b, l]) => (X(b) - X(a)) < l.length * 5.6 + 8 ? ''
                : `<text x="${((X(a) + X(b)) / 2).toFixed(1)}" y="${Y + 15}" ` +
                  `class="ib-bl" fill="${AB_IB_BAND[l]}">${l}</text>`).join('');
        return '<div class="ib-scale"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="Book-to-bill scale: green below ${day.yellow_at}, yellow to ` +
            `${day.red_above}, red above it; the reading sits at ${btb.toFixed(1)}">` +
            seg(0, day.yellow_at, 'green') + seg(day.yellow_at, day.red_above, 'yellow') +
            seg(day.red_above, hi, 'red') + labels +
            tick(day.yellow_at, day.yellow_at.toFixed(1)) +
            tick(day.red_above, day.red_above.toFixed(1)) + marker +
            '</svg></div>';
    }

    // THE READING — where the number sits, and why the light is not what the number says.
    function abInfraReadingHTML(day) {
        const drop = day.to_green_pct;
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">orders must fall</span>' +
              `<span class="v">${drop == null ? '—' : Math.round(Math.abs(drop))}` +
              '<span class="u">%</span></span>' +
              `<span class="s">to reach the ${day.yellow_at} green line</span>` +
              '<span class="r">and green needs two prints, not one</span>' +
            '</div>';
        // The cap, stated as the two-step it is. Written from `capped` rather than from
        // `undisclosed` so the sentence disappears on its own the quarter VRT publishes
        // again, instead of needing a second rule to retire it.
        const cap = day.capped
            ? '<div class="ib-cap">' +
                `<span class="ib-was abh-${AB_LC[day.raw_light]}">the number reads ` +
                `${esc(day.raw_light)}</span>` +
                '<span class="ib-arw">&rarr;</span>' +
                `<span class="ib-is abh-${AB_LC[day.light]}">the light is held at ` +
                `${esc(day.light)}</span>` +
                '<div class="ib-capwhy">Capped, not downgraded. VRT stopped publishing ' +
                'the metric' +
                (day.undisclosed_since ? ` after <b>${esc(day.undisclosed_since)}</b>` : '') +
                ', and going from effusive-and-quantified to qualitative-only is itself ' +
                'information — enough to withdraw the strongest claim, never enough to ' +
                'manufacture a pro-burst one. The cap can only reach yellow; it can ' +
                'never reach green.</div>' +
              '</div>'
            : '<div class="ib-cap"><div class="ib-capwhy">Nothing is capped — the light ' +
              'is what the number says.</div></div>';
        const stale = day.age_days != null
            ? `The <b>${day.btb.toFixed(1)}&#215;</b> is a <b>${esc(day.quarter)}</b> print, ` +
              `<b>${day.age_days}</b> days old when this reading was taken`
            : `The <b>${day.btb.toFixed(1)}&#215;</b> carries no quarter label, so its age ` +
              'cannot be stated';
        return '<div class="ab-pies ib-top">' + hero + abInfraScaleSVG(day) + '</div>' + cap +
            `<div class="ab-overlapbar">${stale}. Book-to-bill is lumpy and VRT's backlog ` +
            'is only about <b>0.9 years</b> of revenue, so it needs a ratio above 1 just to ' +
            `hold ground — which is why a fall to <b>${day.yellow_at}</b> would take roughly ` +
            `a <b>${drop == null ? '—' : Math.round(Math.abs(drop))}%</b> collapse in orders ` +
            'and cannot be faked by share loss.</div>';
    }

    // TWO LEGS — what each input was asked, what it answered, and what it cost. Both
    // legs are currently answering with a SILENCE of a different kind, and a silence
    // renders as nothing at all unless something draws it.
    function abInfraLegsHTML(day) {
        const g = day.gev || {};
        const row = (k, v, alt) =>
            '<div class="ab-lrow">' +
              `<span class="nm2">${esc(k)}</span>` +
              `<span class="fig"><b>${v}</b>` +
              `${alt ? ` <span class="alt">${esc(alt)}</span>` : ''}</span></div>`;
        const quote = (q, cite) => q
            ? `<div class="ib-quote">&ldquo;${esc(q)}&rdquo;` +
              `${cite ? `<span class="ib-cite">${esc(cite)}</span>` : ''}</div>` : '';
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">since the last print</span>' +
              `<span class="v">${day.age_days == null ? '—' : day.age_days}` +
              '<span class="u">d</span></span>' +
              `<span class="s">${esc(day.quarter || 'no quarter label')}` +
              `${day.method ? ' · ' + esc(day.method) : ''}</span>` +
              '<span class="r">VRT has not restated it since</span>' +
            '</div>';

        const vrt =
            '<div class="ab-lens"><div class="lens-hd">' +
              '<div class="t">VRT book-to-bill <span class="ib-role">drives the light</span></div>' +
              `<div class="s">orders booked &divide; billings, same period</div></div>` +
            row('reading', day.btb.toFixed(1) + '&#215;', day.quarter || '') +
            row('previous print', day.prev_btb == null ? '—' : day.prev_btb.toFixed(1) + '&#215;') +
            row('sourcing method', esc(day.method || '—'),
                day.method === 'stated' ? 'from the call' : '') +
            (day.undisclosed
                ? row('this quarter', '<span class="ib-none">not disclosed</span>',
                      day.unavailable_reason || '') +
                  row('asked', esc(day.attempted_at || '—'),
                      (day.attempts || 0) + ' attempt' + ((day.attempts || 0) === 1 ? '' : 's')) +
                  row('spent chasing it', day.cost == null ? '—' : '$' + day.cost.toFixed(4)) +
                  (day.undisclosed_reason ? `<div class="ib-note">${esc(day.undisclosed_reason)}` +
                      `${day.vrt_url ? ` <a class="ab-src-a" href="${esc(day.vrt_url)}" ` +
                        'target="_blank" rel="noopener noreferrer">transcript</a>' : ''}</div>` : '')
                : row('this quarter', 'disclosed')) +
            '</div>';

        const gev =
            '<div class="ab-lens"><div class="lens-hd">' +
              '<div class="t">GEV unsold capacity <span class="ib-role">corroborates only</span></div>' +
              '<div class="s">remaining available GW, a stock</div></div>' +
            row('stated stock', g.total == null ? '—' : g.total + ' GW', g.as_of || '') +
            row('prior stock', g.prev_total == null
                ? '<span class="ib-none">none yet</span>' : g.prev_total + ' GW') +
            row('direction', g.direction
                ? esc(g.direction) : '<span class="ib-none">unresolved</span>',
                g.direction_source ? esc(g.direction_source.replace('_', ' ')) : '') +
            row('glyph', g.arrow === 'plus' ? '+' : g.arrow === 'minus' ? '&minus;'
                : '<span class="ib-none">dark</span>',
                g.arrow ? '' : '±' + g.deadband + ' GW deadband') +
            (g.why_dark ? `<div class="ib-note">${esc(g.why_dark)}</div>` : '') +
            quote(g.quote, g.as_of ? 'GEV · ' + g.as_of : 'GEV') +
            '</div>';

        return '<div class="ab-pies ib-legs">' + hero + '</div>' +
            '<div class="ab-lenses ab-sides">' + vrt + gev + '</div>' +
            '<div class="ab-overlapbar">The light rests on <b>one</b> number the company ' +
            'no longer publishes, and the glyph that would corroborate it is dark — ' +
            (g.why_dark ? esc(g.why_dark) : 'the direction has resolved') +
            '. Both legs are answering with a silence, and the silences say different ' +
            'things: VRT has stopped speaking, GEV has only spoken once.</div>';
    }

    // --- YIELD CURVE (one view) -------------------------------------------------
    // The board-charts payload by id, cached in the same `_chartData` the Charts tab
    // fills. Separate from abHaulChart on purpose: that one works and is not mine to
    // disturb, and the eight lines it would save are not worth touching a view the
    // user is happy with.
    let _ycChartReq = null;
    function abChartById(id) {
        if (_chartData) return (_chartData.charts || []).find(c => c.id === id) || null;
        if (!_ycChartReq) {
            _ycChartReq = fetch(`${API_BASE}/get_board_charts`)
                .then(r => r.json())
                .then(j => { _chartData = j; renderBubbleOverview(); })
                .catch(() => { /* the reading still renders; only the picture is missing */ });
        }
        return null;
    }

    // The Charts tab's own yield-curve entry, drawn in the panel: the spread, the
    // stretches it spent INVERTED, and the recessions that followed. Nothing layered on
    // top (user, 2026-08-31) — an earlier cut marked every un-inversion and shaded the
    // 6-18 month window after each, which is a different chart than the one that
    // already exists and works.
    function abYieldChartSVG(ch) {
        const ser = (ch.series || [])[0] || {};
        const pts = ser.data || [];
        if (pts.length < 2) return '';
        const W = 680, H = 180, PL = 28, PR = 12, PT = 8, PB = 26;
        const t0 = Date.parse(pts[0].time), t1 = Date.parse(pts[pts.length - 1].time);
        const yr = ch.y_range || { min: -2, max: 5 };
        const X = t => PL + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - PL - PR);
        const Y = v => PT + (yr.max - v) / (yr.max - yr.min) * (H - PT - PB);

        // Recessions underneath everything: they are the outcome, so they sit behind
        // the evidence rather than on top of it.
        const rec = (ch.bands || []).map(b =>
            `<rect x="${X(b.from).toFixed(1)}" y="${PT}" ` +
            `width="${Math.max(X(b.to) - X(b.from), 1).toFixed(1)}" ` +
            `height="${H - PT - PB}" class="yc-rec"><title>recession ${esc(b.from)} to ` +
            `${esc(b.to)}</title></rect>`).join('');

        // A YEAR GRID, because a 26-year line with no x-axis cannot be read for
        // WHEN (user, 2026-08-31). Every year gets a hairline so a date can be counted
        // off, every fifth gets a stronger one and a label so you are never counting
        // more than two. Drawn under the data, never over it.
        const y0 = new Date(t0).getUTCFullYear() + 1;
        const y1 = new Date(t1).getUTCFullYear();
        let grid = '';
        for (let y = y0; y <= y1; y++) {
            const x = X(y + '-01-01');
            if (x < PL || x > W - PR) continue;
            const major = y % 5 === 0;
            grid += `<line x1="${x.toFixed(1)}" y1="${PT}" x2="${x.toFixed(1)}" ` +
                    `y2="${H - PB}" class="${major ? 'yc-gridmaj' : 'yc-grid'}"/>`;
            if (major) {
                grid += `<text x="${x.toFixed(1)}" y="${H - PB + 13}" ` +
                        `class="yc-xlab">${y}</text>`;
            }
        }
        // The series starts inside its first year, so that year never gets a gridline
        // and the leftmost label would be 2005 — leaving the five years you would be
        // counting back through unlabelled. Anchor it at the edge instead.
        grid += `<text x="${PL}" y="${H - PB + 13}" class="yc-xlab" ` +
                `text-anchor="start">${new Date(t0).getUTCFullYear()}</text>`;
        // The SPREAD gets the same treatment as the years: a hairline every point so
        // a level can be read off directly, a stronger line and a label every two so you
        // are never counting more than one. Zero is skipped — it has its own rule below,
        // and it is the only level on this axis that means something.
        let hgrid = '';
        for (let v = Math.ceil(yr.min); v <= Math.floor(yr.max); v++) {
            if (v === 0) continue;
            hgrid += `<line x1="${PL}" y1="${Y(v).toFixed(1)}" x2="${W - PR}" ` +
                     `y2="${Y(v).toFixed(1)}" class="${v % 2 === 0 ? 'yc-gridmaj'
                                                                   : 'yc-grid'}"/>`;
        }
        const zero = `<line x1="${PL}" y1="${Y(0).toFixed(1)}" x2="${W - PR}" ` +
                     `y2="${Y(0).toFixed(1)}" class="yc-zero"/>`;
        // The area BELOW zero is the inversion, filled rather than merely crossed: on a
        // 26-year axis the inverted stretches are a few pixels wide and a line alone
        // loses them. This is the payload's own `baseline` styling, in SVG.
        const below = 'M' + pts.map(p => X(p.time).toFixed(1) + ',' +
                      Y(Math.min(p.value, 0)).toFixed(1)).join(' L') +
                      ` L${X(pts[pts.length - 1].time).toFixed(1)},${Y(0).toFixed(1)}` +
                      ` L${X(pts[0].time).toFixed(1)},${Y(0).toFixed(1)} Z`;
        const line = 'M' + pts.map(p => X(p.time).toFixed(1) + ',' +
                     Y(p.value).toFixed(1)).join(' L');
        const last = pts[pts.length - 1];
        // Labelled on the majors, plus the top of the range so the axis is closed.
        const lab = [];
        for (let v = Math.ceil(yr.min); v <= Math.floor(yr.max); v++) {
            if (v % 2 === 0 || v === Math.floor(yr.max)) lab.push(v);
        }
        const ticks = lab.map(v =>
            `<text x="${PL - 4}" y="${(Y(v) + 3.5).toFixed(1)}" class="yc-ax">` +
            `${v > 0 ? '+' : ''}${v}</text>`).join('');
        return '<div class="yc-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="The 10-year minus 3-month spread since ${esc(pts[0].time)}, with ` +
            'the inverted stretches filled and recessions shaded">' +
            rec + grid + hgrid + ticks + zero +
            `<path d="${below}" class="yc-inv"/>` +
            `<path d="${line}" fill="none" stroke="${ser.color || '#60a5fa'}" ` +
            'stroke-width="1.6"/>' +
            `<circle cx="${X(last.time).toFixed(1)}" cy="${Y(last.value).toFixed(1)}" ` +
            `r="3.5" fill="${ser.color || '#60a5fa'}" stroke="#0f172a" stroke-width="1.5"/>` +
            '</svg></div>';
    }

    function abYieldHTML(day) {
        const band = ((AB_WHY.yield_curve || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const head =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">` +
              `${day.months_since != null ? day.months_since.toFixed(1) : '—'}` +
              '<i>mo</i></span>' +
              '<span class="k">since the crossover</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="s">${day.crossover_date
                  ? 'crossed ' + esc(day.crossover_date)
                  : 'no crossover in the window'}</span>` +
            '</div>';
        const ch = abChartById('yield_curve');
        const pic = ch && !ch.error && !ch.placeholder
            ? abYieldChartSVG(ch)
            : '<div class="ab-tbd" style="padding:10px 13px">chart data loading…</div>';
        const key =
            '<div class="yc-key">' +
              '<span><i class="yc-i-inv"></i>inverted (10yr &lt; 3mo)</span>' +
              '<span><i class="yc-i-rec"></i>recession</span>' +
            '</div>';
        return head + pic + key +
            '<div class="ab-overlapbar">The inversion arms the clock; the ' +
            '<b>un-inversion</b> starts it. Inversion preceded six of the last seven ' +
            'recessions, and they landed ' + day.window_from_months + '–' +
            day.window_to_months + ' months after the spread crossed back' +
            (day.crossover_date
                ? ` — this one crossed <b>${esc(day.crossover_date)}</b>, ` +
                  `${day.months_since.toFixed(1)} months ago.`
                : '.') + '</div>';
    }

    // --- MARKET CREDIT (one view) -------------------------------------------------
    // The spread across the only history this factor can see, the bands it is cut on,
    // and the SUSTAIN CLAUSE made legible. That clause is half the green rule -- every
    // one of the last ten prints above 500 -- and until now it was a bare boolean in
    // extras with nothing on screen showing its state.
    //
    // The recalled levels (500 / 700 / 1100 / 2000) are deliberately NOT drawn on the
    // axis. Plotting 2000bps would collapse the entire 259-461 range this window
    // actually contains into a few pixels, and worse, would present numbers the factor
    // cannot measure with the same authority as ones it can. They get a separate
    // for-scale strip that says what they are.
    function abMarketCreditHTML(day) {
        const ser = day.series || [];
        const band = ((AB_WHY.market_credit || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const head =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${Math.round(day.bps)}` +
              '<i>bps</i></span>' +
              '<span class="k">high-yield OAS</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="s">${Math.round(day.to_green)} from green</span>` +
            '</div>';
        if (!ser.length) {
            return head + '<div class="ab-tbd" style="padding:12px 13px">' +
                'no archived history on this reading</div>';
        }

        const W = 680, H = 200, L = 34, R = 14, T = 10, B = 24;
        const t0 = Date.parse(ser[0][0]), t1 = Date.parse(ser[ser.length - 1][0]);
        const hi = Math.max(day.green_bps * 1.12,
                            Math.max.apply(null, ser.map(p => p[1])) * 1.1);
        const X = t => L + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - L - R);
        const Y = v => T + (hi - v) / hi * (H - T - B);

        // Bands under everything. Green is the TOP here: the board is inverted and
        // credit stress firing is the pro-burst end.
        let g = `<rect x="${L}" y="${T}" width="${W - L - R}" ` +
                `height="${(Y(day.green_bps) - T).toFixed(1)}" class="lv-green"/>` +
                `<rect x="${L}" y="${Y(day.green_bps).toFixed(1)}" width="${W - L - R}" ` +
                `height="${(Y(day.yellow_bps) - Y(day.green_bps)).toFixed(1)}" ` +
                'class="lv-yellow"/>';
        for (let y = 2024; y <= new Date(t1).getUTCFullYear(); y++) {
            const x = X(y + '-01-01');
            if (x < L || x > W - R) continue;
            g += `<line x1="${x.toFixed(1)}" y1="${T}" x2="${x.toFixed(1)}" ` +
                 `y2="${H - B}" class="yc-gridmaj"/>` +
                 `<text x="${x.toFixed(1)}" y="${H - B + 13}" class="rp-ax" ` +
                 `text-anchor="middle">${y}</text>`;
        }
        for (let v = 100; v <= hi; v += 100) {
            g += `<line x1="${L}" y1="${Y(v).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(v).toFixed(1)}" class="yc-grid"/>` +
                 `<text x="${L - 5}" y="${(Y(v) + 3.5).toFixed(1)}" class="rp-ax" ` +
                 `text-anchor="end">${v}</text>`;
        }
        [[day.green_bps, 'lv-lg'], [day.yellow_bps, 'lv-ly']].forEach(function (t) {
            g += `<line x1="${L}" y1="${Y(t[0]).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(t[0]).toFixed(1)}" class="${t[1]}"/>`;
        });

        const line = 'M' + ser.map(p => X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(' L');
        // The window's own high, marked because it is the sustain clause's one worked
        // example: 461bps reached the yellow band, never crossed 500, correctly did not
        // fire. That is the whole argument for the clause, and it is in the data.
        const wh = day.window_high || {};
        const peak = wh.date
            ? `<circle cx="${X(wh.date).toFixed(1)}" cy="${Y(wh.bps).toFixed(1)}" r="3.5" ` +
              `class="lv-anch"><title>window high ${Math.round(wh.bps)}bps &middot; ` +
              `${esc(wh.date)} &middot; reached yellow, never fired</title></circle>` +
              `<text x="${X(wh.date).toFixed(1)}" y="${(Y(wh.bps) - 7).toFixed(1)}" ` +
              `class="lv-al" text-anchor="middle">${Math.round(wh.bps)} &middot; ` +
              'never fired</text>'
            : '';
        const now = `<circle cx="${X(ser[ser.length - 1][0]).toFixed(1)}" ` +
            `cy="${Y(ser[ser.length - 1][1]).toFixed(1)}" r="4" class="mc-now"/>`;
        const svg = '<div class="rp-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="High-yield option-adjusted spread in basis points across the ` +
            `archived window, with the 400 and 500 thresholds and the window high marked">` +
            g + `<path d="${line}" fill="none" stroke="#f87171" stroke-width="1.6"/>` +
            peak + now + '</svg></div>';

        // TEN PIPS: the two-week hold, one pip a print, lit when that print cleared 500.
        const strip = (day.sustain_strip || []).map(function (p) {
            const on = p[1] > day.green_bps;
            return `<i class="${on ? 'on' : ''}" title="${esc(p[0])} — ` +
                   `${Math.round(p[1])}bps"></i>`;
        }).join('');
        const sustain =
            '<div class="mc-sustain">' +
              `<span class="k">the hold</span>${strip}` +
              `<span class="mc-sv">${day.sustained_wide ? 'all ' + day.sustain_days +
                  ' above 500' : '0 of ' + day.sustain_days + ' above 500'}</span>` +
            '</div>';

        // Recalled levels as TEXT, never as axis marks -- see the note above.
        const scale = (day.recalled_levels || []).map(l =>
            `<span><b>${l.bps}</b> ${esc(l.label)}</span>`).join('');
        return head + svg + sustain +
            `<div class="mc-scale"><span class="k">for scale &mdash; recalled, not ` +
            `measured</span>${scale}</div>` +
            `<div class="ab-overlapbar">Green needs <b>${day.sustain_days} consecutive</b> ` +
            `prints above ${day.green_bps} &mdash; a two-week hold, so a one-day spike ` +
            `reads yellow. In the <b>${day.archived_points}</b> archived prints since ` +
            `${esc((day.archive_from || '').slice(0, 7))} that gate has fired ` +
            `<b>${day.gate_fired_days}</b> times and the high is ` +
            `<b>${Math.round((day.window_high || {}).bps || 0)}</b>, so the line has ` +
            'never been crossed here. Read that as a fact about the WINDOW, not about ' +
            'credit: the vendor serves a rolling three years, and the levels above are ' +
            'from outside it. Red means no stress NOW, not safe &mdash; spreads sat at ' +
            'record tights through early 2007.</div>';
    }

    // --- COPPER (one view) -------------------------------------------------------
    // The price against its own 200-bar MA since 2020 -- the window the user picked
    // because it starts before the AI melt-up the rest of this board is about.
    // The picture IS the light: green is "any close below the 200", so every stretch
    // under the white line is a stretch that would have fired it. Shading those runs
    // rather than counting them in prose makes the rule's central claim -- copper has
    // not closed below its 200 once in 2026 -- checkable at a glance instead of taken
    // on faith, which is the whole reason the rule carries no persistence clause.
    // KING COPPER. Just the crown -- its base band already reads as the metal, so the
    // ingot under it was saying the same thing twice (user, 2026-08-31). Copper tones
    // throughout and deliberately NOT gold: on this board yellow means the light, and a
    // gold glyph beside a coloured reading reads as a signal rather than a mascot.
    // Self-contained SVG with no CSS of its own, so the stylesheet cannot restyle it.
    const AB_COPPER_KING =
        '<svg viewBox="0 0 24 15" width="24" height="15" role="img" ' +
            'aria-label="King Copper" style="align-self:center;flex:none">' +
          '<title>King Copper</title>' +
          '<path d="M3.5 11 L4.8 3.4 L8.4 7.8 L12 1.8 L15.6 7.8 L19.2 3.4 L20.5 11 Z" ' +
            'fill="#e0955a" stroke="#7c4a1e" stroke-width="0.9" stroke-linejoin="round"/>' +
          // The three points get their jewels; without them the silhouette reads as a
          // sawtooth at this size.
          '<circle cx="4.8" cy="3.4" r="1.15" fill="#f0b884" stroke="#7c4a1e" ' +
            'stroke-width="0.7"/>' +
          '<circle cx="12" cy="1.9" r="1.3" fill="#f0b884" stroke="#7c4a1e" ' +
            'stroke-width="0.7"/>' +
          '<circle cx="19.2" cy="3.4" r="1.15" fill="#f0b884" stroke="#7c4a1e" ' +
            'stroke-width="0.7"/>' +
          '<rect x="3.2" y="10.3" width="17.6" height="3" rx="0.8" ' +
            'fill="#b87333" stroke="#7c4a1e" stroke-width="0.9"/>' +
        '</svg>';

    function abCopperHTML(day) {
        const ser = day.series || [];
        const band = ((AB_WHY.copper || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const head =
            '<div class="yc-head">' + AB_COPPER_KING +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">` +
                `${day.vs200 >= 0 ? '+' : ''}${day.vs200.toFixed(1)}<i>%</i></span>` +
              '<span class="k">vs the 200-bar MA</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="s">$${day.price.toFixed(3)} against $${day.ma200.toFixed(3)}</span>` +
            '</div>';
        if (ser.length < 2) {
            return head + '<div class="ab-tbd" style="padding:12px 13px">' +
                'no series on this reading</div>';
        }

        const W = 680, H = 210, L = 34, R = 14, T = 10, B = 24;
        const t0 = Date.parse(ser[0][0]), t1 = Date.parse(ser[ser.length - 1][0]);
        let lo = Infinity, hi = -Infinity;
        ser.forEach(p => { lo = Math.min(lo, p[1], p[2]); hi = Math.max(hi, p[1], p[2]); });
        const pad = (hi - lo) * 0.08 || 0.1;
        lo -= pad; hi += pad;
        const X = t => L + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - L - R);
        const Y = v => T + (hi - v) / (hi - lo || 1) * (H - T - B);

        let g = '';
        for (let y = new Date(t0).getUTCFullYear() + 1;
                 y <= new Date(t1).getUTCFullYear(); y++) {
            const x = X(y + '-01-01');
            if (x < L || x > W - R) continue;
            g += `<line x1="${x.toFixed(1)}" y1="${T}" x2="${x.toFixed(1)}" ` +
                 `y2="${H - B}" class="yc-gridmaj"/>` +
                 `<text x="${x.toFixed(1)}" y="${H - B + 13}" class="rp-ax" ` +
                 `text-anchor="middle">${y}</text>`;
        }
        for (let v = Math.ceil(lo); v <= hi; v += 1) {
            g += `<line x1="${L}" y1="${Y(v).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(v).toFixed(1)}" class="yc-grid"/>` +
                 `<text x="${L - 5}" y="${(Y(v) + 3.5).toFixed(1)}" class="rp-ax" ` +
                 `text-anchor="end">${v.toFixed(0)}</text>`;
        }

        // Every CONTIGUOUS run of closes under the 200, filled between the two lines.
        // Runs, not per-bar rects: 1,677 bars would be 1,677 nodes and the browser
        // paints the same shape from a handful of polygons.
        const runs = [];
        let cur = null;
        ser.forEach((p, i) => {
            if (p[1] < p[2]) { if (cur) cur[1] = i; else cur = [i, i]; }
            else if (cur) { runs.push(cur); cur = null; }
        });
        if (cur) runs.push(cur);
        const shade = runs.map(r => {
            const a = ser.slice(r[0], r[1] + 1);
            const fwd = a.map(p => X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(' L');
            const back = a.slice().reverse()
                .map(p => X(p[0]).toFixed(1) + ',' + Y(p[2]).toFixed(1)).join(' L');
            return `<path d="M${fwd} L${back} Z" fill="rgba(74,222,128,.22)"/>`;
        }).join('');

        const path = k => 'M' + ser.map(p => X(p[0]).toFixed(1) + ',' +
                                             Y(p[k]).toFixed(1)).join(' L');
        // House colours, both already meaning something on this dashboard: the 200-bar
        // MA is the white SMA-200 line the ticker charts use, the price is the house
        // cyan. Neither is red/yellow/green, which on this board mean the light.
        const lines =
            `<path d="${path(2)}" fill="none" stroke="#f8fafc" stroke-width="1.4"/>` +
            `<path d="${path(1)}" fill="none" stroke="#22d3ee" stroke-width="1.5"/>`;

        const wh = day.window_high || {};
        const peak = wh.date
            ? `<circle cx="${X(wh.date).toFixed(1)}" cy="${Y(wh.price).toFixed(1)}" ` +
              `r="3.5" class="lv-anch"><title>window high $${wh.price} &middot; ` +
              `${esc(wh.date)}</title></circle>` +
              `<text x="${X(wh.date).toFixed(1)}" y="${(Y(wh.price) - 7).toFixed(1)}" ` +
              `class="lv-al" text-anchor="end">$${wh.price}</text>`
            : '';
        const last = ser[ser.length - 1];
        const now = `<circle cx="${X(last[0]).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" ` +
                    'r="4" class="mc-now"/>';

        const svg = '<div class="rp-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'role="img" aria-label="Copper front-month close against its 200-bar ' +
            'moving average since 2020, with every stretch below the average shaded">' +
            g + shade + lines + peak + now + '</svg></div>';

        // The MA on the picture and the MA in the reading are the same mean over the
        // same 200 bars computed two ways. Saying so only when they DISAGREE keeps the
        // normal case quiet and makes the abnormal one impossible to miss.
        const warn = day.ma_matches === false
            ? '<div class="ab-overlapbar">The 200 drawn here does not match the one ' +
              'this reading was decided on &mdash; treat the picture as indicative ' +
              'until that is chased down.</div>'
            : '';
        const lb = day.last_below
            ? `the last on <b>${esc(day.last_below)}</b>`
            : '<b>never</b> in this window';
        return head + svg + warn +
            '<div class="ab-overlapbar">Green is <b>any</b> close below the white ' +
            `line. In the <b>${day.n_bars}</b> bars since ` +
            `${esc((day.chart_from || '').slice(0, 4))} that has happened ` +
            `<b>${day.below_200_days}</b> times, ${lb} &mdash; so a green today would ` +
            'break a streak you can see the length of, which is why the rule carries ' +
            'no persistence clause and no absolute price line. The COMEX front month ' +
            'holds a tariff premium: it distorts the level, not the trend.</div>';
    }

    // --- NET LIQUIDITY (one view) ------------------------------------------------
    // TWO panels, because this factor reads one thing and shows another: the board row
    // carries the LEVEL, the light is cut on the 13-WEEK CHANGE against a +/-0.2T band.
    // A picture of the level alone would explain none of the colours on the row, and a
    // picture of the change alone would not be the number the row displays. Stacked on
    // one shared x-axis so a TGA rebuild in the tide lines up with the bump it puts in
    // the change.
    function abNetLiqHTML(day) {
        const ser = day.series || [];
        const band = ((AB_WHY.net_liquidity || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const sign = v => (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2) + 'T';
        // THE READING IS THE CHANGE (user, 2026-08-31). It takes the big slot and wears
        // the light, because it is the only thing the light is cut on; the LEVEL the
        // factor is named for is context and sits beside it in white. Same order as the
        // board row, which now shows the delta and nothing else -- a header that led
        // with the level would disagree with the row that opened it.
        const head =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">` +
                `${day.chg_3mo_T >= 0 ? '+' : '−'}$` +
                `${Math.abs(day.chg_3mo_T).toFixed(2)}<i>T</i></span>` +
              '<span class="k">13 wk change</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="s">net liquidity <b>$${day.level_T.toFixed(2)}T</b></span>` +
              `<span class="s">6mo <b>${sign(day.chg_6mo_T)}</b></span>` +
            '</div>';
        if (ser.length < 2) {
            return head + '<div class="ab-tbd" style="padding:12px 13px">' +
                'no series on this reading</div>';
        }

        const W = 680, L = 40, R = 14;
        const T1 = 12, B1 = 120;            // the tide
        const T2 = 154, B2 = 234;           // the change that decides the light
        const H = 250;
        const t0 = Date.parse(ser[0][0]), t1 = Date.parse(ser[ser.length - 1][0]);
        const X = t => L + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - L - R);

        let lo1 = Infinity, hi1 = -Infinity, ext = ser[0];
        ser.forEach(p => {
            lo1 = Math.min(lo1, p[1]); hi1 = Math.max(hi1, p[1]);
            if (Math.abs(p[2]) > Math.abs(ext[2])) ext = p;
        });
        // FIXED lower-panel scale, for the same reason yield_curve pins its y-axis:
        // autoscaled, 2020's COVID swing (a 13-week move of $2.09T) sets the range and
        // the ±0.2T band that actually DECIDES the light collapses into a sliver.
        // Pinned at ±0.75T the band is a fifth of the panel and every week since
        // 2021 still fits; the 20 weeks between March 2020 and May 2021 that run past
        // it are clamped to the edge and NAMED, never quietly flattened.
        const mx = 0.75;
        const pad = (hi1 - lo1) * 0.08 || 0.1;
        lo1 -= pad; hi1 += pad;
        const Y1 = v => T1 + (hi1 - v) / (hi1 - lo1) * (B1 - T1);
        const Y2 = v => T2 + (mx - Math.max(-mx, Math.min(mx, v))) / (2 * mx) * (B2 - T2);

        // Shared year rules, drawn through BOTH panels so the eye can carry a date
        // from the tide down to the change.
        let g = '';
        for (let y = new Date(t0).getUTCFullYear() + 1;
                 y <= new Date(t1).getUTCFullYear(); y++) {
            const x = X(y + '-01-01');
            if (x < L || x > W - R) continue;
            g += `<line x1="${x.toFixed(1)}" y1="${T1}" x2="${x.toFixed(1)}" ` +
                 `y2="${B1}" class="yc-gridmaj"/>` +
                 `<line x1="${x.toFixed(1)}" y1="${T2}" x2="${x.toFixed(1)}" ` +
                 `y2="${B2}" class="yc-gridmaj"/>` +
                 `<text x="${x.toFixed(1)}" y="${B2 + 13}" class="rp-ax" ` +
                 `text-anchor="middle">${y}</text>`;
        }
        for (let v = Math.ceil(lo1 * 2) / 2; v <= hi1; v += 0.5) {
            g += `<line x1="${L}" y1="${Y1(v).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y1(v).toFixed(1)}" class="yc-grid"/>` +
                 `<text x="${L - 5}" y="${(Y1(v) + 3.5).toFixed(1)}" class="rp-ax" ` +
                 `text-anchor="end">${v.toFixed(1)}</text>`;
        }

        // The lower panel's three regions ARE the band table, drawn. Draining is
        // NEGATIVE, so green sits at the BOTTOM here -- the one place on this board
        // where the inversion reads naturally rather than needing a note.
        const bT = day.band_T;
        const bands =
            `<rect x="${L}" y="${T2}" width="${W - L - R}" ` +
              `height="${(Y2(bT) - T2).toFixed(1)}" fill="rgba(248,113,113,.10)"/>` +
            `<rect x="${L}" y="${Y2(bT).toFixed(1)}" width="${W - L - R}" ` +
              `height="${(Y2(-bT) - Y2(bT)).toFixed(1)}" class="lv-yellow"/>` +
            `<rect x="${L}" y="${Y2(-bT).toFixed(1)}" width="${W - L - R}" ` +
              `height="${(B2 - Y2(-bT)).toFixed(1)}" class="lv-green"/>` +
            `<line x1="${L}" y1="${Y2(0).toFixed(1)}" x2="${W - R}" ` +
              `y2="${Y2(0).toFixed(1)}" class="yc-zero"/>` +
            [bT, -bT].map(t =>
              `<line x1="${L}" y1="${Y2(t).toFixed(1)}" x2="${W - R}" ` +
              `y2="${Y2(t).toFixed(1)}" stroke="#64748b" stroke-width="1" ` +
              'stroke-dasharray="3 3" stroke-opacity=".55"/>').join('') +
            `<text x="${L - 5}" y="${(Y2(bT) + 3.5).toFixed(1)}" class="rp-ax" ` +
              `text-anchor="end">+${bT}</text>` +
            `<text x="${L - 5}" y="${(Y2(-bT) + 3.5).toFixed(1)}" class="rp-ax" ` +
              `text-anchor="end">−${bT}</text>`;

        const path = (k, Y) => 'M' + ser.map(p => X(p[0]).toFixed(1) + ',' +
                                                  Y(p[k]).toFixed(1)).join(' L');
        const pk = day.peak || {};
        const peak = pk.date
            ? `<circle cx="${X(pk.date).toFixed(1)}" cy="${Y1(pk.level_T).toFixed(1)}" ` +
              `r="3.5" class="lv-anch"><title>peak $${pk.level_T}T &middot; ` +
              `${esc(pk.date)}</title></circle>` +
              `<text x="${X(pk.date).toFixed(1)}" y="${(Y1(pk.level_T) - 7).toFixed(1)}" ` +
              `class="lv-al" text-anchor="middle">$${pk.level_T}T</text>`
            : '';
        const last = ser[ser.length - 1];
        const off = Math.abs(ext[2]) > mx
            // Pinned to the panel's empty top-right rather than to the excursion
            // itself: at the spike's own x it lands on the +0.2 axis label, and the
            // clamped line is already running along the edge there anyway.
            ? '<text x="' + (W - R - 4) + '" y="' + (T2 + 11) + '" class="lv-al" ' +
              'text-anchor="end">' + (ext[2] > 0 ? '+' : '\u2212') + '$' +
              Math.abs(ext[2]).toFixed(2) + 'T in ' + ext[0].slice(0, 4) +
              ' \u00b7 off scale</text>'
            : '';
        const svg = '<div class="rp-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'role="img" aria-label="Net liquidity since 2020 above, and its 13-week ' +
            'change against the plus or minus 0.2 trillion band below">' +
            g + bands +
            `<text x="${L}" y="${T1 - 2}" class="rp-ax">$T</text>` +
            `<text x="${L}" y="${T2 - 6}" class="rp-ax">13-week change, $T</text>` +
            `<path d="${path(1, Y1)}" fill="none" stroke="#22d3ee" stroke-width="1.5"/>` +
            peak +
            `<circle cx="${X(last[0]).toFixed(1)}" cy="${Y1(last[1]).toFixed(1)}" ` +
              'r="4" class="mc-now"/>' +
            `<path d="${path(2, Y2)}" fill="none" stroke="#94a3b8" stroke-width="1.4"/>` +
            `<circle cx="${X(last[0]).toFixed(1)}" cy="${Y2(last[2]).toFixed(1)}" ` +
              'r="4" class="mc-now"/>' + off +
            '</svg></div>';

        // WHICH LEG MOVED. A balance-sheet runoff and a TGA rebuild are the same
        // arithmetic in the total and mean opposite things, so the three components are
        // named rather than left folded into one number.
        const c = day.components || {};
        const parts = c.walcl_T != null
            ? '<div class="mc-scale"><span class="k">the three legs</span>' +
              `<span><b>$${c.walcl_T.toFixed(2)}T</b> balance sheet</span>` +
              `<span>− <b>$${c.tga_T.toFixed(2)}T</b> TGA</span>` +
              `<span>− <b>$${c.rrp_T.toFixed(2)}T</b> reverse repo</span>` +
              `<span>= <b>$${day.level_T.toFixed(2)}T</b></span></div>`
            : '';

        // The RRP caveat is only worth saying while the buffer is actually gone, so it
        // is asked of the data rather than written in as a remembered fact.
        const drained = c.rrp_T != null && c.rrp_T < 0.1
            ? ' Reverse repo is down to <b>$' + (c.rrp_T * 1000).toFixed(0) +
              'B</b> from ~$2.5T in 2022, so the cushion that used to absorb a drain ' +
              'is gone: the same colour bites harder than it did.'
            : '';
        return head + svg + parts +
            '<div class="ab-overlapbar">The light is cut on the LOWER panel, not the ' +
            `tide above it: the 13-week move against a <b>±$${bT}T</b> band, which ` +
            `is one sigma of its own noise. <b>${day.weeks_outside}</b> of ` +
            `<b>${day.n_weeks}</b> weeks since ${esc((day.chart_from || '').slice(0, 4))} ` +
            'cleared it, and a colour needs the 6-month trend to agree as well — ' +
            'TGA swings of $200–400B a quarter dominate this series and would ' +
            `otherwise flip it on one Treasury-account move.${drained}</div>`;
    }

    // --- LEVERAGE (one view) -----------------------------------------------------
    // The ratio since 1999, against the two thresholds and the four peaks the 2.0 line
    // is set FROM. Drawing the anchors on the line rather than as free-floating levels
    // is the point: the green threshold is the average of the 2000 and 2021 peaks, so
    // seeing those two marked shows why it sits where it does, which no number in the
    // About box can.
    function abLeverageHTML(day) {
        const ser = day.series || [];
        const band = ((AB_WHY.leverage || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const peak = day.peak || {};
        const head =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.ratio.toFixed(2)}` +
              '<i>&times;</i></span>' +
              '<span class="k">margin debt / free credit</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `${peak.ratio ? `<span class="s">peak ${peak.ratio.toFixed(2)} ` +
                `${esc((peak.date || '').slice(0, 7))}</span>` : ''}` +
            '</div>';
        if (!ser.length) {
            return head + '<div class="ab-tbd" style="padding:12px 13px">' +
                (day.series_error ? 'history unavailable &mdash; ' + esc(day.series_error)
                                  : 'history rides on the newest reading only') + '</div>';
        }

        const W = 680, H = 210, L = 30, R = 14, T = 10, B = 24;
        const t0 = Date.parse(ser[0][0]), t1 = Date.parse(ser[ser.length - 1][0]);
        const hi = Math.max(3.6, Math.max.apply(null, ser.map(p => p[1])) * 1.05);
        const X = t => L + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - L - R);
        const Y = v => T + (hi - v) / hi * (H - T - B);

        // The bands the light is cut on, under everything. Green is the top of the
        // scale here because the board is inverted: leverage MAXED is pro-burst.
        let g = `<rect x="${L}" y="${T}" width="${W - L - R}" ` +
                `height="${(Y(day.green_above) - T).toFixed(1)}" class="lv-green"/>` +
                `<rect x="${L}" y="${Y(day.green_above).toFixed(1)}" width="${W - L - R}" ` +
                `height="${(Y(day.yellow_above) - Y(day.green_above)).toFixed(1)}" ` +
                'class="lv-yellow"/>';
        for (let y = 2000; y <= new Date(t1).getUTCFullYear(); y++) {
            const x = X(y + '-01-01');
            if (x < L || x > W - R) continue;
            const maj = y % 5 === 0;
            g += `<line x1="${x.toFixed(1)}" y1="${T}" x2="${x.toFixed(1)}" ` +
                 `y2="${H - B}" class="${maj ? 'yc-gridmaj' : 'yc-grid'}"/>`;
            if (maj) g += `<text x="${x.toFixed(1)}" y="${H - B + 13}" class="rp-ax" ` +
                          `text-anchor="middle">${y}</text>`;
        }
        for (let v = 1; v <= Math.floor(hi); v++) {
            g += `<line x1="${L}" y1="${Y(v).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(v).toFixed(1)}" class="yc-grid"/>` +
                 `<text x="${L - 5}" y="${(Y(v) + 3.5).toFixed(1)}" class="rp-ax" ` +
                 `text-anchor="end">${v}</text>`;
        }
        [[day.green_above, 'lv-lg'], [day.yellow_above, 'lv-ly']].forEach(function (t) {
            g += `<line x1="${L}" y1="${Y(t[0]).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(t[0]).toFixed(1)}" class="${t[1]}"/>`;
        });

        const line = 'M' + ser.map(p => X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(' L');
        // Each anchor marked where it happened. `matches` is the build-time check that
        // the series still reproduces the pinned constant; a drifted one is drawn in
        // the warning colour rather than passed off as agreeing.
        const marks = (day.anchors || []).map(function (a) {
            const x = X(a.date), y = Y(a.ratio);
            return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" ` +
                   `class="${a.matches ? 'lv-anch' : 'lv-anch-bad'}"><title>${esc(a.label)} ` +
                   `&middot; ${a.ratio.toFixed(2)} &middot; ${esc(a.date)}` +
                   `${a.matches ? '' : ' (does not match the pinned ' + a.pinned + ')'}` +
                   '</title></circle>' +
                   `<text x="${x.toFixed(1)}" y="${(y - 7).toFixed(1)}" class="lv-al" ` +
                   `text-anchor="middle">${esc(a.label)} ${a.ratio.toFixed(2)}</text>`;
        }).join('');
        const lastP = ser[ser.length - 1];
        const now = `<circle cx="${X(lastP[0]).toFixed(1)}" cy="${Y(lastP[1]).toFixed(1)}" ` +
            'r="4" class="lv-now"/>';
        const svg = '<div class="rp-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="Margin debt divided by free credit, monthly since ` +
            `${esc((day.series_from || '').slice(0, 4))}, with the 1.5 and 2.0 thresholds ` +
            'and the 2000, 2007, 2008 and 2021 anchors marked">' + g +
            `<path d="${line}" fill="none" stroke="#a78bfa" stroke-width="1.8"/>` +
            marks + now + '</svg></div>';

        const key =
            '<div class="yc-key">' +
              '<span><i class="lv-i-g"></i>green &mdash; above ' + day.green_above + '&times;</span>' +
              '<span><i class="lv-i-y"></i>yellow &mdash; ' + day.yellow_above +
              '&ndash;' + day.green_above + '&times;</span>' +
              '<span><i class="rp-i-dot" style="background:#f8fafc"></i>anchors</span>' +
            '</div>';
        const offPeak = (peak.ratio && Math.abs(peak.ratio - day.ratio) > 0.005)
            ? ` It is <b>${(peak.ratio - day.ratio).toFixed(2)}</b> off the high of ` +
              `<b>${peak.ratio.toFixed(2)}</b> set in ${esc((peak.date || '').slice(0, 7))}.`
            : ' That is the high of the whole series.';
        return head + svg + key +
            `<div class="ab-overlapbar">The <b>${day.green_above}&times;</b> line is ` +
            'ANCHORED, not chosen: it is the average of the two peaks that matter, ' +
            `<b>1.85</b> in 2000 and <b>2.19</b> in 2021. Today reads ` +
            `<b>${day.ratio.toFixed(2)}&times;</b>, above both.${offPeak} The numerator ` +
            `does the work &mdash; margin debt <b>$${Math.round(day.margin_debt_b)}B</b> ` +
            `against free credit <b>$${Math.round(day.free_credit_b)}B</b>, which has ` +
            'stayed roughly flat while the debt climbed.</div>';
    }

    // --- RATE PATH (one view) ---------------------------------------------------
    // THE TWO ROUTES. This factor greens on EITHER of two conditions and they are
    // independent, which no single line can show: plotting the pivot against its own
    // six-month change puts both on one picture, with everything left of zero the
    // inverted route and everything above the trigger the tightening one. Every month
    // since 1994 is a dot, so today reads against where the rule has actually spent its
    // time rather than against an assertion about it.
    //
    // Chosen over a time series (user, 2026-08-31) because the Charts tab's Fed dial
    // already answers "where are rates going over time", and a second answer to that
    // question one tab away is duplication that is hard to notice later.
    const AB_RP_C = { tightening: '#4ade80', inverted: '#f87171', quiet: '#64748b' };

    function abRatePathHTML(day) {
        const TRIG = day.trigger;
        const cloud = day.cloud || [];
        const state = (p, d) => d >= TRIG ? 'tightening' : (p < 0 ? 'inverted' : 'quiet');

        const head =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">` +
              `${day.pivot >= 0 ? '+' : ''}${day.pivot.toFixed(2)}</span>` +
              '<span class="k">pivot</span>' +
              `<span class="s">6mo change ${day.delta_6mo >= 0 ? '+' : ''}` +
              `${day.delta_6mo.toFixed(2)}</span>` +
              `<span class="s">${esc(day.state || '')}</span>` +
            '</div>';

        if (!cloud.length) {
            return head + '<div class="ab-tbd" style="padding:12px 13px">' +
                (day.cloud_error
                    ? 'history unavailable &mdash; ' + esc(day.cloud_error)
                    : 'history rides on the newest reading only') + '</div>';
        }

        const W = 680, H = 290, L = 42, R = 14, T = 12, B = 32;
        const ps = cloud.map(c => c[0]).concat([day.pivot]);
        const ds = cloud.map(c => c[1]).concat([day.delta_6mo]);
        const x0 = Math.min(-2, Math.min.apply(null, ps));
        const x1 = Math.max(2.5, Math.max.apply(null, ps));
        const y0 = Math.min(-1.5, Math.min.apply(null, ds));
        const y1 = Math.max(2.5, Math.max.apply(null, ds));
        const X = v => L + (v - x0) / (x1 - x0) * (W - L - R);
        const Y = v => T + (y1 - v) / (y1 - y0) * (H - T - B);

        // The two green regions, under everything: left of zero, and above the trigger.
        let g = `<rect x="${L}" y="${T}" width="${(X(0) - L).toFixed(1)}" ` +
                `height="${H - T - B}" class="rp-win"/>` +
                `<rect x="${L}" y="${T}" width="${W - L - R}" ` +
                `height="${(Y(TRIG) - T).toFixed(1)}" class="rp-win"/>`;
        for (let v = Math.ceil(x0); v <= Math.floor(x1); v++) {
            g += `<line x1="${X(v).toFixed(1)}" y1="${T}" x2="${X(v).toFixed(1)}" ` +
                 `y2="${H - B}" class="${v === 0 ? 'yc-gridmaj' : 'yc-grid'}"/>` +
                 `<text x="${X(v).toFixed(1)}" y="${H - B + 13}" class="rp-ax" ` +
                 `text-anchor="middle">${v > 0 ? '+' + v : v}</text>`;
        }
        for (let v = Math.ceil(y0); v <= Math.floor(y1); v++) {
            g += `<line x1="${L}" y1="${Y(v).toFixed(1)}" x2="${W - R}" ` +
                 `y2="${Y(v).toFixed(1)}" class="${v === 0 ? 'yc-gridmaj' : 'yc-grid'}"/>` +
                 `<text x="${L - 6}" y="${(Y(v) + 3.5).toFixed(1)}" class="rp-ax" ` +
                 `text-anchor="end">${v > 0 ? '+' + v : v}</text>`;
        }
        g += `<line x1="${L}" y1="${Y(TRIG).toFixed(1)}" x2="${W - R}" ` +
             `y2="${Y(TRIG).toFixed(1)}" class="rp-trig"/>` +
             `<text x="${W - R - 4}" y="${(Y(TRIG) - 5).toFixed(1)}" class="rp-ax" ` +
             `text-anchor="end" fill="${AB_RP_C.tightening}">tightening &ge; +${TRIG}</text>` +
             `<text x="${(X(0) - 6).toFixed(1)}" y="${T + 11}" class="rp-ax" ` +
             `text-anchor="end" fill="${AB_RP_C.inverted}">&#9666; inverted</text>`;

        const dots = cloud.map(c =>
            `<circle cx="${X(c[0]).toFixed(1)}" cy="${Y(c[1]).toFixed(1)}" r="2" ` +
            `fill="${AB_RP_C[state(c[0], c[1])]}" opacity=".5"><title>pivot ` +
            `${c[0].toFixed(2)} &middot; 6mo ${c[1].toFixed(2)}</title></circle>`).join('');
        const now = `<circle cx="${X(day.pivot).toFixed(1)}" ` +
            `cy="${Y(day.delta_6mo).toFixed(1)}" r="5" class="rp-now"><title>today ` +
            `${esc(day.date)} &middot; pivot ${day.pivot.toFixed(2)} &middot; 6mo ` +
            `${day.delta_6mo.toFixed(2)}</title></circle>` +
            `<text x="${(X(day.pivot) + 10).toFixed(1)}" ` +
            `y="${(Y(day.delta_6mo) + 4).toFixed(1)}" class="rp-ax" fill="#e2e8f0">today</text>`;
        const axes = `<text x="${W / 2}" y="${H - 3}" class="rp-ax" ` +
            'text-anchor="middle">pivot &mdash; 2yr minus fed funds</text>' +
            `<text x="12" y="${T + 2}" class="rp-ax" text-anchor="end" ` +
            `transform="rotate(-90 12 ${T + 2})">6-month change (floored)</text>`;

        const svg = '<div class="rp-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'role="img" aria-label="The pivot against its floored six-month change, one ' +
            'point a month since 1994, with both green regions shaded and today marked">' +
            g + dots + now + axes + '</svg></div>';
        // Swatches take the SHAPE of the mark they stand for -- an area for the shaded
        // regions, dots for the plotted months. Drawing both as the same square made the
        // region read as an object of its own (user, 2026-08-31).
        const key =
            '<div class="yc-key">' +
              '<span><i class="rp-i-win"></i>shaded &mdash; green window</span>' +
              `<span><i class="rp-i-dot" style="background:${AB_RP_C.tightening}"></i>tightening</span>` +
              `<span><i class="rp-i-dot" style="background:${AB_RP_C.inverted}"></i>inverted</span>` +
              `<span><i class="rp-i-dot" style="background:${AB_RP_C.quiet}"></i>quiet</span>` +
              '<span><i class="rp-i-dot" style="background:#e2e8f0"></i>today</span>' +
            '</div>';
        const far = day.to_tightening != null && day.to_tightening > 0
            ? `<b>${day.to_tightening.toFixed(2)}</b> from the tightening line`
            : `<b>${Math.abs(day.to_inverted).toFixed(2)}</b> from the inverted line`;
        return head + svg + key +
            '<div class="ab-overlapbar">Green fires on <b>either</b> condition, and they ' +
            'are unrelated: a six-month move of <b>+' + TRIG + '</b> or more is the market ' +
            'repricing toward TIGHTENING, a raw pivot below <b>zero</b> is it pricing CUTS. ' +
            'One is the burst’s cause, the other its reaction. Today is ' + far +
            '. The six-month change floors the earlier pivot at zero, so a fading ' +
            'inversion cannot be read as fresh tightening' +
            (day.pivot_prior != null && day.pivot_prior < 0
                ? ` — and it is doing that now: the prior pivot was <b>` +
                  `${day.pivot_prior.toFixed(2)}</b>, floored to 0, which is why the two ` +
                  'figures above read the same.'
                : '.') + '</div>';
    }

    // --- CONCENTRATION (one view) ----------------------------------------------
    // The peak and the print on one axis, because the whole subtlety of this factor is
    // that they are different numbers: the LIGHT reads the running maximum, the
    // sparkline beside it plots today. Drawing both is the only way the pane stops
    // looking like it disagrees with itself.
    function abConcHTML(day) {
        const band = ((AB_WHY.concentration || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">peak</span>' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.peak_pct.toFixed(2)}` +
              '<span class="cc-of">%</span></span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="r">today ${day.current_pct.toFixed(2)}% · ` +
              `${day.off_peak.toFixed(2)}pp off</span>` +
            '</div>';

        const W = 360, H = 96, PL = 10, PR = 10, Y = 30, BH = 20;
        const hi = Math.max(day.green_at * 1.28, day.peak_pct * 1.12);
        const X = v => PL + (v / hi) * (W - PL - PR);
        const seg = (a, b, light) =>
            `<rect x="${X(a).toFixed(1)}" y="${Y}" width="${(X(b) - X(a)).toFixed(1)}" ` +
            `height="${BH}" fill="${AB_IB_BAND[light]}" fill-opacity=".16" ` +
            `stroke="${AB_IB_BAND[light]}" stroke-opacity=".4"/>`;
        const mark = (v, cls, label, up) =>
            `<line x1="${X(v).toFixed(1)}" y1="${up ? Y - 12 : Y + BH}" ` +
            `x2="${X(v).toFixed(1)}" y2="${up ? Y + BH : Y + BH + 12}" class="${cls}"/>` +
            `<text x="${X(v).toFixed(1)}" y="${up ? Y - 16 : Y + BH + 24}" ` +
            `class="cc-mk">${label}</text>`;
        const svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="Semiconductor weight: running peak ${day.peak_pct}% against ` +
            `today's ${day.current_pct}%, on a scale banded at ${day.yellow_at} and ` +
            `${day.green_at} percent">` +
            seg(0, day.yellow_at, 'red') + seg(day.yellow_at, day.green_at, 'yellow') +
            seg(day.green_at, hi, 'green') +
            mark(day.peak_pct, 'cc-peak', 'peak ' + day.peak_pct.toFixed(1) + '%', true) +
            mark(day.current_pct, 'cc-now', 'today ' + day.current_pct.toFixed(1) + '%', false) +
            '</svg>';

        // The roster is a ROSTER. `members` carries tickers and no weights, so there is
        // nothing here to rank or chart, and listing them as chips says exactly that.
        const chips = (day.members || []).map(m =>
            `<span class="cc-chip">${esc(m)}</span>`).join('');
        const rawline = day.raw_peak_pct != null
            ? `The same peak on a RAW-cap basis reads <b>${day.raw_peak_pct}%</b> — about ` +
              '1.09&times; lower, and kept as reference only. Mixing the two conventions ' +
              'into one running maximum would corrupt the number the light is cut on.'
            : '';
        return '<div class="ab-pies">' + hero + svg + '</div>' +
            `<div class="cc-roster"><div class="cc-rh">${day.n_members} GICS ` +
            'semiconductor members · float-adjusted SPY weights</div>' + chips + '</div>' +
            `<div class="ab-overlapbar">The light reads the <b>peak</b>; the strip above ` +
            `reads <b>today</b>. They are ${day.off_peak.toFixed(2)}pp apart, and a peak ` +
            `cannot come back down — which is why red is unreachable here by design. ` +
            rawline + '</div>';
    }

    // ANALOGUES — what this reading looks like against the two bubbles it is usually
    // measured against, and the one it CANNOT see.
    //
    // The view's job is session 28's finding rather than a league table: concentration
    // detects the 2000 kind of bubble and is blind to the 2007 kind, because 2008 was a
    // CREDIT bubble and equity concentration sat near its median through it. So 2007's
    // row is deliberately an absence with a reason, not a number filled in to make the
    // table look complete — and it points at the lights that DO cover that shape.
    function abConcAnaloguesHTML(day) {
        const rows = (day.analogues || []).concat([day.today]).filter(Boolean);
        if (!rows.length) return '<div class="ab-tbd" style="padding:12px 13px">' +
            'no analogues on this reading</div>';
        const top = rows.map(r => r.top10_pct).filter(v => v != null);
        const max = Math.max.apply(null, top.concat([40]));
        const hero =
            '<div class="yc-head">' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.today.top10_pct}` +
              '<i>%</i></span>' +
              '<span class="k">top-10 weight today</span>' +
              `<span class="s">2000 reached ${(day.analogues[0] || {}).top10_pct}%</span>` +
              `<span class="s">tame was ${(day.analogues[2] || {}).top10_pct}%</span>` +
            '</div>';
        // A bar per era on the one measure that spans three of the four. 2007 has no
        // top-10 figure on the record, so it gets no bar — the gap IS the point.
        const bars = rows.map(r => {
            const now = r.era === 'today';
            const w = r.top10_pct != null ? (r.top10_pct / max * 100) : 0;
            return '<div class="ca-row">' +
              `<span class="ca-era${now ? ' now' : ''}">${esc(r.era)}</span>` +
              '<span class="ca-tr">' +
                (r.top10_pct != null
                  ? `<i style="width:${w.toFixed(1)}%" class="${now ? 'now' : ''}"></i>`
                  : '<span class="ca-na">no top-10 figure on the record</span>') +
              '</span>' +
              `<span class="ca-v">${r.top10_pct != null ? r.top10_pct + '%' : '—'}</span>` +
            '</div>';
        }).join('');

        const src = s => s === 'measured'
            ? '<span class="ca-src ok">measured</span>'
            : s === 'published' ? '<span class="ca-src">published</span>'
            : s === 'recalled' ? '<span class="ca-src warn">recalled, unsourced</span>' : '';
        const body = rows.map(r => {
            const now = r.era === 'today';
            return `<tr${now ? ' class="ca-now"' : ''}>` +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(r.era)}` +
                `${r.detected ? '' : '<span class="ca-blind">not detected</span>'}</div>` +
                `<div class="sl">${esc(r.label)}</div></div></td>` +
              `<td>${r.top10_pct != null ? r.top10_pct + '%' : '—'}</td>` +
              `<td class="l">${r.breadth != null
                  ? `<span class="pulled">${r.breadth}</span>` +
                    `<div class="sl">${esc(r.breadth_metric || '')}</div>` : '—'}</td>` +
              `<td class="l">${r.semis_pct != null
                  ? (r.semis_range ? r.semis_range + '%' : r.semis_pct.toFixed(2) + '%')
                    + ' ' + src(r.semis_src)
                  : '<span class="sl">&mdash;</span>'}</td>` +
            '</tr>';
        }).join('');

        const seven = (day.analogues || []).find(a => a.era === '2007') || {};
        return hero +
            `<div class="ca-bars"><div class="ca-bh">Top-10 share of the S&amp;P 500</div>` +
            bars + '</div>' +
            '<div class="ab-scroller"><table class="ab-ledger ca-tbl">' +
            '<thead><tr><th class="l">Era</th><th>Top-10</th><th class="l">Breadth</th>' +
            '<th class="l">Semis</th></tr></thead>' + `<tbody>${body}</tbody></table></div>` +
            '<div class="ab-srcfoot"><b>2007 is the finding, not a gap.</b> ' +
            esc(seven.note || '') + ' No single measure spans all four eras and none is ' +
            'faked to fill the table: RSP is equal-weight and was born in 2003, so 2000 ' +
            'has no RSP/SPY and uses the deep OEX/GSPC stand-in instead. The semi weights ' +
            'for 2000 and the tame baseline are <b>recalled, not sourced</b> — they are ' +
            'the softest numbers here and are marked as such wherever they appear.</div>';
    }

    // --- INFLATION (one view) ---------------------------------------------------
    // Six prints and two lines. A level-only factor has no direction to draw, but the
    // PRINTS are a different series from the rail beside them -- one point per month the
    // BEA published, against one row per day this board looked -- so they are worth
    // their own picture rather than being mistaken for the same thing.
    function abInflationHTML(day) {
        const t = day.trail || [];
        if (!t.length) return '<div class="ab-tbd" style="padding:12px 13px">' +
            'no trail on this reading</div>';
        const band = ((AB_WHY.inflation || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">core PCE</span>' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.yoy.toFixed(2)}` +
              '<span class="cc-of">%</span></span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="r">${Math.abs(day.to_green).toFixed(2)}pp ` +
              `${day.to_green >= 0 ? 'below' : 'above'} the green line</span>` +
            '</div>';
        const W = 360, H = 130, PL = 26, PR = 14, PT = 12, PB = 22;
        const lo = Math.min(day.red_at_or_below - 0.2, Math.min.apply(null, t) - 0.2);
        const hi = Math.max(day.green_above + 0.3, Math.max.apply(null, t) + 0.2);
        const X = i => PL + (i / Math.max(t.length - 1, 1)) * (W - PL - PR);
        const Y = v => PT + (hi - v) / (hi - lo) * (H - PT - PB);
        const line = (v, light, label) =>
            `<line x1="${PL}" y1="${Y(v).toFixed(1)}" x2="${W - PR}" ` +
            `y2="${Y(v).toFixed(1)}" stroke="${AB_IB_BAND[light]}" stroke-width="1" ` +
            'stroke-dasharray="3 3" stroke-opacity=".6"/>' +
            `<text x="${PL - 4}" y="${(Y(v) + 3.5).toFixed(1)}" class="cc-ax">${label}</text>`;
        const path = t.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ',' +
                           Y(v).toFixed(1)).join(' ');
        // WHEN each print is FOR. The axis used to read oldest -> latest, which says
        // nothing about the reporting window -- and core PCE lags 4-6 weeks, so the
        // newest point is a month or two behind the day the light was read. The year
        // rides only on the first label and wherever it changes, so a six-month axis
        // does not repeat the same two digits six times.
        const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const mons = day.trail_months || [];
        const dated = mons.length === t.length;
        const mLabel = (m, always) => {
            const y = m.slice(0, 4), k = +m.slice(5, 7) - 1;
            return MON[k] + (always ? ' ’' + y.slice(2) : '');
        };
        const tick = i => mLabel(mons[i], i === 0 ||
                                mons[i - 1].slice(0, 4) !== mons[i].slice(0, 4));
        const dots = t.map((v, i) =>
            `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" ` +
            `r="${i === t.length - 1 ? 4.5 : 3}" fill="${i === t.length - 1
                ? (AB_IB_BAND[day.light] || '#94a3b8') : '#64748b'}">` +
            `<title>${dated ? tick(i) + ' · ' : ''}${v.toFixed(2)}%</title>` +
            '</circle>').join('');
        // The end labels are anchored INWARD; centred, the last one would overhang the
        // viewBox by half its width.
        const axis = dated
            ? t.map((v, i) => `<text x="${X(i).toFixed(1)}" y="${H - 6}" class="cc-ax2" ` +
                `text-anchor="${i === 0 ? 'start' : i === t.length - 1 ? 'end' : 'middle'}">` +
                `${tick(i)}</text>`).join('')
            : `<text x="${PL}" y="${H - 6}" class="cc-ax2">oldest</text>` +
              `<text x="${W - PR}" y="${H - 6}" class="cc-ax2" text-anchor="end">latest` +
              '</text>';
        const svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="The last ${t.length} core-PCE prints against the 2 and 3.5 ` +
            'percent lines">' +
            line(day.green_above, 'green', day.green_above.toFixed(1)) +
            line(day.red_at_or_below, 'red', day.red_at_or_below.toFixed(1)) +
            `<path d="${path}" fill="none" stroke="#94a3b8" stroke-width="1.5"/>` + dots +
            axis + '</svg>';
        const vals = t.map((v, i) =>
            `<span class="cc-pt${i === t.length - 1 ? ' now' : ''}">${v.toFixed(2)}</span>`)
            .join('<span class="cc-sep">›</span>');
        return '<div class="ab-pies">' + hero + svg + '</div>' +
            `<div class="cc-trail">${vals}</div>` +
            '<div class="ab-overlapbar">' +
            (dated ? `<b>${mLabel(mons[0], true)}</b> to <b>${mLabel(mons[mons.length - 1],
                true)}</b> — six monthly prints, ` : 'Six monthly prints, ') +
            `${day.climbing
                ? 'each at or above the last' : 'not monotonic — it has come off its high'}. ` +
            'The axis is the REFERENCE month, not the publication date: core PCE lands ' +
            '4–6 weeks after the month it measures, so the newest point here is ' +
            'always a month or two behind the day this light was read. ' +
            `This is core PCE, which runs <b>0.3–0.5pp below</b> CPI, so a CPI print read ` +
            'against these lines would sit a third of a band too high.</div>';
    }

    // --- CAPEX SPIGOT (factor #8) ----------------------------------------------
    // TWO marks per company, and only one of them is coloured: the prior year is what
    // WAS and wears the neutral, the guided year is what is being claimed now and
    // wears the accent. Same encoding as capex_pressure's dumbbell — the past is a
    // reference, not a second entity — and it keeps green/yellow/red free to mean the
    // light, which on this factor is a single aggregate rather than five per-name
    // bands. #6366f1 is the indigo already validated against this surface.
    const AB_CS_NOW = '#6366f1';
    const AB_CS_WAS = '#475569';

    // Prior against guided, per company, sorted by guided dollars — which is also the
    // order of influence, because this aggregate is DOLLAR-weighted.
    function abSpigotBarsSVG(day) {
        const ns = day.names || [];
        if (!ns.length) return '';
        const W = 360, RH = 30, PT = 14, PB = 22, PL = 46, PR = 44;
        const H = PT + ns.length * RH + PB;
        const hi = Math.max.apply(null, ns.map(n => n.guidance_b || 0)) * 1.1 || 1;
        const X = v => (v / hi) * (W - PL - PR);
        const rows = ns.map((n, i) => {
            const y = PT + i * RH;
            const wp = Math.max(X(n.prior_b || 0), 1), wg = Math.max(X(n.guidance_b || 0), 1);
            return `<text x="${PL - 7}" y="${(y + 15).toFixed(1)}" class="cs-tk">` +
                   `${esc(n.key)}</text>` +
                   `<rect x="${PL}" y="${y + 2}" width="${wp.toFixed(1)}" height="7" rx="2" ` +
                   `fill="${AB_CS_WAS}"><title>${esc(n.key)} prior year — ` +
                   `$${n.prior_b}B</title></rect>` +
                   `<rect x="${PL}" y="${y + 12}" width="${wg.toFixed(1)}" height="9" rx="2" ` +
                   `fill="${AB_CS_NOW}"><title>${esc(n.key)} guided — $${n.guidance_b}B, ` +
                   `${n.weight_pct}% of the basket</title></rect>` +
                   `<text x="${(PL + wg + 5).toFixed(1)}" y="${(y + 20).toFixed(1)}" ` +
                   `class="cs-v">$${n.guidance_b}B</text>`;
        }).join('');
        return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Prior-year ' +
            'capex against guided capex for each company, in billions">' + rows +
            `<text x="${PL}" y="${H - 6}" class="cs-lg">` +
            `<tspan fill="${AB_CS_WAS}">&#9632;</tspan> prior year   ` +
            `<tspan fill="${AB_CS_NOW}">&#9632;</tspan> guided</text>` + '</svg>';
    }

    // THE SPIGOT — the aggregate, and the five guides it is made of.
    function abSpigotHTML(day) {
        const band = ((AB_WHY.capex_spigot || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">reading</span>' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">` +
              `${day.yoy >= 0 ? '+' : ''}${Math.round(day.yoy)}<span class="cs-of">%</span>` +
              '</span>' +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              `<span class="r">$${day.total_prior_b}B &rarr; $${day.total_guidance_b}B</span>` +
            '</div>';
        // Each row carries its SHARE of the guided dollars, because that is what this
        // name is worth to the light. A dollar-weighted aggregate has no equal members.
        const rows = (day.names || []).map(n =>
            '<div class="ab-lrow">' +
              `<span class="ab-sw" style="background:${AB_CS_NOW}"></span>` +
              `<span class="nm2">${esc(n.key)}</span>` +
              `<span class="fig"><b>${n.yoy_pct >= 0 ? '+' : ''}` +
              `${Math.round(n.yoy_pct)}%</b>` +
              `<span class="alt">${n.weight_pct}% of basket</span></span>` +
            '</div>').join('');
        const miss = (day.undisclosed || []).length
            ? ` <b>${day.undisclosed.map(esc).join(', ')}</b> did not guide, so ` +
              'the sum is short a member rather than carrying a zero.' : '';
        return '<div class="ab-pies">' + hero + abSpigotBarsSVG(day) +
            '<div class="ab-lens cs-leg">' + rows + '</div></div>' +
            `<div class="ab-overlapbar">$${day.total_prior_b}B of prior spend against ` +
            `$${day.total_guidance_b}B guided. Dollar-weighted on purpose — <b>sum of ` +
            `guidance &divide; sum of prior</b>, so the biggest spender moves the light ` +
            `most. ` +
            `That is the opposite of capex pressure next door, which is unweighted so ` +
            `ORCL stays a canary. No arrow here: the measure is already a RATE, and an ` +
            `arrow on a rate would be a second derivative.${miss}</div>`;
    }

    // SOURCES — every guide with where it was read and when. The shape session 48
    // called worth copying, and it earns itself here the same way: one of the five has
    // no pull date recorded at all.
    function abSpigotSourcesHTML(day) {
        const ns = day.names || [];
        if (!ns.length) return '<div class="ab-tbd" style="padding:12px 13px">' +
            'no guidance on this record</div>';
        const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); }
                            catch (e) { return ''; } };
        // Aged against the READING's own date, never against today: a July print must
        // not look staler every time the panel is opened.
        const age = d => {
            if (!d || !day.date) return null;
            const ms = Date.parse(day.date + 'T00:00:00Z') - Date.parse(d + 'T00:00:00Z');
            return isNaN(ms) ? null : Math.round(ms / 86400000);
        };
        const body = ns.map(n => {
            const a = age(n.refreshed_at);
            return '<tr>' +
              `<td class="l"><div class="mdl"><div class="nm2">${esc(n.key)}</div>` +
                `<div class="sl">${esc(n.basis || '')}</div></div></td>` +
              `<td>$${n.guidance_b}B</td>` +
              `<td class="l">${n.refreshed_at
                  ? `<span class="pulled">${esc(n.refreshed_at)}` +
                    `${a != null ? ` <span class="age">${a}d</span>` : ''}</span>`
                  : '<span class="cs-nodate">no pull date</span>'}</td>` +
              `<td class="l">${n.prior_derived
                  ? `<span class="pulled">$${n.prior_b}B</span>` +
                    `<div class="sl">${esc((n.prior_period_start || '').slice(0, 7))}` +
                    `..${esc((n.prior_period_end || '').slice(0, 7))}</div>`
                  : '<span class="cs-nodate">no prior</span>'}</td>` +
              `<td class="l">${n.url ? `<a class="ab-src-a" href="${esc(n.url)}" ` +
                  `target="_blank" rel="noopener noreferrer">${esc(host(n.url) || 'source')}</a>`
                  : '<span class="sl">&mdash;</span>'}</td>` +
            '</tr>';
        }).join('');
        const nodate = ns.filter(n => !n.refreshed_at).map(n => n.key);
        return '<div class="ab-scroller"><table class="ab-ledger cs-tbl">' +
            '<thead><tr><th class="l">Company &amp; basis</th><th>Guided</th>' +
            '<th class="l">Pulled</th><th class="l">Prior (derived)</th>' +
            '<th class="l">Source</th>' +
            '</tr></thead>' + `<tbody>${body}</tbody></table></div>` +
            '<div class="ab-srcfoot">Only the GUIDED figure is model-pulled. The ' +
            'PRIOR is <b>derived from SEC filings</b> — capex plus finance-lease ' +
            'principal payments over the year each company actually guides against, ' +
            'which for ORCL is its own June-to-May fiscal year and for the other four ' +
            'is the calendar year (MSFT guides on the calendar year even though its ' +
            'fiscal one ends in June — reading its fiscal year instead would be 29% ' +
            'light). So the soft half and the hard half are separated, and the hard ' +
            'half updates itself.' +
            (nodate.length ? ` <b>${nodate.map(esc).join(', ')}</b> carries no pull date ` +
             'at all, so its age against this reading cannot be stated.' : '') +
            '</div>';
    }

    // --- CAPEX PRESSURE (factor #7) --------------------------------------------
    // Bars wear the BAND colours, and here that is the literal meaning rather than a
    // borrowing: each bar IS a per-company light, and the majority of those five
    // lights is the factor's light. Painting them anything else would put a second
    // colour language on top of the one the row above already speaks.
    const AB_CP_C = { green: '#4ade80', yellow: '#fbbf24', red: '#f87171' };

    // Five ratios against the two gates that cut them. A bar list, not a pie: this is
    // five independent magnitudes measured against a threshold, not parts of a whole,
    // and the thresholds are the whole point — you read this to see who is over 100.
    function abCapexBarsSVG(day) {
        const ns = (day.names || []).slice().sort((a, b) => b.pct - a.pct);
        if (!ns.length) return '';
        const W = 360, RH = 26, PT = 16, PB = 20, PL = 44, PR = 34;
        const H = PT + ns.length * RH + PB;
        const hi = Math.max(day.green_above * 1.25,
                            Math.max.apply(null, ns.map(n => n.pct)) * 1.08);
        const X = v => PL + (v / hi) * (W - PL - PR);
        const gate = (v, label) =>
            `<line x1="${X(v).toFixed(1)}" y1="${PT - 6}" x2="${X(v).toFixed(1)}" ` +
            `y2="${H - PB + 3}" class="cp-gate"/>` +
            `<text x="${X(v).toFixed(1)}" y="${H - PB + 14}" class="cp-gl">${label}</text>`;
        const bars = ns.map((n, i) => {
            const y = PT + i * RH;
            const w = Math.max(X(n.pct) - PL, 1);
            return `<text x="${PL - 7}" y="${(y + 12).toFixed(1)}" class="cp-tk">` +
                   `${esc(n.key)}</text>` +
                   `<rect x="${PL}" y="${y + 3}" width="${w.toFixed(1)}" height="12" ` +
                   `rx="3" fill="${AB_CP_C[n.light] || '#94a3b8'}" fill-opacity=".85">` +
                   `<title>${esc(n.key)} — ${n.pct}% of operating cash flow</title></rect>` +
                   `<text x="${(PL + w + 5).toFixed(1)}" y="${(y + 13).toFixed(1)}" ` +
                   `class="cp-v">${n.pct}%</text>`;
        }).join('');
        return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Capex as a ' +
            `share of operating cash flow for ${ns.length} companies, against the ` +
            `${day.yellow_at}% and ${day.green_above}% gates">` +
            gate(day.yellow_at, day.yellow_at + '%') +
            gate(day.green_above, day.green_above + '%') + bars + '</svg>';
    }

    // THE FIVE — who is over the gates, and what the majority made of it.
    function abCapexNamesHTML(day) {
        const band = ((AB_WHY.capex_pressure || {}).bands || [])
            .find(b => b.light === day.light) || {};
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">reading</span>' +
              `<span class="v abh-${AB_LC[day.light] || 'y'}">${day.through}` +
              `<span class="cp-of">/${day.n_names}</span></span>` +
              `${band.mean ? `<span class="s">${esc(band.mean)}</span>` : ''}` +
              '<span class="r">through the ' + day.green_above + '% gate</span>' +
            '</div>';
        const ns = (day.names || []).slice().sort((a, b) => b.pct - a.pct);
        const rows = ns.map(n =>
            '<div class="ab-lrow">' +
              `<span class="ab-sw" style="background:${AB_CP_C[n.light] || '#94a3b8'}"></span>` +
              `<span class="nm2">${esc(n.key)}</span>` +
              `<span class="fig"><b>${n.pct}%</b>` +
              `<span class="alt">${esc((n.period_end || '').slice(0, 7))}</span></span>` +
            '</div>').join('');
        // The tie-break is named only when one actually fired. Five lights can deadlock
        // and the resolution defers toward red on purpose; a pane that showed just the
        // winning colour would hide that a rule was involved at all.
        const tie = day.tie_break
            ? `<div class="cp-tie"><span class="k">tie-break</span> ${esc(day.tie_break)}</div>`
            : '';
        const c = day.counts || {};
        const named = (day.through_names || []).length
            ? ` (${(day.through_names || []).map(esc).join(' and ')})` : '';
        return '<div class="ab-pies">' + hero + abCapexBarsSVG(day) +
            '<div class="ab-lens cp-leg">' + rows + '</div></div>' + tie +
            `<div class="ab-overlapbar"><b>${c.red || 0}</b> of ${day.n_names} are ` +
            `self-funding under ${day.yellow_at}%; <b>${c.green || 0}</b>${named} sit ` +
            `above ${day.green_above}% and are funding the build off the balance sheet. ` +
            'Unweighted on purpose — dollar-weighting would shrink ORCL from canary to ' +
            'rounding error.</div>';
    }

    // DIRECTION — each name against ITSELF a year ago, which is what the arrow reads.
    //
    // COLOUR MEANS SOMETHING DIFFERENT HERE, on purpose (user, 2026-08-31). In The five
    // a mark wears the band its LEVEL sits in. In this view it wears the direction of
    // the MOVE against the board's inverted scale: green is pro-burst, so a ratio
    // RISING is travelling toward green and is drawn green even while its level is
    // still red, and a ratio falling is drawn red. The two views answer different
    // questions — where a name stands, and which way it is going — and a name can
    // honestly be red in one and green in the other. The caption under the marks says
    // so, because a reader arriving from the first view will otherwise read these as
    // bands.
    function _cpMove(delta) {
        return delta > 0 ? AB_CP_C.green : delta < 0 ? AB_CP_C.red : '#94a3b8';
    }

    function abCapexDirectionHTML(day) {
        const ns = (day.names || []).filter(n => n.prior_pct != null)
            .slice().sort((a, b) => b.delta - a.delta);
        if (!ns.length) return '<div class="ab-tbd" style="padding:12px 13px">' +
            'no year-ago window on this reading</div>';
        const worse = ns.filter(n => n.delta > 0).length;
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">burning more</span>' +
              `<span class="v">${worse}<span class="cp-of">/${ns.length}</span></span>` +
              '<span class="s">than a year ago</span>' +
              `<span class="r">arrow ${esc(day.arrow || 'none')}</span>` +
            '</div>';
        // A dumbbell per name: where it was, where it is, joined. The pair is the point
        // -- a level alone cannot say whether the build is accelerating.
        const W = 360, RH = 26, PT = 16, PB = 20, PL = 44, PR = 34;
        const H = PT + ns.length * RH + PB;
        const hi = Math.max.apply(null, ns.map(n => Math.max(n.pct, n.prior_pct))) * 1.12;
        const X = v => PL + (v / hi) * (W - PL - PR);
        const marks = ns.map((n, i) => {
            const y = PT + i * RH + 9;
            return `<text x="${PL - 7}" y="${(y + 4).toFixed(1)}" class="cp-tk">` +
                   `${esc(n.key)}</text>` +
                   `<line x1="${X(n.prior_pct).toFixed(1)}" y1="${y}" ` +
                   `x2="${X(n.pct).toFixed(1)}" y2="${y}" class="cp-join" ` +
                   `stroke="${_cpMove(n.delta)}" stroke-opacity=".55"/>` +
                   `<circle cx="${X(n.prior_pct).toFixed(1)}" cy="${y}" r="3.5" ` +
                   `class="cp-then"><title>${esc(n.key)} a year ago — ` +
                   `${n.prior_pct}%</title></circle>` +
                   `<circle cx="${X(n.pct).toFixed(1)}" cy="${y}" r="4.5" ` +
                   `fill="${_cpMove(n.delta)}"><title>${esc(n.key)} now — ${n.pct}%, ` +
                   `${n.delta > 0 ? 'up' : n.delta < 0 ? 'down' : 'flat'} ` +
                   `${Math.abs(n.delta)} points toward ` +
                   `${n.delta > 0 ? 'green' : 'red'}</title></circle>` +
                   `<text x="${(X(Math.max(n.pct, n.prior_pct)) + 6).toFixed(1)}" ` +
                   `y="${(y + 4).toFixed(1)}" class="cp-v">+${n.delta}</text>`;
        }).join('');
        const svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="Each company's capex-to-cash-flow ratio a year ago and now; ` +
            `colour marks the direction of the move, green toward the pro-burst end">` +
            marks + '</svg>';
        const rows = ns.map(n =>
            '<div class="ab-lrow">' +
              `<span class="ab-sw" style="background:${_cpMove(n.delta)}"></span>` +
              `<span class="nm2">${esc(n.key)}</span>` +
              `<span class="fig"><b>${n.prior_pct}% &rarr; ${n.pct}%</b>` +
              `<span class="alt">${n.delta > 0 ? '+' : ''}${n.delta}</span></span>` +
            '</div>').join('');
        // States the basis rather than assuming it. Rows recorded before 2026-08-31 hold
        // a fiscal-YEAR prior against a TTM current -- not comparable, and the delta on
        // such a row is a difference between two different measurements.
        const mixed = ns.filter(n => !n.comparable).length;
        // Identity is never colour alone, and here the colour is carrying a meaning
        // it does NOT carry one view to the left — so it gets named rather than left to
        // be inferred from five marks that all happen to point the same way today.
        const key =
            '<div class="cp-key">' +
              `<span><i style="background:${AB_CP_C.green}"></i>toward green — ` +
              'ratio rising, burning more</span>' +
              `<span><i style="background:${AB_CP_C.red}"></i>toward red — ` +
              'ratio falling, pulling back</span>' +
              '<span class="cp-keynote">colour is the MOVE here, not the band</span>' +
            '</div>';
        return '<div class="ab-pies">' + hero + svg +
            '<div class="ab-lens cp-leg">' + rows + '</div></div>' + key +
            `<div class="ab-overlapbar">Both windows are four contiguous quarters of the ` +
            `same company, one year apart` +
            (mixed ? `, except <b>${mixed}</b> recorded before the basis was fixed — ` +
                     'those pair a fiscal-year prior with a TTM current and are not ' +
                     'comparable' : '') +
            `. Ratios RISING means burning more, which is why the arrow points ` +
            `<b>${esc(day.arrow || 'nowhere')}</b> toward burst.</div>`;
    }

    // --- HEAVY HAUL (factor #5) ------------------------------------------------
    // Sector hues for the Composition view. THREE hues and a neutral, and the count is
    // MEASURED, not chosen: validate_palette.js (dataviz skill) passes this trio
    // all-pairs on the panel's own #0f172a surface — worst CVD ΔE 8.2 deutan,
    // normal-vision 18.5 — and FAILS on any fourth hue, violet against indigo measuring
    // ΔE 14.1 to NORMAL vision against a hard floor of 15. So the three real sectors get
    // hue and the residue gets the neutral every "Other" bucket gets, which is also what
    // stops it reading as a fourth sector. Same three values regulatory's map uses: they
    // never appear on screen together, and one validated set beats two.
    const AB_HAUL_HUES = { rail: '#6366f1', ltl: '#ec4899',
                           truckload: '#0e9fbf', specialised: '#8b98a8' };
    const AB_HAUL_LBL = { rail: 'Rail', ltl: 'LTL',
                          truckload: 'Truckload', specialised: 'Specialised' };

    // The index picture is the CHARTS tab's own heavy_haul entry, fetched once and
    // cached in the same `_chartData` that tab uses. Reused rather than re-sent with the
    // ledger for two reasons: `_build_heavy_haul` calls the FACTOR's build_index, so the
    // chart and the light cannot disagree about what the index is; and 252 bars stored
    // in every daily ledger row would put the same series on disk once a day forever.
    let _haulChartReq = null;
    function abHaulChart() {
        if (_chartData) return (_chartData.charts || []).find(c => c.id === 'heavy_haul') || null;
        if (!_haulChartReq) {                     // one flight, then one re-render
            _haulChartReq = fetch(`${API_BASE}/get_board_charts`)
                .then(r => r.json())
                .then(j => { _chartData = j; renderBubbleOverview(); })
                .catch(() => { /* the table still renders; only the picture is missing */ });
        }
        return null;
    }

    // The index against its own 50 and 200-bar MAs, with the day on screen marked.
    // Inline SVG, not lightweight-charts: this pane is rebuilt by innerHTML on every
    // rail click, and a charting library instantiated into replaced DOM leaks its
    // handles — the Charts tab keeps `_boardCharts` precisely to tear them down. The
    // panel's other pictures (pips, pies, map) are inline SVG for the same reason.
    // Trimmed to the last 252 bars because 252 is the window the factor MEASURES on
    // (the 52-week high its gate counts from). The MAs are computed by charts.py over
    // the full history and only then trimmed, so both lines are seeded at the left edge.
    function abHaulIndexSVG(ch, markDate, highDate) {
        const byName = {};
        (ch.series || []).forEach(s => { byName[s.name] = s.data || []; });
        const idx = byName['Index'] || [];
        if (idx.length < 2) return '';
        const N = 252, from = idx.length > N ? idx[idx.length - N].time : idx[0].time;
        const cut = a => (a || []).filter(p => p.time >= from);
        const lines = [['200-bar MA', '#f8fafc'], ['50-bar MA', '#22d3ee'], ['Index', '#a78bfa']]
            .map(pair => ({ name: pair[0], color: pair[1], pts: cut(byName[pair[0]]) }))
            .filter(s => s.pts.length > 1);
        if (!lines.length) return '';

        const W = 680, H = 190, PL = 6, PR = 44, PT = 10, PB = 14;
        const days = cut(idx).map(p => p.time);
        const x0 = Date.parse(days[0]), x1 = Date.parse(days[days.length - 1]);
        let lo = Infinity, hi = -Infinity;
        lines.forEach(s => s.pts.forEach(p => {
            if (p.value < lo) lo = p.value;
            if (p.value > hi) hi = p.value;
        }));
        const pad = (hi - lo) * 0.08 || 1;
        lo -= pad; hi += pad;
        const X = t => PL + (Date.parse(t) - x0) / (x1 - x0 || 1) * (W - PL - PR);
        const Y = v => PT + (hi - v) / (hi - lo || 1) * (H - PT - PB);
        const path = s => s.pts.map((p, i) => (i ? 'L' : 'M') + X(p.time).toFixed(1) +
                                              ',' + Y(p.value).toFixed(1)).join(' ');

        // The marked day and the 52-week high are the two dates the ladder is computed
        // from, so they are the two the picture names. Drawn only when they fall inside
        // the window: a high older than a year cannot exist by definition, but a rail
        // day can predate the trim on a factor whose history outruns it.
        const ix = lines.filter(s => s.name === 'Index')[0];
        const inWin = d => d && d >= days[0] && d <= days[days.length - 1];
        const at = d => ix.pts.filter(p => p.time >= d)[0] || ix.pts[ix.pts.length - 1];
        let marks = '';
        if (inWin(highDate)) {
            const hx = X(at(highDate).time).toFixed(1);
            marks += `<line x1="${hx}" y1="${PT}" x2="${hx}" y2="${H - PB}" class="hh-high"/>` +
                     `<text x="${(+hx + 4).toFixed(1)}" y="${PT + 9}" class="hh-mk">52wk high</text>`;
        }
        if (inWin(markDate)) {
            const p = at(markDate), mx = X(p.time).toFixed(1);
            marks += `<line x1="${mx}" y1="${PT}" x2="${mx}" y2="${H - PB}" class="hh-mark"/>` +
                     `<circle cx="${mx}" cy="${Y(p.value).toFixed(1)}" r="3.5" class="hh-dot"/>`;
        }
        // Direct labels at the right edge — three series, so identity is never carried
        // by colour alone even without a legend box.
        const tags = lines.map(s => {
            const p = s.pts[s.pts.length - 1];
            return `<text x="${W - PR + 5}" y="${(Y(p.value) + 3.5).toFixed(1)}" ` +
                   `class="hh-tag" fill="${s.color}">${esc(s.name.replace('-bar MA', ''))}</text>`;
        }).join('');
        return '<div class="hh-chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
            `aria-label="Heavy-haul freight index over the last ${days.length} trading bars ` +
            `against its 50 and 200-bar moving averages">` +
            lines.map(s => `<path d="${path(s)}" fill="none" stroke="${s.color}" ` +
                           `stroke-width="${s.name === 'Index' ? '2' : '1.5'}"` +
                           `${s.name === 'Index' ? '' : ' stroke-opacity=".7"'}/>`).join('') +
            marks + tags + '</svg></div>';
    }

    // CONSTITUENTS — the picture, then every name against its OWN trend.
    // Sorted by distance from its own 50, STRONGEST first (user, 2026-08-29), so the
    // column reads down from what is still holding its trend into what has lost it and
    // the crossing point is a rule rather than a colour. Deliberately no red/green on the rows: on
    // this board those hues mean the LIGHT, and this light is INVERTED — a name below
    // its 50 is bearish for freight and therefore pro-burst for the factor, so painting
    // it red would say the opposite of what red means one row above it.
    function abHaulNamesHTML(day) {
        // Priced names by distance from their 50; an UNPRICED name (null — no close past
        // the carry limit) sorts to the bottom instead of poisoning the comparator.
        const names = (day.names || []).slice().sort((a, b) =>
            ((a.vs50 == null) - (b.vs50 == null)) || (b.vs50 - a.vs50));
        // The counts are out of the names that HAVE a price. With nothing missing this is
        // n_names and the panel reads exactly as it always did.
        const of = (day.priced_n != null && day.priced_n < day.n_names) ? day.priced_n : day.n_names;
        const unp = day.unpriced || [];
        if (!names.length) return '<div class="ab-tbd" style="padding:12px 13px">no ledger for this day</div>';
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">below their own 50</span>' +
              `<span class="v">${day.below50_n}<span class="hh-of">/${of}</span></span>` +
              `<span class="s">${day.below200_n} of ${of} below the 200</span>` +
              (unp.length ? `<span class="s" style="color:#fbbf24">${unp.length} unpriced · ` +
                            `${unp.map(u => esc(u.key)).join(', ')}</span>` : '') +
              `<span class="r">index ${day.vs50 >= 0 ? '+' : ''}${day.vs50.toFixed(1)}% vs its 50</span>` +
            '</div>';
        const ch = abHaulChart();
        const pic = ch && !ch.error && !ch.placeholder
            ? abHaulIndexSVG(ch, day.date, day.high_date)
            : '<div class="ab-tbd" style="padding:10px 13px">index chart loading…</div>';

        // One scale for both columns, taken from the day's own widest deviation, so the
        // two bars on a row are comparable and nothing is clipped at a fixed ceiling.
        const span = Math.max.apply(null, names.filter(n => n.vs50 != null)
                                    .map(n => Math.abs(n.vs50))
                                    .concat(names.filter(n => n.vs200 != null)
                                                 .map(n => Math.abs(n.vs200)))
                                    .concat([0])) || 1;
        const dev = v => {
            const w = Math.abs(v) / span * 40;
            return '<svg class="hh-dev" viewBox="0 0 88 12" width="88" height="12">' +
                   '<line x1="44" y1="1" x2="44" y2="11" class="hh-zero"/>' +
                   `<rect x="${(v < 0 ? 44 - w : 44).toFixed(1)}" y="3.5" ` +
                   `width="${w.toFixed(1)}" height="5" rx="2" class="hh-bar"/></svg>`;
        };
        const num = v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
        // The rule sits where the sign flips — the one place on the table that says
        // "everything below this line is under its own trend". Drawn only when there is
        // something on BOTH sides of it: a rule above row one separates the table from
        // nothing and reads as a stray border.
        let ruled = names[0].vs50 != null && names[0].vs50 < 0;
        const cell = v => `<td class="l hh-c2"><span class="hh-cell">${dev(v)}` +
                          `<b>${num(v)}</b></span></td>`;
        const body = names.map(n => {
            let cross = false;
            if (!ruled && n.vs50 != null && n.vs50 < 0) { cross = true; ruled = true; }
            return `<tr${cross ? ' class="hh-cross"' : ''}>` +
              '<td class="l"><span class="nm2">' +
                `<span class="ab-sw" style="background:${AB_HAUL_HUES[n.group] || '#8b98a8'}"></span>` +
                `${esc(n.name)}` +
                `<span class="hh-tk">${esc(n.key)} · ${esc(AB_HAUL_LBL[n.group] || n.group)}` +
                  // CARRIED within the limit reads as a note; PAST it reads as an alert.
                  (n.carried_bars ? ` · <span style="color:#94a3b8">last known, ` +
                      `${n.carried_bars} session${n.carried_bars > 1 ? 's' : ''} back</span>` : '') +
                  (n.missing_bars ? ` · <span style="color:#fbbf24">no price for ` +
                      `${n.missing_bars} sessions</span>` : '') +
                `</span>` +
              '</span></td>' +
              (n.last == null
                  ? '<td class="hh-c1" style="color:#fbbf24">—</td>' +
                    '<td class="l hh-c2">—</td><td class="l hh-c2">—</td>'
                  : `<td class="hh-c1">${n.last.toFixed(2)}</td>` + cell(n.vs50) + cell(n.vs200)) +
            '</tr>';
        }).join('');
        const gate = day.cond_no_high
            ? `the 52-week high is <b>${day.bars_since_high}</b> bars back, past the ` +
              `<b>${day.gate_bars}</b>-bar gate`
            : `<b>${day.gate_bars_remaining}</b> bars to the ${day.gate_bars}-bar gate on ` +
              `<b>${esc(day.gate_date || '—')}</b>, absent a new high`;
        return '<div class="ab-pies hh-top">' + hero + pic + '</div>' +
            '<div class="ab-scroller"><table class="ab-ledger hh-tbl">' +
            '<thead><tr><th class="l">Name</th><th class="hh-c1">Last</th>' +
            '<th class="l hh-c2">vs its 50</th>' +
            '<th class="l hh-c2">vs its 200</th></tr></thead>' +
            `<tbody>${body}</tbody></table></div>` +
            `<div class="ab-overlapbar"><b>${day.below50_n}</b> of ${of} names sit below ` +
            `their own 50-bar MA while the index is <b>${num(day.vs200)}</b> against its 200 — ` +
            `${gate}.` +
            (unp.length
                ? ` <b style="color:#fbbf24">${unp.map(u => esc(u.key) + ' has had no price for ' +
                      u.bars + ' sessions').join('; ')}</b> — past the ${day.carry_limit}-session ` +
                  `carry limit, so ${unp.length > 1 ? 'they are' : 'it is'} left out of the counts ` +
                  'and held flat in the index until it prints again.'
                : '') +
            '</div>';
    }

    // COMPOSITION — what the basket is MADE of, which is the case for weighting it flat.
    // Four slices, inside the <=6 a pie can carry; the sixteen names get BARS underneath,
    // which is the form that actually compares sixteen magnitudes. The rule across them
    // is the equal weight each name is given regardless, so the gap between a bar and
    // that rule is the distortion cap weighting would introduce.
    function abHaulCompositionHTML(day, all) {
        // Caps ride on the newest ledger day only — attaching today's to a three-week-old
        // row would present today's composition as that day's. A recorded day carries the
        // caps that were true when it was written, so an older day usually has its own.
        const has = d => ((d || {}).names || []).some(n => n.cap != null);
        const src = has(day) ? day : (all || []).filter(has)[0];
        if (!src) return '<div class="ab-tbd" style="padding:12px 13px">no market caps on this ' +
            'day — composition is recorded from the newest reading forward</div>';
        const rows = (src.names || []).filter(n => n.cap != null).sort((a, b) => b.cap - a.cap);
        const missing = (src.names || []).filter(n => n.cap == null);
        const tot = rows.reduce((s, n) => s + n.cap, 0);
        if (!tot) return '<div class="ab-tbd" style="padding:12px 13px">market caps unavailable</div>';

        const g = {};
        rows.forEach(n => { g[n.group] = (g[n.group] || 0) + n.cap; });
        const order = ['rail', 'ltl', 'specialised', 'truckload'];
        const inPie = order.filter(k => g[k]);
        const slices = inPie.map(k => ({
            value: g[k], fill: AB_HAUL_HUES[k],
            title: `${AB_HAUL_LBL[k]} — ${abB(g[k] / 1e9)} (${(g[k] / tot * 100).toFixed(1)}%)`
        }));
        const each = 100 / (src.names || []).length;          // 6.25% — the equal weight
        const railPct = (g.rail || 0) / tot * 100;
        const railN = rows.filter(n => n.group === 'rail').length;
        const hero =
            '<div class="ab-hero">' +
              '<span class="k">rail share of cap</span>' +
              `<span class="v">${Math.round(railPct)}<span class="hh-of">%</span></span>` +
              `<span class="s">${railN} of ${src.names.length} names</span>` +
              `<span class="r">${(railN * each).toFixed(1)}% by design</span>` +
            '</div>';
        const pie = '<svg viewBox="0 0 300 172" role="img" aria-label="Market capitalisation of ' +
            `the basket by sub-sector: rail ${Math.round(railPct)} percent of ` +
            `${abB(tot / 1e9)}">` + abPie(150, 82, 66, slices, tot) + '</svg>';
        const legend = inPie.map(k =>
            '<div class="ab-lrow">' +
              `<span class="ab-sw" style="background:${AB_HAUL_HUES[k]}"></span>` +
              `<span class="nm2">${esc(AB_HAUL_LBL[k])}</span>` +
              `<span class="fig"><b>${(g[k] / tot * 100).toFixed(1)}%</b> ` +
              `<span class="alt">${(rows.filter(n => n.group === k).length * each).toFixed(2)}% ` +
              'by design</span></span>' +
            '</div>').join('');

        const max = rows[0].cap / tot * 100;
        const bars = rows.map(n => {
            const pct = n.cap / tot * 100;
            return '<div class="hh-brow">' +
              `<span class="hh-bk">${esc(n.key)}</span>` +
              '<span class="hh-btr">' +
                `<i style="width:${(pct / max * 100).toFixed(2)}%;` +
                `background:${AB_HAUL_HUES[n.group] || '#8b98a8'}"></i>` +
                `<u style="left:${(each / max * 100).toFixed(2)}%"></u>` +
              '</span>' +
              `<span class="hh-bc">${abB(n.cap / 1e9)}</span>` +
              `<span class="hh-bv">${pct.toFixed(1)}%</span>` +
            '</div>';
        }).join('');
        const miss = missing.length
            ? ` ${missing.length} name${missing.length > 1 ? 's' : ''} could not be sized (` +
              missing.map(n => esc(n.key)).join(', ') + ') and sit outside the total.'
            : '';
        return '<div class="ab-pies hh-comp">' + hero + pie +
            '<div class="ab-lens hh-leg">' + legend + '</div></div>' +
            '<div class="hh-bars"><div class="hh-bhd">Every name by market cap · the rule is the ' +
            `<b>${each.toFixed(2)}%</b> each one gets regardless</div>${bars}</div>` +
            `<div class="ab-overlapbar">Three rails are <b>${railPct.toFixed(1)}%</b> of the ` +
            `basket's ${abB(tot / 1e9)} and would run the light under cap weighting; equal weight ` +
            `gives them <b>${(railN * each).toFixed(1)}%</b> and lets the ${rows.length - railN} ` +
            `smaller names be seen.${miss}</div>`;
    }

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
        },
        heavy_haul: {
            // CONSTITUENTS leads: the light is a statement about the basket, and the basket
            // is what the first view shows. Composition is the argument for HOW it is
            // weighted, which is the question you ask second.
            views:   [{ key: 'names',       label: 'Constituents' },
                      { key: 'composition', label: 'Composition' }],
            value:   d => d.vs200,
            reading: d => (d.vs200 >= 0 ? '+' : '') + d.vs200.toFixed(1) + '%',
            light:   d => d.light,
            // A tenth of the reading's own precision (it is published to 0.1). Nothing
            // should ever trip it: this ledger replays stored CLOSES, which are not
            // restated, so a re-derived day equals the recorded one.
            tol:     0.05,
            // ...which is why the re-derivation banner does NOT borrow premium_share's
            // wording. Nothing was re-priced here; the same bars were read again.
            reconLabel: 'replayed from the same closes',
            count:   d => d.n_names + ' names',
            // The LADDER's own inputs, so the two conditions behind the light are on screen
            // without spending a view on them: how many names are under their 50, where the
            // index sits against its own 50, and how far the self-executing gate has left.
            figures: d => [['below 50', d.below50_n + '/' + (d.priced_n ?? d.n_names)],
                           ['vs 50MA', (d.vs50 >= 0 ? '+' : '') + d.vs50.toFixed(1) + '%'],
                           ['gate', d.cond_no_high ? 'open' : d.gate_bars_remaining + ' bars'],
                           ['52wk high', abMD(d.high_date)]],
            render:  (key, day, all) => key === 'composition'
                ? abHaulCompositionHTML(day, all) : abHaulNamesHTML(day)
        },
        infra_backlog: {
            // THE READING leads. The board row says "yellow · 2.9x" and those two read as
            // a contradiction until the cap is visible, so the view that explains the
            // light comes before the view that sources it.
            views:   [{ key: 'reading', label: 'The reading' },
                      { key: 'legs',    label: 'Two legs' }],
            value:   d => d.btb,
            reading: d => d.btb.toFixed(1) + '×',
            light:   d => d.light,
            // Half the reading's published precision. Nothing should trip it: this ledger
            // re-reads the same stored record compute() reads, so the two cannot drift.
            tol:     0.05,
            reconLabel: 'read from the same record',
            count:   d => '2 legs',
            // The four facts a '2.9x' hides: which quarter it is, how old that made it,
            // what the number would have read uncapped, and whether the corroborator has
            // anything to say.
            figures: d => [['print', d.quarter || 'unlabelled'],
                           ['age', d.age_days == null ? '—' : d.age_days + 'd'],
                           ['uncapped', d.capped ? d.raw_light : 'not capped'],
                           ['glyph', (d.gev || {}).arrow === 'plus' ? '+'
                                   : (d.gev || {}).arrow === 'minus' ? '−' : 'dark']],
            render:  (key, day) => key === 'legs'
                ? abInfraLegsHTML(day) : abInfraReadingHTML(day)
        },
        capex_pressure: {
            // THE FIVE leads, for the same reason silicon_payback's pies do: it is what
            // the factor is for. The light is a majority of five per-company lights, so
            // the five ARE the reading, and Direction is the check you run on them.
            views:   [{ key: 'names',     label: 'The five' },
                      { key: 'direction', label: 'Direction' }],
            value:   d => d.through,
            reading: d => d.through + '/' + d.n_names + ' thru',
            light:   d => d.light,
            // The reading is an INTEGER count of names through the gate, so half a step
            // is a whole band away from being a rounding difference — and this ledger
            // re-shapes the day's own snapshot rather than re-deriving it, so the two
            // cannot drift in the first place.
            tol:     0.5,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => d.n_names + ' companies',
            // The band mix, the tie-break if one fired, and the direction — the three
            // things a bare "2/5 thru" cannot tell you.
            figures: d => [['mix', `${(d.counts || {}).green || 0}g/` +
                                   `${(d.counts || {}).yellow || 0}y/` +
                                   `${(d.counts || {}).red || 0}r`],
                           ['tie-break', d.tie_break ? 'fired' : 'none'],
                           ['arrow', d.arrow || 'none'],
                           ['through', (d.through_names || []).join(' ') || '—']],
            render:  (key, day) => key === 'direction'
                ? abCapexDirectionHTML(day) : abCapexNamesHTML(day)
        },
        capex_spigot: {
            // THE SPIGOT leads: the aggregate is the reading, and the five guides are
            // what it is made of. Sources is the check you run on them.
            views:   [{ key: 'spigot',  label: 'The spigot' },
                      { key: 'sources', label: 'Sources' }],
            value:   d => d.yoy,
            reading: d => (d.yoy >= 0 ? '+' : '') + Math.round(d.yoy) + '%',
            light:   d => d.light,
            tol:     0.05,
            reconLabel: 'read from the same record',
            count:   d => d.n_names + ' companies',
            figures: d => [['guided', '$' + d.total_guidance_b + 'B'],
                           ['prior', '$' + d.total_prior_b + 'B'],
                           ['widest', (d.names || []).length
                               ? d.names.reduce((a, b) => a.yoy_pct > b.yoy_pct ? a : b).key
                               : '—'],
                           ['undisclosed', (d.undisclosed || []).length
                               ? d.undisclosed.join(' ') : 'none']],
            render:  (key, day) => key === 'sources'
                ? abSpigotSourcesHTML(day) : abSpigotHTML(day)
        },
        // ONE view each (user, 2026-08-31): the switcher only renders past a single
        // entry, so a lone view costs no chrome and promises no second tab.
        concentration: {
            views:   [{ key: 'peak', label: 'Peak & print' },
                      { key: 'analogues', label: 'Analogues' }],
            value:   d => d.peak_pct,
            reading: d => d.peak_pct.toFixed(2) + '%',
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => d.n_members + ' members',
            figures: d => [['today', d.current_pct.toFixed(2) + '%'],
                           ['off peak', d.off_peak.toFixed(2) + 'pp'],
                           ['basis', 'float'],
                           ['raw peak', d.raw_peak_pct != null ? d.raw_peak_pct + '%' : '—']],
            render:  (key, day) => key === 'analogues'
                ? abConcAnaloguesHTML(day) : abConcHTML(day)
        },
        inflation: {
            views:   [{ key: 'trail', label: 'The trail' }],
            value:   d => d.yoy,
            reading: d => d.yoy.toFixed(2) + '%',
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => d.trail.length + ' prints',
            figures: d => [['to green', d.to_green.toFixed(2) + 'pp'],
                           ['6mo ago', d.trail[0].toFixed(2) + '%'],
                           ['high', Math.max.apply(null, d.trail).toFixed(2) + '%'],
                           ['monotonic', d.climbing ? 'yes' : 'no']],
            render:  (key, day) => abInflationHTML(day)
        },
        yield_curve: {
            views:   [{ key: 'history', label: 'History' }],
            value:   d => d.spread,
            reading: d => (d.spread >= 0 ? '+' : '') + d.spread.toFixed(2),
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => d.months_since != null
                ? d.months_since.toFixed(1) + ' months in' : 'no crossover',
            figures: d => [['crossed', d.crossover_date || '—'],
                           ['months', d.months_since != null ? d.months_since.toFixed(1) : '—'],
                           ['window', d.window_from_months + '–' + d.window_to_months + 'mo'],
                           ['lookback', d.lookback_years + 'y']],
            render:  (key, day) => abYieldHTML(day)
        },
        rate_path: {
            views:   [{ key: 'routes', label: 'The two routes' }],
            value:   d => d.pivot,
            reading: d => (d.pivot >= 0 ? '+' : '') + d.pivot.toFixed(2),
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => (d.cloud || []).length ? (d.cloud.length + ' months') : 'no history',
            // The DISTANCE to each route, which is the thing a single reading cannot say
            // and the reason this factor was invisible on its second condition.
            figures: d => [['6mo change', (d.delta_6mo >= 0 ? '+' : '') + d.delta_6mo.toFixed(2)],
                           ['to tightening', d.to_tightening != null
                               ? (d.to_tightening > 0 ? d.to_tightening.toFixed(2) : 'fired') : '—'],
                           ['to inverted', d.to_inverted != null
                               ? d.to_inverted.toFixed(2) : '—'],
                           ['prior pivot', d.pivot_prior != null
                               ? (d.pivot_prior >= 0 ? '+' : '') + d.pivot_prior.toFixed(2) : '—']],
            render:  (key, day) => abRatePathHTML(day)
        },
        leverage: {
            views:   [{ key: 'history', label: 'Since 1999' }],
            value:   d => d.ratio,
            reading: d => d.ratio.toFixed(2) + '\u00d7',
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day\u2019s own record',
            count:   d => d.n_months ? d.n_months + ' months' : 'no history',
            figures: d => [['margin debt', '$' + Math.round(d.margin_debt_b) + 'B'],
                           ['free credit', '$' + Math.round(d.free_credit_b) + 'B'],
                           ['peak', d.peak ? d.peak.ratio.toFixed(2) + '\u00d7' : '\u2014'],
                           ['vs 2000', d.ratio && (d.refs || {})['2000_peak']
                               ? (d.ratio / d.refs['2000_peak']).toFixed(1) + '\u00d7' : '\u2014']],
            render:  (key, day) => abLeverageHTML(day)
        },
        market_credit: {
            views:   [{ key: 'window', label: 'The window' }],
            value:   d => d.bps,
            reading: d => Math.round(d.bps) + 'bps',
            light:   d => d.light,
            tol:     0.5,
            reconLabel: 're-shaped from the day\u2019s own record',
            count:   d => d.archived_points ? d.archived_points + ' prints' : 'no history',
            figures: d => [['to green', Math.round(d.to_green) + 'bps'],
                           ['the hold', d.sustained_wide ? 'held' : '0/' + d.sustain_days],
                           ['window high', d.window_high ? Math.round(d.window_high.bps) + 'bps' : '\u2014'],
                           ['1y low', d.min_1y_bps != null ? d.min_1y_bps + 'bps' : '\u2014']],
            render:  (key, day) => abMarketCreditHTML(day)
        },
        copper: {
            // ONE view. There is no per-item evidence here -- copper is a single
            // instrument, not a basket or a book -- so the ledger's job is to carry
            // the SERIES, and the series is the whole evidence.
            views:   [{ key: 'trend', label: 'Since 2020' }],
            value:   d => d.vs200,
            reading: d => (d.vs200 >= 0 ? '+' : '') + d.vs200.toFixed(1) + '%',
            light:   d => d.light,
            tol:     0.05,
            reconLabel: 're-shaped from the day’s own record',
            count:   d => d.n_bars ? d.n_bars + ' bars' : 'no series',
            // What a single reading cannot say: where the 200 actually IS, and how far
            // the price has to fall to reach it. `to the 200` is the move that turns
            // this light green, which is the only number on the row that is a trigger.
            figures: d => [['price', '$' + d.price.toFixed(3)],
                           ['the 200', '$' + d.ma200.toFixed(3)],
                           ['to the 200', d.vs200 != null
                               ? (-d.vs200).toFixed(1) + '%' : '—'],
                           ['52wk high', abMD(d.high_date)]],
            render:  (key, day) => abCopperHTML(day)
        },
        net_liquidity: {
            views:   [{ key: 'tide', label: 'Since 2020' }],
            // The board row shows the LEVEL, so the pane keys off the level too -- the
            // 13-week change is what decides the light, but a Reading that disagreed
            // with the row that opened it would read as a bug.
            value:   d => d.level_T,
            reading: d => '$' + d.level_T.toFixed(2) + 'T',
            light:   d => d.light,
            tol:     0.005,
            reconLabel: 're-shaped from the day’s own record',
            // The identity line shows the LEVEL, which is not what the light reads.
            // Both changes ride beside it because they can disagree -- and when they
            // do, that disagreement IS the yellow.
            // The identity line's big reading is the 13-week delta, wearing the
            // light. The LEVEL is context, so it rides beside it in white -- it is
            // still the number the factor is named for, just not the one that decides
            // the colour.
            badge:   f => {
                const e = f.extras || {};
                const lv = f.value != null
                    ? '<b class="abh-dl">$' + f.value.toFixed(2) + 'T</b> level' : '';
                const six = e.chg_6mo_T != null
                    ? ' · 6mo <b class="abh-dl">' + (e.chg_6mo_T >= 0 ? '+' : '−') +
                      '$' + Math.abs(e.chg_6mo_T).toFixed(2) + 'T</b>' : '';
                return lv + six;
            },
            count:   d => d.n_weeks ? d.n_weeks + ' weeks' : 'no series',
            // `to green` is the only trigger on the row: how much FURTHER the 13-week
            // move has to drain before it clears the band. Positive means not there.
            figures: d => [['13wk', (d.chg_3mo_T >= 0 ? '+' : '−') + '$' +
                                Math.abs(d.chg_3mo_T).toFixed(2) + 'T'],
                           ['6mo', (d.chg_6mo_T >= 0 ? '+' : '−') + '$' +
                                Math.abs(d.chg_6mo_T).toFixed(2) + 'T'],
                           ['to green', '$' +
                                Math.max(0, d.chg_3mo_T + d.band_T).toFixed(2) + 'T'],
                           ['reverse repo', d.rrp_T != null
                                ? '$' + (d.rrp_T * 1000).toFixed(0) + 'B' : '—']],
            render:  (key, day) => abNetLiqHTML(day)
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
            `${recon ? ' · <span class="ab-recon">' + esc(v.reconLabel || 're-priced today') +
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
    // charts.js.
    // THE PAYLOAD IS RE-FETCHED, not held for the life of the tab (2026-09-03). It used
    // to be fetched once per page load, on the reasoning that "the engine rebuilds its
    // cache daily, so there is nothing to poll" — which is backwards: a daily rebuild is
    // exactly what an open dashboard has to go back and ask for. A page left up since
    // Monday sat on Monday's Fed print into Thursday while the engine had had the new
    // one since 09:37 that morning, and the only way to see it was a manual reload.
    // Cheap and quiet: one small GET riding the stoplight's own poll, and a REDRAW ONLY
    // when `generated_at` actually moves — so a tab nobody is touching stays untouched,
    // and charts are never rebuilt under the cursor on a payload that did not change.
    let _chartData = null;      // cached payload
    let _chartsGen = null;      // its `generated_at` — the redraw discriminator
    let _boardCharts = [];      // live chart instances (teardown handles)
    let _chartsTick = 0;
    // Every board poll (5 min), so the Fed dial's live header keeps pace with the Rocket
    // Strategy sidebar (user, 2026-09-11). Same build -> header text only, no redraw.
    const SL_CHARTS_EVERY = 1;

    async function renderBubbleCharts() {
        const body = document.getElementById('ab-charts-body');
        if (!body || _boardCharts.length) return;          // already drawn
        if (!_chartData) {
            body.innerHTML = '<div class="ab-tbd" style="padding:14px 0">loading chart data…</div>';
            try {
                const res = await fetch(`${API_BASE}/get_board_charts`);
                _chartData = await res.json();
                _chartsGen = _chartData.generated_at || null;
            } catch (e) {
                console.error('rate charts fetch failed', e);
                body.innerHTML = '<div class="ab-rt-err">chart data unavailable — is the engine running?</div>';
                return;
            }
        }
        drawBoardCharts(body, _chartData);
    }

    // Ask again, and act only on a genuinely new build. Also re-renders the detail
    // panel, because its yield-curve and heavy-haul pictures read the same `_chartData`.
    async function refreshBoardCharts() {
        let j;
        try {
            const res = await fetch(`${API_BASE}/get_board_charts`);
            j = await res.json();
        } catch (e) {
            return;                      // leave whatever is on screen; try again next tick
        }
        if (!j) return;
        if (_chartsGen && j.generated_at === _chartsGen) {
            // SAME BUILD: only a header can have moved. The Fed dial's header reads a
            // live quote server-side (charts.with_live_tip) while its picture stays the
            // daily build, so rewrite the header text in place every poll (user,
            // 2026-09-11) -- and never redraw charts under the cursor for series that
            // did not change.
            _chartData = j;
            updateBoardChartHeaders(j);
            return;
        }
        _chartsGen = j.generated_at || null;
        _chartData = j;
        const body = document.getElementById('ab-charts-body');
        if (body && _boardCharts.length) drawBoardCharts(body, _chartData);
        const panel = document.getElementById('ai-bubble-dive');
        if (panel && !panel.classList.contains('hidden')) renderBubbleOverview();
    }

    // Header text only -- the value label and its as-of date -- matched by chart id.
    // A tab that has not been drawn yet has nothing to update; it draws from
    // `_chartData` (already the fresh payload) when it opens.
    function updateBoardChartHeaders(payload) {
        const body = document.getElementById('ab-charts-body');
        if (!body) return;
        (payload.charts || []).forEach(ch => {
            if (!ch.id) return;
            const sec = body.querySelector(`.ab-rt[data-chart-id="${CSS.escape(ch.id)}"]`);
            if (!sec) return;
            const val = sec.querySelector('.ab-rt-val');
            if (val) val.textContent = (ch.latest && ch.latest.label) || '';
            const asof = sec.querySelector('.ab-rt-asof');
            if (asof && ch.asof) asof.textContent = ch.asof;
        });
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
            sec.dataset.chartId = ch.id || '';           // updateBoardChartHeaders finds it
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
            // A CARRIED chart draws its real data and says so. The server keeps the last
            // good build when a source is briefly unreachable (see charts.refresh), so
            // the picture stands rather than blanking — but a chart quietly showing old
            // numbers is worse than one that admits it, so the header carries a mark and
            // the reason sits in its tooltip.
            if (ch.stale) {
                const w = document.createElement('div');
                w.className = 'ab-rt-sub';
                w.style.color = '#fbbf24';
                w.textContent = 'last good build — the source was unreachable on the '
                              + 'most recent attempt; retrying';
                w.title = ch.stale_error || '';
                sec.appendChild(w);
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
