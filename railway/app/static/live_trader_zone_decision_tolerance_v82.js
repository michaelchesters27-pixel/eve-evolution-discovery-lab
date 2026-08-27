(() => {
  if (window.eveZoneDecisionToleranceV82) return;
  window.eveZoneDecisionToleranceV82 = true;

  const POLL_MS = 2500;
  const HOLD_MS = 20 * 60 * 1000;
  const TOLERANCE_ATR = 0.35;
  const EARLY_REACTION_ATR = 0.20;
  let active = null;

  const num = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const tfDirection = (state, key) => {
    const item = state?.bias?.timeframes?.[key];
    if (item && typeof item === 'object') return String(item.direction || '').toLowerCase();
    return String(item || '').toLowerCase();
  };

  const sameZone = (left, right) => {
    if (!left || !right || left.kind !== right.kind) return false;
    const atr = Math.max(left.atr || 0, right.atr || 0, 0.01);
    const overlap = Math.max(left.low, right.low) <= Math.min(left.high, right.high) + atr * 0.20;
    const nearby = Math.abs(left.low - right.low) <= atr * 0.50 && Math.abs(left.high - right.high) <= atr * 0.50;
    return overlap || nearby;
  };

  function candidates(state) {
    const price = num(state?.price);
    const atr = Math.max(num(state?.market?.atr) || 0, 0.01);
    if (price == null) return [];
    const out = [];
    for (const kind of ['demand', 'supply']) {
      const zones = Array.isArray(state?.zones?.[kind]) ? state.zones[kind].slice(0, 3) : [];
      for (const zone of zones) {
        const low = num(zone?.low);
        const high = num(zone?.high);
        if (low == null || high == null || high < low) continue;
        const inZone = low <= price && price <= high;
        const distance = inZone ? 0 : price < low ? low - price : price - high;
        out.push({
          kind, low, high, atr, price, inZone,
          distance,
          tolerance: Math.max(atr * TOLERANCE_ATR, 0.25),
          quality: num(zone?.quality),
        });
      }
    }
    return out;
  }

  function armOrUpdate(state) {
    const now = Date.now();
    const all = candidates(state);

    if (active) {
      const current = all.find(item => sameZone(item, active));
      if (current && now < active.until) {
        active.low = current.low;
        active.high = current.high;
        active.atr = current.atr;
        active.price = current.price;
        active.inZone = current.inZone;
        active.quality = current.quality;
        active.wasInside = active.wasInside || current.inZone;
        active.extreme = active.kind === 'demand'
          ? Math.min(active.extreme, current.price)
          : Math.max(active.extreme, current.price);
        return active;
      }
      active = null;
    }

    const near = all
      .filter(item => item.distance <= item.tolerance)
      .sort((a, b) => (a.distance / a.atr) - (b.distance / b.atr))[0];
    if (!near) return null;

    active = {
      ...near,
      started: now,
      until: now + HOLD_MS,
      wasInside: near.inZone,
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
    const confirmed = actionable && specialist && (tradeSide === side || action === side || action.startsWith(side));
    const reaction = test.kind === 'demand' ? test.price - test.extreme : test.extreme - test.price;
    const reactionAtr = Math.max(0, reaction) / Math.max(test.atr, 0.01);

    if (confirmed) return {
      tone: desired,
      arrow: desiredArrow,
      title: `${desired.toUpperCase()} REJECTION CONFIRMED`,
      note: `EVE's existing live retracement strategy has confirmed the ${side}.`,
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

  function render(state) {
    const panel = document.getElementById('ltSessionOutlookPanel');
    if (!panel) return;
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
    card.innerHTML = `
      <div class="lt-zone-decision-arrow" aria-hidden="true">${decision.arrow}</div>
      <div>
        <div class="lt-zone-decision-kicker">${position} ${test.kind.toUpperCase()} · ZONE DECISION</div>
        <div class="lt-zone-decision-title">${decision.title}</div>
        <p class="lt-zone-decision-note">${decision.note}</p>
        <div class="lt-zone-decision-tfs">M5 ${tfLabel(decision.m5)} · M15 ${tfLabel(decision.m15)} · ACTIVE FOR 20 MIN AFTER TEST</div>
      </div>`;
  }

  async function tick() {
    const view = document.getElementById('view-live-trader');
    if (view && !view.classList.contains('active')) return;
    try {
      const state = await api('/live-trader');
      render(state);
    } catch (_) {}
  }

  setInterval(tick, POLL_MS);
  tick();
})();
