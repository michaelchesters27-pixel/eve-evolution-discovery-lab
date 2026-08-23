(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltHistoricalAcademy')) return;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const dateText = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB', {day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
  };

  const style = document.createElement('style');
  style.textContent = `
    .lt-academy{margin-top:14px;border-top:1px solid var(--line);padding-top:14px}
    .lt-academy-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:9px}
    .lt-academy-head b{font-size:11px;letter-spacing:.08em;color:var(--green)}
    .lt-academy-head span{font-size:9px;color:var(--muted)}
    .lt-academy-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
    .lt-academy-grid>div{border:1px solid var(--line);background:#06100b;border-radius:11px;padding:11px}
    .lt-academy-grid span,.lt-academy-grid strong{display:block}
    .lt-academy-grid span{font-size:8px;color:var(--muted)}
    .lt-academy-grid strong{font-size:17px;margin-top:4px}
    .lt-academy-note{font-size:10px;color:#a9c4b6;line-height:1.55;margin:10px 0 0}
    .lt-market-closed-banner{display:none;margin:0 0 14px;border:1px solid #725b22;background:#171307;border-radius:12px;padding:12px 14px;color:#e8d99d;font-size:11px;line-height:1.55}
    .lt-market-closed-banner.show{display:block}
    .lt-feed.market-closed{border-color:#725b22!important;color:#e8d99d!important}
    @media(max-width:760px){.lt-academy-grid{grid-template-columns:1fr 1fr}}
  `;
  document.head.appendChild(style);

  const warning = view.querySelector('.lt-manual-warning');
  const banner = document.createElement('div');
  banner.id = 'ltMarketClosedBanner';
  banner.className = 'lt-market-closed-banner';
  if (warning) warning.insertAdjacentElement('afterend', banner);

  const policy = document.getElementById('ltLearningPolicy');
  const academy = document.createElement('div');
  academy.id = 'ltHistoricalAcademy';
  academy.className = 'lt-academy';
  academy.innerHTML = `
    <div class="lt-academy-head"><b>HISTORICAL ACADEMY</b><span id="ltAcademyStatus">Starting</span></div>
    <div class="lt-academy-grid" id="ltAcademyGrid"></div>
    <p class="lt-academy-note" id="ltAcademyNote">EVE is preparing causal replay of the six-year archive.</p>
  `;
  if (policy) policy.insertAdjacentElement('beforebegin', academy);

  // Automatic market announcements are only allowed when the broker-hours payload
  // explicitly says tradable=true. Missing/unknown hours fail closed. User-requested
  // spoken replies remain allowed.
  if (window.eveLiveVoice?.say && !window.eveLiveVoice._academyWrapped) {
    const rawSay = window.eveLiveVoice.say.bind(window.eveLiveVoice);
    window.eveLiveVoice._academyWrapped = true;
    window.eveLiveVoice._academyRawSay = rawSay;
    window.eveLiveVoice.say = (text, options = {}) => {
      const key = String(options.key || '');
      const userReply = key.startsWith('reply:');
      if (window.eveLiveMarketTradable !== true && !userReply) {
        window.eveLiveVoice.stats.suppressed += 1;
        return false;
      }
      return rawSay(text, options);
    };
  }

  let timer = null;

  function marketStatus(state) {
    const hours = state?.market_hours;
    if (!hours || typeof hours.tradable !== 'boolean') return 'unknown';
    return hours.tradable === true ? 'open' : 'closed';
  }

  function renderMarket(state) {
    const status = marketStatus(state);
    const tradable = status === 'open';
    const previous = window.eveLiveMarketTradable;
    // true=open, false=closed, null=unknown. Only true permits automatic market speech.
    window.eveLiveMarketTradable = status === 'unknown' ? null : tradable;
    const feed = document.getElementById('ltFeed');
    const feedText = feed?.querySelector('b');

    if (status === 'unknown') {
      if (feed) feed.classList.add('market-closed');
      if (feedText) feedText.textContent = 'MARKET STATUS UNKNOWN';
      banner.classList.add('show');
      banner.innerHTML = '<b>MARKET STATUS UNKNOWN — CLOSED-SAFE:</b> EVE has not received an explicit broker-hours confirmation. She will not treat the market as open or make an automatic market-open announcement until tradable status is confirmed.';
      return;
    }

    if (!tradable) {
      if (feed) feed.classList.add('market-closed');
      if (feedText) feedText.textContent = 'MARKET CLOSED';
      const campaign = state?.trade_campaign;
      banner.classList.add('show');
      banner.innerHTML = campaign
        ? `<b>LIVE CAMPAIGN FROZEN:</b> ${safe(String(campaign.side || ''))} ${safe(String(campaign.order_type || '').replaceAll('_',' ').toUpperCase())} ${safe(campaign.entry ?? '')}. Closed-market quotes cannot trigger it, hit TP/SL, invalidate it or expire it. Historical Academy remains active and monitors for newly completed causal data.`
        : '<b>MARKET CLOSED:</b> Live trading and forward learning are paused. Historical Academy remains active and monitors for newly completed causal data.';
    } else {
      if (feed) feed.classList.remove('market-closed');
      banner.classList.remove('show');
      // Announce a reopen only after a previously explicit CLOSED state. Unknown -> OPEN
      // is deliberately silent so startup/deployment gaps cannot create a false reopen alert.
      if (previous === false && window.eveLiveVoice?._academyRawSay && document.getElementById('ltSpeakChanges')?.checked) {
        window.eveLiveVoice._academyRawSay(
          'Micky, the broker market is open again. Live campaign management and forward learning have resumed.',
          {key:'academy:market-open', priority:2, cooldownMs:300000}
        );
      }
    }
  }

  function renderAcademy(summary) {
    const hist = summary?.historical_learning || {};
    const rows = number(hist.rows_scanned);
    const episodes = number(hist.episodes_recorded);
    const scored = number(hist.scored_episodes);
    const challengers = number(hist.challenger_runs);
    const caughtUp = hist.caught_up === true;
    document.getElementById('ltAcademyStatus').textContent = hist.last_error
      ? 'ATTENTION'
      : caughtUp
        ? 'CAUGHT UP — MONITORING'
        : 'RUNNING 24/7';
    document.getElementById('ltAcademyGrid').innerHTML = [
      ['M5 rows scanned', rows.toLocaleString('en-GB')],
      ['Historical episodes', episodes.toLocaleString('en-GB')],
      ['Episodes scored', scored.toLocaleString('en-GB')],
      ['Challengers tested', challengers.toLocaleString('en-GB')],
    ].map(([name,value]) => `<div><span>${safe(name)}</span><strong>${safe(value)}</strong></div>`).join('');
    const note = document.getElementById('ltAcademyNote');
    if (hist.last_error) {
      note.textContent = `Historical Academy hit an error and will retry automatically: ${hist.last_error}`;
    } else if (!episodes) {
      note.textContent = 'Historical Academy is starting at the beginning of EVE’s six-year every-M5 fabric. Future data is hidden until each historical decision is made.';
    } else if (caughtUp) {
      note.textContent = `Archive replay is caught up through ${dateText(hist.cursor_time)}. EVE keeps checking for newly completed causal rows and will score them automatically. Historical evidence remains deliberately down-weighted versus genuine forward-live experience.`;
    } else {
      note.textContent = `Replay has reached ${dateText(hist.cursor_time)}. Each historical family is down-weighted versus genuine forward-live experience, while market, confirmation-stop and pullback-limit challengers are scored on the exact same causal M1 future path.`;
    }
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const [state, summary] = await Promise.all([api('/live-trader'), api('/live-trader/learning')]);
      renderMarket(state);
      renderAcademy(summary);
      window.eveLiveNewsRender?.(state, summary);
    } catch (_) {
      // A failed refresh must never leave a prior OPEN state authoritative.
      window.eveLiveMarketTradable = null;
      const feed = document.getElementById('ltFeed');
      const feedText = feed?.querySelector('b');
      if (feed) feed.classList.add('market-closed');
      if (feedText) feedText.textContent = 'MARKET STATUS UNKNOWN';
      banner.classList.add('show');
      banner.innerHTML = '<b>MARKET STATUS UNKNOWN — CLOSED-SAFE:</b> Live market status could not be refreshed. Automatic market-open announcements are suppressed until broker-hours status is confirmed.';
    }
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 5000);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (view.classList.contains('active')) start();

  function loadWeekConfirmation() {
    if (document.getElementById('ltNewsWeekScript')) return;
    const script = document.createElement('script');
    script.id = 'ltNewsWeekScript';
    script.src = 'live_trader_news_week_confirmation.js';
    document.body.appendChild(script);
  }

  // Load the weekly news UI from this already-loaded extension rather than adding
  // another permanent HTML dependency. The panel itself adds no extra polling loop.
  if (!document.getElementById('ltNewsScript')) {
    const newsScript = document.createElement('script');
    newsScript.id = 'ltNewsScript';
    newsScript.src = 'live_trader_news.js';
    newsScript.addEventListener('load', loadWeekConfirmation, {once:true});
    document.body.appendChild(newsScript);
  } else {
    loadWeekConfirmation();
  }
})();
