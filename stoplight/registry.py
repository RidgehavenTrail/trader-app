"""
Stoplight factor registry — the single manifest of the board.

One row per factor (16 ranked lights + the Silicon E module), mirroring the
locked AT-A-GLANCE table in `AI Stoplight/STOPLIGHT_SOURCES.md`. Rank = the
conviction ranking (SESSION_DELTA_2026-07-18.md) — yield curve is PERMANENTLY #1.

Fields:
  id         stable snake_case key (persistence + endpoint + frontend)
  name       display name
  rank       1-16 conviction rank; None for the Silicon E module
  module     True for Silicon E (a number-with-direction gauge, not a ranked light)
  cadence    check/refresh rate: hourly | daily | weekly | monthly | quarterly
  catalyst   dated driver, if any: earnings | data-release | self-gate | None
  highlight  display behavior on a fresh value: "new-tag" (a fresh print is news)
             vs "state-change" (highlight only on a color flip)
  builder    module name under stoplight/factors/ exporting compute() -> reading,
             or None while unbuilt (renders as a grayed placeholder)
  refine     optional True — factor is LIVE but flagged for refinement (renders a
             small badge). infra_backlog carries it: VRT structurally doesn't
             disclose orders/book-to-bill every quarter (confirmed Q1'26), so the
             number goes stale between disclosure quarters, and GEV's `combined`
             figure can change year-span between prints (scope non-comparability).

Direction convention (INVERTED board): GREEN = pro-burst, RED = bubble-supportive.
"""

