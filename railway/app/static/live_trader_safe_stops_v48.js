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
    .lt-status.lt-safe-stop{grid-column:span 2}
    .lt-safe-buy{border-color:#2c6a48!important}.lt-safe-buy strong{color:var(--green)}
    .lt-safe-sell{border-color:#744343!important}.lt-safe-sell strong{color:var(--red)}
    @media(max-width:1180px){.lt-status.lt-safe-stop{grid-column:span 1}}
  `;
  document.head.appendChild(style);

  const buy = document.createElement('div');
  buy.className = 'lt-status lt-safe-stop lt-safe-buy';
  buy.innerHTML = '<span>Buy safe SL</span><strong id="ltSafeBuyStop">—</strong>';

  const sell = document.createElement('div');
  sell.className = 'lt-status lt-safe-stop lt-safe-sell';
  sell.innerHTML = '<span>Sell safe SL</span><strong id="ltSafeSellStop">—</strong>';

  statusRow.append(buy, sell);

  const candidate = (value, label, price, side) => {
    const level = num(value, NaN);
    if (!Number.isFinite(level) || level <= 0) return null;
    if (side === 'below' && level >= price) return null;
    if (side === 'above' && level <= price) return null;
    return {level, label};
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

    (zones.demand || []).slice(0,4).forEach(zone => below.push(candidate(zone?.low, 'Demand zone', price, 'below')));
    (zones.supply || []).slice(0,4).forEach(zone => above.push(candidate(zone?.high, 'Supply zone', price, 'above')));

    [
      ['recent_low','Recent low'],
      ['previous_day_low','Previous day low'],
      ['london_low','London low'],
      ['new_york_low','New York low'],
    ].forEach(([key,label]) => below.push(candidate(liquidity[key], label, price, 'below')));

    [
      ['recent_high','Recent high'],
      ['previous_day_high','Previous day high'],
      ['london_high','London high'],
      ['new_york_high','New York high'],
    ].forEach(([key,label]) => above.push(candidate(liquidity[key], label, price, 'above')));

    return {
      buy: structuralReference(price, atr, below, 'below'),
      sell: structuralReference(price, atr, above, 'above'),
    };
  }

  let timer = null;

  function render(state) {
    const refs = safeStops(state);
    const buyValue = document.getElementById('ltSafeBuyStop');
    const sellValue = document.getElementById('ltSafeSellStop');
    if (buyValue) buyValue.textContent = formatPrice(refs.buy.level);
    if (sellValue) sellValue.textContent = formatPrice(refs.sell.level);
    buy.title = refs.buy.sources.length ? `Structural reference beyond: ${refs.buy.sources.join(', ')}` : 'Informational structural stop reference';
    sell.title = refs.sell.sources.length ? `Structural reference beyond: ${refs.sell.sources.join(', ')}` : 'Informational structural stop reference';
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

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  document.getElementById('ltRefresh')?.addEventListener('click', () => setTimeout(refresh, 250));
  if (view.classList.contains('active')) start();
})();
