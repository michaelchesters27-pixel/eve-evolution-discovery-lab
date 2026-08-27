(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltSafeBuyStop')) return;

  const statusRow = view.querySelector('.lt-status-row');
  if (!statusRow) return;

  const num = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const formatPrice = value => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2})
    : '—';

  const style = document.createElement('style');
  style.textContent = `
    .lt-status.lt-safe-stop,.lt-status.lt-sweep-protection{grid-column:span 2}
    .lt-safe-buy,.lt-sweep-buy{border-color:#2c6a48!important}.lt-safe-buy strong,.lt-sweep-buy strong{color:var(--green)}
    .lt-safe-sell,.lt-sweep-sell{border-color:#744343!important}.lt-safe-sell strong,.lt-sweep-sell strong{color:var(--red)}
    .lt-sweep-protection strong.lt-no-extra{font-size:.86rem;letter-spacing:.04em;opacity:.8}
    @media(max-width:1180px){.lt-status.lt-safe-stop,.lt-status.lt-sweep-protection{grid-column:span 1}}
  `;
  document.head.appendChild(style);

  const buy = document.createElement('div');
  buy.className = 'lt-status lt-safe-stop lt-safe-buy';
  buy.innerHTML = '<span>Buy safe SL</span><strong id="ltSafeBuyStop">—</strong>';

  const buySweep = document.createElement('div');
  buySweep.className = 'lt-status lt-sweep-protection lt-sweep-buy';
  buySweep.innerHTML = '<span>Buy sweep protection</span><strong id="ltBuySweepProtection">—</strong>';

  const sell = document.createElement('div');
  sell.className = 'lt-status lt-safe-stop lt-safe-sell';
  sell.innerHTML = '<span>Sell safe SL</span><strong id="ltSafeSellStop">—</strong>';

  const sellSweep = document.createElement('div');
  sellSweep.className = 'lt-status lt-sweep-protection lt-sweep-sell';
  sellSweep.innerHTML = '<span>Sell sweep protection</span><strong id="ltSellSweepProtection">—</strong>';

  statusRow.append(buy, buySweep, sell, sellSweep);

  const candidate = (value, label, price, side, key = '') => {
    const level = num(value, NaN);
    if (!Number.isFinite(level) || level <= 0) return null;
    if (side === 'below' && level >= price) return null;
    if (side === 'above' && level <= price) return null;
    return {level, label, key};
  };

  function structuralReference(price, atr, candidates, side) {
    const safeAtr = Math.max(num(atr), 0.01);
    const clusterWidth = safeAtr * 0.75;
    const buffer = Math.max(safeAtr * 0.22, 0.01);
    const clean = candidates.filter(Boolean);
    if (!clean.length) {
      return {
        level: side === 'below' ? price - safeAtr * 1.5 : price + safeAtr * 1.5,
        sources: ['ATR fallback'],
      };
    }

    if (side === 'below') {
      const nearest = Math.max(...clean.map(item => item.level));
      const cluster = clean.filter(item => nearest - item.level <= clusterWidth);
      const anchor = Math.min(...cluster.map(item => item.level));
      return {level: anchor - buffer, sources:[...new Set(cluster.map(item => item.label))]};
    }

    const nearest = Math.min(...clean.map(item => item.level));
    const cluster = clean.filter(item => item.level - nearest <= clusterWidth);
    const anchor = Math.max(...cluster.map(item => item.level));
    return {level: anchor + buffer, sources:[...new Set(cluster.map(item => item.label))]};
  }

  function safeStops(state) {
    const price = num(state?.price, NaN);
    const atr = Math.max(num(state?.market?.atr), 0.01);
    if (!Number.isFinite(price) || price <= 0) return {buy:{level:null,sources:[]}, sell:{level:null,sources:[]}};

    const zones = state?.zones || {};
    const liquidity = state?.liquidity || {};
    const below = [];
    const above = [];

    (zones.demand || []).slice(0,4).forEach(zone => below.push(candidate(zone?.low, 'Demand zone', price, 'below', `demand_${zone?.id || ''}`)));
    (zones.supply || []).slice(0,4).forEach(zone => above.push(candidate(zone?.high, 'Supply zone', price, 'above', `supply_${zone?.id || ''}`)));

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
    const atr = Math.max(num(state?.market?.atr), 0.01);
    const safeLevel = num(safeRef?.level, NaN);
    if (!Number.isFinite(safeLevel)) return {needed:false, level:null, sources:[]};

    // Only protect against liquidity close enough to be a realistic extension of
    // the same stop-run. More distant levels remain separate market objectives.
    const huntBand = atr * 1.25;
    const buffer = Math.max(atr * 0.22, 0.01);
    const candidates = sweepLiquidityCandidates(state, side).filter(item => {
      if (side === 'below') return item.level < safeLevel && safeLevel - item.level <= huntBand;
      return item.level > safeLevel && item.level - safeLevel <= huntBand;
    });

    if (!candidates.length) return {needed:false, level:safeLevel, sources:[]};

    if (side === 'below') {
      const furthest = Math.min(...candidates.map(item => item.level));
      const protectedLevel = furthest - buffer;
      if (protectedLevel >= safeLevel) return {needed:false, level:safeLevel, sources:[]};
      return {
        needed:true,
        level:protectedLevel,
        sources:[...new Set(candidates.filter(item => item.level >= furthest).map(item => item.label))],
      };
    }

    const furthest = Math.max(...candidates.map(item => item.level));
    const protectedLevel = furthest + buffer;
    if (protectedLevel <= safeLevel) return {needed:false, level:safeLevel, sources:[]};
    return {
      needed:true,
      level:protectedLevel,
      sources:[...new Set(candidates.filter(item => item.level <= furthest).map(item => item.label))],
    };
  }

  function renderProtection(element, protection) {
    if (!element) return;
    element.classList.toggle('lt-no-extra', !protection.needed);
    element.textContent = protection.needed ? formatPrice(protection.level) : 'NO EXTRA';
  }

  function render(state) {
    const refs = safeStops(state);
    const buyProtection = sweepProtection(state, refs.buy, 'below');
    const sellProtection = sweepProtection(state, refs.sell, 'above');
    const buyValue = document.getElementById('ltSafeBuyStop');
    const sellValue = document.getElementById('ltSafeSellStop');
    const buySweepValue = document.getElementById('ltBuySweepProtection');
    const sellSweepValue = document.getElementById('ltSellSweepProtection');

    if (buyValue) buyValue.textContent = formatPrice(refs.buy.level);
    if (sellValue) sellValue.textContent = formatPrice(refs.sell.level);
    renderProtection(buySweepValue, buyProtection);
    renderProtection(sellSweepValue, sellProtection);

    buy.title = refs.buy.sources.length ? `Structural reference beyond: ${refs.buy.sources.join(', ')}` : 'Informational structural stop reference';
    sell.title = refs.sell.sources.length ? `Structural reference beyond: ${refs.sell.sources.join(', ')}` : 'Informational structural stop reference';
    buySweep.title = buyProtection.needed
      ? `Extra sweep protection beyond nearby liquidity: ${buyProtection.sources.join(', ')}`
      : 'No additional nearby liquidity target is currently sitting beyond the buy safe SL inside the sweep-protection band.';
    sellSweep.title = sellProtection.needed
      ? `Extra sweep protection beyond nearby liquidity: ${sellProtection.sources.join(', ')}`
      : 'No additional nearby liquidity target is currently sitting beyond the sell safe SL inside the sweep-protection band.';
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      render(await api('/live-trader'));
    } catch (_) {
      // Keep the last valid references on screen if a single refresh fails.
    }
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 15000);
  }

  let timer = null;
  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  document.getElementById('ltRefresh')?.addEventListener('click', () => setTimeout(refresh, 250));
  if (view.classList.contains('active')) start();
})();
