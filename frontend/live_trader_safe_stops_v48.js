(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltSafeBuyStop')) return;

  const statusRow = view.querySelector('.lt-status-row');
  if (!statusRow) return;

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

  let timer = null;

  function render(state) {
    const refs = state?.safe_stops || {};
    const buyRef = refs.buy || {};
    const sellRef = refs.sell || {};
    const buyValue = document.getElementById('ltSafeBuyStop');
    const sellValue = document.getElementById('ltSafeSellStop');
    if (buyValue) buyValue.textContent = formatPrice(buyRef.level);
    if (sellValue) sellValue.textContent = formatPrice(sellRef.level);
    buy.title = buyRef.sources?.length ? `Structural reference beyond: ${buyRef.sources.join(', ')}` : 'Informational structural stop reference';
    sell.title = sellRef.sources?.length ? `Structural reference beyond: ${sellRef.sources.join(', ')}` : 'Informational structural stop reference';
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
