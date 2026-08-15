// core.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    // watchtower_engine.py (port 5001) serves the full endpoint set — watchlist,
    // Actionable Moves, macro, price history — AND the newsletter ingestion +
    // read endpoints, so every call in this file routes through one base.
    const API_BASE = 'http://localhost:5001';

    // --- The right-hand column shows exactly ONE panel -------------------------------
    //
    // WHY THIS IS CENTRAL (2026-08-15). Every opener used to hide its siblings BY NAME:
    // updateContext hid three, showNewsletterDive hid three, openBubbleDetail hid three.
    // Adding a fourth panel therefore had to edit all three of them, and adding
    // `strategy-dive` edited none — so opening the AI Bubble detail did not REPLACE the
    // strategy panel, it left it visible and stacked underneath. Four openers each held a
    // private copy of the list and three of them were wrong the moment the list changed.
    //
    // One list, one helper. A fifth panel is added HERE and nowhere else.
    const DETAIL_PANELS = ['empty-state', 'populated-state', 'newsletter-dive',
                           'ai-bubble-dive', 'strategy-dive'];
    // `empty-state` carries `flex` statically in its markup; the dive panels have it ADDED
    // on show. Toggling it off `empty-state` would break it the next time it is shown.
    const DETAIL_PANELS_STATIC_FLEX = new Set(['empty-state']);

    function showOnlyPanel(id) {
        DETAIL_PANELS.forEach(p => {
            const el = document.getElementById(p);
            if (!el) return;
            const on = (p === id);
            el.classList.toggle('hidden', !on);
            if (!DETAIL_PANELS_STATIC_FLEX.has(p)) el.classList.toggle('flex', on);
        });
    }

    // Persist a <details> section's open/closed state across reloads. The section
    // collapses natively on summary click; this restores the last state on load and
    // records changes to localStorage. Shared by the Macro + AI Bubble sidebar
    // sections (core.js loads first, so this is defined before either caller runs).
    function persistCollapse(sectionId, storageKey) {
        const sec = document.getElementById(sectionId);
        if (!sec) return;
        const saved = localStorage.getItem(storageKey);
        if (saved !== null) sec.open = (saved === '1');
        sec.addEventListener('toggle', () => {
            localStorage.setItem(storageKey, sec.open ? '1' : '0');
        });
    }

    // --- LEFT PANEL: Watchlist/Portfolio/Dividends lists + macro panel ---
    // Ported verbatim from trader_dashboard.html so both dashboards share the
    // same localStorage('userStocks') category construct and the same
    // backend endpoints (tickers.json itself is a flat list server-side —
    // the Watchlist/Portfolio/Dividends split is a client-side grouping
    // layered on top via the 'category' field stored per-entry in localStorage).
    function initHorizontalScrollStrip(elId) {
        const el = document.getElementById(elId);
        if (!el) return;
        let isDown = false;
        let startX, startScrollLeft;
        let hasDragged = false;

        window.addEventListener('pointerdown', e => {
            const rect = el.getBoundingClientRect();
            const inStrip = e.clientX >= rect.left && e.clientX <= rect.right &&
                             e.clientY >= rect.top  && e.clientY <= rect.bottom;
            if (!inStrip || e.button !== 0) return;
            isDown = true;
            hasDragged = false;
            startX = e.clientX;
            startScrollLeft = el.scrollLeft;
            el.classList.add('is-dragging');
        }, {capture: true});

        window.addEventListener('pointermove', e => {
            if (!isDown) return;
            const dx = e.clientX - startX;
            if (Math.abs(dx) > 4) hasDragged = true;
            el.scrollLeft = startScrollLeft - dx;
        }, {capture: true});

        window.addEventListener('pointerup', e => {
            if (!isDown) return;
            isDown = false;
            el.classList.remove('is-dragging');
            if (hasDragged) {
                window.addEventListener('click', e => e.stopImmediatePropagation(), {capture: true, once: true});
            }
            hasDragged = false;
        }, {capture: true});

        // Wheel scrolls horizontally
        el.addEventListener('wheel', e => {
            e.preventDefault();
            el.scrollLeft += e.deltaY !== 0 ? e.deltaY : e.deltaX;
        }, {passive: false});
    }
    initHorizontalScrollStrip('actionable-container');
    initHorizontalScrollStrip('newsletter-container');

    // Extensible trigger checklist - add new triggers here as they're defined.
    // 'id' must be unique; 'label' is what's shown next to the check circle.
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g,
            c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    // The two digest-header controls (Import + Past Editions). Both live inside
    // the header div, whose parent has onclick="toggleDigest()" — so each button
    // calls event.stopPropagation() first, or clicking it would also expand/
    // collapse the strip. See newsletter-ingestion.md "UI — Import control".