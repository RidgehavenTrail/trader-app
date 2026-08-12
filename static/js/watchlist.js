// watchlist.js — split from watchtower.html (classic script, global scope). Do not add import/export.

    const categories = ["Watchlist", "Portfolio", "Dividends"];

    // Sidebar layout: one <details> per GROUP. A group with 2+ cats renders them as
    // side-by-side columns (Portfolio | Dividends), rows otherwise unchanged.
    const LIST_GROUPS = [
        { key: 'Watchlist', label: 'Watchlist', cats: ['Watchlist'] },
        { key: 'PortDiv', label: 'Portfolio / Dividends', cats: ['Portfolio', 'Dividends'] },
    ];
    const groupKeyForCat = (cat) =>
        (LIST_GROUPS.find(g => g.cats.includes(cat)) || {}).key || cat;

    const openStates = {};

    async function syncTickersWithBackend() {
        let stocks = JSON.parse(localStorage.getItem('userStocks')) || [];
        if (stocks.length === 0) return;
        const tickers = stocks.map(s => s.ticker);
        try {
            await fetch(`${API_BASE}/sync_tickers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tickers })
            });
        } catch (err) {
            console.error("Failed to sync tickers with backend", err);
        }
    }

    function saveState(cat) {
        const el = document.getElementById(`details-${cat}`);
        if (el) { openStates[cat] = el.open; }
    }

    async function deleteStock(ticker) {
        await fetch(`${API_BASE}/delete_ticker`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker })
        });
        let stocks = JSON.parse(localStorage.getItem('userStocks')) || [];
        stocks = stocks.filter(s => s.ticker !== ticker);
        localStorage.setItem('userStocks', JSON.stringify(stocks));
        await syncTickersWithBackend();
        renderDashboard();
    }

    async function addStock() {
        const ticker = document.getElementById('ticker-input').value.toUpperCase();
        const category = document.getElementById('category-input').value;
        if (!ticker) return;

        await fetch(`${API_BASE}/add_ticker`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker })
        });

        let stocks = JSON.parse(localStorage.getItem('userStocks')) || [];
        stocks = stocks.filter(s => s.ticker !== ticker);
        stocks.push({ ticker, category });
        localStorage.setItem('userStocks', JSON.stringify(stocks));

        await syncTickersWithBackend();
        document.getElementById('ticker-input').value = '';
        openStates[groupKeyForCat(category)] = true;
        renderDashboard();
    }

    async function renderDashboard() {
        LIST_GROUPS.forEach(g => saveState(g.key));
        const sidebar = document.getElementById('sidebar-lists');
        const stocks = JSON.parse(localStorage.getItem('userStocks')) || [];

        try {
            const res = await fetch(`${API_BASE}/get_market_data`);
            const marketData = await res.json();

            const getChangeVal = (ticker) => {
                const data = marketData[ticker];
                if (!data || !data.change || data.change === "--" || data.change === "...") return -Infinity;
                const val = parseFloat(data.change);
                return isNaN(val) ? -Infinity : val;
            };

            sidebar.innerHTML = LIST_GROUPS.map(group => {
                const multi = group.cats.length > 1;
                let groupCount = 0;

                const columns = group.cats.map(cat => {
                    const filtered = stocks.filter(s => s.category === cat);
                    filtered.sort((a, b) => getChangeVal(b.ticker) - getChangeVal(a.ticker));
                    groupCount += filtered.length;

                    const header = multi
                        ? `<div class="flex items-baseline gap-1 px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                               <span class="truncate">${cat}</span>
                               <span class="ml-auto shrink-0 text-slate-600">${filtered.length}</span>
                           </div>`
                        : '';

                    return `
                        <div class="flex-1 min-w-0">
                            ${header}
                            <div class="space-y-1">
                                ${filtered.length === 0 ? '<p class="text-xs text-slate-500 p-2 italic text-center">No tickers added.</p>' : ''}
                                ${filtered.map(s => {
                                    const data = marketData[s.ticker] || { price: "...", change: "..." };
                                    let changeColor = 'text-slate-400';
                                    if (data.is_positive === true) changeColor = 'text-emerald-400';
                                    if (data.is_positive === false) changeColor = 'text-red-400';
                                    return `
                                    <div class="py-1 px-2 rounded flex items-center group/item hover:bg-slate-800 transition-colors">
                                        <span class="font-bold text-slate-200 w-12 shrink-0 text-xs">${s.ticker}</span>
                                        <span class="text-xs font-mono text-slate-300 flex-1 text-right price-col">${data.price}</span>
                                        <span class="text-[10px] font-mono ${changeColor} font-medium bg-slate-950/50 px-1.5 py-0.5 rounded ml-2 w-12 text-right shrink-0">${data.change}</span>
                                        <button onclick="deleteStock('${s.ticker}')" class="text-slate-600 hover:text-red-400 opacity-0 group-hover/item:opacity-100 transition-opacity ml-1 shrink-0 flex items-center justify-center w-5 text-xs" title="Remove">✕</button>
                                    </div>
                                    `;
                                }).join('')}
                            </div>
                        </div>
                    `;
                }).join('');

                const isOpen = openStates[group.key] ? 'open' : '';

                return `
                    <details id="details-${group.key}" class="group glass-panel rounded-lg overflow-hidden" ${isOpen} ontoggle="saveState('${group.key}')">
                        <summary class="cursor-pointer font-medium p-3 hover:bg-slate-800/80 transition-colors flex justify-between items-center select-none text-sm border-b border-slate-700/50">
                            <div>
                                <span class="text-slate-300">${group.label}</span>
                                <span class="text-xs font-normal text-slate-500 ml-2 py-0.5 px-2 bg-slate-900 rounded-full">${groupCount}</span>
                            </div>
                            <span class="text-slate-500 group-open:rotate-90 transition-transform duration-200 text-xs">▶</span>
                        </summary>
                        <div class="p-1 bg-slate-900/50 flex gap-2 items-start">
                            ${columns}
                        </div>
                    </details>
                `;
            }).join('');
        } catch (err) {
            console.error("Error fetching data:", err);
        }
    }
