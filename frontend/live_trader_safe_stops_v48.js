(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltSafeBuyStop')) return;

  const statusRow = view.querySelector('.lt-status-row');
  if (!statusRow) return;

  const MAX_CONTEXT_LAG_MINUTES = 10;
  const MAX_TICK_AGE_SECONDS = 90;
  const MAX_DECISION_AGE_MINUTES = 15;
  const num = (value, fallback = 0) => {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const formatPrice = value => {
    const parsed = num(value, NaN);
    return Number.isFinite(parsed)
      ? parsed.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2})
      : '—';
  };

  const style = document.createElement('style');
  style.textContent = `
    .lt-status.lt-safe-stop,.lt-status.lt-sweep-protection{grid-column:span 2}
    .lt-safe-buy,.lt-sweep-buy{border-color:#2c6a48!important}.lt-safe-buy strong,.lt-sweep-buy strong{color:var(--green)}
    .lt-safe-sell,.lt-sweep-sell{border-color:#744343!important}.lt-safe-sell strong,.lt-sweep-sell strong{color:var(--red)}
    .lt-status.lt-safe-stop small,.lt-status.lt-sweep-protection small{display:block;margin-top:5px;color:var(--muted);font-size:8px;line-height:1.3}
    .lt-sweep-protection strong.lt-no-extra{font-size:.78rem;letter-spacing:.03em;opacity:.86}
    .lt-safe-unavailable strong{color:var(--amber)!important}
    @media(max-width:1180px){.lt-status.lt-safe-stop,.lt-status.lt-sweep-protection{grid-column:span 1}}
  `;
  document.head.appendChild(style);

  const buy = document.createElement('div');
  buy.className = 'lt-status lt-safe-stop lt-safe-buy';
  buy.innerHTML = '<span>Global buy structural ref</span><strong id="ltSafeBuyStop">—</strong><small>Overall structure · use zone-specific SL refs above</small>';

  const buySweep = document.createElement('div');
  buySweep.className = 'lt-status lt-sweep-protection lt-sweep-buy';
  buySweep.innerHTML = '<span>Global buy sweep check</span><strong id="ltBuySweepProtection">—</strong><small>Overall structure only</small>';

  const sell = document.createElement('div');
  sell.className = 'lt-status lt-safe-stop lt-safe-sell';
  sell.innerHTML = '<span>Global sell structural ref</span><strong id="ltSafeSellStop">—</strong><small>Overall structure · use zone-specific SL refs above</small>';

  const sellSweep = document.createElement('div');
  sellSweep.className = 'lt-status lt-sweep-protection lt-sweep-sell';
  sellSweep.innerHTML = '<span>Global sell sweep check</span><strong id="ltSellSweepProtection">—</strong><small>Overall structure only</small>';

  statusRow.append(buy, buySweep, sell, sellSweep);

  function contextValid(state) {
    const feed = state?.feed || {};
    const dq = state?.bias?.data_quality || {};
    const ctx = state?.live_context_freshness || {};
    const lag = num(ctx.context_lag_minutes ?? dq.live_context_lag_minutes, NaN);
    const tickMs = Date.parse(String(feed.last_tick_received_at || ctx.live_tick_at || feed.last_tick_at || ''));
    const decisionMs = Date.parse(String(ctx.effective_decision_time || ''));
    const now = Date.now();
    const tickAgeSeconds = Number.isFinite(tickMs) ? Math.max(0, (now - tickMs) / 1000) : NaN;
    const decisionAgeMinutes = Number.isFinite(decisionMs) ? Math.max(0, (now - decisionMs) / 60000) : NaN;
    const price = num(state?.price, NaN);
    const atr = num(state?.market?.atr, NaN);
    return feed.status === 'live'
      && feed.connected === true
      && ctx.context_valid === true
      && ctx.fresh === true
      && dq.live_context_stale !== true
      && dq.trade_bias_blocked !== true
      && Number.isFinite(lag)
      && lag >= 0
      && lag <= MAX_CONTEXT_LAG_MINUTES
      && Number.isFinite(tickAgeSeconds)
      && tickAgeSeconds <= MAX_TICK_AGE_SECONDS
      && Number.isFinite(decisionAgeMinutes)
      && decisionAgeMinutes <= MAX_DECISION_AGE_MINUTES
      && Number.isFinite(price)
      && price > 0
      && Number.isFinite(atr)
      && atr > 0;
  }

  const candidate = (value, label, price, side, key = '') => {
    const level = num(value, NaN);
    if (!Number.isFinite(level) || level <= 0) return null;
    if (side === 'below' && level >= price) return null;
    if (side === 'above' && level <= price) return null;
    return {level, label, key};
  };

  function structuralReference(price, atr, candidates, side) {
    const safeAtr = num(atr, NaN);
    if (!Number.isFinite(safeAtr) || safeAtr <= 0) return {level:null, sources:[], available:false, reason:'ATR DATA INVALID'};
    const clusterWidth = safeAtr * 0.75;
    const buffer = safeAtr * 0.22;
    const clean = candidates.filter(Boolean);
    if (!clean.length) return {level:null, sources:[], available:false};

    if (side === 'below') {
      const nearest = Math.max(...clean.map(item => item.level));
      const cluster = clean.filter(item => nearest - item.level <= clusterWidth);
      const anchor = Math.min(...cluster.map(item => item.level));
      return {level:anchor - buffer, sources:[...new Set(cluster.map(item => item.label))], available:true};
    }

    const nearest = Math.min(...clean.map(item => item.level));
    const cluster = clean.filter(item => item.level - nearest <= clusterWidth);
    const anchor = Math.max(...cluster.map(item => item.level));
    return {level:anchor + buffer, sources:[...new Set(cluster.map(item => item.label))], available:true};
  }

  function eligibleZone(zone) {
    const status = String(zone?.status || '').toUpperCase();
    return zone && zone.fresh !== false && !['BROKEN','INVALID','EXPIRED'].includes(status);
  }

  function safeStops(state) {
    const price = num(state?.price, NaN);
    const atr = num(state?.market?.atr, NaN);
    if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(atr) || atr <= 0) {
      return {
        buy:{level:null,sources:[],available:false,reason:'PRICE OR ATR DATA INVALID'},
        sell:{level:null,sources:[],available:false,reason:'PRICE OR ATR DATA INVALID'},
      };
    }

    const zones = state?.zones || {};
    const liquidity = state?.liquidity || {};
    const below = [];
    const above = [];

    (zones.demand || []).slice(0,4).filter(eligibleZone).forEach(zone => {
      below.push(candidate(zone?.low, 'Demand zone', price, 'below', `demand_${zone?.id || ''}`));
    });
    (zones.supply || []).slice(0,4).filter(eligibleZone).forEach(zone => {
      above.push(candidate(zone?.high, 'Supply zone', price, 'above', `supply_${zone?.id || ''}`));
    });

    [
      ['recent_low','Recent low'],
      ['previous_day_low','Previous day low'],
      ['london_low','London low'],
      ['new_york_low','New York low'],
    ].forEach(([key,label]) => below.push(candidate(liquidity[key], label, price, 'below', key)));

    [
      ['recent_high','Recent high'],
      ['previous_day_high','Previous day high'],
      ['london_high','London high'],
      ['new_york_high','New York high'],
    ].forEach(([key,label]) => above.push(candidate(liquidity[key], label, price, 'above', key)));

    return {
      buy: structuralReference(price, atr, below, 'below'),
      sell: structuralReference(price, atr, above, 'above'),
    };
  }

  function reclaimedLiquidityKeys(liquidity) {
    const reclaimed = new Set();
    (liquidity?.market_events || []).forEach(event => {
      const eventClass = String(event?.event_class || '');
      const key = String(event?.level_key || '');
      const isSweep = eventClass.includes('sweep_reclaim') || eventClass.startsWith('failed_breakout');
      if (key && isSweep && event?.reclaimed === true) reclaimed.add(key);
    });
    return reclaimed;
  }

  function sweepLiquidityCandidates(state, side) {
    const price = num(state?.price, NaN);
    const liquidity = state?.liquidity || {};
    const reclaimed = reclaimedLiquidityKeys(liquidity);
    const definitions = side === 'below'
      ? [
          ['recent_low','Recent low'],
          ['previous_day_low','Previous day low'],
          ['london_low','London low'],
          ['new_york_low','New York low'],
        ]
      : [
          ['recent_high','Recent high'],
          ['previous_day_high','Previous day high'],
          ['london_high','London high'],
          ['new_york_high','New York high'],
        ];

    return definitions
      .filter(([key]) => !reclaimed.has(key))
      .map(([key,label]) => candidate(liquidity[key], label, price, side, key))
      .filter(Boolean);
  }

  function sweepProtection(state, safeRef, side) {
    const atr = num(state?.market?.atr, NaN);
    const safeLevel = num(safeRef?.level, NaN);
    if (!Number.isFinite(atr) || atr <= 0 || !Number.isFinite(safeLevel) || safeRef?.available !== true) {
      return {available:false, needed:false, level:null, sources:[]};
    }

    const huntBand = atr * 1.25;
    const buffer = atr * 0.22;
    const candidates = sweepLiquidityCandidates(state, side).filter(item => {
      if (side === 'below') return item.level < safeLevel && safeLevel - item.level <= huntBand;
      return item.level > safeLevel && item.level - safeLevel <= huntBand;
    });

    if (!candidates.length) return {available:true, needed:false, level:safeLevel, sources:[]};

    if (side === 'below') {
      const furthest = Math.min(...candidates.map(item => item.level));
      const protectedLevel = furthest - buffer;
      if (protectedLevel >= safeLevel) return {available:true, needed:false, level:safeLevel, sources:[]};
      return {
        available:true,
        needed:true,
        level:protectedLevel,
        sources:[...new Set(candidates.filter(item => item.level >= furthest).map(item => item.label))],
      };
    }

    const furthest = Math.max(...candidates.map(item => item.level));
    const protectedLevel = furthest + buffer;
    if (protectedLevel <= safeLevel) return {available:true, needed:false, level:safeLevel, sources:[]};
    return {
      available:true,
      needed:true,
      level:protectedLevel,
      sources:[...new Set(candidates.filter(item => item.level <= furthest).map(item => item.label))],
    };
  }

  function renderProtection(element, protection) {
    if (!element) return;
    element.classList.toggle('lt-no-extra', protection.available === true && !protection.needed);
    if (protection.available !== true) element.textContent = 'UNAVAILABLE';
    else if (protection.needed) element.textContent = formatPrice(protection.level);
    else element.textContent = 'REF COVERS NEARBY SWEEPS';
  }

  function unavailable() {
    for (const root of [buy,buySweep,sell,sellSweep]) root.classList.add('lt-safe-unavailable');
    document.getElementById('ltSafeBuyStop').textContent = 'UNAVAILABLE';
    document.getElementById('ltSafeSellStop').textContent = 'UNAVAILABLE';
    document.getElementById('ltBuySweepProtection').textContent = 'UNAVAILABLE';
    document.getElementById('ltSellSweepProtection').textContent = 'UNAVAILABLE';
    buy.title = sell.title = buySweep.title = sellSweep.title = 'Live context is not currently validated and fresh.';
  }

  function render(state) {
    if (!contextValid(state)) {
      unavailable();
      return;
    }
    for (const root of [buy,buySweep,sell,sellSweep]) root.classList.remove('lt-safe-unavailable');

    const refs = safeStops(state);
    const buyProtection = sweepProtection(state, refs.buy, 'below');
    const sellProtection = sweepProtection(state, refs.sell, 'above');
    const buyValue = document.getElementById('ltSafeBuyStop');
    const sellValue = document.getElementById('ltSafeSellStop');
    const buySweepValue = document.getElementById('ltBuySweepProtection');
    const sellSweepValue = document.getElementById('ltSellSweepProtection');

    if (buyValue) buyValue.textContent = refs.buy.available ? formatPrice(refs.buy.level) : 'NO STRUCTURE';
    if (sellValue) sellValue.textContent = refs.sell.available ? formatPrice(refs.sell.level) : 'NO STRUCTURE';
    renderProtection(buySweepValue, buyProtection);
    renderProtection(sellSweepValue, sellProtection);

    buy.title = refs.buy.sources.length
      ? `Structural reference beyond: ${refs.buy.sources.join(', ')}. Informational only; the 1.25 ATR sweep band and 0.22 ATR buffer are design parameters, not proven optimal stops. Use an authoritative published trade stop if EVE issues a trade.`
      : 'No qualifying structural reference below current price.';
    sell.title = refs.sell.sources.length
      ? `Structural reference beyond: ${refs.sell.sources.join(', ')}. Informational only; use an authoritative published trade stop if EVE issues a trade.`
      : 'No qualifying structural reference above current price.';
    buySweep.title = buyProtection.needed
      ? `Additional reference buffer beyond nearby liquidity: ${buyProtection.sources.join(', ')}`
      : 'The displayed structural reference is already beyond nearby unreclaimed liquidity inside the sweep band.';
    sellSweep.title = sellProtection.needed
      ? `Additional reference buffer beyond nearby liquidity: ${sellProtection.sources.join(', ')}`
      : 'The displayed structural reference is already beyond nearby unreclaimed liquidity inside the sweep band.';
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
