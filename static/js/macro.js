// macro.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    // Live Macro Regime section remembers open/closed across reloads (shared
    // helper in core.js). The headline stays visible either way — clamped to its
    // first two lines when collapsed (CSS in watchtower.html).
    persistCollapse('macro-section', 'macroSectionOpen');

    async function fetchMacroRegime() {
        try {
            const res = await fetch(`${API_BASE}/get_macro_regime`);
            const data = await res.json();
            if (!data.headline) return;
            document.getElementById('macro-headline').innerText = data.headline;
            document.getElementById('macro-summary').innerText = data.summary;
            document.getElementById('macro-updated').innerText =
                data.updated_at ? 'Updated ' + data.updated_at : '';
            document.getElementById('macro-tnx').innerText =
                data.tnx ? '10Y: ' + data.tnx + '%' : '10Y: --';
            document.getElementById('macro-vix').innerText =
                data.vix ? 'VIX: ' + data.vix : 'VIX: --';
        } catch (err) {
            console.error('Error fetching macro regime:', err);
        }
    }

    // --- Macro poll: window-gated + self-waking (2026-07-13) ---
    // The backend only regenerates the macro briefing during market hours, so poll
    // /get_macro_regime every 10 min ONLY within the market window (8:00am–4:30pm ET,
    // Mon–Fri; the 30-min tail past the 4:00 close catches a near-close briefing).
    // OUTSIDE the window there is NO backend call at all — a light local timer just
    // re-checks the wall clock every few minutes and the loop resumes itself at the
    // next open. So it never needs a manual restart, and it does zero off-hours polling.
    // (10-min in-window lag is intentional — the user is fine with it; see SESSIONS.md.)
    const MACRO_POLL_MS    = 600000;      // 10 min — in-window poll cadence
    const MACRO_DORMANT_MS = 300000;      // 5 min — off-hours CLOCK re-check only (no fetch)
    const MACRO_WIN_OPEN   = 8 * 60;      // 08:00 ET (minutes since ET midnight)
    const MACRO_WIN_CLOSE  = 16 * 60 + 30; // 16:30 ET — 4:00 close + 30-min grace

    // Current ET wall-clock as { dow: 0=Sun..6=Sat, minutes: since ET midnight }.
    // Uses the IANA zone so it's correct no matter the machine's local timezone.
    function etNow() {
        const parts = new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York', hour12: false,
            weekday: 'short', hour: '2-digit', minute: '2-digit'
        }).formatToParts(new Date());
        const val = t => parts.find(p => p.type === t).value;
        const dow = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[val('weekday')];
        let hour = parseInt(val('hour'), 10);
        if (hour === 24) hour = 0;         // some engines report midnight as '24'
        return { dow, minutes: hour * 60 + parseInt(val('minute'), 10) };
    }
    function inMacroWindow() {
        const { dow, minutes } = etNow();
        return dow >= 1 && dow <= 5 && minutes >= MACRO_WIN_OPEN && minutes < MACRO_WIN_CLOSE;
    }
    // Self-scheduling loop. Fetches ONLY while in-window; the delay is 10 min in-window
    // and a 5-min clock-recheck (no fetch) off-hours, so it wakes itself at the next
    // open with no interval polling overnight/weekends. A `fetchMacroRegime()` on page
    // load already paints the current briefing, so the first scheduled fetch is one
    // interval out (no double fetch on load).
    function scheduleMacroPoll() {
        const delay = inMacroWindow() ? MACRO_POLL_MS : MACRO_DORMANT_MS;
        setTimeout(() => {
            if (inMacroWindow()) fetchMacroRegime();   // network call ONLY during market hours
            scheduleMacroPoll();
        }, delay);
    }

    // --- Actionable Moves: real data from /get_actionable_moves, replacing
    // the old TICKER_MOCK. Every entry here is currently guaranteed
    // asset_class 'equity' — per .claude/rules/newsletter-tracker.md, only
    // equities/ETFs trigger Actionable Moves today (futures/forex are
    // deferred to Newsletter Plays only), so it's safe to inject that here
    // rather than guess from a suffix the engine doesn't send. ---