FACTORS = [
    dict(id="yield_curve",     name="Yield curve",     rank=1,  cadence="daily",     catalyst=None,           highlight="state-change", builder="yield_curve"),
    dict(id="concentration",   name="Concentration",   rank=2,  cadence="daily",     catalyst=None,           highlight="state-change", builder="concentration"),
    # asof_keyed 2026-08-31: DGS2 prints on business days and FRED publishes it with
    # a lag, so a Friday poll sees Thursday and the weekend carries it forward --
    # 44 rows over 30 actual prints, 13 of them written on a Sat or Sun. Every
    # duplicate group is identical, so no correction is involved and keep-first is
    # right. Safe on the usual test: nothing does arithmetic on this history.
    dict(id="rate_path",       name="Rate path",       rank=3,  cadence="weekly",    catalyst="data-release", highlight="new-tag",      builder="rate_path", asof_keyed=True),
    # asof_keyed: this factor's snapshot row is keyed on the DATA date it reports, not
    # the ET date it was written. OpenRouter publishes the completed day with a lag, so
    # a write-date key files two ET days under one data day and orphans another — the
    # same mistake the ledgers table already avoids. Deliberately per-factor rather than
    # discovered from "does the reading carry an asof": the quarterly factors carry one
    # too, and re-keying them would reshape the series concentration and silicon_e do
    # arithmetic on. See store.record_snapshot(keep_first=).
    dict(id="premium_share",   name="Premium share",   rank=4,  cadence="daily",     catalyst=None,           highlight="state-change", builder="premium_share", asof_keyed=True),
    # asof_keyed for the reason the rail renderer asks for: a QUARTERLY factor keyed on
    # the write date shows ninety identical days instead of the seven prints it has
    # actually made, and the spec for this one says to track the TREND, not the level.
    # Safe here specifically -- nothing does arithmetic on this factor's history the way
    # concentration and silicon_e do on their own.
    dict(id="silicon_payback", name="Silicon payback", rank=5,  cadence="quarterly", catalyst="earnings",     highlight="new-tag",      builder="silicon_payback", asof_keyed=True),
    # asof_keyed 2026-08-31: FINRA publishes margin statistics MONTHLY, about six
    # weeks after the reference month -- the asof moved 2026-06-01 -> 2026-07-01 on
    # 2026-08-15. Polled daily, that filed 44 rows for 2 published figures, 13 of
    # them on a Sat or Sun. Every duplicate group is identical, so keep-first is
    # right; nothing does arithmetic on this history.
    dict(id="leverage",        name="Leverage",        rank=6,  cadence="monthly",   catalyst="data-release", highlight="new-tag",      builder="leverage", asof_keyed=True),
    dict(id="market_credit",   name="Market credit",   rank=7,  cadence="daily",     catalyst=None,           highlight="state-change", builder="market_credit"),
    # asof_keyed 2026-08-29: this factor polls daily and OBSERVES episodically -- 42
    # snapshot days held 10 distinct observations. Keyed on the observation date, the
    # log stops recording 32 restatements as if they were readings. Safe to flag: the
    # only consumer of its history is its own ledger(), which is display; nothing does
    # arithmetic on it (cf. concentration / silicon_e, which must NOT be flagged).
    dict(id="memory_canary",   name="Memory canary",   rank=8,  cadence="daily",     catalyst=None,           highlight="state-change", builder="memory_canary", asof_keyed=True),
    dict(id="regulatory",      name="Regulatory",      rank=9,  cadence="daily",     catalyst=None,           highlight="new-tag",      builder="regulatory"),
    # asof_keyed 2026-08-30: this factor polls daily but its index only PRINTS on a
    # trading day, so Friday's bar was re-filed on the Saturday, the Sunday, and the
    # Monday Yahoo had not yet assembled a new one -- 42 rows describing 29
    # observations, with the rail's weekday label a day ahead of its own data. Safe on
    # the same test memory_canary passed: NOTHING does arithmetic on this factor's
    # history. charts.py re-derives the index live from the factor's own build_index,
    # and events.py reads gate_date off the LIVE state rather than the log.
    dict(id="heavy_haul",      name="Heavy haul",      rank=10, cadence="daily",     catalyst="self-gate",    highlight="state-change", builder="heavy_haul", asof_keyed=True),
    # infra_backlog demoted 8 -> 11 and flagged for refinement (2026-07-19): VRT
    # doesn't disclose orders/BtB every quarter, so the light-driving number is often
    # stale; GEV combined-figure scope can shift between prints. Still LIVE on the board.
    # asof_keyed 2026-08-30, and this is the silicon_payback case exactly: a QUARTERLY
    # factor polled daily filed 42 rows over 5 data days, so the log recorded 37
    # restatements as if they were readings and the rail offered 42 clicks at 5 answers.
    # Safe on the same test the other three passed -- nothing does arithmetic on this
    # factor's history (cf. concentration / silicon_e, which must NOT be flagged).
    dict(id="infra_backlog",   name="Infra backlog",   rank=11, cadence="quarterly", catalyst="earnings",     highlight="new-tag",      builder="infra_backlog", refine=True, asof_keyed=True),
    # asof_keyed 2026-08-31: quarterly factors polled daily. capex_pressure filed 44
    # rows over 2 data days, capex_spigot 43 over 4 — the silicon_payback case again.
    # Safe on the same test: nothing does arithmetic on either factor's history.
    dict(id="capex_pressure",  name="Capex pressure",  rank=12, cadence="quarterly", catalyst="earnings",     highlight="new-tag",      builder="capex_pressure", asof_keyed=True),
    dict(id="capex_spigot",    name="Capex spigot",    rank=13, cadence="quarterly", catalyst="earnings",     highlight="new-tag",      builder="capex_spigot", asof_keyed=True),
    dict(id="copper",          name="Copper",          rank=14, cadence="hourly",    catalyst="self-gate",    highlight="state-change", builder="copper"),
    # asof_keyed 2026-09-03: the leverage case exactly, and missed when that one was
    # done. BEA publishes core PCE MONTHLY and this factor polls daily, so a capture-
    # keyed row was written every morning holding the same print: 47 rows carrying 3
    # observations, 44 of them byte-identical re-captures. Keyed on the DATA date the
    # rail shows one row per print, which is what the reading actually is.
    dict(id="inflation",       name="Inflation",       rank=15, cadence="monthly",   catalyst="data-release", highlight="new-tag",      builder="inflation", asof_keyed=True),
    dict(id="net_liquidity",   name="Net liquidity",   rank=16, cadence="weekly",    catalyst="data-release", highlight="new-tag",      builder="net_liquidity"),
    # Silicon E — the earnings module, displayed below the ranked 16 as an odometer gauge.
    dict(id="silicon_e",       name="Silicon E",       rank=None, module=True,
         cadence="daily", catalyst=None, highlight="state-change", builder="silicon_e"),
]

BY_ID = {f["id"]: f for f in FACTORS}
