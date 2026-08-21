(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltMarketEventCard')) return;

  const style = document.createElement('style');
  style.textContent = `
    .lt-event-card{border-color:#28563d!important}
    .lt-event-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}
    .lt-event-title{font-size:24px;font-weight:900;letter-spacing:.01em}
    .lt-event-title.bullish{color:var(--green)}
    .lt-event-title.bearish{color:var(--red)}
    .lt-event-title.neutral{color:var(--muted)}
    .lt-event-strength{border:1px solid var(--line);border-radius:999px;padding:6px 10px;font-size:10px;font-weight:900;white-space:nowrap}
    .lt-event-meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-top:16px}
    .lt-event-meta>div{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:11px}
    .lt-event-meta span,.lt-event-meta b{display:block}.lt-event-meta span{font-size:9px;color:var(--muted);text-transform:uppercase}
    .lt-event-meta b{font-size:12px;margin-top:5px}
    .lt-event-explain{margin:14px 0 0;color:#b8d1c4;line-height:1.6;font-size:12px}
    .lt-event-more{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}
    .lt-event-chip{border:1px solid var(--line);border-radius:999px;padding:5px 8px;font-size:9px;color:var(--muted)}
    @media(max-width:760px){.lt-event-meta{grid-template-columns:1fr 1fr}.lt-event-title{font-size:19px}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('article');
  card.className = 'lt-card lt-event-card';
  card.id = 'ltMarketEventCard';
  card.innerHTML = `
    <div class="lt-event-head">
      <div><p class="eyebrow">MARKET EVENT</p><div class="lt-event-title neutral" id="ltEventTitle">WATCHING LIQUIDITY</div></div>
      <div class="lt-event-strength" id="ltEventStrength">NO EVENT</div>
    </div>
    <div class="lt-event-meta" id="ltEventMeta"></div>
    <p class="lt-event-explain" id="ltEventExplain">EVE is watching for a sweep, reclaim, failed breakout or clean accepted break.</p>
    <div class="lt-event-more" id="ltEventMore"></div>
  `;
  const tradeCard = view.querySelector('.lt-trade-card');
  if (tradeCard) tradeCard.insertAdjacentElement('afterend', card);
  else view.querySelector('.live-trader-shell')?.prepend(card);

  const fmt = value => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2})
    : '—';
  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const human = value => String(value || '—').replaceAll('_',' ').replace(/\b\w/g, ch => ch.toUpperCase());

  let lastEventSignature = null;
  let lastTradeSignature = null;
  let timer = null;

  function eventSpeech(event) {
    const level = fmt(event.level);
    const label = event.level_label || 'the liquidity level';
    const cls = String(event.event_class || '');
    if (cls === 'sell_side_sweep_reclaim') return `Micky, sell-side liquidity has been swept below ${label} around ${level} and reclaimed. I read that as a possible bullish fake-out.`;
    if (cls === 'buy_side_sweep_reclaim') return `Micky, buy-side liquidity has been swept above ${label} around ${level} and reclaimed. I read that as a possible bearish fake-out.`;
    if (cls === 'failed_breakout_up') return `Micky, the break above ${label} around ${level} has failed. I currently read that as a bearish fake-out.`;
    if (cls === 'failed_breakout_down') return `Micky, the break below ${label} around ${level} has failed and reclaimed. I currently read that as a bullish fake-out.`;
    if (cls === 'accepted_breakout_up') return `Micky, the break above ${label} around ${level} is holding. I am not treating it as a fake-out right now.`;
    if (cls === 'accepted_breakout_down') return `Micky, the break below ${label} around ${level} is holding. I am not treating it as a fake-out right now.`;
    return '';
  }

  function speakEvent(text) {
    if (!text || !document.getElementById('ltSpeakChanges')?.checked || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-GB';
    utterance.rate = 1.02;
    window.speechSynthesis.speak(utterance);
  }

  function appendEventMessage(text) {
    const box = document.getElementById('ltConversation');
    if (!box || !text) return;
    const item = document.createElement('div');
    item.className = 'lt-msg assistant';
    item.innerHTML = `${safe(text)}<small>Live liquidity event</small>`;
    box.appendChild(item);
    box.scrollTop = box.scrollHeight;
  }

  function render(state) {
    const liquidity = state?.liquidity || {};
    const event = liquidity.primary_event || {};
    const cls = String(event.event_class || 'none');
    const active = cls !== 'none';
    const implication = String(event.implication || 'neutral');
    const title = document.getElementById('ltEventTitle');
    const strength = document.getElementById('ltEventStrength');
    const meta = document.getElementById('ltEventMeta');
    const explain = document.getElementById('ltEventExplain');
    const more = document.getElementById('ltEventMore');

    title.textContent = active ? (event.label || human(cls)).toUpperCase() : 'NO ACTIVE SWEEP / FAKE-OUT';
    title.className = `lt-event-title ${active ? implication : 'neutral'}`;
    strength.textContent = active ? `STRENGTH ${Number(event.strength || 0)}/100` : 'WATCHING';
    meta.innerHTML = [
      ['Level', active ? event.level_label || 'Liquidity' : '—'],
      ['Price', active ? fmt(event.level) : '—'],
      ['Implication', active ? human(implication) : 'Neutral'],
      ['Status', active ? human(event.confirmation) : 'Waiting']
    ].map(([name,value]) => `<div><span>${safe(name)}</span><b>${safe(value)}</b></div>`).join('');
    explain.textContent = active
      ? (event.explanation || eventSpeech(event) || 'EVE has identified an active liquidity event.')
      : 'EVE is watching prior-day, London, New York, M15/H1 and prior M5 swing levels for sweeps, reclaims and failed breaks.';
    more.innerHTML = (liquidity.market_events || []).slice(1,4)
      .map(item => `<span class="lt-event-chip">${safe(item.label || human(item.event_class))} · ${safe(item.level_label || '')}</span>`).join('');

    const eventSig = active ? `${cls}|${event.level_key || event.level}|${event.confirmation || ''}` : 'none';
    const tradeSig = `${state?.setup?.status || ''}|${state?.trade?.action || ''}`;
    if (
      lastEventSignature &&
      eventSig !== lastEventSignature &&
      active &&
      tradeSig === lastTradeSignature &&
      view.classList.contains('active')
    ) {
      const message = eventSpeech(event);
      speakEvent(message);
      appendEventMessage(message);
    }
    lastEventSignature = eventSig;
    lastTradeSignature = tradeSig;
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const state = await api('/live-trader');
      render(state);
    } catch (_) {}
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 2500);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (view.classList.contains('active')) start();
})();
