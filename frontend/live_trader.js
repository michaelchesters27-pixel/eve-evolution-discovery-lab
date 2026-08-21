(() => {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = 'live_trader.css';
  document.head.appendChild(css);

  const nav = document.querySelector('#nav');
  const main = document.querySelector('main');
  if (!nav || !main || document.querySelector('[data-view="live-trader"]')) return;

  const navButton = document.createElement('button');
  navButton.className = 'nav-item';
  navButton.dataset.view = 'live-trader';
  navButton.innerHTML = '<span>07</span><b>Live Trader</b><small>Real-time market assistant</small>';
  nav.appendChild(navButton);

  const view = document.createElement('section');
  view.className = 'view';
  view.id = 'view-live-trader';
  view.innerHTML = `
    <div class="section-intro">
      <div><p class="eyebrow">EVE LIVE TRADER</p><h2>Real-time market intelligence for Micky</h2><p>EVE watches the live Twelve Data price feed against the audited every-M5 fabric, keeps a multi-timeframe opinion, ranks supply and demand, and tells you how she would execute. Every opinion is recorded and measured.</p></div>
      <button class="lt-refresh" id="ltRefresh">Refresh now</button>
    </div>
    <div class="lt-manual-warning"><b>MANUAL / PAPER MODE:</b> EVE can recommend market, stop or limit execution, but this module has no broker write access and cannot place orders.</div>
    <div class="live-trader-shell">
      <div class="lt-hero">
        <article class="lt-card">
          <div class="lt-live-head"><div><p class="eyebrow">LIVE MARKET</p><h2 id="ltSymbol">XAU/USD</h2><p id="ltAsOf">Waiting for live feed</p></div><div class="lt-feed" id="ltFeed"><span class="dot"></span><b>CONNECTING</b></div></div>
          <div class="lt-price" id="ltPrice">—</div>
          <div class="lt-market-line" id="ltMarketLine"></div>
          <div class="lt-opinion" id="ltOpinion">Micky, I am loading the live market picture.</div>
        </article>
        <article class="lt-card">
          <p class="eyebrow">EVE'S VIEW</p>
          <div class="lt-bias-word neutral" id="ltBias">NEUTRAL</div>
          <div class="lt-confidence" id="ltConfidence">Confidence —</div>
          <div class="lt-status-row" style="margin-top:18px">
            <div class="lt-status"><span>Setup</span><strong id="ltSetup">WATCHING</strong></div>
            <div class="lt-status"><span>Session</span><strong id="ltSession">—</strong></div>
            <div class="lt-status"><span>Regime</span><strong id="ltRegime">—</strong></div>
            <div class="lt-status"><span>Price magnet</span><strong id="ltMagnet">—</strong></div>
          </div>
        </article>
      </div>

      <div class="lt-grid">
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">BEST DEMAND</p><h3>Zones EVE would consider buying</h3></div></div><div class="lt-zones" id="ltDemand"></div></article>
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">BEST SUPPLY</p><h3>Zones EVE would consider selling</h3></div></div><div class="lt-zones" id="ltSupply"></div></article>
      </div>

      <article class="lt-card lt-trade-card">
        <div class="lt-trade-action"><div><p class="eyebrow">WHAT TRADE WOULD EVE TAKE?</p><strong id="ltTradeAction" class="wait">NO TRADE</strong></div><span class="badge" id="ltTradeConfidence">WAITING</span></div>
        <div class="lt-order-grid" id="ltOrderGrid"></div>
        <p class="lt-reason" id="ltTradeReason">EVE is waiting for a clean execution.</p>
        <p class="lt-invalidation" id="ltInvalidation"></p>
      </article>

      <div class="lt-grid">
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">MULTI-TIMEFRAME BIAS</p><h3>What each timeframe is saying</h3></div></div><div class="lt-timeframes" id="ltTimeframes"></div></article>
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">LIQUIDITY & LEVELS</p><h3>Levels that can attract or reject price</h3></div></div><div class="lt-levels" id="ltLevels"></div></article>
      </div>

      <div class="lt-grid">
        <article class="lt-card lt-chat">
          <div class="panel-head"><div><p class="eyebrow">TALK TO EVE</p><h3>Your live trading conversation</h3></div></div>
          <div class="lt-conversation" id="ltConversation"><div class="lt-msg assistant">Micky, I am here. Ask me what I think, where the best supply or demand is, or what trade I would take.</div></div>
          <form class="lt-compose" id="ltForm"><button class="lt-mic" type="button" id="ltMic" title="Talk to EVE">🎙</button><input id="ltQuestion" autocomplete="off" placeholder="EVE, what are we doing on gold?"/><button class="lt-send" type="submit">Send</button></form>
          <div class="lt-talk-options"><label><input type="checkbox" id="ltSpeakReplies" checked> Speak replies</label><label><input type="checkbox" id="ltSpeakChanges" checked> Speak important market changes</label></div>
        </article>
        <article class="lt-card">
          <div class="panel-head"><div><p class="eyebrow">GETTING SMARTER</p><h3>Measured live opinion learning</h3></div></div>
          <div class="lt-learning" id="ltLearning"></div>
          <p class="muted" id="ltLearningPolicy" style="font-size:11px;margin-top:14px">EVE records what she believed, why she believed it and what price did next. Confidence can calibrate from repeated evidence; core research rules do not rewrite themselves after a few trades.</p>
          <div class="lt-manual-warning" style="margin-top:18px">The Live Trader is an analyst and decision-support tool. A trade idea is not a promise of profit. Micky remains the final decision maker.</div>
        </article>
      </div>
    </div>`;
  main.appendChild(view);

  let pollTimer = null;
  let learningTimer = null;
  let lastState = null;
  let lastImportantSignature = null;
  let recognition = null;

  const byId = id => document.getElementById(id);
  const formatPrice = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
  const label = value => String(value || '—').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
  const timeText = value => value ? new Date(value).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';

  function speak(text) {
    if (!text || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-GB';
    utterance.rate = 1.02;
    window.speechSynthesis.speak(utterance);
  }

  function zoneHtml(zone, kind) {
    const statusClass = String(zone.status || '').toLowerCase().replaceAll(' ','-');
    return `<div class="lt-zone ${esc(kind)} ${esc(statusClass)}"><div><strong>${esc(formatPrice(zone.low))} – ${esc(formatPrice(zone.high))}</strong><small>${esc(zone.status || 'ACTIVE')} · ${esc(zone.fresh ? 'Fresh' : `${zone.retests || 0} retests`)} · departure ${esc(zone.departure_atr || '—')} ATR · ${esc(zone.distance_atr || '—')} ATR away</small></div><span class="quality">${esc(zone.quality_label || 'MEDIUM')} ${esc(zone.quality || '—')}</span></div>`;
  }

  function renderZones(kind, zones) {
    const target = byId(kind === 'demand' ? 'ltDemand' : 'ltSupply');
    target.innerHTML = zones?.length ? zones.slice(0,3).map(z => zoneHtml(z, kind)).join('') : `<div class="lt-empty">No ${esc(kind)} zone is clean and relevant enough right now.</div>`;
  }

  function renderTrade(trade = {}) {
    const action = trade.action || 'NO TRADE';
    const ready = !['NO TRADE','WAIT'].includes(action);
    const actionEl = byId('ltTradeAction');
    actionEl.textContent = action;
    actionEl.className = ready ? 'ready' : 'wait';
    byId('ltTradeConfidence').textContent = trade.confidence ? `${trade.confidence}/100` : ready ? 'IDEA' : 'WAITING';
    const rows = [
      ['Order type', trade.order_type ? label(trade.order_type) : 'None'],
      ['Entry', formatPrice(trade.entry)],
      ['Stop', formatPrice(trade.stop)],
      ['Target', formatPrice(trade.target)],
    ];
    byId('ltOrderGrid').innerHTML = rows.map(([name,value]) => `<div><span>${esc(name)}</span><b>${esc(value)}</b></div>`).join('');
    if (trade.risk_reward) byId('ltOrderGrid').innerHTML += `<div><span>Risk / reward</span><b>${esc(Number(trade.risk_reward).toFixed(1))}R</b></div>`;
    byId('ltTradeReason').textContent = trade.reason || 'EVE is waiting for a clean execution.';
    byId('ltInvalidation').textContent = trade.invalidation || '';
  }

  function importantSignature(state) {
    return [state?.bias?.overall,state?.setup?.status,state?.trade?.action,state?.zones?.demand?.[0]?.id,state?.zones?.supply?.[0]?.id].join('|');
  }

  function renderState(state, allowSpeak = true) {
    lastState = state;
    const feed = state.feed || {};
    byId('ltSymbol').textContent = state.symbol || 'XAU/USD';
    byId('ltPrice').textContent = formatPrice(state.price);
    byId('ltAsOf').textContent = `${feed.connected ? 'Live tick' : 'Latest EVE market state'} · ${timeText(state.as_of)}`;
    const feedEl = byId('ltFeed');
    feedEl.className = `lt-feed ${feed.connected ? 'live' : ''}`;
    const feedStatus = String(feed.status || '').toLowerCase();
    feedEl.querySelector('b').textContent = feed.connected ? 'LIVE' : feedStatus === 'stale' ? 'STALE — RECONNECTING' : feed.api_key_configured ? 'RECONNECTING' : 'API KEY NEEDED';
    const bias = state.bias || {};
    const biasEl = byId('ltBias');
    biasEl.textContent = String(bias.overall || 'neutral').toUpperCase();
    biasEl.className = `lt-bias-word ${bias.overall || 'neutral'}`;
    byId('ltConfidence').textContent = `Confidence ${bias.confidence ?? '—'}/100`;
    byId('ltOpinion').textContent = state.opinion || 'Micky, I am watching.';
    const market = state.market || {};
    byId('ltSession').textContent = label(market.session);
    byId('ltRegime').textContent = label(market.regime);
    byId('ltMagnet').textContent = formatPrice(market.magnet);
    byId('ltSetup').textContent = state.setup?.status || 'WATCHING';
    byId('ltMarketLine').innerHTML = [
      `ATR ${formatPrice(market.atr)}`,
      `12-bar ${Number(market.return_12_pct || 0).toFixed(3)}%`,
      `48-bar ${Number(market.return_48_pct || 0).toFixed(3)}%`,
      `Fabric ${timeText(market.fabric_time)}`
    ].map(x=>`<span>${esc(x)}</span>`).join('');
    renderZones('demand', state.zones?.demand || []);
    renderZones('supply', state.zones?.supply || []);
    renderTrade(state.trade || {});
    const order = ['D1','H4','H1','M30','M15','M5','M1'];
    byId('ltTimeframes').innerHTML = order.map(tf => {
      const item = bias.timeframes?.[tf] || {};
      const dir = item.direction || 'neutral';
      return `<div class="lt-tf"><span>${esc(tf)}</span><b class="${esc(dir)}">${esc(dir)}</b></div>`;
    }).join('');
    const levelNames = {
      previous_day_high:'Previous day high',previous_day_low:'Previous day low',london_high:'London high',london_low:'London low',
      new_york_high:'New York high',new_york_low:'New York low',recent_high:'Recent swing high',recent_low:'Recent swing low'
    };
    byId('ltLevels').innerHTML = Object.entries(levelNames).map(([key,name]) => `<div class="lt-level"><span>${esc(name)}</span><b>${esc(formatPrice(state.liquidity?.[key]))}</b></div>`).join('');
    const learning = state.learning || {};
    byId('ltLearning').innerHTML = [
      ['Matching samples', learning.samples ?? 0],
      ['Setup accuracy', learning.accuracy == null ? 'Learning' : `${Math.round(learning.accuracy*100)}%`],
      ['Confidence calibration', `${Number(learning.confidence_adjustment || 0) >= 0 ? '+' : ''}${Number(learning.confidence_adjustment || 0).toFixed(1)}`]
    ].map(([name,value])=>`<div><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`).join('');

    const sig = importantSignature(state);
    if (allowSpeak && lastImportantSignature && sig !== lastImportantSignature && byId('ltSpeakChanges')?.checked && view.classList.contains('active')) {
      speak(state.opinion);
      appendMessage('assistant', state.opinion, true);
    }
    lastImportantSignature = sig;
  }

  function appendMessage(role, message, transient = false) {
    const box = byId('ltConversation');
    const item = document.createElement('div');
    item.className = `lt-msg ${role}`;
    item.innerHTML = `${esc(message)}${transient ? '<small>Live market update</small>' : ''}`;
    box.appendChild(item);
    box.scrollTop = box.scrollHeight;
  }

  async function loadConversation() {
    try {
      const payload = await api('/live-trader/conversation?limit=30');
      const items = payload.items || [];
      if (!items.length) return;
      const box = byId('ltConversation');
      box.innerHTML = '';
      items.forEach(item => appendMessage(item.role === 'user' ? 'user' : 'assistant', item.message));
    } catch (_) {}
  }

  async function refreshLiveTrader(allowSpeak = true) {
    if (!view.classList.contains('active') && allowSpeak) return;
    try {
      const state = await api('/live-trader');
      renderState(state, allowSpeak);
    } catch (error) {
      byId('ltFeed').querySelector('b').textContent = 'OFFLINE';
      byId('ltOpinion').textContent = `Micky, I cannot read the Live Trader service right now: ${error.message}`;
    }
  }

  async function refreshLearning() {
    try {
      const learning = await api('/live-trader/learning');
      if (learning.resolved > 0) {
        byId('ltLearningPolicy').textContent = `${learning.resolved} live opinions resolved at a ${learning.horizon_minutes}-minute horizon; ${Math.round((learning.accuracy || 0)*100)}% directional accuracy so far. ${learning.policy}`;
      }
    } catch (_) {}
  }

  async function sendQuestion(question) {
    const text = String(question || '').trim();
    if (!text) return;
    appendMessage('user', text);
    byId('ltQuestion').value = '';
    try {
      const payload = await api('/live-trader/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
      appendMessage('assistant', payload.reply);
      if (payload.state) renderState(payload.state, false);
      if (byId('ltSpeakReplies').checked) speak(payload.reply);
    } catch (error) {
      appendMessage('assistant', `Micky, I could not answer that because the Live Trader service returned: ${error.message}`);
    }
  }

  function startPolling() {
    clearInterval(pollTimer);clearInterval(learningTimer);
    refreshLiveTrader(false);refreshLearning();loadConversation();
    pollTimer = setInterval(()=>refreshLiveTrader(true),2500);
    learningTimer = setInterval(refreshLearning,30000);
  }

  navButton.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x===navButton));
    document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x===view));
    const title = byId('pageTitle'); if (title) title.textContent = 'Live Trader';
    startPolling();
  });
  byId('ltRefresh').addEventListener('click',()=>refreshLiveTrader(false));
  byId('ltForm').addEventListener('submit',event=>{event.preventDefault();sendQuestion(byId('ltQuestion').value);});

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'en-GB';recognition.interimResults = false;recognition.continuous = false;
    recognition.onstart = ()=>byId('ltMic').classList.add('listening');
    recognition.onend = ()=>byId('ltMic').classList.remove('listening');
    recognition.onerror = ()=>byId('ltMic').classList.remove('listening');
    recognition.onresult = event => {
      const text = event.results?.[0]?.[0]?.transcript || '';
      byId('ltQuestion').value = text;
      sendQuestion(text);
    };
    byId('ltMic').addEventListener('click',()=>{try{recognition.start();}catch{}});
  } else {
    byId('ltMic').title = 'Speech recognition is not supported by this browser';
    byId('ltMic').disabled = true;
  }
})();
