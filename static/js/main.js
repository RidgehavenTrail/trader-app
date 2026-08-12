// main.js — split from watchtower.html (classic script, global scope). Do not add import/export.


    loadNewsletterState();

    // --- Left panel + Actionable Moves init: sync localStorage list to
    // backend, then render sidebar/macro/actionable strip and poll on the
    // same cadence as trader_dashboard.html (10s prices/lists/moves, 10min macro). ---
    syncTickersWithBackend().then(() => {
        renderDashboard();
        fetchActionableMoves();
        fetchMacroRegime();          // immediate paint of the current briefing (even off-hours)
        setInterval(() => {
            renderDashboard();
            fetchActionableMoves();
        }, 10000);
        scheduleMacroPoll();         // window-gated + self-waking (replaces the flat 10-min setInterval)
    });

    // --- Rocket Strategy (Fed dial). Independent of the ticker sync above — it
    // reads FRED, not the watchlist, so it must not wait on syncTickersWithBackend.
    // 15-min poll: the dial's series prints once a business day, server caches 6h. ---
    fetchStrategyDial();
    setInterval(fetchStrategyDial, STR_POLL_MS);