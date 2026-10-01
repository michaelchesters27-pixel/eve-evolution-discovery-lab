(() => {
  if (window.eveZoneDecisionToleranceV82) return;
  window.eveZoneDecisionToleranceV82 = true;

  const HOLD_MS = 20 * 60 * 1000;
  const TOLERANCE_ATR = 0.35;
  const EARLY_REACTION_ATR = 0.20;
  let active = null;
  let expiredZoneId = null;
  const MAX_TICK_AGE_SECONDS = 90;
  const MAX_DECISION_AGE_MINUTES = 15;

  const num = value => {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const fmt = value => {
    const parsed = num(value);
    return parsed == null ? '—' : parsed.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
  };

  const tfDirection = (state, key) => {
    const item = state?.bias?.timeframes?.[key];
    if (item && typeof item === 'object') return String(item.direction || '').toLowerCase();
    return String(item || '').toLowerCase();
  };

  const sameZone = (left, right) => {
    if (!left || !right || left.kind !== right.kind) return false;
    const leftId = String(left.id || '').trim();
    const rightId = String(right.id || '').trim();
    return leftId.length > 0 && rightId.length > 0 && leftId === rightId
      && Math.abs(left.low - right.low) <= 0.001
      && Math.abs(left.high - right.high) <= 0.001;
  };

  function candidates(state) {
    if (state?.chart_zones_status?.available !== true) return [];
    const price = num(state?.price);
    const atr = num(state?.market?.atr);
    if (price == null || price <= 0 || atr == null || atr <= 0) return [];
    const out = [];
    for (const kind of ['demand', 'supply']) {
      // ZONE TEST must use the exact same active-zone truth as RELEVANT CHART
      // ZONES. Fail closed if the dedicated chart feed is unavailable; never
      // fall back to the more tolerant trade-facing zones array.
      const zones = Array.isArray(state?.chart_zones?.[kind]) ? state.chart_zones[kind] : [];
      for (const zone of zones) {
        const id = String(zone?.id || '').trim();
        const low = num(zone?.low);
        const high = num(zone?.high);
        const status = String(zone?.status || '').toUpperCase();
        if (!id || low == null || high == null || low <= 0 || high <= 0 || high < low) continue;
        if (['BROKEN','INVALID','EXPIRED'].includes(status)) continue;
        const inZone = low <= price && price <= high;
        const distance = inZone ? 0 : price < low ? low - price : price - high;
        out.push({
          id,
          kind, low, high, atr, price, inZone,
          distance,
          tolerance: Math.max(atr * TOLERANCE_ATR, 0.25),
          quality: num(zone?.quality),
          fresh: zone?.fresh === true,
          retests: Math.max(0, Number(zone?.retests || 0)),
          zoneRole: String(zone?.zone_role || 'M5_ONLY'),
          h1Confluence: zone?.h1_confluence === true,
          m15Confluence: zone?.m15_confluence === true,
        });
      }
    }
    return out;
  }

  function armOrUpdate(state) {
    const now = Date.now();
    const all = candidates(state);
    const near = all
      .filter(item => item.distance <= item.tolerance)
      .sort((a, b) => (a.distance / a.atr) - (b.distance / b.atr))[0] || null;

    if (expiredZoneId && (!near || near.id !== expiredZoneId)) expiredZoneId = null;

    if (active) {
      const current = all.find(item => sameZone(item, active));
      if (!current) {
        active = null;
      } else if (now >= active.until) {
        expiredZoneId = active.id;
        active = null;
      } else {
        active.low = current.low;
        active.high = current.high;
        active.atr = current.atr;
        active.price = current.price;
        active.inZone = current.inZone;
        active.quality = current.quality;
        active.fresh = current.fresh;
        active.retests = current.retests;
        active.zoneRole = current.zoneRole;
        active.h1Confluence = current.h1Confluence;
        active.m15Confluence = current.m15Confluence;
        active.wasInside = active.wasInside || current.inZone;
        active.extreme = active.kind === 'demand'
          ? Math.min(active.extreme, current.price)
          : Math.max(active.extreme, current.price);
        return active;
      }
    }

    if (!near) return null;

    if (expiredZoneId === near.id) {
      return {...near, started:null, until:null, wasInside:true, tracking:false, expired:true, extreme:near.price};
    }

    if (!near.inZone) {
      return {...near, started:null, until:null, wasInside:false, tracking:false, expired:false, extreme:near.price};
    }

    active = {
      ...near,
      started: now,
      until: now + HOLD_MS,
      wasInside: true,
      tracking: true,
      expired: false,
      extreme: near.price,
    };
    return active;
  }

  function decisionFor(state, test) {
    const desired = test.kind === 'demand' ? 'bullish' : 'bearish';
    const opposite = desired === 'bullish' ? 'bearish' : 'bullish';
    const side = test.kind === 'demand' ? 'BUY' : 'SELL';
    const desiredArrow = desired === 'bullish' ? '↑' : '↓';
    const oppositeArrow = opposite === 'bullish' ? '↑' : '↓';
    const m5 = tfDirection(state, 'M5');
    const m15 = tfDirection(state, 'M15');
    const trade = state?.trade || {};
    const action = String(trade.action || '').toUpperCase();
    const tradeSide = String(trade.side || '').toUpperCase();
    const specialist = String(trade.strategy_key || '') === 'zone_retrace_v1' || String(trade.execution_class || '') === 'zone_retrace_confirmation';
    const actionable = !['', 'WAIT', 'NO TRADE'].includes(action);
    const sourceZone = trade?.source_zone || {};
    const sourceZoneId = String(sourceZone?.id || '').trim();
    const sourceZoneLow = num(sourceZone?.low);
    const sourceZoneHigh = num(sourceZone?.high);
    const sourceMatches = sourceZoneId.length > 0
      && sourceZoneId === test.id
      && sourceZoneLow != null
      && sourceZoneHigh != null
      && Math.abs(sourceZoneLow - test.low) <= 0.001
      && Math.abs(sourceZoneHigh - test.high) <= 0.001;
    const confirmed = actionable && specialist && test.wasInside === true && sourceMatches
      && (tradeSide === side || action === side || action.startsWith(side));
    const reaction = test.wasInside === true
      ? (test.kind === 'demand' ? test.price - test.extreme : test.extreme - test.price)
      : 0;
    const reactionAtr = test.atr > 0 ? Math.max(0, reaction) / test.atr : 0;

    if (confirmed) return {
      tone: desired,
      arrow: desiredArrow,
      title: `${desired.toUpperCase()} REJECTION CONFIRMED`,
      note: `EVE's existing live retracement strategy has confirmed the ${side}.`,
      m5, m15,
    };

    if (test.expired === true) return {
      tone:'undecided',
      arrow:'↕',
      title:'TEST WINDOW EXPIRED — WAIT',
      note:'The previous 20-minute test window has expired. EVE will not re-arm this zone until price leaves the test area and later returns.',
      m5, m15,
    };

    if (test.wasInside !== true) return {
      tone:'undecided',
      arrow:'↕',
      title:'APPROACHING ZONE — WAIT',
      note:`Price is near ${test.kind} but has not entered this exact zone yet. No rejection or break claim is active.`,
      m5, m15,
    };

    if (m5 === opposite && m15 === opposite) return {
      tone: opposite,
      arrow: oppositeArrow,
      title: `${opposite.toUpperCase()} BREAK BUILDING`,
      note: `${test.kind.toUpperCase()} is under pressure. M5 and M15 are both ${opposite}. Do not take the ${side} while this remains.`,
      m5, m15,
    };

    if (m5 === desired && m15 !== opposite) return {
      tone: desired,
      arrow: desiredArrow,
      title: 'REJECTION BUILDING',
      note: `Price has tested ${test.kind} and M5 is turning ${desired}. EVE is watching for M15 confirmation before treating the ${side} as confirmed.`,
      m5, m15,
    };

    if (reactionAtr >= EARLY_REACTION_ATR) return {
      tone: 'undecided',
      arrow: desiredArrow,
      title: 'EARLY REJECTION — WAIT',
      note: `Price has reacted about ${reactionAtr.toFixed(2)} ATR away from ${test.kind}. The reaction has started, but M5/M15 have not confirmed it yet.`,
      m5, m15,
    };

    return {
      tone: 'undecided',
      arrow: '↕',
      title: 'ZONE TEST — WAIT',
      note: `Price is testing ${test.kind}. EVE does not yet have enough evidence to call a rejection or a break.`,
      m5, m15,
    };
  }

  function ensureCard(panel) {
    let card = document.getElementById('ltZoneDecisionTolerance');
    if (!card) {
      card = document.createElement('div');
      card.id = 'ltZoneDecisionTolerance';
      card.className = 'lt-zone-decision undecided';
    }
    if (panel.nextElementSibling !== card) panel.insertAdjacentElement('afterend', card);
    return card;
  }

  function nativeDecisionMode(panel, activeMode) {
    panel.classList.toggle('eve-tolerant-zone-decision-active', activeMode);
    if (!document.getElementById('eveZoneDecisionToleranceStyle')) {
      const style = document.createElement('style');
      style.id = 'eveZoneDecisionToleranceStyle';
      style.textContent = `
        .eve-tolerant-zone-decision-active .lt-zone-decision{display:none!important}
        #ltZoneDecisionTolerance{margin-top:10px}
        #ltZoneDecisionTolerance .lt-zone-decision-side{margin-top:4px;font-size:11px;font-weight:900;letter-spacing:.05em}
        #ltZoneDecisionTolerance .lt-zone-decision-range{margin-top:3px;font-size:12px;font-weight:900;color:#e7f4ed;font-variant-numeric:tabular-nums}
        #ltZoneDecisionTolerance .lt-zone-decision-meta{margin-top:4px;font-size:8px;color:var(--muted);font-weight:800;letter-spacing:.04em;text-transform:uppercase}
        #ltZoneDecisionTolerance .lt-zone-decision-arrow{animation:eve-zone-tolerance-pulse .85s ease-in-out infinite;transform-origin:center}
        #ltZoneDecisionTolerance.bullish .lt-zone-decision-arrow{filter:drop-shadow(0 0 8px rgba(75,240,150,.85))}
        #ltZoneDecisionTolerance.bearish .lt-zone-decision-arrow{filter:drop-shadow(0 0 8px rgba(255,105,125,.85))}
        #ltZoneDecisionTolerance.undecided .lt-zone-decision-arrow{filter:drop-shadow(0 0 8px rgba(255,195,90,.85))}
        @keyframes eve-zone-tolerance-pulse{0%,100%{transform:scale(.72);opacity:.55}50%{transform:scale(1.32);opacity:1}}
        @media(prefers-reduced-motion:reduce){#ltZoneDecisionTolerance .lt-zone-decision-arrow{animation:none}}
      `;
      document.head.appendChild(style);
    }
  }

  function contextValid(state) {
    const feed = state?.feed || {};
    const dq = state?.bias?.data_quality || {};
    const ctx = state?.live_context_freshness || {};
    const lag = num(ctx.context_lag_minutes ?? dq.live_context_lag_minutes);
    const tickMs = Date.parse(String(ctx.live_tick_at || feed.last_tick_at || ''));
    const decisionMs = Date.parse(String(ctx.effective_decision_time || ''));
    const now = Date.now();
    const tickAgeSeconds = Number.isFinite(tickMs) ? Math.max(0, (now - tickMs) / 1000) : null;
    const decisionAgeMinutes = Number.isFinite(decisionMs) ? Math.max(0, (now - decisionMs) / 60000) : null;
    const price = num(state?.price);
    const atr = num(state?.market?.atr);
    return feed.status === 'live'
      && feed.connected === true
      && ctx.context_valid === true
      && ctx.fresh === true
      && dq.live_context_stale !== true
      && dq.trade_bias_blocked !== true
      && lag != null
      && lag >= 0
      && lag <= 10
      && tickAgeSeconds != null
      && tickAgeSeconds <= MAX_TICK_AGE_SECONDS
      && decisionAgeMinutes != null
      && decisionAgeMinutes <= MAX_DECISION_AGE_MINUTES
      && price != null
      && price > 0
      && atr != null
      && atr > 0;
  }

  function render(state) {
    const panel = document.getElementById('ltSessionOutlookPanel');
    if (!panel) return;
    if (!contextValid(state)) {
      active = null;
      document.getElementById('ltZoneDecisionTolerance')?.remove();
      nativeDecisionMode(panel, false);
      return;
    }
    const test = armOrUpdate(state);
    const existing = document.getElementById('ltZoneDecisionTolerance');

    if (!test) {
      if (existing) existing.remove();
      nativeDecisionMode(panel, false);
      return;
    }

    nativeDecisionMode(panel, true);
    const decision = decisionFor(state, test);
    const card = ensureCard(panel);
    card.className = `lt-zone-decision ${decision.tone}`;
    const tfLabel = value => ['bullish', 'bearish', 'neutral'].includes(value) ? value.toUpperCase() : 'UNKNOWN';
    const position = test.inZone ? 'PRICE IS IN' : test.wasInside ? 'ZONE TOUCHED' : 'PRICE IS NEAR';
    const side = test.kind === 'demand' ? 'BUY' : 'SELL';
    const backing = test.h1Confluence && test.m15Confluence
      ? 'H1 + M15 BACKED'
      : test.h1Confluence
        ? 'H1 BACKED'
        : test.m15Confluence
          ? 'M15 BACKED'
          : 'M5 ONLY';
    const quality = test.quality == null ? 'HEURISTIC QUALITY —' : `HEURISTIC QUALITY ${Math.round(test.quality)}/100`;
    const retests = `${test.retests} TOUCH BAR${test.retests === 1 ? '' : 'S'}`;
    const freshness = test.fresh ? 'FRESH' : 'USED';
    card.innerHTML = `
      <div class="lt-zone-decision-arrow" aria-hidden="true">${decision.arrow}</div>
      <div>
        <div class="lt-zone-decision-kicker">${position} ${test.kind.toUpperCase()} · ZONE DECISION</div>
        <div class="lt-zone-decision-title">${decision.title}</div>
        <div class="lt-zone-decision-side">POTENTIAL ${side} ZONE</div>
        <div class="lt-zone-decision-range">${test.kind.toUpperCase()} ${fmt(test.low)} – ${fmt(test.high)}</div>
        <div class="lt-zone-decision-meta">${backing} · ${quality} · ${retests} · ${freshness}</div>
        <p class="lt-zone-decision-note">${decision.note}</p>
        <div class="lt-zone-decision-tfs">M5 ${tfLabel(decision.m5)} · M15 ${tfLabel(decision.m15)} · ${test.tracking ? 'ACTIVE FOR 20 MIN AFTER ACTUAL TOUCH' : test.expired ? 'WAITING FOR A NEW RETEST' : 'NOT YET TOUCHED'}</div>
      </div>`;
  }

  function consume(event) {
    const state = event?.detail?.state;
    if (state && typeof state === 'object') render(state);
  }

  window.addEventListener('eve:live-trader-state', consume);
  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', () => {
    if (window.__eveLiveTraderState) render(window.__eveLiveTraderState);
  });
  if (window.__eveLiveTraderState) render(window.__eveLiveTraderState);
})();
