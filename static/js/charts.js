// charts.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    const viewState = {
        dd: { entity: null, chart: null, series: null, loadedFor: null },
        nd: { entity: null, chart: null, series: null, loadedFor: null },
        // `sd` = the Rocket Strategy detail panel (static/js/strategy-dive.js). Same shape
        // as the other two plus `levels`: the horizontal price lines the strategy wants
        // drawn on its own chart (entry/target while holding, the trigger while flat).
        sd: { entity: null, chart: null, series: null, loadedFor: null, levels: [] }
    };

    function setTabsForAssetClass(view, assetClass) {
        const tabsEl = document.getElementById(view + '-tabs');
        tabsEl.querySelectorAll('.view-tab').forEach(btn => {
            if (btn.dataset.requires === 'equity' && assetClass !== 'equity') {
                btn.style.display = 'none';
            } else {
                btn.style.display = '';
            }
        });
    }

    // Options Data quadrant (ATM Strike/Put Premium/Expiration/IV/Put Wall/Call Wall)
    // only makes sense for single-name equities - futures, forex, and pairs trades
    // have no single options chain to show here, so the quadrant stays blank.
    function setOptionsDataVisibility(view, assetClass) {
        const el = document.getElementById(view + '-options-data');
        if (el) el.style.visibility = (assetClass === 'equity') ? 'visible' : 'hidden';
    }

    function switchTab(view, tabName) {
        const tabsEl = document.getElementById(view + '-tabs');
        if (!tabsEl) return;
        const btns = [...tabsEl.querySelectorAll('.view-tab')];
        btns.forEach(btn => btn.classList.toggle('active', btn.dataset.view === tabName));
        // PANE NAMES COME FROM THE BUTTONS, not a hardcoded list. This used to be
        // ['narrative','chart','options'] — the dd/nd vocabulary — so the strategy panel's
        // own tabs (strategy/chart/dial) would have switched the button styling and left
        // every pane exactly as it was. A panel's tab strip is the authority on its own
        // panes; anything else is a second copy of the same list waiting to disagree.
        btns.map(b => b.dataset.view).forEach(name => {
            const pane = document.getElementById(view + '-pane-' + name);
            if (pane) pane.classList.toggle('hidden', name !== tabName);
        });
        // Charts stay LAZY — a chart built into a display:none pane measures zero and
        // renders collapsed, which is why this fires on selection rather than on open.
        if (tabName === 'chart') loadChart(view);
    }

    function resetToNarrativeTab(view) {
        switchTab(view, 'narrative');
    }

    // --- SMA helper: computes trailing simple moving average over a series
    // of {time, value} points. Returns only points where the window is full
    // (no partial/misleading SMA values at the very start of the series). ---
    function calcSMA(points, period) {
        const out = [];
        let sum = 0;
        for (let i = 0; i < points.length; i++) {
            sum += points[i].value;
            if (i >= period) sum -= points[i - period].value;
            if (i >= period - 1) out.push({ time: points[i].time, value: sum / period });
        }
        return out;
    }

    // Trims a {time, value}-shaped series to the last `months` calendar
    // months. Used to display 6mo daily candles while still fetching a much
    // longer lookback (2y) so the 200-day SMA is fully seeded before the
    // visible window even starts — otherwise the SMA line would be missing
    // or wrong for its first ~200 days on screen.
    // How many months each view SHOWS. The fetch is 2y regardless -- that is the seeding
    // buffer, not the window -- and this is the part of it that reaches the screen.
    // The strategy view runs a YEAR (user, 2026-08-26): its rules are annual, so at six
    // months the 52-week extremes that decide a state were off the chart meant to
    // explain them. Still seeded: 2y is ~504 bars, the SMA200 is valid from bar 200, and
    // a 12-month window starts around bar 252, so the 200 line is complete across the
    // whole visible range.
    // dd and nd stay at 6 deliberately; nobody asked them to change and a longer window
    // makes a newsletter trade's levels smaller on screen.
    const CHART_MONTHS = { sd: 12 };
    const CHART_MONTHS_DEFAULT = 6;

    function trimToMonths(points, months) {
        const cutoff = new Date();
        cutoff.setMonth(cutoff.getMonth() - months);
        const cutoffStr = cutoff.toISOString().slice(0, 10);
        return points.filter(p => p.time >= cutoffStr);
    }

    // Translate a stored ticker to a yfinance-fetchable symbol at the FETCH
    // boundary only (A.7). The store deliberately keeps bare, identity-correct
    // tickers (USDJPY not USDJPY=X, HG not HG=F — the suffix is a fetch-mechanics
    // detail, per newsletter-schema.md B.2), so it's applied here, not stored.
    // yfinance needs =X for forex (bare "USDJPY" 404s) and =F for futures (bare
    // "HG" mis-resolves to an unrelated equity). Only a CLEAN futures root
    // (letters only) is translated; an exotic display-name (e.g. "CL1!") is left
    // bare rather than naively suffixed — matches the backend quote's guard.
    function chartSymbol(ticker, assetClass) {
        if (!ticker) return ticker;
        if (assetClass === 'forex') return `${ticker}=X`;
        if (assetClass === 'future' && /^[A-Za-z]{1,4}$/.test(ticker)) return `${ticker}=F`;
        return ticker;
    }

    // --- Chart loading against the real /get_price_history endpoint ---
    async function loadChart(view) {
        const state = viewState[view];
        const entity = state.entity;
        if (!entity) return;

        // A pair is signalled by its basketLegs, NOT asset_class — the tightened schema
        // retired the 'pair' asset_class value (a pairs trade is now asset_class 'equity',
        // structure 'pairs'), so the old `asset_class === 'pair'` test silently never fired
        // and the ratio chart fell through to a null-ticker single-instrument fetch.
        const isPair = !!(entity.basketLegs && entity.basketLegs.length);
        // A ratio-triggered outright charts the numerator/denominator ratio (not a basket).
        const rt = entity.ratioTrigger;
        const isRatioTrigger = !isPair && !!(rt && rt.numerator && rt.denominator);
        // Key includes each leg's side so a re-render is triggered if the pairing
        // ever changes, not just the ticker set.
        const entityKey = isPair
            ? (entity.basketLegs || []).map(l => `${(l.side || '?')[0]}:${l.ticker}`).join('+')
            : isRatioTrigger ? `${rt.numerator}/${rt.denominator}`
            : entity.ticker;
        if (state.loadedFor === entityKey) return; // already loaded for this entity

        const container = document.getElementById(view + '-chart-container');
        container.innerHTML = '<div class="chart-loading">Loading price history…</div>';
        // Ratio charts re-show this in applyRatioRender; hidden by default (single-name has no invert).
        document.getElementById(view + '-chart-controls')?.classList.add('hidden');

        try {
            if (isPair) {
                // Ratio = sum of LONG-leg closes / sum of SHORT-leg closes (raw
                // prices, no weighting) — split by `side`, matching the card's own
                // XLV+XLP+XLF/IGV notation and verified against live prices (A.6).
                // The old code did `const [a,b] = entity.legs` and charted a/b by
                // ARRAY POSITION, which for a 3-long/1-short basket silently
                // compared two long legs and never touched the short leg at all.
                const legs = entity.basketLegs || [];
                const longLegs = legs.filter(l => l.side === 'long');
                const shortLegs = legs.filter(l => l.side === 'short');
                const longs = longLegs.map(l => l.ticker);
                const shorts = shortLegs.map(l => l.ticker);
                if (!longs.length || !shorts.length) {
                    container.innerHTML = '<div class="chart-loading">This pair has no long/short split to chart.</div>';
                    return;
                }
                const tickers = [...longs, ...shorts];
                const hists = await Promise.all(tickers.map(tk =>
                    fetch(`${API_BASE}/get_price_history/${chartSymbol(tk, 'equity')}?range=2y`).then(r => r.json())
                ));
                const closeMaps = hists.map(h => Object.fromEntries((h.candles || []).map(c => [c.time, c.close])));
                const longMaps = closeMaps.slice(0, longs.length);
                const shortMaps = closeMaps.slice(longs.length);
                // WHICH RATIO THE ISSUE MONITORS is an extracted field, not a guess off
                // the weights (see derive_ratio_method in newsletter_ingest.py). Every
                // basket carries weights; almost always they are beta-neutral EXECUTION
                // sizing and the tracked number is the raw sum over sum. One issue so far
                // blends a side into a composite ("$600 of XLV and $400 of XLP per
                // $1,000") and monitors THAT — charting it unweighted put it at 0.34
                // against a stated 0.1761, nowhere near its own 0.172 stop.
                // Weights are normalized WITHIN a side, so a blend keeps its proportions
                // while cross-side sizing (1.0 vs 0.5) cannot rescale the ratio.
                const weighted = entity.ratioMethod === 'weighted';
                const norm = (ls) => {
                    if (!weighted) return ls.map(() => 1);
                    const ws = ls.map(l => (typeof l.weight === 'number' && l.weight > 0) ? l.weight : 0);
                    const tot = ws.reduce((a, b) => a + b, 0);
                    return tot > 0 ? ws.map(w => w / tot) : ls.map(() => 1);
                };
                const longW = norm(longLegs), shortW = norm(shortLegs);
                // Only dates present in EVERY leg yield a valid ratio point.
                const baseTimes = (hists[0].candles || []).map(c => c.time);
                const fullRatio = [];
                for (const time of baseTimes) {
                    let longSum = 0, shortSum = 0, ok = true;
                    longMaps.forEach((m, i) => { if (!ok) return; if (m[time] == null) { ok = false; return; } longSum += m[time] * longW[i]; });
                    if (ok) shortMaps.forEach((m, i) => { if (!ok) return; if (m[time] == null) { ok = false; return; } shortSum += m[time] * shortW[i]; });
                    if (!ok || shortSum === 0) continue;
                    fullRatio.push({ time, value: longSum / shortSum });
                }
                // Cache the base (long/short) ratio; render via applyRatioRender so the
                // Invert (1/x) toggle can flip it without re-fetching. A small ratio
                // (IGV/SOXX ~0.17) reads better as its reciprocal (~5.9) — display only,
                // the stored long/short orientation and header quote are unchanged.
                state.baseRatio = fullRatio;
                state.ratioNum = longs.join('+');
                state.ratioDen = shorts.join('+');
                state.invert = false;
                applyRatioRender(view);
            } else if (isRatioTrigger) {
                // Ratio-triggered outright: chart the numerator/denominator ratio (SOXX/MAGS)
                // with its 50/200-DMA — the exact line the entry trigger watches — instead of
                // the single-stock candles. Same construction as a pair (num ÷ den, raw closes).
                const [numHist, denHist] = await Promise.all([
                    fetch(`${API_BASE}/get_price_history/${chartSymbol(rt.numerator, 'equity')}?range=2y`).then(r => r.json()),
                    fetch(`${API_BASE}/get_price_history/${chartSymbol(rt.denominator, 'equity')}?range=2y`).then(r => r.json())
                ]);
                const denMap = Object.fromEntries((denHist.candles || []).map(c => [c.time, c.close]));
                const fullRatio = [];
                for (const c of (numHist.candles || [])) {
                    const d = denMap[c.time];
                    if (d == null || d === 0) continue;
                    fullRatio.push({ time: c.time, value: c.close / d });
                }
                if (!fullRatio.length) {
                    container.innerHTML = '<div class="chart-loading">Couldn\'t build the ratio series.</div>';
                    return;
                }
                state.baseRatio = fullRatio;
                state.ratioNum = rt.numerator;
                state.ratioDen = rt.denominator;
                state.invert = false;
                applyRatioRender(view);
            } else {
                state.baseRatio = null;                          // single-name: nothing to invert
                const sym = chartSymbol(entity.ticker, entity.asset_class);
                const hist = await fetch(`${API_BASE}/get_price_history/${sym}?range=2y`).then(r => r.json());
                const closesForSMA = hist.candles.map(c => ({ time: c.time, value: c.close }));
                const mo = CHART_MONTHS[view] || CHART_MONTHS_DEFAULT;
                const sma50 = trimToMonths(calcSMA(closesForSMA, 50), mo);
                const sma200 = trimToMonths(calcSMA(closesForSMA, 200), mo);
                const candles = trimToMonths(hist.candles, mo);
                renderCandlestickChart(view, container, candles, sma50, sma200);
            }
            state.loadedFor = entityKey;
        } catch (err) {
            console.error('Chart load failed:', err);
            container.innerHTML = '<div class="chart-loading">Couldn\'t load price history — is the engine running on :5001?</div>';
        }
    }

    // Re-maps the cached base (long/short) ratio for the Invert (1/x) toggle and redraws it
    // WITHOUT re-fetching. SMAs are recomputed on the (possibly inverted) series because
    // SMA(1/x) != 1/SMA(x). Also refreshes the toggle button's numerator/denominator label.
    function applyRatioRender(view) {
        const state = viewState[view];
        const base = state.baseRatio || [];
        const inv = !!state.invert;
        const series = inv ? base.map(p => ({ time: p.time, value: p.value ? 1 / p.value : 0 })) : base;
        const container = document.getElementById(view + '-chart-container');
        renderLineChart(view, container,
            trimToMonths(series, CHART_MONTHS[view] || CHART_MONTHS_DEFAULT), '#a78bfa',
            trimToMonths(calcSMA(series, 50), CHART_MONTHS[view] || CHART_MONTHS_DEFAULT),
            trimToMonths(calcSMA(series, 200), CHART_MONTHS[view] || CHART_MONTHS_DEFAULT));
        const ctrl = document.getElementById(view + '-chart-controls');
        const lbl = document.getElementById(view + '-invert-label');
        if (ctrl && lbl) {
            lbl.innerText = inv ? `${state.ratioDen} / ${state.ratioNum}` : `${state.ratioNum} / ${state.ratioDen}`;
            ctrl.classList.remove('hidden');
        }
    }

    // Invert (1/x) toggle for a pair / ratio-trigger chart. Display-only: flips which side
    // is the numerator so a small ratio can be viewed as its larger reciprocal. The stored
    // long/short orientation and the header quote are untouched.
    function toggleRatioInvert(view) {
        const state = viewState[view];
        if (!state.baseRatio) return;
        state.invert = !state.invert;
        applyRatioRender(view);
    }

    function destroyChart(view) {
        const state = viewState[view];
        if (state.chart) { state.chart.remove(); state.chart = null; state.series = null; }
    }

    // SMA overlays MUST share the price series' scale (the default RIGHT scale) so they
    // align with the candles/ratio. They were previously pinned to a separate 'left' price
    // scale to keep their value labels off the right axis — but a separate scale AUTO-FITS
    // to the SMAs' own (narrower) range INDEPENDENTLY of the price, which rendered the lines
    // vertically offset (the 50-DMA looked shifted up on an uptrend like MAGS). Verified
    // 2026-07-13: MAGS SMA50 range 43.5–67.3 sits inside the close range 39.9–70.9, so it
    // belongs on the price scale. Correct alignment beats label placement — Lightweight
    // Charts stacks the last-value labels on a shared scale so they don't bury each other.
    // Cyan = 50, white = 200.
    // PRECISION FOLLOWS THE MAGNITUDE (user, 2026-09-01). Lightweight Charts defaults
    // to `precision: 2`, which is right for a $56.94 quote and useless for a RATIO: the
    // XLF/ITB pair trades around 0.6036 and rendered as "0.60", so its entry (0.588),
    // its stop (0.575) and its first target (0.620) were three indistinguishable
    // two-digit numbers on the axis and in the crosshair.
    // Sub-1 series get FOUR decimals — the precision the letter itself quotes ratios to
    // ("ratio 0.6036") — and anything at or above 1 keeps the two it already had.
    // `minMove` must move with `precision` or the scale still snaps to 0.01.
    function priceFormatFor(rows) {
        let mx = 0;
        (rows || []).forEach(r => {
            ['value', 'close', 'open', 'high', 'low'].forEach(k => {
                const v = Math.abs(r && r[k]);
                if (isFinite(v) && v > mx) mx = v;
            });
        });
        // SIGNIFICANT DIGITS, not a threshold. The first cut of this keyed off "is the
        // max below 1", which broke on the case that needs it most: a pair ratio
        // hovering around parity (0.98 / 1.02 / 0.94) has a max above 1 and collapsed
        // straight back to two decimals. Targeting ~4 significant digits instead scales
        // continuously, so nothing falls off a cliff at 1.0.
        //   0.6036 -> 4    1.02 -> 3    56.94 -> 2    755 -> 2    6543 -> 2
        // Floored at 2 so every equity keeps its cents, capped at 6 so a near-zero
        // series cannot run the axis off the panel.
        const precision = mx > 0
            ? Math.min(6, Math.max(2, 3 - Math.floor(Math.log10(mx))))
            : 2;
        return { type: 'price', precision: precision, minMove: Math.pow(10, -precision) };
    }

    // The overlays share the price scale, so they take the SAME format — a 200-bar MA
    // left on the default would put 2-decimal labels back on a 4-decimal axis.
    function addSMAOverlays(chart, sma50, sma200, priceFormat) {
        const fmt = priceFormat ? { priceFormat: priceFormat } : {};
        if (sma50 && sma50.length) {
            const s50 = chart.addLineSeries(Object.assign({ color: '#22d3ee', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true }, fmt));
            s50.setData(sma50);
        }
        if (sma200 && sma200.length) {
            const s200 = chart.addLineSeries(Object.assign({ color: '#ffffff', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true }, fmt));
            s200.setData(sma200);
        }
    }

    function renderCandlestickChart(view, container, candles, sma50, sma200) {
        destroyChart(view);
        container.innerHTML = '';
        const chart = LightweightCharts.createChart(container, {
            autoSize: true,
            layout: { background: { color: 'transparent' }, textColor: '#94a3b8', fontFamily: 'Inter, sans-serif' },
            grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
            timeScale: { borderColor: '#334155' },
            rightPriceScale: { borderColor: '#334155' },
            leftPriceScale: { visible: false },
            crosshair: { mode: 0 }
        });
        const fmt = priceFormatFor(candles);
        const series = chart.addCandlestickSeries({
            upColor: '#34d399', downColor: '#f87171',
            borderUpColor: '#34d399', borderDownColor: '#f87171',
            wickUpColor: '#34d399', wickDownColor: '#f87171',
            priceFormat: fmt
        });
        series.setData(candles);
        addSMAOverlays(chart, sma50, sma200, fmt);
        chart.timeScale().fitContent();
        viewState[view].chart = chart;
        viewState[view].series = series;
        // A chart rebuilt under a view that carries levels redraws them itself, so the
        // caller never has to sequence "load, then draw" — which matters because the
        // strategy panel starts its chart BEFORE its state has arrived.
        drawStrategyLevels(view);
    }

    // Horizontal levels on a price series — the strategy panel's entry/target/trigger.
    //
    // IDEMPOTENT BY CONSTRUCTION. The chart and the strategy state arrive on independent
    // round trips in either order, so this is called from both and each call removes the
    // lines it drew last time before drawing again. Without that, a slow state response
    // landing after a chart rebuild would stack a second set of lines on the first.
    function drawStrategyLevels(view) {
        const state = viewState[view];
        if (!state || !state.series) return;
        (state._priceLines || []).forEach(pl => {
            try { state.series.removePriceLine(pl); } catch (e) { /* series already gone */ }
        });
        state._priceLines = (state.levels || []).map(l => state.series.createPriceLine({
            price: l.price,
            color: l.color,
            lineWidth: 1,
            // Dashed, always: a level is a line the price has NOT reached (or a fill that
            // is already history). Solid would read as another data series.
            // Read through a guard — LineStyle is a library enum, and a version that moved
            // or renamed it would throw here and take every level down with it.
            lineStyle: (window.LightweightCharts && LightweightCharts.LineStyle
                        && LightweightCharts.LineStyle.Dashed) || 2,
            // THE LABEL LIVES IN THE AXIS GUTTER, NOT ON THE PANE (user, 2026-08-15).
            // A price line's `title` is drawn inside the plot area hard against the price
            // scale, and Lightweight Charts gives it no position option — so the text sat
            // exactly where the candles matter most, and worst of all precisely when price
            // approached the level, which is when the chart is being read closely.
            //
            // axisLabelVisible puts the LEVEL ITSELF in the right-hand gutter, tinted with
            // the line's own colour, outside the plot area. Nothing is lost: the facts strip
            // above the chart already names entry / target / entry @ with their values, and
            // the colours match it. The gutter also stacks colliding labels rather than
            // burying them — the same property the SMA overlays rely on above.
            axisLabelVisible: true,
            title: '',
        }));
    }

    function renderLineChart(view, container, points, color, sma50, sma200) {
        destroyChart(view);
        container.innerHTML = '';
        const chart = LightweightCharts.createChart(container, {
            autoSize: true,
            layout: { background: { color: 'transparent' }, textColor: '#94a3b8', fontFamily: 'Inter, sans-serif' },
            grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
            timeScale: { borderColor: '#334155' },
            rightPriceScale: { borderColor: '#334155' },
            leftPriceScale: { visible: false },
            // mode 0 = Normal, matching the candlestick chart. The library DEFAULTS to
            // Magnet, which pins the dashed price line to the series value at the
            // hovered time — so you cannot float it to read a support/resistance level
            // off the axis. This line chart had been on the default all along; it only
            // became visible when ratio charts went to 4 decimals, because at 2 the
            // snapped price and a free one rounded to the same label (user, 2026-09-01).
            crosshair: { mode: 0 }
        });
        const fmt = priceFormatFor(points);
        const series = chart.addLineSeries({ color: color, lineWidth: 2, priceFormat: fmt });
        series.setData(points);
        addSMAOverlays(chart, sma50, sma200, fmt);
        chart.timeScale().fitContent();
        viewState[view].chart = chart;
        viewState[view].series = series;
    }

    // --- Ticker deep-dive (Actionable Moves cards) ---
    function updateContext(ticker) {
        const d = dynamicContextData[ticker];
        if (!d) return;
        showOnlyPanel('populated-state');   // shared list in core.js — see DETAIL_PANELS

        const assetClass = 'equity'; // Actionable Moves are equity/ETF-only today

        document.getElementById('dd-ticker').innerText = ticker;
        document.getElementById('dd-dollar-price').innerText = d.price;
        // #dd-why is now a master-detail container, not a paragraph — news-archive.js
        // owns its contents. Today's card is the first entry the endpoint returns, so
        // this still shows the live narrative; it just arrives with its history.
        loadNewsArchive(ticker);
        document.getElementById('dd-structure').innerText = d.structure || 'Analyzing options chain...';
        document.getElementById('dd-impact').innerText = d.impact || 'Calculating optimal trade mechanics...';
        // Pre-market carries the prior session's mark; name it rather than let a
        // stale-by-design number read as a live quote.
        let sigmaNote = '';
        if (d.em_source === 'prior_close' && d.em_asof) {
            const t = new Date(d.em_asof);
            sigmaNote = isNaN(t) ? ' · prior close' : ' · prior close ' +
                t.toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        }
        document.getElementById('dd-sigma').innerText = d.expected_move ? '1σ bound: ±' + d.expected_move + '%' + sigmaNote : '';

        document.getElementById('dd-atm-strike').innerText = d.atm_strike ? `$${d.atm_strike}` : '--';
        document.getElementById('dd-atm-put-price').innerText = d.atm_put_price ? `$${d.atm_put_price}` : '--';
        document.getElementById('dd-atm-expiration').innerText = d.atm_expiration || '--';
        document.getElementById('dd-atm-iv').innerText = d.atm_iv ? `${d.atm_iv}%` : '--';
        document.getElementById('dd-put-wall').innerText = d.put_wall ? `$${d.put_wall}` : '--';
        document.getElementById('dd-call-wall').innerText = d.call_wall ? `$${d.call_wall}` : '--';

        // Options tab (dd-pane-options) was previously a hardcoded static
        // duplicate of this same quadrant — wire it to the same live fields
        // rather than showing stale example numbers on every ticker.
        document.getElementById('dd-opt-atm-strike').innerText = d.atm_strike ? `$${d.atm_strike}` : '--';
        document.getElementById('dd-opt-put-premium').innerText = d.atm_put_price ? `$${d.atm_put_price}` : '--';
        document.getElementById('dd-opt-iv').innerText = d.atm_iv ? `${d.atm_iv}%` : '--';

        // The engine now tags each card with the SET of fired conditions
        // (1-sigma / 2x-volume / turtle-trade) in `conditions`, so the checklist
        // reflects the true fired set. Fall back to 1-sigma for any legacy card
        // written before the multi-condition schema (turtle-volume-indicators.md).
        renderTriggers('dd', d.conditions || ['1-sigma']);
        setTradeDataQuadrant('dd', d);

        const priceEl = document.getElementById('dd-price');
        const isPositive = d.price_change > 0;
        priceEl.innerText = (isPositive ? '+' : '') + d.price_change + '%';
        priceEl.className = 'text-2xl font-mono ' + (isPositive ? 'text-emerald-400' : 'text-red-400');

        viewState.dd.entity = { asset_class: assetClass, ticker };
        viewState.dd.loadedFor = null;
        setTabsForAssetClass('dd', assetClass);
        setOptionsDataVisibility('dd', assetClass);
        resetToNarrativeTab('dd');
    }

    // "Trade Data" quadrant = a priority stack of pluggable sections. A Turtle
    // breakout on the card (condition_meta['turtle-trade']) renders the Turtle
    // Setup section and SUPPRESSES Options Data; otherwise Options Data shows.
    // To STACK instead of swap (options below turtle), just stop hiding oEl.
    function setTradeDataQuadrant(view, d) {
        const turtle = d && d.condition_meta && d.condition_meta['turtle-trade'];
        const tEl = document.getElementById(view + '-td-turtle');
        const oEl = document.getElementById(view + '-td-options');
        if (!tEl || !oEl) return;
        if (turtle) {
            tEl.innerHTML = renderTurtleSetup(turtle);
            tEl.classList.remove('hidden');
            oEl.classList.add('hidden');
        } else {
            tEl.classList.add('hidden');
            tEl.innerHTML = '';
            oEl.classList.remove('hidden');
        }
    }

    // Turtle Setup block: direction header, the four key levels, the pyramid add
    // ladder, and the historical win/loss record IN R FOR THE FIRED DIRECTION
    // (a long breakout must not show short-diluted stats).
    function renderTurtleSetup(m) {
        const isLong = m.direction === 'long';
        const px = (v) => (v === null || v === undefined) ? '--' : '$' + Number(v).toFixed(2);
        const row = (label, val, valCls) =>
            '<div class="flex justify-between items-baseline">' +
                '<span class="text-xs text-slate-400">' + label + '</span>' +
                '<span class="text-sm font-mono ' + (valCls || 'text-slate-200') + '">' + val + '</span></div>';
        const hdr = (t) => '<p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mt-3 mb-0.5">' + t + '</p>';

        let pyrRows = '';
        if (m.pyramid && m.pyramid.length) {
            m.pyramid.forEach((lvl, i) => { pyrRows += row('Unit ' + (i + 2), px(lvl)); });
        }

        const s = m.stats || {};
        const R1 = (v) => (v === null || v === undefined) ? '--' : (v >= 0 ? '+' : '') + Number(v).toFixed(1) + 'R';
        const hasExp = (s.expectancy_R !== null && s.expectancy_R !== undefined);
        const expColor = !hasExp ? 'text-slate-400' : (s.expectancy_R >= 0 ? 'text-emerald-400' : 'text-red-400');
        const expR = !hasExp ? '--' : (s.expectancy_R >= 0 ? '+' : '') + Number(s.expectancy_R).toFixed(2) + 'R';

        // A narrow, flat list in a tight bordered card — deliberately does NOT
        // stretch to fill the quadrant.
        return '' +
            '<div class="max-w-[15rem] rounded-lg border border-slate-700 bg-slate-800/30 px-3 py-2">' +
                row('ATR (N)', px(m.atr)) +
                row('Breakout level', px(m.breakout_level)) +
                row('Suggested stop', px(m.suggested_stop), 'text-red-400') +
                row('20d opposite channel', px(m.opposite_channel)) +
                hdr('Pyramid Levels Remaining') +
                pyrRows +
                hdr((isLong ? 'Long' : 'Short') + ' Breakouts · 5Y') +
                '<div class="flex justify-between items-baseline">' +
                    '<span class="text-xs font-mono text-emerald-400">' + (s.n_success || 0) + ' won avg ' + R1(s.avg_win_R) + '</span>' +
                    '<span class="text-xs font-mono text-red-400">' + (s.n_fail || 0) + ' lost avg ' + R1(s.avg_loss_R) + '</span></div>' +
                row('Expectancy', expR + '<span class="text-[10px] text-slate-500"> /trade</span>', 'font-bold ' + expColor) +
            '</div>';
    }

    // Live current-price / day-change header (section E). The % is the
    // instrument's OWN raw day move (watchlist convention), NOT the position's
    // directional P&L — a short doesn't flip the sign. Only meaningful for
    // planned/open trades; a closed trade shows realized P&L instead, so the
    // quote is hidden for it. Fetches the backend /get_trade_quote (Python owns the
    // per-structure dispatch: outright underlying price / pair ratio / options spread
    // mark). Shown in the header next to the trade tag; blank for expired-leg options.
    // Render a price + day% quote into `el`, colored by the day's move (green up,
    // red down, neutral gray/white when flat or unavailable — the instrument's own
    // raw move, not the position's directional P&L). Hides `el` when price is null.
    // `label` overrides the price text (e.g. "3.30 ratio", "FIVN 24.50").
