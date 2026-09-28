// strategy-dive.js — the Rocket Strategy DETAIL panel (classic script, global scope).
// Do not add import/export; every function here must stay global, same as the other
// static/js modules (see .claude/rules/newsletter-tracker.md).
//
// SPLIT MIRRORS THE NEWSLETTER PAIR: newsletter-cards.js renders the strip and
// newsletter-dive.js owns its panel; strategy.js renders the sidebar and this owns
// the panel. strategy.js's own header scopes itself that way — "nothing numeric …
// lives here; that is detail-panel content" — so this is where the numeric side goes.
//
// WHAT THIS PANEL IS FOR (user, 2026-08-15): seeing a vehicle's strategy state AGAINST
// its price. The sidebar block already states the position in words; the value here is
// the chart with the strategy's own levels drawn on it.
//
// The chart is NOT reimplemented. charts.js is parameterised by view key (`dd`, `nd`)
// and gains a third, `sd` — same fetch, same candles, same SMA 50/200, same 2-year
// buffer for seeding. This file only supplies the entity and the levels to draw.

    let _sdSeq = 0;          // stale-guard: a slow fetch must not paint over a newer open

    // NO hideStrategyDive(). One was written for symmetry and never called: every other
    // panel's opener hides this one through showOnlyPanel(), so a private hide would be a
    // second way to do the same thing and the first to fall out of step. `_sdTicker` went
    // with it — that function was its only reader, so keeping it left a variable written
    // on every open and consulted by nothing.

    // The levels the chart draws, derived from the CONTRACT and nothing else.
    //
    // HOLDING -> where you got in and where it is going. FLAT -> the one price that would
    // put you in. Never both: a trigger while holding is not the next thing to happen, and
    // an entry line with no position is a line from a trade that is over.
    //
    // Colors follow the sidebar's own scheme rather than inventing tokens: the instrument's
    // hue for its entry, green for a target (the one place green already means "gain"), and
    // the instrument's hue at 55% for a trigger — visibly this name, visibly not a fill.
    function sdLevels(st, color) {
        const out = [];
        if (st.state_tier !== 'flat') {
            if (st.entry_price !== null && st.entry_price !== undefined) {
                out.push({ price: st.entry_price, color: color, title: 'entry' });
            }
            if (st.target !== null && st.target !== undefined) {
                out.push({ price: st.target, color: '#4ade80', title: 'target' });
            }
        } else if (Array.isArray(st.triggers) && st.triggers.length) {
            // EVERY resting bid gets a line, nearest first and fading behind it — the
            // tobacco ruleset keeps a deep bid under its regime bid every flat day, and
            // one line for two live orders showed half the book.
            st.triggers.forEach((t, i) => {
                out.push({ price: t.level, color: strHexToRgba(color, i === 0 ? 0.55 : 0.3),
                           title: t.label || 'resting bid' });
            });
        } else if (st.trigger !== null && st.trigger !== undefined) {
            out.push({ price: st.trigger, color: strHexToRgba(color, 0.55),
                       title: st.trigger_basis || 'entry' });
        }
        // WHERE THE STATE ENDS, drawn whether the book is long or flat — unlike the pair
        // above it is not an order and does not compete with them. During a trend run it
        // is the ONLY line the chart would otherwise have besides the entry: the position
        // has no target and no resting exit, so a chart without it shows a holding with
        // nothing ahead of it (user, 2026-08-26: track where histate ends and annotate it
        // on the chart).
        // SLATE, and never the instrument's hue: breaking it ends the STATE and hands the
        // book to a 200 retest — it fills nothing, so it must not read like the entry and
        // target lines that do. Colour is the only lever available: drawStrategyLevels
        // dashes EVERY line by construction, so a `dashed` flag here would be a
        // distinction the renderer does not make.
        if (st.state_end_level !== null && st.state_end_level !== undefined) {
            out.push({ price: st.state_end_level, color: '#64748b',
                       title: (st.state_end_label || 'state') + ' ends' });
        }
        // The gate gets a line too — same slate as the state-end level, and for the same
        // reason: neither is an order. A level that is never drawn is a level you have to
        // hold in your head while looking at the chart it belongs to.
        if (st.gate_level !== null && st.gate_level !== undefined) {
            out.push({ price: st.gate_level, color: '#64748b',
                       title: st.gate_status || 'gate' });
        }
        return out;
    }

    // The facts strip. Deliberately ONE row of inline items, not a grid of boxes — the
    // sidebar states the same position vertically and a second stacked copy would just be
    // the sidebar again, larger.
    // `color` is the instrument's own hue, and the LEVEL VALUES here are tinted to match
    // the lines drawn on the chart beside them (user, 2026-08-15) — entry in the
    // instrument's colour, target green, the trigger in the dimmed variant. That pairing is
    // what lets you read a level off the strip and find its line without a legend.
    //
    // PANEL ONLY. The sidebar's rows stay as they are: the same treatment was tried there
    // and reads busier, because that block is a narrow stack of many rows rather than one
    // strip sitting directly above the chart it refers to.
    function sdFactsHTML(st, color) {
        const item = (k, v, color) =>
            `<span class="sd-fact"><span class="sd-fact-k">${esc(k)}</span>` +
            `<span class="sd-fact-v"${color ? ` style="color:${color}"` : ''}>${v}</span></span>`;

        // Keyed on 'dark': the era is dark, the cross that starts it is a death cross.
        const eraColor = { golden: '#d4af37', WARNING: '#fbbf24', dark: '#f87171' }[st.era]
                       || '#64748b';
        let out = item('Era', esc(st.era || '—') +
                       (st.era_days ? ` <span class="sd-fact-sub">${st.era_days} td</span>` : ''),
                       eraColor);

        // Phase reads as the qualifier on the state, same rule as the sidebar: it explains
        // a flat system and adds nothing to an active one, which already names itself.
        const phase = (st.state_tier === 'flat' && st.phase)
            ? ` <span class="sd-fact-sub">${esc(st.phase)}</span>` : '';
        // Tinted like the sidebar's State row, through the SAME helper — the strip and
        // the block state the same posture and must not disagree about its colour.
        out += item('State', esc(st.state || '—') + phase,
                    strStateColor(st.state_tier, color));

        // A flat book's P&L is its cash accrual, and a return with no duration beside it
        // invites the wrong comparison — 0.93% reads very differently over 63 days than
        // over 6. `days_held` carries the cash run when there is no position.
        if (st.pnl_pct !== null && st.pnl_pct !== undefined) {
            const dur = (st.state_tier === 'flat' && st.days_held)
                ? ` <span class="sd-fact-sub">${st.days_held} td</span>` : '';
            out += item('P&L', strPct(st.pnl_pct) + dur);
        }
        if (st.entry_price !== null && st.entry_price !== undefined) {
            const held = (st.days_held === null || st.days_held === undefined)
                ? '' : ` <span class="sd-fact-sub">${st.days_held} td</span>`;
            out += item('Entry', st.entry_price.toFixed(2) + held, color);
        }
        if (st.target !== null && st.target !== undefined) {
            out += item('Target', st.target.toFixed(2), '#4ade80');
        }
        if (st.state_tier === 'flat' && Array.isArray(st.triggers) && st.triggers.length) {
            st.triggers.forEach((t, i) => {
                out += item('Entry @', t.level.toFixed(2) +
                            ` <span class="sd-fact-sub">${esc(t.label || 'resting bid')}</span>`,
                            strHexToRgba(color, i === 0 ? 0.55 : 0.3));
            });
        } else if (st.state_tier === 'flat' && st.trigger !== null && st.trigger !== undefined) {
            out += item('Entry @', st.trigger.toFixed(2) +
                        (st.trigger_basis ? ` <span class="sd-fact-sub">${esc(st.trigger_basis)}</span>` : ''),
                        strHexToRgba(color, 0.55));
        }
        // Paired with its dashed slate line on the chart, same slate here — the strip and
        // the chart are read together and a level must be findable from one in the other.
        if (st.state_end_level !== null && st.state_end_level !== undefined) {
            out += item(`${st.state_end_label || 'State'} ends`,
                        st.state_end_level.toFixed(2), '#64748b');
        }
        if (st.gate_status) {
            out += item('Gate', (st.gate_level !== null && st.gate_level !== undefined
                                 ? st.gate_level.toFixed(2) : '—') +
                        ` <span class="sd-fact-sub">${esc(st.gate_status)}</span>`, '#64748b');
        }
        out += item('Era P&L', strPct(st.era_pnl_pct));
        return `<div class="sd-facts-row">${out}</div>`;
    }


    // --- Strategy tab, three parts (user, 2026-09-01) ---------------------------------
    // TOP, full width: the notional phase diagram, which spans the pane so the rail can
    // show every phase. BELOW, half and half: LEFT the ruleset in force, RIGHT the recent
    // ledger. All three come from the SAME contract fetch the facts strip uses — no second
    // round trip, and no way for the rules pane to describe one strategy while the state
    // above it shows another.
    //
    // `rules` is served from the private config block, never authored here: it carries the
    // strategy's parameter VALUES and this repo has a public remote. If this file ever
    // hardcodes a rule, that is the leak — and a COMMENT naming the numbers is the same
    // leak, which is why none of them appear anywhere below either.
    // --- The notional phase diagram (user, 2026-09-01) --------------------------------
    // A TEACHING PICTURE, not QQQ: a synthetic price path so the golden cross, the phases it
    // opens, and every trade they produce can be read in one glance.
    //
    // WHAT IS REAL HERE AND WHAT IS NOT — the distinction is the whole design.
    //   REAL: the series is deterministic (a seeded LCG, never Math.random, or the picture
    //         would move on every render); the 50 and 200 SMAs are computed ON it; both
    //         crosses are FOUND by searching those two lines; and every buy and sell caret
    //         comes from `sdSimulate()` walking the ACTUAL RULES over that series — the two
    //         timers, the 50 SMA offsets that define a dip and a warning, the 50/200 gap the
    //         warning needs, and the multiple that sets a dip's target. Every one of those is
    //         SERVED from the published spec, never written here. No mark is placed because
    //         it looked good there.
    //   NOT REAL: the price path, and the band WIDTHS. The user's call (2026-09-01): the
    //         bands name the sequence, so they are laid out for LEGIBILITY — post-B1 gets
    //         the most room because that is where the day-to-day trading happens. The
    //         durations stay in the labels; the caption says they are not to scale.
    //
    // THE TAIL IS TUNED SO EVERY SELL LANDS ABOVE THE 200 (user, 2026-09-01), which lets the
    // warning read as a clean exit instead of tangling with never-sell-below-the-200. That
    // rule is a footnote here rather than a drawn case. Getting there took a real search:
    // a steep rollover puts price under the 200 before the gap ever narrows to 6%, so no
    // warning could fire above the line. A SHALLOW tail (-0.08) with a gentler uptrend
    // (0.13) leaves the gap in the 4-6% band while price is still above the 200 — verified
    // against the simulator, all four exits at +2.3 / +12.9 / +16.7 / +1.3 above it.
    // THE DARK-ERA TAIL (user, 2026-09-01): a cash stretch, then a steep selloff, then a
    // capitulation candle whose WICK takes out the 52-week low — the flush's price-side
    // condition. Every constant below came out of a parameter SEARCH, not a nudge, against
    // four assertions checked before any of it was written:
    //   1. bars 0..DC are BYTE-IDENTICAL to the old series, so the golden cross, the death
    //      cross and every golden-era trade are untouched. Trailing SMAs only look back, so
    //      changing the tail cannot move anything at or before the death cross — verified,
    //      not assumed.
    //   2. the capitulation bar is the FIRST 52-week low after the death cross. This is the
    //      whole difficulty: in a monotonic decline EVERY bar is a new low, so a selloff that
    //      runs through the level breaches it 8 bars early and the marked candle is not the
    //      one the rule would have fired on. The selloff therefore bottoms 4.9 ABOVE the
    //      level and only the wick goes through it, by 7.6.
    //   3. the wobble is damped to 0.25 through the selloff. At full amplitude (+/-13) the
    //      oscillation is larger than the crash and breaches the low on its own.
    //   4. the rebound reaches the 200 SMA inside the drawn window, so the flush's exit is
    //      visible rather than implied.
    // THE PATH IS PUBLISHED, NOT WRITTEN HERE (2026-09-01). It used to be six drift
    // constants and a hand-placed spike, tuned for QQQ: a cash drift after the death cross,
    // a steep selloff, and a capitulation wick that takes out the 52-week low so the VIX
    // flush has something to fire on.
    //
    // THAT SHAPE IS QQQ'S ARGUMENT, NOT A NEUTRAL BACKDROP, and a second strategy needs its
    // own. GLD's dark sleeve waits for a 23-day low to be TAKEN OUT and then keeps waiting
    // while lower lows print — on QQQ's tail the level gives way on the first bar after the
    // cross, so the sleeve enters two bars in and the picture shows none of the waiting that
    // is the whole character of the rule. One series cannot teach both.
    //
    // So the generator takes a spec: a seed, a starting level, drift SEGMENTS, the wobble
    // components, an optional damping window and an optional spike bar. Same determinism as
    // before — a seeded LCG, never Math.random — and the values live in the strategy repo
    // with every other parameter.
    // TWO WAYS TO SPECIFY THE PATH, and `points` is the one to reach for.
    //
    //   points   — the shape is DRAWN: waypoints of [fraction across, level], smoothly
    //              interpolated. You say what the picture looks like and get it.
    //   segments — the shape is GROWN from per-bar drifts. Every property of the result is
    //              emergent, so "make the run start further right" is a search, not an edit.
    //              Kept because QQQ's picture is tuned in it and reproducing that exactly
    //              matters more than uniformity.
    //
    // A drawn path is the right default for a TEACHING picture: the diagram exists to show
    // the shape of a strategy, and a shape you can only reach by hill-climbing drift
    // constants is one you cannot correct when someone points at it and says "not like that"
    // (user, 2026-09-01).
    function sdNotionalBars(PA) {
        let seed = PA.seed;
        const rnd = () => {
            seed = (seed * 1103515245 + 12345) & 0x7fffffff;
            return seed / 0x7fffffff - 0.5;
        };
        if (PA.points) {
            const pts = PA.points, n = PA.n, noise = PA.noise == null ? 2.2 : PA.noise;
            // WAYPOINTS ARE THE TREND, WOBBLE IS THE MARKET. The first drawn version had the
            // waypoints alone plus a little speckle, and came out a smooth curve with dust on
            // it — nothing like a price series, and the 50 had no curvature because there was
            // nothing for it to lag behind. A real chart swings INSIDE its trend: pullbacks on
            // the way up, overshoots at the turns. That swing is what the eye reads as a
            // market, and it is what makes the 50 bend.
            // So the shape is drawn and the texture is oscillated, which is also what lets a
            // dip sleeve have anything to buy.
            const wob = PA.wobble || [];
            const body = PA.body == null ? 1.0 : PA.body;
            const out = [];
            for (let i = 0; i < n; i++) {
                const f = i / (n - 1);
                let k = 0;
                while (k < pts.length - 2 && f > pts[k + 1][0]) k++;
                const f0 = pts[k][0], v0 = pts[k][1], f1 = pts[k + 1][0], v1 = pts[k + 1][1];
                const t = (f - f0) / ((f1 - f0) || 1);
                // smoothstep, so the joins between waypoints have no corners in them
                let px = v0 + (v1 - v0) * (t * t * (3 - 2 * t));
                for (let j = 0; j < wob.length; j++) px += Math.sin(i / wob[j][0]) * wob[j][1];
                px += rnd() * noise;
                const o = px + rnd() * body, c = px + rnd() * body;
                const w = Math.abs(rnd()) * body * 1.2;
                out.push({ o: o, c: c, h: Math.max(o, c) + w, l: Math.min(o, c) - w });
            }
            return out;
        }
        const out = [];
        let trend = PA.trend0;
        const damp = PA.damp, spike = PA.spike;
        for (let i = 0; i < PA.n; i++) {
            // The FIRST segment whose bound the bar is under owns it; the last is open-ended.
            // The decline must outlast the 200-bar WARM-UP, or the cross happens where no
            // 200 SMA exists yet and cannot be detected at all — that is a property of any
            // path published here, not of this one.
            let drift = PA.segments[PA.segments.length - 1][1];
            for (let k = 0; k < PA.segments.length; k++) {
                if (i < PA.segments[k][0]) { drift = PA.segments[k][1]; break; }
            }
            trend += drift;
            // Trend PLUS oscillation, not a random walk: the phases where dips and warnings
            // live need the path to actually pull back to the 50 from time to time.
            // Damping exists because a selloff steeper than the wobble is still invisible
            // underneath it — at full amplitude the oscillation makes the new lows, not the
            // decline.
            let amp = 1;
            if (damp) {
                if (i > damp.from && i <= damp.to) amp = damp.amp;
                else if (i > damp.to && i <= damp.to + damp.ramp)
                    amp = damp.amp + (1 - damp.amp) * ((i - damp.to) / damp.ramp);
            }
            let wob = 0;
            for (let k = 0; k < PA.wobble.length; k++)
                wob += Math.sin(i / PA.wobble[k][0]) * PA.wobble[k][1];
            wob *= amp;
            const px = Math.max(15, trend + wob + rnd() * 1.5);
            const o = px + rnd() * 1.0, c = px + rnd() * 1.0;
            const w = Math.abs(rnd()) * 1.4;
            const bar = { o: o, c: c, h: Math.max(o, c) + w, l: Math.min(o, c) - w };
            // A capitulation candle: long lower wick, closing back near the open. A rule that
            // buys the CLOSE needs the close well off the low, or its caret sits at a price
            // the rule never pays.
            if (spike && i === spike.bar) {
                const base = Math.min(o, c);
                bar.l = base - spike.wick;
                bar.o = base + 1.2; bar.c = base + 0.2; bar.h = base + 1.6;
            }
            out.push(bar);
        }
        return out;
    }

    function sdSMA(bars, k) {
        const out = new Array(bars.length).fill(null);
        let sum = 0;
        for (let i = 0; i < bars.length; i++) {
            sum += bars[i].c;
            if (i >= k) sum -= bars[i - k].c;
            if (i >= k - 1) out[i] = sum / k;
        }
        return out;
    }

    // Trailing k-bar high and low of the PRIOR window — the current bar excluded, so "takes
    // out the 52-week high" means it beats what came before it rather than beating itself.
    // Feeds three things that must agree: where Breakout 1 fires, where the flush fires, and
    // the levels DRAWN on the chart. One computation, so a mark cannot disagree with the line
    // that is supposed to explain it.
    function sdRolling(bars, k) {
        const hi = [], lo = [];
        for (let i = 0; i < bars.length; i++) {
            if (i < k) { hi.push(null); lo.push(null); continue; }
            let h = -Infinity, l = Infinity;
            for (let j = i - k; j < i; j++) { h = Math.max(h, bars[j].h); l = Math.min(l, bars[j].l); }
            hi.push(h); lo.push(l);
        }
        return { hi: hi, lo: lo };
    }

    // Walks the real rules over the notional series and returns round trips. ONE SLOT, the
    // same as the system: nothing opens while something is held.
    //
    // EVERY NUMBER COMES FROM `P`, THE PUBLISHED phase_diagram. This function used to carry
    // the dip offset, the target multiple, the warning offset and the warning's gap ceiling
    // as LITERALS — the strategy's actual rule parameters, in a file whose repo has a public
    // remote, which is the exact leak this file's own header warns about. They are served at
    // runtime now, the way `gate_td` always was.
    //
    // `P.opens` says which sleeve may open in each BAND, which is what lets one simulator
    // draw more than one strategy. QQQ holds a halo through the gate band and is flat in the
    // dark; GLD's halo is switched off so its gate band takes DIPS, and its dark band is
    // owned by the dark sleeve. Same skeleton, different occupants.
    function sdSimulate(bars, s50, s200, gc, dc, gateEnd, b1, b1End, P) {
        const opens = (P && P.opens) || {};
        const band = i => i < gateEnd ? 'gate' : i < b1 ? 'pre_b1'
                        : i < b1End ? 'b1' : 'post_b1';
        const tr = [];
        let pos = null;
        for (let i = gc; i <= dc; i++) {
            if (s50[i] === null || s200[i] === null || s50[i - 1] === null) continue;
            const gap = (s50[i] - s200[i]) / s200[i] * 100;
            const warn = bars[i].l <= s50[i - 1] * P.warn_mult && gap < P.warn_gap;
            if (pos) {
                let why = null;
                if (pos.kind === 'halo' && i >= gateEnd) why = 'timer';
                else if (pos.kind === 'b1' && i >= b1End) why = 'timer';
                else if (pos.kind === 'dip' && bars[i].h >= pos.fill * P.target_mult) why = 'target';
                else if (pos.kind === 'dip' && warn) why = 'warning';
                else if (i === dc) why = 'death cross';
                if (why) { tr.push({ kind: pos.kind, e: pos.i, x: i, why: why }); pos = null; }
            }
            if (!pos) {
                const b = band(i);
                if (i === gc && opens.gate === 'halo') pos = { kind: 'halo', i: i, fill: bars[i].c };
                else if (i === b1 && opens.b1 === 'b1') pos = { kind: 'b1', i: i, fill: bars[i].c };
                else if (opens[b] === 'dip' && i < dc && !warn
                         && bars[i].l <= s50[i - 1] * P.dip_mult) {
                    pos = { kind: 'dip', i: i, fill: s50[i - 1] * P.dip_mult };
                }
            }
        }
        return tr;
    }

    // THE DARK-ERA SLEEVE, the one mechanism the core simulator has no shape for. Four
    // clauses, walked exactly as `gld_system.py`'s header states them:
    //   1  at the DEATH CROSS take the N-day low. The window INCLUDES the dc bar, and the
    //      dc bar can never itself be the breach bar.
    //   2  wait for price to take that level out, then keep waiting while lower lows print.
    //      BUY the close of the first day that does NOT make a new low.
    //   3  the first 52-week low WHILE HELD exits at that close — a genuine stop that sells
    //      below the 200 on purpose. Re-enter at the close of the first day with no new
    //      52-week low, then ignore lows for the rest of the era.
    //   4  exit at the GOLDEN CROSS, always.
    // Clause 4's asymmetry is why never-sell-below-the-200 is not applied to clause 3: on a
    // stop it would remove the stop.
    function sdDarkSleeve(bars, s50, s200, roll, dc, to, look) {
        const tr = [];
        let lvl = Infinity;
        for (let k = Math.max(0, dc - look + 1); k <= dc; k++) lvl = Math.min(lvl, bars[k].l);
        let run = null, pos = null, armed = false, reenter = false;
        for (let i = dc + 1; i <= to; i++) {
            // Clause 4 first: the golden cross ends the era whatever is happening.
            if (s50[i] !== null && s200[i] !== null && s50[i] > s200[i] && s50[i - 1] <= s200[i - 1]) {
                if (pos) tr.push({ kind: 'dark', e: pos, x: i, why: 'golden cross' });
                return tr;
            }
            const newLow = roll.lo[i] !== null && bars[i].l < roll.lo[i];
            if (pos !== null) {
                if (!armed && newLow) {                      // clause 3, the stop
                    tr.push({ kind: 'dark', e: pos, x: i, why: '52wk low' });
                    pos = null; reenter = true; armed = true;
                }
                continue;
            }
            if (reenter) { if (!newLow) { pos = i; reenter = false; } continue; }
            if (run === null) { if (bars[i].l <= lvl) run = bars[i].l; continue; }  // clause 2
            if (bars[i].l < run) { run = bars[i].l; continue; }
            pos = i;                                          // first bar with no new low
        }
        if (pos !== null) tr.push({ kind: 'dark', e: pos, x: to, why: 'OPEN' });
        return tr;
    }

    // THE DARK-ERA OVERLAY as a drawn position. It is a DAY FILTER in the backtest -- an
    // array of days it is long, with no trade records -- and I first read that as "nothing to
    // draw". Wrong: the filter produces visible RUNS, and the run boundaries are exactly the
    // rule (user, 2026-09-02).
    //   * the core goes flat at the DEATH CROSS, so the overlay is long from there;
    //   * a new 252-day low sends it to T-bills the NEXT session, and it stays out while the
    //     lows keep printing;
    //   * it re-enters once they stop;
    //   * the GOLDEN CROSS ends the era and hands the book back to the core.
    // Long on a dark day UNLESS the PRIOR session made a new 252-day low -- the shift is the
    // no-look-ahead rule, and it is why the exit lands the bar AFTER the low.
    //
    // RE-ENTRY WAITS FOR THE LOWS TO STOP, which is a DISPLAY simplification and the only one
    // here. Taken literally the filter is per-day, so through a decline it flickers on and off
    // as some bars make new lows and some do not -- five round trips on this path, which is
    // mechanically right and unreadable. Requiring a few quiet bars first draws what the rule
    // MEANS: out at the low, out while they keep coming, back in once they stop. The exits are
    // untouched; only the re-entries are debounced.
    function sdOverlayLong(bars, s50, s200, roll, dc, to, quiet) {
        const CLEAR = quiet || 5;   // bars of NO new low before it goes back on
        const tr = [];
        let pos = null, calm = CLEAR;
        for (let i = dc + 1; i <= to; i++) {
            if (s50[i] !== null && s200[i] !== null && s50[i] > s200[i] && s50[i - 1] <= s200[i - 1]) {
                if (pos !== null) tr.push({ kind: 'overlay', e: pos, x: i, why: 'golden cross' });
                return tr;                                   // era over
            }
            const postLow = roll.lo[i - 1] !== null && bars[i - 1].l <= roll.lo[i - 1];
            calm = postLow ? 0 : calm + 1;
            if (pos !== null && postLow) {
                tr.push({ kind: 'overlay', e: pos, x: i, why: '52wk low' });
                pos = null;
            } else if (pos === null && calm >= CLEAR) {
                pos = i;
            }
        }
        if (pos !== null) tr.push({ kind: 'overlay', e: pos, x: to, why: 'OPEN' });
        return tr;
    }

    // TOBACCO. Two tiers over one slot, which is a different picture from the other three:
    // no timed gate, no breakout hold, no post-B1 regime. What it has instead is a HANDOVER,
    // and the handover is the thing worth drawing (user, 2026-09-02).
    //
    //   a bid fills          -> BUY caret. The book is long, tier 2 owns it.
    //   a 252-day HIGH prints -> tier 1 takes over. NO CARET: nothing was bought or sold,
    //                            the slot simply changed hands. The band changes instead.
    //   a 252-day LOW prints  -> SELL caret. Tier 1's only exit, and it sells below the 200
    //                            on purpose -- never-sell-below-the-200 is scoped to dip
    //                            exits and does not reach here.
    //
    // Returns the round trip plus the bar the handover happened on, so the caller can band
    // the run in two colours and show one position held by two tiers.
    function sdTobacco(bars, s50, s200, roll, from, to, P) {
        let his = false, pos = null, hand = -1;
        const tr = [];
        for (let i = from + 1; i <= to; i++) {
            if (roll.hi[i] === null || s50[i - 1] === null || s200[i] === null) continue;
            const newHigh = bars[i].h >= roll.hi[i];
            const newLow = roll.lo[i] !== null && bars[i].l <= roll.lo[i];
            const was = his;
            if (newHigh) his = true; else if (newLow) his = false;

            if (was && !his && pos !== null) {          // tier 1's 252-day low ends the run
                tr.push({ kind: pos.kind, e: pos.i, x: i, why: '252d low', hand: hand });
                pos = null; hand = -1;
                continue;
            }
            if (!was && his && pos !== null && hand < 0) hand = i;   // the handover
            if (!was && his && pos === null) { pos = { kind: 'histate', i: i }; hand = i; }
            if (pos !== null || his) continue;

            // Tier 2, only while tier 1 is flat. The golden dip needs the 50/200 gap ABOVE
            // its floor -- the opposite test to the warning, and the reason a dip here is a
            // trend pullback rather than a breakdown.
            const gap = (s50[i] - s200[i]) / s200[i] * 100;
            if (gap >= P.gap_min && bars[i].l <= s50[i - 1] * P.dip_mult) {
                pos = { kind: 'dip', i: i };
            }
        }
        if (pos !== null) tr.push({ kind: pos.kind, e: pos.i, x: to, why: 'OPEN', hand: hand });
        return tr;
    }

    // TOBACCO. Relabelling the shared bands was not enough and the picture said so: a TIMER
    // fired inside "histate", and the band edges sat where QQQ's gate and B1 hold end rather
    // than where anything tobacco does happens (user, 2026-09-02). The bands have to come
    // from the STATE MACHINE.
    //
    //   tier 1 turns ON at a 252-day HIGH and OFF at a 252-day LOW. Between them it owns the
    //   slot and NOTHING else trades -- no timer, no target, no warning. That stretch is one
    //   band and one held position.
    //   tier 2 trades only while tier 1 is flat: a dark bid under the 200, or a golden dip,
    //   and it exits on the 200 TOUCH rather than on a target.
    //   the takeover is a HANDOVER: labelled, banded, but no caret, because nothing is bought.
    function sdTobacco(bars, s50, s200, roll, from, to, P) {
        const tr = [];
        let his = false, pos = null, on = -1, off = -1;
        for (let i = from + 1; i <= to; i++) {
            if (roll.hi[i] === null || s50[i - 1] === null || s200[i] === null) continue;
            const nh = bars[i].h >= roll.hi[i];
            const nl = roll.lo[i] !== null && bars[i].l <= roll.lo[i];
            const was = his;
            if (nh) his = true; else if (nl) his = false;

            if (!was && his) {                       // 252-day high: tier 1 takes the slot
                if (on < 0) on = i;
                if (pos) { pos.hand = i; } else { pos = { kind: 'histate', i: i, hand: i }; }
                continue;
            }
            if (was && !his) {                       // 252-day low: tier 1's only exit
                if (off < 0) off = i;
                if (pos) { tr.push({ kind: pos.kind, e: pos.i, x: i, why: '252d low',
                                     hand: pos.hand }); pos = null; }
                continue;
            }
            if (his) continue;                       // tier 1 owns it -- nothing else trades

            if (pos) {
                // THE TWO TIER-2 SLEEVES DO NOT EXIT THE SAME WAY, and drawing them alike was
                // wrong: the golden dip runs to a TARGET of fill x the multiple (or is exited
                // by a warning), while the deep and dark BIDS exit on the first 200 touch.
                // The engine header lists them as separate lines for that reason.
                let why = null;
                if (pos.kind === 'dip') {
                    const warn = bars[i].l <= s50[i - 1] * P.warn_mult
                                 && (s50[i] - s200[i]) / s200[i] * 100 < P.warn_gap;
                    // NO FALLBACKS (2026-09-10). The target, the dip-gap floor and the dark-bid
                    // depth each carried an `|| <default>` here -- rule values, in a file with a
                    // PUBLIC remote, the same literals that moved out on 2026-08-12. A missing
                    // parameter now compares false and the simulator draws nothing, which is
                    // what sdSetColumns' contract says it must do. Do not write the numbers
                    // back in, and do not name them in a comment either.
                    if (bars[i].h >= pos.fill * P.target_mult) why = 'target';
                    else if (warn) why = 'warning';
                } else if (s200[i - 1] !== null && bars[i].h >= s200[i - 1]) {
                    why = '200 touch';
                }
                if (why) { tr.push({ kind: pos.kind, e: pos.i, x: i, why: why }); pos = null; }
                continue;
            }
            const dark = s50[i] <= s200[i];
            const gap = (s50[i] - s200[i]) / s200[i] * 100;
            if (dark && bars[i].l <= s200[i - 1] * P.dark_bid_mult) {
                pos = { kind: 'dark', i: i };        // the dark bid, under the 200
            } else if (!dark && gap >= P.gap_min && bars[i].l <= s50[i - 1] * P.dip_mult) {
                pos = { kind: 'dip', i: i, fill: s50[i - 1] * P.dip_mult };
            }
        }
        if (pos) tr.push({ kind: pos.kind, e: pos.i, x: to, why: 'OPEN', hand: pos.hand });
        return { trades: tr, on: on, off: off };
    }

    // `aspect` is the rendered box's width/height. The viewBox WIDTH is derived from it so
    // the drawing stays ISOTROPIC — see SD_DIAG_H's note. Defaults to the shape the card had
    // when it was half the pane, so a render that cannot measure still looks like something.
    function sdPhaseDiagramHTML(pd, aspect) {
        const GATE = (pd && pd.gate_td) || 63;
        const B1H = (pd && pd.b1_hold_td) || 126;
        const B1W = (pd && pd.b1_window_td) || 252;   // "within 252 td of the cross"
        const N = pd.path.n;
        const bars = sdNotionalBars(pd.path);
        const s50 = sdSMA(bars, 50), s200 = sdSMA(bars, 200);
        const roll = sdRolling(bars, B1W);

        let gc = -1, dc = -1;
        for (let i = 1; i < N; i++) {
            if (s50[i] === null || s200[i] === null || s50[i - 1] === null) continue;
            if (gc < 0 && s50[i] > s200[i] && s50[i - 1] <= s200[i - 1]) gc = i;
            else if (gc > 0 && dc < 0 && s50[i] <= s200[i] && s50[i - 1] > s200[i - 1]) dc = i;
        }
        if (gc < 0 || dc < 0) return '';

        const span = dc - gc;
        // The band WIDTHS stay fractions of the span, which is the legibility call the user
        // made and is why the caption says they are not to scale.
        const gateEnd = gc + Math.round(span * 0.15);

        // BREAKOUT 1 IS FOUND, NOT PLACED (user, 2026-09-01). It used to sit at a flat
        // gateEnd + 9% of the span, which on this series is bar 328 — where price is 76.0
        // against a trailing 52-week high of 92.0, i.e. a "52-week breakout" caret drawn 17%
        // BELOW the 52-week high. The rule is "the first 52-week breakout within 252 td of
        // the cross", so it is searched for the same way the two crosses are, inside that
        // published window. The fallback keeps the old placement rather than returning no
        // diagram at all, since a series with no breakout is still a legible picture.
        let b1 = -1;
        for (let i = gateEnd + 1; i <= Math.min(dc, gc + B1W); i++) {
            if (roll.hi[i] !== null && bars[i].h > roll.hi[i]) { b1 = i; break; }
        }
        if (b1 < 0) b1 = gateEnd + Math.round(span * 0.09);
        const b1End = b1 + Math.round(span * 0.20);
        const tob = !!(pd.opens && pd.opens.tiers === 'tobacco');
        // Tobacco's book is computed once the drawn WINDOW is known, below — its sleeves are
        // scoped to what is on screen rather than to the era.
        let tobOut = null;
        let trades = tob ? [] : sdSimulate(bars, s50, s200, gc, dc, gateEnd, b1, b1End, pd || {});

        // THE VIX FLUSH, price side only. Entry = the first 52-week low after the death
        // cross, bought at the CLOSE; exit = the first touch of the prior day's 200 SMA.
        // Both are read off this series exactly as the rule states them.
        // WHAT IS ASSUMED: the rule also needs the VIX intraday high over 40, and a
        // price-only chart cannot carry that. The caption says so. It is the one mark here
        // not fully derived from the drawn series, and it is called out rather than hidden.
        // ONLY FOR A STRATEGY THAT HAS ONE. This ran unconditionally and drew a "VIX flush"
        // round trip on GLD, which has no flush sleeve at all — the overlay is QQQ's. The
        // trigger is a 52-week low, which any falling path produces, so nothing about the
        // series was going to stop it; the gate has to be the published spec.
        let flushIn = -1, flushOut = -1;
        if (pd.opens && pd.opens.flush === 'flush') {
        for (let i = dc + 1; i < N; i++) {
            if (roll.lo[i] !== null && bars[i].l < roll.lo[i]) { flushIn = i; break; }
        }
        if (flushIn > 0) {
            for (let i = flushIn + 1; i < N; i++) {
                if (s200[i - 1] !== null && bars[i].h >= s200[i - 1]) { flushOut = i; break; }
            }
            if (flushOut < 0) flushOut = N - 1;
        }
        }

        const from = Math.max(0, gc - Math.round(span * (pd.path.pre_frac || 0.22)));
        // The window runs far enough past the death cross to hold the cash stretch, the
        // selloff and the flush's ROUND TRIP. Drawing the entry without its exit would show
        // the overlay opening a position and never closing it.
        const to = Math.min(N - 1, Math.max(dc + Math.round(span * (pd.path.post_frac || 0.34)),
                                            (flushOut > 0 ? flushOut : dc) + 10));

        if (tob) {
            tobOut = sdTobacco(bars, s50, s200, roll, from, to, pd);
            trades = tobOut.trades;
        }

        // The dark sleeve, where a strategy has one. Its trades are real round trips like
        // the core's, so they get carets and rail bands rather than a label.
        const dk = pd.opens && pd.opens.dark;
        const dark = dk === 'dark'
            ? sdDarkSleeve(bars, s50, s200, roll, dc, to, pd.dark_lookback_td || 23)
            : dk === 'overlay' ? sdOverlayLong(bars, s50, s200, roll, dc, to) : [];
        // A second golden cross inside the window ends the dark era and starts a new one —
        // which is the whole cycle for a strategy whose two sleeves hand the book back and
        // forth. Found by search, like the first two crosses.
        let gc2 = -1;
        for (let i = dc + 1; i <= to; i++) {
            if (s50[i] !== null && s200[i] !== null && s50[i] > s200[i] && s50[i - 1] <= s200[i - 1]) {
                gc2 = i; break;
            }
        }
        // THE VIEWBOX IS SIZED TO THE BOX IT WILL BE DRAWN IN (2026-09-01). This svg is
        // preserveAspectRatio="none", so a viewBox whose shape does not match the element's
        // gets stretched on ONE axis: when the diagram moved to a full-width row the fixed
        // 100x40 box was stretched 2.26x horizontally, and the buy/sell carets — drawn in
        // viewBox units — went from 8.1x5.3px to 20.2x5.3px, flat slivers instead of carets.
        // Deriving W from the aspect makes both axes scale by the same factor, so carets,
        // candles and stroke widths all keep their proportions at ANY width.
        const H = 40, W = Math.max(60, Math.round(H * (aspect || 2.5)));
        // Kept as the same FRACTION of the width it was at W=100, so the side margins do
        // not shrink to nothing as W grows.
        const PAD = 1.1, PADX = W * 0.011;
        let lo = Infinity, hi = -Infinity;
        for (let i = from; i <= to; i++) {
            lo = Math.min(lo, bars[i].l, s200[i] === null ? Infinity : s200[i]);
            hi = Math.max(hi, bars[i].h, s200[i] === null ? -Infinity : s200[i]);
        }
        const nb = to - from;
        const X = i => PADX + (i - from) / nb * (W - PADX * 2);
        const Y = v => PAD + (hi - v) / (hi - lo) * (H - PAD * 2);
        const cw = Math.max(0.24, (W - PADX * 2) / (nb + 1) * 0.6);

        // Bands are declared ONCE and drive three things — the shading behind the candles,
        // the rail under them, and the key under that. They used to be declared after the
        // shade, which is why only post-B1 was ever tinted (user, 2026-09-01: shade them
        // all). A phase that is named in the rail and unnamed on the chart makes the reader
        // map one to the other by eye.
        // `sc` is a lighter SHADE colour where the band colour is too dark to register as a
        // wash: slate at 9% on this background is invisible.
        // PALETTE: every phase a different HUE, because the colour is now the only thing
        // telling them apart — the wash is gone (user, 2026-09-01).
        //   pre-B1 was #64748b, a second grey next to the dark era's #475569, and the two were
        //   not tellable apart. It is rose now; the dark era is the only grey left, which suits
        //   it being the only phase that is not a phase of the trade.
        //   post-B1 was #4ade80, the same green as the buy carets and the up candles, so the
        //   band read as part of the price. Teal instead.
        // WHAT THE DARK ERA IS DOING is per strategy and comes from the spec, because the
        // three answers are genuinely different: QQQ sits in T-bills, GLD's dark sleeve
        // TRADES it, and XLE is LONG most of it under a day-filter overlay. Defaulting any
        // of those onto another would put a wrong description under a correct band.
        const darkNote = pd.dark_note
                      || (dark.length ? 'the dark sleeve trades it' : 'flat, in T-bills');
        const bands = [
            { a: from, b: gc, t: 'dark era', s: darkNote, c: '#475569' },
            // The gate band's SUBTITLE comes from `opens`, not from QQQ's habit. GLD's halo is
            // switched off, so its 63 td window is an exclusion zone that only dips may enter
            // — labelling it "halo holds" there would name a trade the strategy never takes.
            { a: gc, b: gateEnd,  t: GATE + 'd gate',
              s: (pd.opens && pd.opens.gate === 'dip') ? 'dips only' : 'halo holds',
              c: '#a78bfa' },
            { a: gateEnd, b: b1, t: 'pre-B1', s: 'hunting', c: '#fb7185' },
            { a: b1, b: b1End, t: 'Breakout 1', s: B1H + 'd hold', c: '#38bdf8' },
            { a: b1End, b: dc, t: 'post-B1', s: 'dips + warning', c: '#2dd4bf' },
        ];
        // The dark era splits around the flush, which is what shows the CASH stretch: the
        // death cross puts the book flat, it sits in T-bills, the overlay takes one trade,
        // and it goes back to flat.
        const darkEnd = gc2 > 0 ? gc2 : to;
        if (flushIn > 0) {
            bands.push({ a: dc, b: flushIn, t: 'dark era', s: darkNote, c: '#475569' });
            bands.push({ a: flushIn, b: flushOut, t: 'VIX flush', s: 'overlay, while flat', c: '#f59e0b' });
            bands.push({ a: flushOut, b: darkEnd, t: 'dark era', s: darkNote, c: '#475569' });
        } else {
            bands.push({ a: dc, b: darkEnd, t: 'dark era', s: darkNote, c: '#475569' });
        }
        // The era the second cross opens. Named for what it IS rather than repeating the
        // gate's label: nothing is drawn past it, so it is the cycle closing, not a phase.
        if (gc2 > 0) bands.push({ a: gc2, b: to, t: 'golden era', s: 'the core resumes',
                                  c: '#a78bfa' });
        // RENAMED FROM THE SPEC, not re-derived. Tobacco has the same SHAPE as the others on
        // this picture — a pullback bought, a 252-day high that changes who owns the slot, a
        // 252-day low that ends it — but none of the same WORDS: no gate, no Breakout 1, no
        // post-B1. Overriding the band titles is the whole difference, and it beats a second
        // renderer that would draw the same lines under different names.
        const bn = pd.band_names || {};
        const BK = { 'dark era': 'dark', 'pre-B1': 'pre_b1', 'golden era': 'golden' };
        bands.forEach(z => {
            const key = BK[z.t] || (z.t.indexOf('gate') >= 0 ? 'gate'
                       : z.t.indexOf('Breakout') >= 0 ? 'b1'
                       : z.t.indexOf('post-B1') >= 0 ? 'post_b1' : null);
            const o = key && bn[key];
            if (o) { z.t = o[0]; z.s = o[1]; }
        });
        // TOBACCO'S BANDS FOLLOW THE BOOK, one phase per position held, cash in between --
        // "that's what the trades in the phase diagram demand" (user, 2026-09-02). Three
        // bands keyed on the histate state alone did not line up with what was drawn: a dip
        // and a dark bid sat inside stretches labelled "bids rest", which is what the book
        // does BETWEEN them.
        // A run that hands over is SPLIT at the handover, so one position shows as two
        // phases -- which is the whole point of the handover being visible at all.
        if (tob) {
            const NM = { dip: ['golden dip', 'tier 2 holds, target x1.12'],
                         dark: ['dark bid', 'tier 2 holds, exits on the 200'],
                         histate: ['histate', 'tier 1 owns the slot'] };
            const CL = { dip: '#38bdf8', dark: '#f59e0b', histate: '#2dd4bf' };
            bands.length = 0;
            let cur = from;
            trades.forEach(t => {
                if (t.e > cur) bands.push({ a: cur, b: t.e, t: 'cash',
                                            s: 'flat, in T-bills', c: '#475569' });
                const nm = NM[t.kind] || [t.kind, ''];
                if (t.hand > t.e) {
                    bands.push({ a: t.e, b: t.hand, t: nm[0], s: nm[1], c: CL[t.kind] });
                    bands.push({ a: t.hand, b: t.x, t: NM.histate[0], s: NM.histate[1],
                                 c: CL.histate });
                } else {
                    bands.push({ a: t.e, b: t.x, t: nm[0], s: nm[1], c: CL[t.kind] || '#38bdf8' });
                }
                cur = t.x;
            });
            if (cur < to) bands.push({ a: cur, b: to, t: 'cash', s: 'flat, in T-bills',
                                       c: '#475569' });
        }
        const shown = bands.filter(z => z.b > z.a);

        // PHASES ARE DEMARCATED BY LINES, NOT A WASH (user, 2026-09-01). Six tinted rects
        // behind the candles muted the whole picture — the price is what is being read, and
        // every pixel of it was sitting under a colour. A boundary is a one-pixel event, so
        // a line says the same thing and costs the chart nothing.
        //   SOLID for the two crosses: they are real events on the SMAs, and the only two
        //   boundaries the rules actually key off.
        //   DASHED for the rest: a timer expiring or a breakout printing. Each is drawn in
        //   the colour of the phase it OPENS, so a line and the rail bar under it carry the
        //   same colour.
        const edge = (i, col, solid) =>
            '<line x1="' + X(i).toFixed(2) + '" y1="0" x2="' + X(i).toFixed(2) +
            '" y2="' + H + '" stroke="' + col + '" stroke-width="' + (solid ? 0.3 : 0.18) +
            '"' + (solid ? '' : ' stroke-dasharray="1.0 0.8"') +
            ' opacity="' + (solid ? 0.95 : 0.6) + '"/>';
        // Skip `from`: the left edge of the window is not a boundary, it is where we started
        // looking. Every other band start is a real transition.
        const edges = shown.filter(z => z.a !== from).map(z =>
            (z.a === gc || z.a === dc) ? '' : edge(z.a, z.c, false)).join('') +
            edge(gc, '#facc15', true) + edge(dc, '#f87171', true);

        // THE LEVELS THE TWO MARKS ARE MADE AGAINST, drawn only where they are load-bearing:
        // the 52-week HIGH into the Breakout 1 caret, the 52-week LOW into the flush wick.
        // Without them the reader has to take on trust that a caret sits at a real breakout —
        // which is exactly the thing that was wrong here. Drawn across the whole window they
        // would just be clutter, so each stops at the bar it explains.
        const lvl = (arr, a, b, col) => {
            let d = '', started = false;
            for (let i = Math.max(a, from); i <= Math.min(b, to); i++) {
                if (arr[i] === null) continue;
                d += (started ? 'L' : 'M') + X(i).toFixed(2) + ' ' + Y(arr[i]).toFixed(2) + ' ';
                started = true;
            }
            return d ? '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="0.22" ' +
                       'stroke-dasharray="1.1 0.9" opacity="0.85"/>' : '';
        };
        // THE BREAKOUT HAS TO LOOK LIKE ONE (user, 2026-09-01: "it's not obvious to my eye
        // that that point is a break out"). Two changes, both to the LINE rather than the
        // path: the 52-week high is drawn brighter and in the Breakout 1 band's own colour,
        // so the level and the caret that takes it out are visibly the same subject; and it
        // is carried a little PAST b1, so what you see is price crossing above a level that
        // continues — a break — instead of a line that stops where the price meets it, which
        // reads as the line simply ending.
        // PAST THE BREAK THE LEVEL IS HELD FLAT, not tracked. The trailing 252-bar high
        // climbs with price once the high is taken out, so continuing to draw it made the
        // line hug the candles — which is the opposite of a breakout, where the point is
        // that price left a level BEHIND. Projected flat at the level that was broken, it
        // reads the way resistance does on a real chart.
        const past = Math.max(8, Math.round(span * 0.07));
        const shelfTo = Math.min(to, b1 + past);
        const shelf = (roll.hi[b1] == null) ? '' :
            '<path d="M' + X(b1).toFixed(2) + ' ' + Y(roll.hi[b1]).toFixed(2) +
            'L' + X(shelfTo).toFixed(2) + ' ' + Y(roll.hi[b1]).toFixed(2) +
            '" fill="none" stroke="#38bdf8" stroke-width="0.22" stroke-dasharray="1.1 0.9" ' +
            'opacity="0.85"/>';
        const levels = lvl(roll.hi, from, b1, '#38bdf8') + shelf +
                       (flushIn > 0 ? lvl(roll.lo, dc, flushIn, '#cbd5e1') : '') +
                       (dark.length ? lvl(roll.lo, dc, Math.min(to, dark[0].e), '#cbd5e1') : '');

        // THE CAPITULATION CANDLE IS DRAWN FAT (user, 2026-09-01: make it thick enough to see
        // the price action). At ~430 bars in the window an ordinary candle is about 1.7px of
        // body and a hairline wick — which is fine for the mass of them and useless for the
        // one bar the reader is being asked to look at. It is the bar the whole dark-era
        // sequence exists to show, and its WICK is the part that carries the rule, so the
        // wick is thickened harder than the body.
        let candles = '';
        for (let i = from; i <= to; i++) {
            const b = bars[i], col = b.c >= b.o ? '#22c55e' : '#ef4444';
            const isFlush = (i === flushIn);
            const w = isFlush ? cw * 4.0 : cw;
            const sw = isFlush ? 0.5 : 0.12;
            const yTop = Y(Math.max(b.o, b.c)), yBot = Y(Math.min(b.o, b.c));
            candles += '<line x1="' + X(i).toFixed(2) + '" y1="' + Y(b.h).toFixed(2) +
                       '" x2="' + X(i).toFixed(2) + '" y2="' + Y(b.l).toFixed(2) +
                       '" stroke="' + col + '" stroke-width="' + sw + '"/>' +
                       '<rect x="' + (X(i) - w / 2).toFixed(2) + '" y="' + yTop.toFixed(2) +
                       '" width="' + w.toFixed(2) + '" height="' +
                       Math.max(isFlush ? 0.4 : 0.15, yBot - yTop).toFixed(2) +
                       '" fill="' + col + '"/>';
        }
        const path = arr => {
            let d = '', started = false;
            for (let i = from; i <= to; i++) {
                if (arr[i] === null) continue;
                d += (started ? 'L' : 'M') + X(i).toFixed(2) + ' ' + Y(arr[i]).toFixed(2) + ' ';
                started = true;
            }
            return d;
        };
        // BUY = green caret under the bar, pointing up. SELL = red caret over it, pointing
        // down. Every one is a round trip from sdSimulate(), so the picture cannot show a
        // trade the rules did not make.
        let marks = '';
        const caret = (i, up) => {
            const x = X(i);
            const y = up ? Y(bars[i].l) + 1.3 : Y(bars[i].h) - 1.3;
            const t = up ? y - 1.0 : y + 1.0;        // tip
            const col = up ? '#22c55e' : '#ef4444';
            return '<path d="M' + x.toFixed(2) + ' ' + t.toFixed(2) +
                   'L' + (x - 0.85).toFixed(2) + ' ' + y.toFixed(2) +
                   'L' + (x + 0.85).toFixed(2) + ' ' + y.toFixed(2) +
                   'Z" fill="' + col + '"/>';
        };
        // A SILENT SLEEVE gets no BUY caret: on tobacco the 252-day high hands the slot from
        // tier 2 to tier 1 and nothing is bought, so a green caret there would assert a
        // transaction that never happened (user, 2026-09-02: "just no green caret").
        const silent = pd.silent_entry || {};
        trades.forEach(t => {
            if (!silent[t.kind]) marks += caret(t.e, true);
            marks += caret(t.x, false);
        });
        // The flush is a round trip like any other, so it gets the same pair of carets.
        const book = trades.slice();
        dark.forEach(t => {
            marks += caret(t.e, true) + (t.why === 'OPEN' ? '' : caret(t.x, false));
            book.push(t);
        });
        if (flushIn > 0) {
            marks += caret(flushIn, true) + caret(flushOut, false);
            book.push({ kind: 'VIX flush', e: flushIn, x: flushOut, why: '200 touch' });
        }

        // EVERY CARET GETS A SHORT LABEL (user, 2026-09-01). A BUY is named for the SLEEVE
        // that opened it and a SELL for the REASON it closed — which is the question each
        // side actually answers, and it means the labels never just repeat one another.
        //
        // THEY ARE HTML, NOT <text> IN THE SVG, and that is deliberate. This svg is
        // preserveAspectRatio="none": it stretches its contents on one axis, text included,
        // which is the reason the rail was never SVG either. Deriving the viewBox from the
        // rendered aspect made the stretch ~1, so svg text would look right TODAY — but it
        // would silently distort again the moment a render could not measure its box and fell
        // back to the default aspect. Positioning HTML by PERCENTAGE of the same box is
        // immune to that: the percentages are the viewBox coordinates, and the glyphs are
        // laid out by the browser at whatever size the box really is.
        const BUY_NAME = Object.assign(
            { halo: 'Halo', b1: 'B1', dip: 'Dip', 'VIX flush': 'Flush',
              dark: 'Dark', overlay: 'Long', histate: 'Histate' },
            pd.sleeve_names || {});
        const SELL_NAME = { timer: 'Timer', target: 'Target', warning: 'Warning',
                            'death cross': 'Cross', '200 touch': '200',
                            'golden cross': 'GC', '52wk low': '52 wk', '252d low': '52 wk',
                            OPEN: '' };
        // Buys sit BELOW the bar and sells ABOVE it, following their carets. That separation
        // is load-bearing, not decoration: the B1 timer sell and the dip buy that follows it
        // are two bars apart, so on one line they would collide outright.
        const label = (i, text, buy) => {
            const yv = buy ? Y(bars[i].l) + 3.4 : Y(bars[i].h) - 3.4;
            const y = Math.min(H - 1.2, Math.max(1.2, yv));
            return '<span class="sd-lab ' + (buy ? 'buy' : 'sell') + '" style="left:' +
                   (X(i) / W * 100).toFixed(3) + '%;top:' + (y / H * 100).toFixed(3) + '%">' +
                   esc(text) + '</span>';
        };
        // DROPPED ENTIRELY ON A NARROW CARD rather than allowed to pile up. Two constraints
        // bind, both measured on the rendered labels: the B1 timer sell and the B1 buy sit
        // 8.87% apart at the SAME height, and "200 Sell" is centred at 95.9% so it runs past
        // the right edge. Both fail below about 410px, so 460 leaves a margin. Ten labels
        // overlapping each other is worse than no labels — the carets still read, and the
        // sequence under the chart still names every trade in order.
        const pxW = (aspect || 2.5) * SD_DIAG_H;
        // THE HANDOVER IS LABELLED EVEN THOUGH IT IS NOT A CARET (user, 2026-09-02). A band
        // change alone does not say what happened; the reader needs the word.
        const hands = pxW < 460 ? '' : book.filter(t => t.hand > 0)
            .map(t => label(t.hand, 'Histate', false)).join('');
        const labels = pxW < 460 ? '' : hands + book.map(t =>
            (silent[t.kind] ? '' : label(t.e, (BUY_NAME[t.kind] || t.kind) + ' Buy', true)) +
            (t.why === 'OPEN' ? ''
             : label(t.x, (SELL_NAME[t.why] || t.why) + ' Sell', false))).join('');

        // THE RAIL SHARES THE PLOT'S COORDINATE SYSTEM (user, 2026-09-01: the bars did not
        // line up with the regions above them). It was an HTML flex row of percentage widths,
        // which could not align: the container had 6px of horizontal padding the chart did
        // not, a 2px flex gap ate width between every pair, and the percentages were of the
        // window while the plot insets itself by PADX inside its own viewBox. Three separate
        // offsets, all small, all in the same direction.
        // Drawn as an SVG on the SAME viewBox width with the SAME X(), the two cannot drift:
        // a band edge and the boundary line above it are the same computed coordinate.
        const rail = '<svg viewBox="0 0 ' + W + ' 8" preserveAspectRatio="none" ' +
            'class="sd-rail-svg">' +
            shown.map(z => '<rect x="' + X(z.a).toFixed(2) + '" y="0" width="' +
                (X(z.b) - X(z.a)).toFixed(2) + '" height="8" fill="' + z.c + '"/>').join('') +
            '</svg>';
        // Keyed ONCE per name, not once per band. The dark era is now three separate bands
        // with the flush between them, so "is the previous band the same" no longer suppresses
        // the repeat — it only ever caught bands that happened to be adjacent.
        // KEYED ON NAME **AND** SUBTITLE. Keying on the name alone dropped GLD's second dark
        // band — the one the dark sleeve trades — because a "dark era" had already been keyed
        // for the stretch before the first cross, where the book really is just flat. Two
        // bands sharing a name can still be saying different things.
        const keyed = {};
        const railKey = shown.map(z => {
            const k = z.t + '|' + z.s;
            if (keyed[k]) return '';
            keyed[k] = 1;
            return '<span class="sd-bandk"><i style="background:' + z.c + '"></i><b>' +
                   esc(z.t) + '</b> ' + esc(z.s) + '</span>';
        }).join('');

        // What the simulated book actually did, so the carets can be read back as a sequence.
        const seq = book.map(t => esc(t.kind) + ' &rarr; ' + esc(t.why)).join(' &middot; ');

        return '<div class="sd-diag">' +
            '<div class="sd-diag-wrap">' +
            '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" class="sd-diag-px">' +
              edges + levels + candles +
              '<path d="' + path(s200) + '" fill="none" stroke="#f8fafc" stroke-width="0.26"/>' +
              '<path d="' + path(s50) + '" fill="none" stroke="#22d3ee" stroke-width="0.26"/>' +
              marks +
            '</svg>' + labels +
            '</div>' +
            '<div class="sd-rail">' + rail + '</div>' +
            '<div class="sd-railkey">' + railKey + '</div>' +
            '<div class="sd-diag-key">' +
              '<span><i class="up"></i>buy</span>' +
              '<span><i class="dn"></i>sell</span>' +
              '<span><i style="background:#22d3ee"></i>50 SMA</span>' +
              '<span><i style="background:#f8fafc"></i>200 SMA</span>' +
              '<span><i class="vert" style="background:#facc15"></i>golden cross</span>' +
              '<span><i class="vert" style="background:#f87171"></i>death cross</span>' +
              '<span><i class="vert dash"></i>phase boundary</span>' +
              '<span><i class="lvl"></i>52-wk high / low</span>' +
            '</div>' +
            '<div class="sd-diag-seq">' + seq + '</div>' +
            '<div class="sd-diag-cap">Notional path — not QQQ. The SMAs, both crosses, ' +
            'the 52-week levels and every buy and sell are computed on this series with the ' +
            'real rules: Breakout 1 is the first bar to take out the dashed 52-week high, ' +
            'and the flush is the first to take out the 52-week low. Band widths are for ' +
            'legibility, not to scale; durations are in the labels.<br>' +
            '<b>The flush&rsquo;s VIX condition is asserted, not drawn.</b> The rule needs a ' +
            '52-week low <i>and</i> the VIX intraday high over 40; a price-only chart carries ' +
            'the first and cannot carry the second. Every other mark here is derived from the ' +
            'series.<br>' +
            '<b>Never sell below the 200</b> is not drawn: every exit here happens above the ' +
            'line. When one would not, the position is held and sold into the first 200 ' +
            'retest instead.</div>' +
          '</div>';
    }

    function sdRulesHTML(rules) {
        if (!Array.isArray(rules) || !rules.length) {
            return '<div class="sd-empty">No ruleset published for this strategy.</div>';
        }
        const rule = r => {
            const tag = ['regime', 'entry', 'exit', 'overlay'].includes(r.tag) ? r.tag : '';
            return `<div class="sd-rule ${tag}">` +
                   `<div class="sd-rule-nm">${esc(r.name || '')}</div>` +
                   `<div class="sd-rule-tx">${esc(r.text || '')}</div></div>`;
        };
        // GROUPED BY ERA when the config supplies groups (`era` + `items`); a flat list still
        // renders, so a strategy that has not been reorganised yet is not blank.
        if (rules[0] && Array.isArray(rules[0].items)) {
            return rules.map(g =>
                `<div class="sd-era">` +
                `<div class="sd-era-nm">${esc(g.era || '')}</div>` +
                (g.hint ? `<div class="sd-era-hint">${esc(g.hint)}</div>` : '') +
                (g.items || []).map(rule).join('') +
                `</div>`).join('');
        }
        return rules.map(rule).join('');
    }

    // Newest first, as the engine sends it — one BOOK, core sleeves and the VIX flush
    // interleaved by entry date. A live position keeps its row with the exit side blank
    // rather than being dropped: the ledger must not disagree with the state shown
    // directly above it about whether something is open.
    //
    // A TABLE, not a stack of cards (user, 2026-09-01). Six columns, one row per trade.
    // The previous layout put the sleeve and P&L on one line, stacked the two legs under
    // them and the reason under that, so no two trades lined up and the column could only
    // be read a trade at a time — which is the thing a ledger exists to make easy.
    // Cells are emitted straight into one grid so every column aligns across every row.
    function sdTradesHTML(trades) {
        if (!Array.isArray(trades) || !trades.length) {
            return '<div class="sd-empty">No closed trades on record.</div>';
        }
        const px = v => (v === null || v === undefined) ? '—' : v.toFixed(2);
        const cell = (cls, html, open, first) =>
            '<div class="sd-tt-c' + (open ? ' op' : '') + (first ? ' r0' : '') +
            (cls ? ' ' + cls : '') + '">' + html + '</div>';
        // NUMBERED 1-10, newest first — 1 is the latest trade, matching the order the rows
        // are already in. It gives the reader something to point at ("the +1.23% one" is
        // "3"), and makes it obvious at a glance that the column is showing ten and not
        // however many happen to fit.
        // HEADED BY WHAT THE COLUMN ANSWERS, not by the field it comes from (user,
        // 2026-09-01). The sleeve IS the entry rule — which rule put the book in — and the
        // reason IS the exit rule. "Sleeve" and "Why" named the payload; "Entry" and "Exit"
        // name the trade.
        const head = [['#', 'num'], ['Entry', ''], ['In', ''], ['Out', ''],
                      ['Td', 'num'], ['Exit', ''], ['P&L', 'num']]
            .map(h => '<div class="sd-tt-h ' + h[1] + '">' + h[0] + '</div>').join('');

        const rows = trades.map((t, i) => {
            const f = i === 0;
            // Date and price share a cell: they are one fact about one leg, and splitting
            // them into separate columns spent width on a second header that said nothing.
            //
            // BOTH DATES ARE TINTED BY THE ERA THEY HAPPENED IN (user, 2026-09-01), using
            // the same era tokens as the facts strip and the sidebar — gold for golden, red
            // for dark. The pair is the point: a row whose two dates differ in colour is a
            // trade that CROSSED an era boundary while held, which nothing else in the row
            // says. On QQQ that is the exit side (10 of 57 close dark, carried through the
            // death cross by never-sell-below-the-200 or by the flush's own 200 exit).
            //
            // THE ENTRY TINT IS NOT REDUNDANT, AND THIS RENDERER IS A TEMPLATE. QQQ's core
            // happens to enter only while golden, so its In column is one colour — but that
            // is a fact about QQQ's core, not about the column. GLD's dark sleeve enters in
            // dark eras by definition (16 of its 46 trades) and XLE's prehalo does too, so
            // the same table on those strategies carries information in both columns. Do not
            // "optimise" the entry tint away on the strength of one strategy's data.
            // PURPLE FOR DARK, NOT RED (user, 2026-09-01). Red is already spoken for twice in
            // this panel — the sell carets and a negative P&L two columns over — and an era
            // is not a loss. NOTE the facts strip and the sidebar still tint a dark era
            // #f87171 from their own copy of this map.
            //
            // THE TINT IS ON THE PRICE, not the date. The date is the row's spine and stays
            // plain #e2e8f0; the price is the softer half of the cell and can carry a hue
            // without the column losing its shape.
            const ERA = { golden: '#d4af37', dark: '#c084fc' };
            const leg = (d, p, era) => d
                ? esc(d) + ' <span class="sd-tt-px"' +
                  (era ? ' style="color:' + ERA[era] + '"' : '') + '>' + px(p) + '</span>'
                : '<span class="sd-tt-px">—</span>';
            const pnl = t.open
                ? '<span style="color:#4ade80">open</span>'
                : strPct(t.pnl_pct);
            return cell('sd-tt-num sd-tt-idx', String(i + 1), t.open, f) +
                   cell('sd-tt-sleeve', esc(t.sleeve || ''), t.open, f) +
                   cell('sd-tt-num', leg(t.entry_date, t.entry_price, t.entry_era),
                        t.open, f) +
                   cell('sd-tt-num', t.open ? '<span class="sd-tt-px">—</span>'
                                            : leg(t.exit_date, t.exit_price, t.exit_era),
                        t.open, f) +
                   cell('sd-tt-num sd-tt-held',
                        (t.held || t.held === 0) ? String(t.held) : '', t.open, f) +
                   cell('sd-tt-why', esc(t.open ? 'held' : (t.why || '')), t.open, f) +
                   cell('sd-tt-num sd-tt-pnl', pnl, t.open, f);
        }).join('');
        return '<div class="sd-tt">' + head + rows + '</div>';
    }

    // The svg's CSS height (`.sd-diag-px` in watchtower.html). The aspect it is drawn at is
    // width/height, and the width is whatever the pane gives it, so the height is the half
    // that has to be known here. Measured back off the DOM after the first paint, so the two
    // cannot drift if the CSS changes.
    let SD_DIAG_H = 210;

    // The last payload's diagram spec, kept so the picture can be REDRAWN at a new width
    // without another fetch. Null means DRAW NOTHING.
    //
    // A DIAGRAM IS ONLY DRAWN FOR A STRATEGY THAT PUBLISHES ONE. `sdPhaseDiagramHTML` falls
    // back to 63/126 when handed no spec, so an unguarded call renders QQQ's phases under
    // whatever name is open — XLE, MO, PM and GLD have no `phase_diagram` block yet, and a
    // teaching picture of the wrong strategy is worse than no picture. The gate is on a
    // published spec, not on the key being absent: `phase_diagram: null` must behave the
    // same way as the key not being sent at all.
    let sdDiagPD = null;
    let sdDiagW = 0;

    // Redraw the diagram fitted to the box it is actually in. Same reasoning as loadChart()'s
    // laziness in charts.js: this pane starts hidden, and an element in a display:none parent
    // measures ZERO — so this is driven by a ResizeObserver, which fires both when the tab is
    // first shown and whenever the window changes size.
    function sdDrawDiagram() {
        const D = document.getElementById('sd-diagram');
        if (!D) return;
        // Hide the whole CARD, not just its body: an empty "Phase diagram" header is a
        // promise of a picture that is not coming.
        const card = D.closest('.sd-top');
        if (card) card.style.display = sdDiagPD ? '' : 'none';
        if (!sdDiagPD) { D.innerHTML = ''; return; }
        const w = D.clientWidth;
        if (!w) return;                          // hidden: nothing to fit to yet
        if (Math.abs(w - sdDiagW) < 8) return;   // ignore scrollbar-width jitter
        sdDiagW = w;
        D.innerHTML = sdPhaseDiagramHTML(sdDiagPD, w / SD_DIAG_H);
        const svg = D.querySelector('.sd-diag-px');
        const h = svg && Math.round(svg.getBoundingClientRect().height);
        if (h && Math.abs(h - SD_DIAG_H) > 2) {  // the CSS height moved: refit once, not forever
            SD_DIAG_H = h;
            D.innerHTML = sdPhaseDiagramHTML(sdDiagPD, w / SD_DIAG_H);
        }
        sdDecollide(D);
    }

    // Trade labels can COLLIDE, and no width threshold catches it. The 460px guard drops
    // them on a narrow card, which handles a cramped panel — but GLD's book opens with three
    // consecutive zone dips a few bars apart, each "Dip Buy" over "Warning Sell", and they
    // overlap at any width. Clustering is a property of the STRATEGY, not of the box, so it
    // has to be resolved against real geometry rather than predicted from one.
    //
    // Nudged AWAY from the price: a buy label sits under its bar and moves further down, a
    // sell sits above and moves further up, so de-colliding never pushes text over the
    // candles it belongs to. A label with nowhere to go is HIDDEN rather than left stacked —
    // the caret is still there, and the sequence under the chart still names every trade in
    // order, so nothing is lost that the picture does not say twice.
    function sdDecollide(host) {
        const labs = [...host.querySelectorAll('.sd-lab')];
        const placed = [];
        const hits = (r) => placed.some(p => r.left < p.right && p.left < r.right &&
                                             r.top < p.bottom && p.top < r.bottom);
        labs.forEach(el => {
            const buy = el.classList.contains('buy');
            for (let step = 0; step <= 3; step++) {
                el.style.marginTop = step ? (buy ? step * 11 : -step * 11) + 'px' : '';
                const r = el.getBoundingClientRect();
                if (!hits(r)) { placed.push(r); return; }
            }
            el.style.marginTop = '';
            el.hidden = true;
        });
    }

    // THREE WAYS IN, because no single one covers every case and they are all idempotent
    // (the width guard above makes a redundant call free):
    //   1. new data arrives -> sdSetColumns()
    //   2. the tab is selected -> the Strategy button calls this directly, the same shape as
    //      charts.js's `if (tabName === 'chart') loadChart(view)`. A ResizeObserver SHOULD
    //      cover this, but it only delivers callbacks while the page is actually being
    //      rendered — in a background or non-rendered tab it never fires, and the diagram
    //      stays blank. Observed, not theorised.
    //   3. the window is resized -> the listener below, so the viewBox refits.
    if (typeof ResizeObserver === 'function') {
        const ro = new ResizeObserver(() => sdDrawDiagram());
        const attach = () => {
            const D = document.getElementById('sd-diagram');
            if (D) ro.observe(D);
        };
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', attach);
        } else {
            attach();
        }
    }
    window.addEventListener('resize', () => sdDrawDiagram());

    // THREE TARGETS since the pane was split (user, 2026-09-01): the diagram has its own
    // full-width row above the two columns, so it is no longer prepended into the rules
    // column. All three still come from the SAME contract fetch the facts strip uses — no
    // second round trip, and no way for one part to describe a strategy the others do not.
    function sdSetColumns(d) {
        const D = document.getElementById('sd-diagram');
        const R = document.getElementById('sd-rules');
        const T = document.getElementById('sd-trades');
        // `target_mult` lives on the payload beside the diagram spec rather than inside it,
        // so the picture and the facts strip cannot quote two different targets.
        //
        // A SPEC MISSING ITS PARAMETERS DRAWS NOTHING. The simulator has no fallbacks by
        // design — a default here would be the literal it was just relieved of — so an
        // engine still serving the old three-timing block yields no picture rather than one
        // drawn with NaN comparisons, which would silently produce a chart with no trades.
        const _pd = d && d.phase_diagram;
        const _ok = _pd && _pd.opens && _pd.path && _pd.dip_mult != null
                    && _pd.warn_mult != null && _pd.warn_gap != null && d.target_mult != null;
        sdDiagPD = _ok ? Object.assign({}, _pd, { target_mult: d.target_mult }) : null;
        sdDiagW = 0;                             // a new strategy always redraws
        if (D) D.innerHTML = '';
        sdDrawDiagram();
        if (R) R.innerHTML = sdRulesHTML(d && d.rules);
        if (T) T.innerHTML = sdTradesHTML(d && d.trades);
    }

    // ONE site: the panel HEADER, which is on screen whichever tab is open.
    //
    // It used to write a second copy into the Strategy pane as well, and that was right
    // while the pane held nothing else — the tab would otherwise have been empty. Once the
    // pane grew the rules/ledger columns (2026-09-01) the second copy sat ~30px below the
    // first showing the identical row, so it came out (user). The header copy is the one to
    // keep: the in-pane copy was invisible from the Chart and Dial tabs.
    //
    // Kept as a function rather than inlined because it is called from four places (loading,
    // no-strategy, loaded, and the error path) and a fact set written from four sites is how
    // a stale copy gets left behind.
    function sdSetFacts(html) {
        ['sd-facts-hd'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = html;
        });
    }

    // The DIAL tab — the macro half, above the vehicle.
    //
    // Every field here has been shipped in the dial payload since 2026-08-10 and read by
    // nothing: strategy.js's header states outright that the rate, the change over the
    // lookback, the distance to a flip and the latch counter are "detail-panel content" and
    // that "the payload still carries those fields, unused here, ready for that panel."
    // This is that panel. No new endpoint and no new computation — the numbers were already
    // arriving on every poll.
    function renderDialPane() {
        const box = document.getElementById('sd-dial');
        if (!box) return;
        const d = (typeof strLast !== 'undefined') ? strLast : null;
        if (!d || !d.ok) { box.innerHTML = ''; return; }

        const sign = v => (v === null || v === undefined || !isFinite(v))
            ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(3)}`;

        let rows = strRow('Regime', esc(d.label || '—'),
                          d.days_in_state ? `${d.days_in_state} td` : null, d.color);
        if (d.rate !== null && d.rate !== undefined) {
            rows += strRow(esc(d.rate_label || 'rate'), `${d.rate.toFixed(2)}%`,
                           d.lookback_months ? `${d.lookback_months}mo lookback` : null);
        }
        rows += strRow('change', sign(d.chg), 'over the lookback');
        // DISTANCE TO EACH FLIP, signed as the payload defines them: to_tighten is how far
        // the change must RISE, to_ease how far it must FALL. Shown as magnitudes with the
        // direction in the footnote rather than as raw signs, which read as gains/losses.
        if (d.to_tighten !== null && d.to_tighten !== undefined) {
            rows += strRow('to tighten', Math.abs(d.to_tighten).toFixed(3), 'pp the change must rise');
        }
        if (d.to_ease !== null && d.to_ease !== undefined) {
            rows += strRow('to ease', Math.abs(d.to_ease).toFixed(3), 'pp the change must fall');
        }
        if (d.nearest_pp !== null && d.nearest_pp !== undefined) {
            // `near` is the payload's own proximity flag — amber, the same token the sidebar
            // uses for a pending latch, because both mean "a flip is in reach, not made".
            rows += strRow('nearest flip', Math.abs(d.nearest_pp).toFixed(3),
                           d.near ? 'within the near band' : 'pp away',
                           d.near ? '#fbbf24' : null);
        }
        if (d.latch_days) {
            rows += strRow('latch', `${d.latch_days} td`,
                           d.latched_on ? esc(`latched ${d.latched_on}`) : 'to confirm a flip');
        }
        if (d.pending) rows += strRow('pending', esc(String(d.pending)), 'unconfirmed flip', '#fbbf24');
        if (d.asof) rows += strRow('as of', esc(d.asof), d.stale ? 'stale' : null);

        box.innerHTML = `<div class="str-blk-hd"><span class="str-blk-nm" ` +
                        `style="color:${d.color}">Fed dial</span></div>` + rows;
    }

    // Opened from a ticker pill. Reached by TICKER, so it works for a vehicle in a column
    // the dial has not allocated — the same decoupling GET /get_ticker_strategy exists for.
    // ===== MOONSHOT (2026-09-09) ==========================================================
    // The momentum BOOK, opened from the header button rather than a ticker card. It shares
    // this panel -- title row, facts strip, tab strip, the Strategy tab's rules and ledger
    // -- and adds two panes of its own. Everything below reads /get_moonshot; no rule,
    // number or name of a sleeve is written here, this file has a public remote.

    // Tabs are per STRATEGY KIND. `data-for` on each tab lists the kinds that show it; a
    // single-ticker sleeve keeps Strategy / Chart / Dial, the book gets Strategy /
    // Portfolio / Custom. Same idiom as setTabsForAssetClass on the dd panel.
    function setTabsForStrategy(kind) {
        const tabsEl = document.getElementById('sd-tabs');
        if (!tabsEl) return;
        tabsEl.querySelectorAll('.view-tab').forEach(btn => {
            const forKinds = (btn.dataset.for || 'ticker').split(/\s+/);
            btn.style.display = forKinds.includes(kind) ? '' : 'none';
        });
        // The phase diagram card is a single-sleeve picture; a ten-slot book has no
        // phases to draw. Hide the card rather than render an empty one under a header.
        const diag = document.getElementById('sd-diagram');
        const card = diag && diag.closest('.sd-top');
        if (card) card.style.display = (kind === 'moonshot') ? 'none' : '';
    }

    let _moSeq = 0;
    let _moLast = null;              // the last book payload, for the rail clicks
    let _moStart = '';               // '' = full history -- the start the book was BUILT from
    let _moPending = null;           // a date typed into the calendar but not yet run; survives re-renders
    let _moBusy = false;

    function moSetStatus(text, cls) {
        const el = document.getElementById('mo-status');
        if (!el) return;
        el.className = 'mo-status' + (cls ? ' ' + cls : '');
        el.textContent = text || '';
        const btn = document.getElementById('mo-run');
        if (btn) btn.disabled = (cls === 'busy');
    }

    // THE BUTTON. The calendar alone changes nothing; this is the only way a re-run starts.
    function moRun() {
        const inp = document.getElementById('mo-start');
        if (!inp || _moBusy) return;
        const v = (inp.value || '').trim();
        if (!v) { moSetStatus('pick a date first', 'err'); return; }
        _moPending = v;
        showMoonshotDive(v);
    }

    const moPct = v => (v === null || v === undefined) ? '—'
        : (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
    const moCls = v => (v >= 0 ? 'str-up' : 'str-dn');
    const moBar = (w, max, cls) => (w == null || !max) ? '' :
        `<span class="mo-bar ${cls || ''}" style="width:${Math.max(2, Math.round(28 * w / max))}px"></span>`;

    function moSelectTicker(tk, px, ret) {
        const t = document.getElementById('sd-ticker');
        if (t) t.innerHTML = 'Moonshot' + (tk ? `<span class="mo-sep">/</span><span class="font-mono" style="color:#fbbf24">${esc(tk)}</span>` : '');
        const p = document.getElementById('sd-price');
        if (p) p.innerText = (px === null || px === undefined) ? '—' : Number(px).toFixed(2);
        const c = document.getElementById('sd-day');
        if (c) c.innerHTML = (ret === null || ret === undefined) ? '' :
            `<span class="${moCls(ret)}">${moPct(ret)}</span>`;
    }

    function moFactsHTML(d) {
        const f = d.facts || {};
        const item = (k, v, color) =>
            `<span class="sd-fact"><span class="sd-fact-k">${esc(k)}</span>` +
            `<span class="sd-fact-v"${color ? ` style="color:${color}"` : ''}>${v}</span></span>`;
        const sub = s => ` <span class="sd-fact-sub">${esc(s)}</span>`;
        let out = item('Slots', `${f.slots_used ?? '—'} / ${f.slots_n ?? '—'}`);
        out += item('Banked', `${f.n_banked ?? '—'}`, '#a78bfa');
        out += item('Bank', f.bank_share == null ? '—' : `${f.bank_share.toFixed(1)}%`, '#a78bfa');
        out += item('Equity', f.equity == null ? '—' : `${f.equity.toFixed(2)}u` +
                    (f.yrs ? sub(`${f.yrs}y`) : ''));
        if (f.cagr != null) out += item('CAGR', `${f.cagr.toFixed(1)}%`, f.cagr >= 0 ? '#34d399' : '#f87171');
        // THE BENCHMARK OVER THE SAME SPAN (user, 2026-09-10): QQQ's CAGR from the book's
        // first session to its last, with the edge beside it. Omitted when the engine
        // could not fetch it -- never a stale or invented number.
        const b = d.bench;
        if (b && b.cagr != null) {
            const edge = (b.edge_pp == null) ? '' :
                ` <span class="sd-fact-sub" style="color:${b.edge_pp >= 0 ? '#34d399' : '#f87171'}">${b.edge_pp >= 0 ? '+' : ''}${b.edge_pp.toFixed(1)}pp</span>`;
            out += item(esc(b.ticker || 'QQQ'), `${b.cagr.toFixed(1)}%` + edge, '#94a3b8');
        }
        if (f.maxdd != null) out += item('maxDD', `${f.maxdd.toFixed(1)}%` +
            (b && b.maxdd != null ? ` <span class="sd-fact-sub">${esc(b.ticker || 'QQQ')} ${b.maxdd.toFixed(1)}%</span>` : ''), '#f87171');
        if (f.calmar != null) out += item('Calmar', f.calmar.toFixed(2));
        out += item('Begins', esc(d.begins || '—'));
        // Two marks a session apart, on purpose: the book and its equity are at the as-of
        // close; CAGR, drawdown and the multiple run through the last SIGNAL session (the
        // research convention -- the engine says why). The sub names that date.
        out += item('As of', esc(d.asof || '—') + (d.stale ? sub('stale') : '') +
                    (d.refreshing ? sub('updating') : '') +
                    (d.stats_through && d.stats_through !== d.asof ? sub(`stats through ${d.stats_through}`) : ''));
        return `<div class="sd-facts-row">${out}</div>`;
    }

    // The day's events in words, for the substrip: "cut AMAT −18.2% · banked WDC +192.1%
    // · bought PLTR". Kind muted, ticker bright, the return in its own colour.
    function moEventsHTML(s) {
        const ev = s.events || [];
        if (!ev.length) return '';
        return ev.map(e =>
            `<span class="mo-ev"><span class="mo-muted">${esc(e.kind === 'buy' ? 'bought' : e.kind)}</span> ` +
            `<b>${esc(e.tk)}</b>` +
            (e.ret == null ? '' : ` <span class="${moCls(e.ret)}">${moPct(e.ret)}</span>`) + `</span>`
        ).join('<span class="mo-muted"> · </span>');
    }

    // The rail: TRADE DATES newest first, CURRENT on top (user, 2026-09-09 -- "update with
    // each new trade"). The figure beside a date is what the book DID that day, the way
    // the news archive's chip carries the day's move: a close shows its P&L in colour, a
    // buy alone shows the ticker. More than one event on a day is in the tooltip and the
    // substrip. CURRENT carries no figure, per .na-cur: it is in the header.
    function moRenderRail(d) {
        const rail = document.getElementById('mo-rail');
        if (!rail) return;
        const snaps = (d.snapshots || []).slice().reverse();
        rail.innerHTML = snaps.map((s, i) => {
            const sel = i === 0 ? ' sel live' : '';
            const label = i === 0 ? `<span class="na-d na-cur">current</span>`
                                  : `<span class="na-d">${esc((s.date || '').slice(5))}</span>`;
            const ev = s.events || [];
            const close = ev.find(e => e.ret != null);
            const v = i === 0 ? ''
                    : close ? `<span class="na-chg ${moCls(close.ret)}">${moPct(close.ret)}</span>`
                    : ev[0] ? `<span class="na-chg mo-muted">${esc(ev[0].tk)}</span>` : '';
            const tip = ev.map(e => (e.kind === 'buy' ? 'bought ' : e.kind + ' ') + e.tk +
                                    (e.ret == null ? '' : ' ' + moPct(e.ret))).join(' · ');
            return `<div class="na-card${sel}" role="option" data-i="${i}" title="${esc(tip)}">${label}${v}</div>`;
        }).join('') || '<div class="mo-empty">No history.</div>';
        rail.querySelectorAll('.na-card').forEach(el => el.addEventListener('click', () => {
            rail.querySelectorAll('.na-card').forEach(x => x.classList.remove('sel'));
            el.classList.add('sel');
            moRenderBooks(d, +el.dataset.i);
        }));
    }

    // The two books for one rail selection. EVERY chip -- the live book and each trade
    // date -- is an ENGINE SNAPSHOT (2026-09-10): composition, weight, pick, drought, the
    // bank and the cash as the walk recorded them after that session's trades, priced at
    // that close. Until then a historical date em-dashed weight and pick as a hole on
    // purpose. i === 0 is the live book and adds the next-out mark and the ranking; a
    // past date has no ranking (the signal is today's) and no next-out, and its moon is
    // the split on that date.
    function moRenderBooks(d, i) {
        const box = document.getElementById('mo-books');
        const strip = document.getElementById('mo-substrip');
        if (!box) return;
        const snaps = (d.snapshots || []).slice().reverse();
        const live = (i === 0);
        const s = snaps[i] || { date: d.asof, active: d.active, bank: d.bank,
                                n_active: (d.active || []).length, n_banked: (d.bank || []).length,
                                equity: d.facts && d.facts.equity, bank_share: d.facts && d.facts.bank_share };
        const known = s.equity != null;            // a session the walk marked

        if (strip) strip.innerHTML =
            `<span>book as of <b>${esc(s.date || '')}</b></span>` +
            (s.equity != null ? `<span>equity <b>${Number(s.equity).toFixed(2)}u</b></span>` : '') +
            `<span>${s.n_active ?? '—'} active</span><span>${s.n_banked ?? '—'} banked</span>` +
            (live ? '' : `<span>${moEventsHTML(s)}</span>`) +
            (known ? '' : `<span class="mo-warn">the walk did not mark this session — composition unknown</span>`);

        const rows = s.active || [];
        const maxW = Math.max(0, ...rows.map(a => a.weight || 0));
        // Pick brightness: 45% for a fresh pick rising to full for the book's largest --
        // the one the exit rule would act on. Same number, but now you can see which.
        const maxPick = Math.max(0, ...rows.map(a => a.pick || 0));
        const pickStyle = pk => (pk == null) ? '' :
            ` style="color:rgba(56,189,248,${(0.45 + 0.55 * (maxPick ? pk / maxPick : 1)).toFixed(2)})"`;
        const activeRows = rows.map(r => {
            const isNext = live && r.tk === d.next_out;
            const fate = d.next_fate || 'cut';
            const badge = isNext ? `<span class="mo-badge ${fate}">next: ${fate}</span>` : '';
            const drought = r.drought;
            return `<tr class="${isNext ? 'next ' + fate : ''}" data-tk="${esc(r.tk)}" data-px="${r.px}" data-ret="${r.ret}">` +
                `<td class="sym">${esc(r.tk)}${badge}</td>` +
                `<td class="mo-muted">${esc(r.entry || '')}</td>` +
                `<td>${r.entry_px == null ? '—' : Number(r.entry_px).toFixed(2)}</td>` +
                `<td>${r.px == null ? '—' : Number(r.px).toFixed(2)}</td>` +
                `<td class="mo-pl ${moCls(r.ret)}">${moPct(r.ret)}</td>` +
                `<td>${r.days ?? '—'}</td>` +
                `<td${(d.gate_days != null && drought > d.gate_days) ? ' class="mo-warn"' : ''}>${drought == null ? '—' : drought}</td>` +
                `<td class="mo-pick"${pickStyle(r.pick != null ? r.pick : null)}>${r.pick != null ? r.pick : '<span class="mo-muted">—</span>'}</td>` +
                `<td>${r.weight != null ? r.weight.toFixed(1) + '%' + moBar(r.weight, maxW) : '<span class="mo-muted">—</span>'}</td>` +
                `</tr>`;
        }).join('') || `<tr><td colspan="9" class="mo-empty">No active positions.</td></tr>`;

        // SORTED BY MULTIPLE, compact (user, 2026-09-09): the bank tracks sizing and gains
        // only, so the biggest winner leads and the rows are tight -- no weight bar, the
        // percentage alone. The snapshot's bank is the bank ON THAT DATE, multiple and
        // weight at that close; an older payload without one falls back to the live bank
        // filtered by banking date.
        const bank = (s.bank || (d.bank || []).filter(b => !s.date || (b.banked || '') <= s.date))
            .slice().sort((a, b) => (b.mult || 0) - (a.mult || 0));
        const bankRows = bank.map(b =>
            `<tr><td class="sym">${esc(b.tk)}</td>` +
            `<td class="mo-muted">${esc(b.banked || '')}</td>` +
            `<td class="mo-pl ${moCls((b.mult || 1) - 1)}">${b.mult == null ? '—' : (b.mult >= 10 ? b.mult.toFixed(0) : b.mult.toFixed(1))}x</td>` +
            `<td>${b.weight != null ? b.weight.toFixed(1) + '%' : '<span class="mo-muted">—</span>'}</td></tr>`
        ).join('') || `<tr><td colspan="4" class="mo-empty">Nothing banked yet.</td></tr>`;

        // THE CURRENT RANKING (user, 2026-09-10): a thin list between the books -- the
        // momentum leaders on the last close, the signal the book acts on at the next
        // open. A gated name (drought over the gate -- the limit itself arrives in the
        // payload as `gate_days`; THIS FILE HAS A PUBLIC REMOTE) is muted and marked ✕;
        // a name already in the book or the bank is tagged, which is why a #1 can sit
        // there unbought. If the raw #1 is gated the session stands down -- the veto --
        // and the card says so. Today's ranking only: a historical date has no list.
        // THIN (user, 2026-09-10: "a third of its size ... not a prominent list"). No card,
        // no table, no header row, no badges: rank, ticker, momentum, one mark. Red ✕ =
        // gated (drought over the limit); green ✓ = already held (PLTR is also banked --
        // held is the reason it cannot be bought, so ✓ wins). Drought and the rest live
        // in the tooltip. The veto is an amber tag on the label, not a sentence.
        const rk = live ? (d.ranking || []) : [];
        const rankRows = rk.map((r, i) => {
            const mk = r.gated ? '<span class="mk x">✕</span>' : r.held ? '<span class="mk ok">✓</span>' : '<span class="mk"></span>';
            const tip = `${r.tk} — ${moPct(r.mom)} over ${d.lookback_days != null ? d.lookback_days + ' sessions' : 'the lookback'} · drought ${r.drought == null ? 'n/a' : r.drought}` +
                        (r.gated ? ' · GATED' : r.held ? ' · held' : r.banked ? ' · in the bank' : '');
            return `<div class="mo-rank-row${r.gated ? ' gated' : ''}" title="${esc(tip)}">` +
                `<span class="n">${i + 1}</span><span class="tk">${esc(r.tk)}</span>` +
                `<span class="m ${moCls(r.mom)}">${(r.mom >= 0 ? '+' : '') + Math.round(r.mom)}%</span>${mk}</div>`;
        }).join('');
        // The middle column is always drawn so the three headings stay on one line and the
        // moon keeps its place; a past date has no ranking (the signal is today's), so the
        // card says so in one muted line and the moon below it shows THAT date's split.
        const rankCard =
            `<section class="mo-rank">` +
            (live
                ? `<div class="mo-rank-h" title="Top ${rk.length} by ${d.lookback_days != null ? d.lookback_days + '-session ' : ''}momentum on the last close — the signal the book acts on at the next open` +
                  (d.intraday_at ? `. PROVISIONAL: today's row is an intraday poll at ${esc(d.intraday_at.slice(11))} ET; the after-close re-pull replaces it` : '') + `">` +
                  // An intraday poll (user, 2026-09-10: "situational awareness ... just the
                  // rank list") stamps the heading with its time so a provisional #1 is not
                  // read as the close the book will act on.
                  `Rank <span class="d">${esc((d.ranking_date || '').slice(5))}${d.intraday_at ? ' · ' + esc(d.intraday_at.slice(11)) + ' intraday' : ''}</span>` +
                  (d.veto ? `<span class="v" title="The raw #1 is gated, so the session stands down: no buy, no displacement">veto</span>` : '') +
                  `</div>` +
                  `<div class="mo-card mo-fit mo-rank-card">` + (rankRows || '<div class="mo-empty">—</div>') + `</div>`
                : `<div class="mo-rank-h" title="The ranking is today's signal; a past date shows its split only">` +
                  `Rank <span class="d">${esc((s.date || '').slice(5))}</span></div>` +
                  `<div class="mo-card mo-fit mo-rank-card"><div class="mo-empty">live only</div></div>`) +
            // THE MOON SITS UNDER THE RANK LIST (user, 2026-09-10: "it looks off balance"),
            // so all three columns start with a heading and a card on the same line and the
            // middle one carries the split below its five rows.
            moPieSVG(d, s) +
            `</section>`;

        // INDEX ROTATION under the active book (user, 2026-09-11: "the last 10 to enter
        // and last 10 to exit"), two compact tables side by side, a mark on a name the
        // book holds (✓) or has banked (◆). Above them, an amber line per ANNOUNCED change
        // the index watch has read that is not yet in the recorded membership; red once
        // its effective date has passed and the roster still does not show it.
        const rot = d.rotation || {}, iw = d.index_watch || {};
        const heldSet = new Set((d.active || []).map(a => a.tk)), bankSet = new Set((d.bank || []).map(b => b.tk));
        const rotMark = tk => heldSet.has(tk) ? '<span style="color:#34d399" title="held">✓</span>'
                            : bankSet.has(tk) ? '<span style="color:#a78bfa" title="in the bank">◆</span>' : '';
        const rotRows = list => (list || []).map(r =>
            `<tr><td class="mo-muted">${esc(r.date || '')}</td><td class="sym">${esc(r.tk)}</td><td class="mk">${rotMark(r.tk)}</td></tr>`
        ).join('') || `<tr><td colspan="3" class="mo-empty">—</td></tr>`;
        const pendHTML = (iw.pending || []).map(p => {
            const adds = p.added || [], rems = p.removed || [];
            const what = [adds.length ? `joins <b>${adds.map(esc).join(', ')}</b>` : '',
                          rems.length ? `leaves <b>${rems.map(esc).join(', ')}</b>` : ''].filter(Boolean).join(' · ');
            const when = p.effective ? `effective <b>${esc(p.effective)}</b>` : 'effective date not stated';
            const note = p.unparsed ? 'the release could not be read' :
                         p.in_force ? 'past its effective date, not yet in the recorded membership' :
                                      'announced, not yet in the index';
            return `<div class="mo-pending${p.in_force ? ' late' : ''}" title="${esc(p.title || '')}">📣 ` +
                `<span class="mo-muted">${esc((p.published || '').slice(0, 10))}</span> ${what || esc(p.title || '')} · ${when} ` +
                `<span class="mo-muted">— ${note}</span>` +
                (p.url ? ` <a href="${esc(p.url)}" target="_blank" rel="noopener" class="mo-muted">release ↗</a>` : '') + `</div>`;
        }).join('');
        const unmapped = (iw.unmapped || []).length
            ? `<div class="mo-pending late">⚠ on the latest roster but unmapped to a ticker: ${iw.unmapped.map(esc).join(', ')}</div>` : '';
        const rotHTML =
            `<div class="mo-h3 mo-rot-h">Index rotation <span class="cnt">${rot.n_members ?? '—'} members · as of ${esc(rot.asof || '—')}` +
            `${iw.checked_at ? ' · watch ' + esc(iw.checked_at) : ''}</span>` +
            `<span class="lg"><span style="color:#34d399">✓</span> held · <span style="color:#a78bfa">◆</span> banked</span></div>` +
            pendHTML + unmapped +
            `<div class="mo-rot">` +
            `<div><div class="mo-h4 in">Entered</div><div class="mo-card mo-fit"><table class="mo-tbl mo-compact"><thead><tr>` +
            `<th>Date</th><th>Ticker</th><th></th></tr></thead><tbody>${rotRows(rot.entered)}</tbody></table></div></div>` +
            `<div><div class="mo-h4 out">Exited</div><div class="mo-card mo-fit"><table class="mo-tbl mo-compact"><thead><tr>` +
            `<th>Date</th><th>Ticker</th><th></th></tr></thead><tbody>${rotRows(rot.exited)}</tbody></table></div></div>` +
            `</div>`;

        box.innerHTML =
            `<div class="mo-halves with-rank">` +
            `<section><div class="mo-h3">Active book <span class="cnt">${rows.length} positions</span></div>` +
            `<div class="mo-card"><div class="mo-tblwrap"><table class="mo-tbl"><thead><tr>` +
            `<th>Ticker</th><th>Entry</th><th>Basis</th><th>Last</th><th>Ret</th><th>Held</th>` +
            `<th title="Sessions since the last 52-week high">Drought</th>` +
            `<th class="mo-pick-h" title="Sessions since the name was last the pick — the exit rule cuts the largest">Pick</th><th>Wt</th>` +
            `</tr></thead><tbody id="mo-active">${activeRows}</tbody></table></div></div>` +
            // THE RESET CONTROL, under the active book (user, 2026-09-09). The input is
            // seeded from whatever was typed last (or the book's own start), so a rail click
            // that re-renders this does not wipe an unrun date. Bounded to the panel.
            `<div class="mo-ctl mo-ctl-run">` +
            `<label for="mo-start">Strategy begins</label>` +
            `<input type="date" id="mo-start" min="${esc((d.starts || [])[0] || '')}" max="${esc(d.asof || '')}" value="${esc(_moPending || d.begins || '')}">` +
            `<button id="mo-run" type="button" title="Re-run the book from this date (~11s)">Reset &amp; run</button>` +
            `<span id="mo-status" class="mo-status"></span>` +
            `</div>` + rotHTML + `</section>` +
            rankCard +
            `<section>` +
            `<div class="mo-h3 bank">Bank book <span class="cnt">${bank.length} sleeves, held to the end</span></div>` +
            `<div class="mo-card mo-fit"><div class="mo-tblwrap"><table class="mo-tbl mo-compact"><thead><tr>` +
            `<th>Ticker</th><th>Banked</th><th>Multiple</th><th>Wt</th>` +
            `</tr></thead><tbody>${bankRows}</tbody></table></div></div></section>` +
            `</div>`;

        const run = document.getElementById('mo-run');
        if (run) run.addEventListener('click', moRun);
        const inp = document.getElementById('mo-start');
        if (inp) {
            inp.addEventListener('change', () => { _moPending = inp.value || null; });
            inp.addEventListener('keydown', e => { if (e.key === 'Enter') moRun(); });
        }
        if (_moBusy) moSetStatus(`rebuilding the book from ${_moPending || 'the start'} — about 11 seconds`, 'busy');

        // Clicking a holding puts it in the title row: strategy first, then the ticker.
        box.querySelectorAll('#mo-active tr[data-tk]').forEach(tr => tr.addEventListener('click', () => {
            box.querySelectorAll('#mo-active tr').forEach(x => x.removeAttribute('aria-current'));
            tr.setAttribute('aria-current', 'true');
            moSelectTicker(tr.dataset.tk, +tr.dataset.px, +tr.dataset.ret);
        }));
    }

    // THE SPLIT, DRAWN (user, 2026-09-09): bank share against active share as one pie in
    // the AI bubble's idiom -- abPie from stoplight.js, so the arcs, the 2px surface gap,
    // the inside labels and the caption pair are the same marks the board already uses.
    // Bank is SOLID in the bank's violet; the active book is the HATCH, the board's one
    // textured mark, here meaning "the search, not the return". The hatch pattern is
    // declared in this SVG's own defs so it does not depend on the AI bubble having drawn.
    // `s` is the selected rail snapshot: its split and equity are that date's (the live
    // chip's are the facts strip's own). Without one, the facts.
    function moPieSVG(d, s) {
        const f = d.facts || {};
        const share = (s && s.bank_share != null) ? s.bank_share : f.bank_share;
        const equity = (s && s.equity != null) ? Number(s.equity) : f.equity;
        if (share == null || equity == null) return '';
        const bank = Math.max(0, Math.min(100, share)), active = 100 - bank;
        const bankU = equity * bank / 100, activeU = equity - bankU;
        const R = 46, cx = 52, cy = 52, W = 104, H = 150;
        // A MOON (user, 2026-09-09 -- "give that pie chart a moon texture"). The bank is
        // the LIT face in the bank's violet; the active book is the DARK SIDE. The phase
        // is the split, so the hatch that used to mark "the search" retires -- the
        // shadow says it. Everything is procedural SVG: no image, nothing fetched.
        const LIT = '#a78bfa', DARK = '#3b4557';
        const slices = [
            { value: bank, fill: LIT, title: `Bank — ${bank.toFixed(1)}% of equity, ${bankU.toFixed(2)}u` },
            { value: active, fill: DARK, title: `Active book + cash — ${active.toFixed(1)}%, ${activeU.toFixed(2)}u` },
        ].filter(s => s.value > 0);
        const arcs = (typeof abPie === 'function') ? abPie(cx, cy, R, slices, 100) : '';

        // THE SURFACE, four layers, all clipped to the disc because each IS the disc:
        //   maria   -- two soft dark basins, so the face is not uniform
        //   craters -- a tiled pattern of radial-gradient rims (dark floor, lit lip)
        //   grain   -- fractal-noise regolith, soft-light so it textures without tinting
        //   limb    -- darkening toward the edge, which is what makes a disc read as a sphere
        // Inserted BEFORE the labels abPie emits, so the percentages sit on top, crisp.
        const defs =
            `<defs>` +
            `<radialGradient id="moCrater"><stop offset="0%" stop-color="#000" stop-opacity=".40"/>` +
            `<stop offset="58%" stop-color="#000" stop-opacity=".20"/>` +
            `<stop offset="82%" stop-color="#fff" stop-opacity=".22"/>` +
            `<stop offset="100%" stop-color="#fff" stop-opacity="0"/></radialGradient>` +
            `<radialGradient id="moMare"><stop offset="0%" stop-color="#000" stop-opacity=".28"/>` +
            `<stop offset="100%" stop-color="#000" stop-opacity="0"/></radialGradient>` +
            `<radialGradient id="moLimb"><stop offset="0%" stop-color="#fff" stop-opacity=".07"/>` +
            `<stop offset="70%" stop-color="#000" stop-opacity="0"/>` +
            `<stop offset="100%" stop-color="#000" stop-opacity=".45"/></radialGradient>` +
            `<pattern id="moCraters" width="34" height="34" patternUnits="userSpaceOnUse" patternTransform="rotate(17)">` +
            `<circle cx="9" cy="8" r="5.2" fill="url(#moCrater)"/>` +
            `<circle cx="25" cy="21" r="3.4" fill="url(#moCrater)"/>` +
            `<circle cx="14" cy="27" r="2.1" fill="url(#moCrater)"/>` +
            `<circle cx="29" cy="5" r="1.6" fill="url(#moCrater)"/></pattern>` +
            `<filter id="moGrain" x="0" y="0" width="1" height="1">` +
            `<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="4" seed="11" result="n"/>` +
            `<feColorMatrix in="n" type="saturate" values="0" result="g"/>` +
            `<feComposite in="g" in2="SourceGraphic" operator="in"/></filter>` +
            `</defs>`;
        const surface =
            `<g pointer-events="none">` +
            `<circle cx="${cx - 14}" cy="${cy - 10}" r="15" fill="url(#moMare)"/>` +
            `<circle cx="${cx + 12}" cy="${cy + 16}" r="11" fill="url(#moMare)"/>` +
            `<circle cx="${cx}" cy="${cy}" r="${R}" fill="url(#moCraters)"/>` +
            `<circle cx="${cx}" cy="${cy}" r="${R}" fill="#fff" filter="url(#moGrain)" opacity=".5" style="mix-blend-mode:soft-light"/>` +
            `<circle cx="${cx}" cy="${cy}" r="${R}" fill="url(#moLimb)"/>` +
            `</g>`;
        const cut = arcs.indexOf('<text');
        const disc = cut < 0 ? arcs + surface : arcs.slice(0, cut) + surface + arcs.slice(cut);

        // Key left, pie right, the pair centred over the bank book (user). DOM order
        // matches visual order.
        return `<div class="mo-pie">` +
            `<div class="mo-pie-key">` +
            `<div><span class="sw" style="background:${LIT}"></span>Bank <b>${bank.toFixed(1)}%</b> · ${bankU.toFixed(2)}u</div>` +
            `<div><span class="sw" style="background:${DARK}"></span>Active <b>${active.toFixed(1)}%</b> · ${activeU.toFixed(2)}u</div>` +
            `</div>` +
            `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" ` +
            `aria-label="Bank ${bank.toFixed(0)} percent of equity, active book ${active.toFixed(0)} percent">` +
            defs + disc +
            `<text x="${cx}" y="${cy + R + 26}" class="ab-pie-c">Total equity</text>` +
            `<text x="${cx}" y="${cy + R + 41}" class="ab-pie-v">${equity.toFixed(2)}u</text>` +
            `</svg></div>`;
    }

    // THE CHART TAB (user, 2026-09-12: "plot out the equity curve of the moonshot strategy
    // based on the current 'start' date"; "make the base amount $100,000"). The curve is
    // the book this payload was BUILT from -- the start the Reset & run control last ran,
    // not a date typed and not yet run. Rebased so its first mark is the payload's dollar
    // base; QQQ buy and hold on the same base beside it (the house rule: a buy-and-hold
    // line beside every result). Log by default: over a decade the early years of a
    // compounding book are a flat line on a linear axis. The legend reads the hovered day,
    // or the last one.
    let _moEqChart = null;
    let _moEqScale = 'log';
    function moDrawEquity() {
        const box = document.getElementById('mo-eq-chart');
        const legend = document.getElementById('mo-eq-legend');
        if (!box || typeof LightweightCharts === 'undefined') return;
        if (_moEqChart) { _moEqChart.remove(); _moEqChart = null; }
        box.innerHTML = '';
        const d = _moLast, c = d && d.curve;
        if (!c || !(c.dates || []).length) {
            box.innerHTML = `<div class="mo-empty">${d ? 'This book carries no equity curve yet.' : 'Building the book…'}</div>`;
            if (legend) legend.innerHTML = '';
            return;
        }
        const base = d.chart_base_usd;
        const k = base ? base / c.equity[0] : 1;
        const money = v => !base ? v.toFixed(2) + 'u'
            : v >= 1e6 ? '$' + (v / 1e6).toFixed(2) + 'M' : '$' + Math.round(v).toLocaleString('en-US');
        const MO = '#818cf8', BH = '#94a3b8';
        const chart = LightweightCharts.createChart(box, {
            autoSize: true,
            layout: { background: { color: 'transparent' }, textColor: '#94a3b8', fontFamily: 'Inter, sans-serif' },
            grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
            // minBarSpacing well under the library's 0.5px default: twelve years of daily marks
            // are ~3,150 points, and at 0.5px fitContent() cannot fit them and clips the
            // start -- the first cut drew 2019 onward for a 2014 book.
            timeScale: { borderColor: '#334155', minBarSpacing: 0.05 },
            rightPriceScale: { borderColor: '#334155', mode: _moEqScale === 'log' ? 1 : 0 },
            leftPriceScale: { visible: false },
            localization: { priceFormatter: money },
            crosshair: { mode: 0 }
        });
        // NO SERIES TITLES (user, 2026-09-12): the library paints a title inside the plot beside
        // the axis, over the last stretch of the line. The legend names both lines; the value
        // tag stays, on the axis itself.
        // A DAY WITH NO VALUE IS A GAP, NOT A ZERO (2026-09-23). The payload carries null
        // where the walk could not price a day -- the price source dropped the whole
        // 2026-09-22 session for most names -- and `null * k` is 0 in JavaScript, so the
        // line dived to the axis and back. A point with a time and no value is the
        // library's own "whitespace": it holds the date on the scale and draws nothing.
        const pt = (t, v) => (typeof v === 'number' && isFinite(v)) ? { time: t, value: v * k }
                                                                   : { time: t };
        const mo = chart.addLineSeries({ color: MO, lineWidth: 2, priceLineVisible: false });
        mo.setData(c.dates.map((t, i) => pt(t, c.equity[i])));
        if (c.bench) {
            const bh = chart.addLineSeries({ color: BH, lineWidth: 1.5, priceLineVisible: false });
            bh.setData(c.dates.map((t, i) => pt(t, c.bench[i])));
        }
        chart.timeScale().fitContent();
        _moEqChart = chart;

        const byTime = {};
        c.dates.forEach((t, i) => { byTime[t] = i; });
        // The readout says the day had no mark rather than printing $0 / 0.0x for it.
        const num = v => typeof v === 'number' && isFinite(v);
        const show = i => {
            if (!legend) return;
            const e = c.equity[i], b = c.bench ? c.bench[i] : null;
            const mTxt = num(e) ? `<b>${money(e * k)}</b> ${(e / c.equity[0]).toFixed(1)}×`
                                : '<b>—</b> <span class="mo-muted">no mark that day</span>';
            const qTxt = num(b) ? `<b>${money(b * k)}</b> ${(b / c.bench[0]).toFixed(1)}×` : '<b>—</b>';
            legend.innerHTML =
                `<span>${esc(c.dates[i])}${i === c.dates.length - 1 ? ' · as of' : ''}</span>` +
                `<span><span class="sw" style="background:${MO}"></span>Moonshot ${mTxt}</span>` +
                (b == null && !c.bench ? '' :
                    `<span><span class="sw" style="background:${BH}"></span>` +
                    `${esc(c.bench_ticker || 'Benchmark')} ${qTxt}</span>`) +
                `<span>from ${money(c.equity[0] * k)} on ${esc(c.dates[0])}</span>`;
        };
        show(c.dates.length - 1);
        chart.subscribeCrosshairMove(p => {
            const t = p && p.time;
            const key = !t ? null : (typeof t === 'string' ? t
                : `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`);
            show(key != null && byTime[key] != null ? byTime[key] : c.dates.length - 1);
        });

        document.querySelectorAll('.mo-eq-scale button').forEach(btn => {
            btn.classList.toggle('on', btn.dataset.scale === _moEqScale);
            btn.onclick = () => {
                _moEqScale = btn.dataset.scale;
                document.querySelectorAll('.mo-eq-scale button').forEach(b => b.classList.toggle('on', b === btn));
                if (_moEqChart) _moEqChart.priceScale('right').applyOptions({ mode: _moEqScale === 'log' ? 1 : 0 });
            };
        });
    }

    function moRenderPortfolio(d) {
        moRenderRail(d);
        moRenderBooks(d, 0);
    }

    // THE BUTTON'S TARGET. Opens this panel on the Strategy tab -- not the chart, which
    // is where a ticker click lands (a book has no single price series) -- then fills the
    // title row, the facts strip, the rules and ledger, and the Portfolio tab.
    async function showMoonshotDive(start) {
        if (!document.getElementById('strategy-dive')) return;
        const seq = ++_moSeq;
        ++_sdSeq;                                  // any in-flight ticker load must not land on us
        _moStart = (start === undefined) ? _moStart : (start || '');

        showOnlyPanel('strategy-dive');
        setTabsForStrategy('moonshot');
        viewState.sd.entity = null;
        viewState.sd.levels = [];
        viewState.sd.loadedFor = null;

        // Strategy first, then the selected ticker (user, 2026-09-09). None yet.
        moSelectTicker(null, null, null);
        const t = document.getElementById('sd-ticker');
        if (t) t.style.color = '#e2e8f0';
        document.getElementById('sd-regime').innerText =
            (typeof strLast !== 'undefined' && strLast && strLast.label) ? `dial: ${strLast.label}` : '';

        // REOPENING ON THE SAME START DATE SHOWS THE BOOK ALREADY IN THE PAGE AT ONCE (user,
        // 2026-09-14: "I should never have to wait for the tab to appear"), then asks the
        // engine, which answers immediately too -- with its newest book, or with the one it has
        // flagged `refreshing` while it walks a new one (moPollRefresh swaps that in).
        const sameStart = !!_moLast && (start === undefined || (start || '') === (_moLast.begins_key || ''));
        const rerun = !!_moLast && !sameStart;
        _moBusy = true;
        if (sameStart) {
            moApply(_moLast);
        } else if (rerun) {
            moSetStatus(`rebuilding the book from ${_moStart || 'the start'} — about 11 seconds`, 'busy');
        } else {
            sdSetFacts('<div class="sd-facts-row"><span class="sd-fact"><span class="sd-fact-k">Book</span>' +
                       '<span class="sd-fact-v">loading…</span></span></div>');
            sdSetColumns(null);
            const rail = document.getElementById('mo-rail');
            if (rail) rail.innerHTML = '<div class="mo-empty">Building the book…</div>';
        }

        // Keep whichever of our tabs is showing; a ticker's Chart/Dial can't be.
        const active = document.querySelector('#sd-tabs .view-tab.active');
        const cur = active && active.dataset.view;
        switchTab('sd', (cur === 'portfolio' || cur === 'equity' || cur === 'custom') ? cur : 'strategy');

        let d = null;
        try {
            const r = await fetch(`${API_BASE}/get_moonshot?start=${encodeURIComponent(_moStart)}`);
            d = await r.json();
        } catch (e) { /* falls through */ }
        if (seq !== _moSeq) return;
        _moBusy = false;

        if (!d || !d.ok) {
            const msg = (d && d.error) || 'unavailable';
            if (sameStart) {
                return;                            // keep the book on screen; nothing new to show
            } else if (rerun) {
                moSetStatus(`failed: ${msg}`, 'err');
            } else {
                sdSetFacts('<div class="sd-facts-row"><span class="sd-fact"><span class="sd-fact-k">Book</span>' +
                           `<span class="sd-fact-v str-st-off">${esc(msg)}</span></span></div>`);
            }
            return;
        }
        d.begins_key = _moStart;
        _moPending = null;                         // the typed date is now the built one
        moApply(d);
        if (rerun) moSetStatus(`rebuilt from ${d.begins}${d.built_in ? ' in ' + d.built_in + 's' : ' (cached)'}`, 'ok');
        moPollRefresh(seq);
    }

    // Render one book into every Moonshot tab. The Portfolio rail keeps the current chip; the
    // Chart tab redraws only if it is the one showing (a chart built hidden measures zero).
    function moApply(d) {
        _moLast = d;
        sdSetFacts(moFactsHTML(d));
        sdSetColumns({ rules: d.rules, trades: d.trades });   // no phase_diagram: draws nothing
        moRenderPortfolio(d);
        const shown = document.querySelector('#sd-tabs .view-tab.active');
        if (shown && shown.dataset.view === 'equity') moDrawEquity();
    }

    // WHILE THE ENGINE WALKS A NEWER BOOK, the panel shows the previous one flagged "updating"
    // and asks again every ten seconds, swapping the new book in when it lands. Stops when the
    // viewer opens something else (a new showMoonshotDive or ticker load moves the sequence).
    let _moRefreshTimer = null;
    function moPollRefresh(seq) {
        clearTimeout(_moRefreshTimer);
        if (!_moLast || !_moLast.refreshing) return;
        _moRefreshTimer = setTimeout(async () => {
            if (seq !== _moSeq) return;
            let d = null;
            try {
                const r = await fetch(`${API_BASE}/get_moonshot?start=${encodeURIComponent(_moStart)}`);
                d = await r.json();
            } catch (e) { /* try again next tick */ }
            if (seq !== _moSeq) return;
            if (d && d.ok) {
                d.begins_key = _moStart;
                if (!d.refreshing) moApply(d);
                else _moLast.refreshing = true;
            }
            moPollRefresh(seq);
        }, 10000);
    }

    async function showStrategyDive(ticker) {
        if (!ticker) return;
        const seq = ++_sdSeq;

        if (!document.getElementById('strategy-dive')) return;
        showOnlyPanel('strategy-dive');     // shared list in core.js — see DETAIL_PANELS
        setTabsForStrategy('ticker');       // a ticker's panel: Chart and Dial back, Portfolio and Custom away
        // ENTITY BEFORE THE TAB SWITCH — the order is load-bearing. switchTab('sd','chart')
        // calls loadChart SYNCHRONOUSLY, and loadChart reads viewState.sd.entity and returns
        // early when `loadedFor` already matches it. Setting these afterwards meant clicking
        // from one ticker to the next rendered the PREVIOUS chart and only then armed the
        // reload — which is exactly why leaving the tab and coming back showed the right one.
        //
        // `loadedFor: null` forces a rebuild even when the ticker has NOT changed, because
        // the levels move daily even when the entity does not.
        viewState.sd.entity = { asset_class: 'equity', ticker };
        viewState.sd.levels = [];
        viewState.sd.loadedFor = null;

        // CHART BY DEFAULT (user, 2026-08-15). A pill click is a request to see the name
        // against its price; the facts strip rides in the header, so opening on the chart
        // costs none of that information.
        switchTab('sd', 'chart');

        // The holding gives price/day/color without a second round trip — the dial payload
        // is already in hand and already carries technicals for every column.
        const h = (typeof strLast !== 'undefined' && strLast)
            ? strFindHolding(strLast, ticker) : null;
        const color = (h && h.color) || '#94a3b8';

        document.getElementById('sd-ticker').innerText = ticker;
        document.getElementById('sd-ticker').style.color = color;
        document.getElementById('sd-price').innerText =
            (h && h.price !== null && h.price !== undefined) ? h.price.toFixed(2) : '—';
        document.getElementById('sd-day').innerHTML =
            (h && h.day_pct !== null && h.day_pct !== undefined) ? strPct(h.day_pct) : '';
        document.getElementById('sd-regime').innerText =
            (typeof strLast !== 'undefined' && strLast && strLast.label)
                ? `dial: ${strLast.label}` : '';

        sdSetFacts('<div class="sd-facts-row"><span class="sd-fact">loading…</span></div>');
        sdSetColumns(null);

        renderDialPane();

        let d = null;
        try {
            const r = await fetch(`${API_BASE}/get_ticker_strategy/${encodeURIComponent(ticker)}`);
            d = await r.json();
        } catch (e) { /* fall through to the no-state message */ }

        if (seq !== _sdSeq) return;    // a newer pill was clicked mid-fetch

        if (!d || !d.ok || !d.has_strategy) {
            sdSetFacts('<div class="sd-facts-row"><span class="sd-fact">' +
                '<span class="sd-fact-k">State</span>' +
                '<span class="sd-fact-v str-st-off">no strategy wired</span></span></div>');
            sdSetColumns(null);
            return;
        }

        sdSetFacts(sdFactsHTML(d, color));
        sdSetColumns(d);

        // Redraw with the levels now that the contract has landed. The chart may still be
        // fetching; drawStrategyLevels is idempotent and reapplies on the next render.
        viewState.sd.levels = sdLevels(d, color);
        drawStrategyLevels('sd');
    }

    // THE HEADER ALERT (user, 2026-09-11: "alert the user to any new announced tickers
    // joining the QQQ, but haven't formally been incorporated"). On page load the
    // Moonshot button asks the light notices route -- no walk behind it -- and carries an
    // amber count of announced index changes not yet in force, with the names and
    // effective dates in its tooltip. Nothing pending, nothing shown.
    async function moNotices() {
        const el = document.getElementById('mo-btn-alert'), btn = document.getElementById('mo-btn');
        if (!el || !btn) return;
        try {
            const r = await fetch(`${API_BASE}/get_moonshot_notices`);
            const d = await r.json();
            const pend = (d && d.ok) ? (d.pending || []) : [];
            el.hidden = !pend.length;
            el.textContent = pend.length ? String(pend.length) : '';
            btn.title = !pend.length ? 'Moonshot — the momentum book' :
                `Moonshot — ${pend.length} announced index change${pend.length > 1 ? 's' : ''} not yet in force: ` +
                pend.map(p => ((p.added || []).map(t => '+' + t).concat((p.removed || []).map(t => '−' + t)).join(' ') || p.title || '?') +
                              (p.effective ? ` (effective ${p.effective})` : '')).join('; ');
        } catch (e) { /* the button stays plain */ }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', moNotices);
    else moNotices();
