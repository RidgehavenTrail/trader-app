// news-archive.js — the per-ticker news history inside the "Why" box (classic
// script, global scope; do not add import/export — the onclick handlers below
// depend on these staying global, same as every other static/js module).
//
// Master-detail: a slim scrollable column of dated cards on the left, the selected
// narrative on the right. Lives INSIDE #dd-why rather than in its own tab, because
// that box is stretched to match the Trade Data grid and rarely fills the height.
//
// Data: GET /get_news_archive/<ticker> (engine/news_archive.py). Nothing new is
// captured — it reads archive/*.json plus today's live card.

    let _naEntries = [];
    let _naSel = 0;
    let _naTicker = null;

    function naChgHTML(v) {
        if (v === null || v === undefined || v === '') return '';
        const n = Number(v);
        if (!isFinite(n)) return '';
        return `<span class="na-chg ${n >= 0 ? 'str-up' : 'str-dn'}">` +
               `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(2)}%</span>`;
    }

    // One compact row per day: MM-DD and that day's % move, nothing else. The hover
    // title carries the trigger and a short preview, so the detail is reachable
    // without spending a line on it.
    function renderNewsList() {
        const el = document.getElementById('dd-why-list');
        if (!el) return;
        // Nothing on record: the list stays empty and the narrative card carries the
        // explanation (user, 2026-08-10) rather than both halves saying it.
        el.innerHTML = _naEntries.map((e, i) => {
            const cls = ['na-card'];
            if (i === _naSel) cls.push('sel');
            if (e.live) cls.push('live');
            const tip = [e.date, e.status, (e.why || '').slice(0, 140) + '…']
                        .filter(Boolean).join(' · ');
            // The newest entry reads "current" and drops its % move — the detail
            // panel already shows today's price right above this box.
            const head = i === 0
                ? `<span class="na-d na-cur">current</span>`
                : `<span class="na-d">${esc((e.date || '').slice(5))}</span>` +
                  naChgHTML(e.price_change);
            return `<div class="${cls.join(' ')}" onclick="selectNewsEntry(${i})" ` +
                   `title="${esc(tip)}">${head}</div>`;
        }).join('');
    }

    function renderNewsBody() {
        const el = document.getElementById('dd-why-body');
        if (!el) return;
        const e = _naEntries[_naSel];
        if (!e) {
            el.innerHTML = `<div class="na-empty">No news on record for this ticker. ` +
                           `Entries appear here when a trigger pulls a synthesis — ` +
                           `a mechanical-only fire does not create one.</div>`;
            return;
        }
        // structure/impact are the options-mechanics halves of the same synthesis.
        // They already have their own box lower in the pane, so only the extra
        // context that is NOT duplicated there rides along here.
        el.innerHTML =
            `<div class="na-meta">${esc(e.date || '')}` +
            (e.status ? ` · ${esc(e.status)}` : '') +
            (e.price ? ` · ${esc(String(e.price))}` : '') +
            (e.news_source ? ` · ${esc(e.news_source)}` : '') + `</div>` +
            `<div class="na-why">${esc(e.why || '—')}</div>`;
    }

    function selectNewsEntry(i) {
        _naSel = i;
        renderNewsList();
        renderNewsBody();
    }

    // Called by updateContext() when a ticker deep-dive opens.
    function loadNewsArchive(ticker) {
        if (!document.getElementById('dd-why-list')) return;
        _naTicker = ticker;
        _naEntries = [];
        _naSel = 0;
        document.getElementById('dd-why-list').innerHTML = '';
        document.getElementById('dd-why-body').innerHTML =
            `<div class="na-empty">Loading…</div>`;

        fetch(`${API_BASE}/get_news_archive/${encodeURIComponent(ticker)}`)
            .then(r => r.json())
            .then(d => {
                if (_naTicker !== ticker) return;      // a later click won the race
                // NEWS archive, not an alert archive (user, 2026-08-10): a day whose
                // card fired on a mechanical trigger only carries no synthesis, so it
                // is not an entry. Filtering here rather than server-side keeps the
                // endpoint returning the full record for anything else that wants it.
                _naEntries = ((d && d.entries) || []).filter(e => e.has_news);
                _naSel = 0;     // every entry has news now, so newest IS the latest news
                renderNewsList();
                renderNewsBody();
            })
            .catch(e => {
                console.error('[news] archive fetch failed:', e);
                const b = document.getElementById('dd-why-body');
                if (b) b.innerHTML = `<div class="na-empty">News history unavailable.</div>`;
            });
    }
