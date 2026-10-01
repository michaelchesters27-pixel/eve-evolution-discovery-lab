(() => {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = 'live_trader.css?v=99';
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
          <p class="eyebrow">EVE'S VIEW · TRADE BIAS</p>
          <div class="lt-bias-word neutral" id="ltBias">NEUTRAL</div>
          <div class="lt-confidence" id="ltConfidence">Bias confidence —</div>
          <div class="lt-status-row" style="margin-top:18px">
            <div class="lt-status"><span>Trade action</span><strong id="ltSetup">WAIT</strong><small id="ltSetupGate" style="display:block;margin-top:4px;color:var(--muted);font-size:8px">Setup gate: WATCHING</small></div>
            <div class="lt-status"><span>Market session</span><strong id="ltSession">—</strong></div>
            <div class="lt-status"><span>Regime</span><strong id="ltRegime">—</strong></div>
            <div class="lt-status"><span>Bias-side magnet</span><strong id="ltMagnet">—</strong><small style="display:block;margin-top:4px;color:var(--muted);font-size:8px">Nearest level in current bias direction</small></div>
          </div>
        </article>
      </div>

      <div class="lt-grid">
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">TRADE-FACING DEMAND</p><h3>Internal execution candidates · not the chart map</h3></div></div><div class="lt-zones" id="ltDemand"></div></article>
        <article class="lt-card"><div class="panel-head"><div><p class="eyebrow">TRADE-FACING SUPPLY</p><h3>Internal execution candidates · not the chart map</h3></div></div><div class="lt-zones" id="ltSupply"></div></article>
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
  let staleWatchdogTimer = null;
  let lastState = null;
  let recognition = null;

  const byId = id => document.getElementById(id);
  const MAX_CONTEXT_LAG_MINUTES = 10;
  const MAX_TICK_AGE_SECONDS = 90;
  const MAX_DECISION_AGE_MINUTES = 15;
  const strictNumber = value => {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const formatPrice = value => {
    const parsed = strictNumber(value);
    return parsed == null ? '—' : parsed.toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
  };
  const formatPct = value => {
    const parsed = strictNumber(value);
    return parsed == null ? '—' : `${parsed.toFixed(3)}%`;
  };
  const formatZoneEdge = value => {
    const parsed = strictNumber(value);
    return parsed == null ? '—' : parsed.toLocaleString('en-GB',{minimumFractionDigits:3,maximumFractionDigits:3});
  };
  const label = value => String(value || '—').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
  const timeText = value => {
    const ms = Date.parse(String(value || ''));
    return Number.isFinite(ms) ? new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
  };
  const number = (value, fallback = 0) => {
    const parsed = strictNumber(value);
    return parsed == null ? fallback : parsed;
  };
  const actionable = action => !['NO TRADE','WAIT',''].includes(String(action || '').toUpperCase());

  function contextHealth(state) {
    const feed = state?.feed || {};
    const ctx = state?.live_context_freshness || {};
    const dq = state?.bias?.data_quality || {};
    const lag = strictNumber(ctx.context_lag_minutes ?? dq.live_context_lag_minutes);
    const tickText = String(feed.last_tick_received_at || feed.last_tick_received_at || ctx.live_tick_at || feed.last_tick_at || '');
    const decisionText = String(ctx.effective_decision_time || '');
    const tickMs = Date.parse(tickText);
    const decisionMs = Date.parse(decisionText);
    const now = Date.now();
    const tickAgeSeconds = Number.isFinite(tickMs) ? Math.max(0, (now - tickMs) / 1000) : null;
    const decisionAgeMinutes = Number.isFinite(decisionMs) ? Math.max(0, (now - decisionMs) / 60000) : null;
    const price = strictNumber(state?.price);
    const atr = strictNumber(state?.market?.atr);

    let reason = '';
    if (feed.status !== 'live' || feed.connected !== true) reason = 'live feed unavailable';
    else if (ctx.context_valid !== true || ctx.fresh !== true) reason = 'live context is not validated and fresh';
    else if (dq.live_context_stale === true || dq.trade_bias_blocked === true) reason = 'data quality has blocked live trading context';
    else if (lag == null || lag < 0 || lag > MAX_CONTEXT_LAG_MINUTES) reason = 'context lag is unavailable or outside the accepted range';
    else if (tickAgeSeconds == null || tickAgeSeconds > MAX_TICK_AGE_SECONDS) reason = 'live tick is too old or unavailable';
    else if (decisionAgeMinutes == null || decisionAgeMinutes > MAX_DECISION_AGE_MINUTES) reason = 'decision snapshot is too old or unavailable';
    else if (price == null || price <= 0) reason = 'live price is unavailable';
    else if (atr == null || atr <= 0) reason = 'ATR is unavailable';

    return {valid:!reason, reason, lag, tickAgeSeconds, decisionAgeMinutes};
  }

  function failClosedState(source, reason) {
    const state = source && typeof source === 'object' ? source : {};
    const message = `DATA NOT VALID — ${reason || 'live service unavailable'}`;
    return {
      symbol: state.symbol || 'XAU/USD',
      as_of: new Date().toISOString(),
      price: null,
      opinion: `EVE cannot provide a live trading view: ${reason || 'live service unavailable'}.`,
      feed: {...(state.feed || {}), status:'offline', connected:false, tradable:false},
      bias: {
        ...(state.bias || {}),
        overall:'neutral',
        confidence:null,
        data_quality:{
          ...((state.bias || {}).data_quality || {}),
          live_context_stale:true,
          live_context_valid:false,
          trade_bias_blocked:true,
        },
      },
      market:{
        ...(state.market || {}),
        atr:null,
        magnet:null,
        return_12_pct:null,
        return_48_pct:null,
        fabric_time:null,
      },
      trade:{action:'WAIT', order_type:'none', side:null, reason:message, manual_only:true, automatic_order_placement:false},
      setup:{status:'WAIT', reason:message},
      zones:{demand:[], supply:[]},
      chart_zones:{demand:[], supply:[]},
      liquidity:{},
      session_outlook:{},
      live_context_freshness:{
        ...((state.live_context_freshness) || {}),
        fresh:false,
        context_valid:false,
        validation_error:reason || 'live service unavailable',
        context_lag_minutes:null,
      },
      __display_fail_closed:true,
    };
  }

  function buildVoiceGovernor() {
    if (window.eveLiveVoice) return window.eveLiveVoice;
    const supported = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
    const recentKeys = new Map();
    const recentTexts = [];
    const stats = {spoken:0,suppressed:0,interrupted:0};
    let current = null;

    const normalise = text => String(text || '')
      .toLowerCase()
      .replace(/\d+(?:[.,]\d+)?/g, '#')
      .replace(/[^a-z# ]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    const similarity = (a, b) => {
      const left = new Set(normalise(a).split(' ').filter(Boolean));
      const right = new Set(normalise(b).split(' ').filter(Boolean));
      if (!left.size || !right.size) return 0;
      let overlap = 0;
      left.forEach(token => { if (right.has(token)) overlap += 1; });
      return overlap / Math.max(left.size, right.size);
    };

    function say(text, options = {}) {
      const message = String(text || '').trim();
      if (!message || !supported) return false;
      const now = Date.now();
      const key = String(options.key || '');
      const priority = Number(options.priority || 1);
      const cooldownMs = Math.max(0, Number(options.cooldownMs ?? 45000));
      const interrupt = Boolean(options.interrupt);

      if (key && recentKeys.has(key) && now - recentKeys.get(key) < cooldownMs) {
        stats.suppressed += 1;
        return false;
      }

      while (recentTexts.length && now - recentTexts[0].at > 25000) recentTexts.shift();
      if (recentTexts.some(item => similarity(message, item.text) >= 0.82)) {
        stats.suppressed += 1;
        return false;
      }

      if (current) {
        if (interrupt || priority >= 3) {
          window.speechSynthesis.cancel();
          current = null;
          stats.interrupted += 1;
        } else {
          stats.suppressed += 1;
          return false;
        }
      }

      const utterance = new SpeechSynthesisUtterance(message);
      utterance.lang = 'en-GB';
      utterance.rate = 1.02;
      const token = `${now}-${Math.random()}`;
      current = {token, priority, text:message};
      const clear = () => { if (current?.token === token) current = null; };
      utterance.onend = clear;
      utterance.onerror = clear;
      window.speechSynthesis.speak(utterance);
      if (key) recentKeys.set(key, now);
      recentTexts.push({text:message, at:now});
      stats.spoken += 1;
      return true;
    }

    window.eveLiveVoice = {
      version:'eve-live-voice-governor-v1',
      say,
      stats,
      stop:() => { if (supported) window.speechSynthesis.cancel(); current = null; },
    };
    return window.eveLiveVoice;
  }

  const voice = buildVoiceGovernor();
  const speak = (text, options = {}) => voice.say(text, options);

  function validTradeZoneForDisplay(zone, kind) {
    const id = String(zone?.id || '').trim();
    const zoneKind = String(zone?.kind || '').toLowerCase();
    const low = strictNumber(zone?.low);
    const high = strictNumber(zone?.high);
    const quality = strictNumber(zone?.quality);
    const retests = strictNumber(zone?.retests);
    const status = String(zone?.status || '').toUpperCase();
    return id.length > 0
      && zoneKind === kind
      && low != null && high != null && low > 0 && high > 0 && high >= low
      && quality != null && quality >= 1 && quality <= 99
      && retests != null && Number.isInteger(retests) && retests >= 0
      && !['BROKEN','INVALID','EXPIRED'].includes(status);
  }

  function zoneHtml(zone, kind) {
    const statusClass = String(zone.status || '').toLowerCase().replaceAll(' ','-');
    const retests = strictNumber(zone.retests);
    const touchText = retests === 0 ? 'FRESH · 0 TOUCH BARS' : `${retests} TOUCH BAR${retests === 1 ? '' : 'S'}`;
    const quality = strictNumber(zone.quality);
    return `<div class="lt-zone ${esc(kind)} ${esc(statusClass)}"><div><strong>${esc(formatZoneEdge(zone.low))} – ${esc(formatZoneEdge(zone.high))}</strong><small>${esc(zone.status || 'ACTIVE')} · ${esc(touchText)} · departure ${esc(zone.departure_atr ?? '—')} ATR · ${esc(zone.distance_atr ?? '—')} ATR away</small></div><span class="quality" title="Heuristic quality score; not a win probability">Q ${esc(quality == null ? '—' : Math.round(quality))}/100</span></div>`;
  }

  function renderZones(kind, zones) {
    const target = byId(kind === 'demand' ? 'ltDemand' : 'ltSupply');
    const valid = Array.isArray(zones) ? zones.filter(zone => validTradeZoneForDisplay(zone, kind)) : [];
    target.innerHTML = valid.length
      ? valid.slice(0,3).map(z => zoneHtml(z, kind)).join('')
      : `<div class="lt-empty">No validated trade-facing ${esc(kind)} zone is available right now.</div>`;
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

  function feedFresh(state) {
    const feed = state?.feed || {};
    return Boolean(feed.connected) && String(feed.status || 'live').toLowerCase() !== 'stale';
  }

  function zoneRelation(state, kind) {
    const zone = state?.zones?.[kind]?.[0];
    const price = number(state?.price, NaN);
    if (!zone || !Number.isFinite(price)) return {relation:'none',zone:null};
    const low = number(zone.low, NaN);
    const high = number(zone.high, NaN);
    if (Number.isFinite(low) && Number.isFinite(high) && low <= price && price <= high) return {relation:'in',zone};
    const distance = number(zone.distance_atr, 99);
    return {relation:distance <= 0.5 ? 'near' : 'far',zone};
  }

  function geometryChanged(previous, current, atr) {
    if (!actionable(previous?.action) || !actionable(current?.action)) return false;
    if (String(previous.action) !== String(current.action)) return true;
    const threshold = Math.max(number(atr, 0) * 0.25, 0.5);
    return ['entry','stop','target'].some(key => {
      const a = number(previous?.[key], NaN);
      const b = number(current?.[key], NaN);
      return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) >= threshold;
    });
  }

  function marketChangeAnnouncement(previous, current) {
    if (!previous || !current) return null;
    const beforeFresh = feedFresh(previous);
    const nowFresh = feedFresh(current);
    if (beforeFresh && !nowFresh) {
      return {
        text:"Micky, EVE's live price feed has gone stale or disconnected. Do not act on a new trade until I tell you the feed is live again.",
        key:'feed:stale', priority:3, cooldownMs:60000,
      };
    }
    if (!beforeFresh && nowFresh) {
      return {text:"Micky, the live price feed is back and current.", key:'feed:restored', priority:2, cooldownMs:60000};
    }

    const oldTrade = previous.trade || {};
    const newTrade = current.trade || {};
    const oldAction = String(oldTrade.action || 'NO TRADE').toUpperCase();
    const newAction = String(newTrade.action || 'NO TRADE').toUpperCase();
    if (actionable(oldAction) && !actionable(newAction)) {
      return {
        text:`Micky, cancel the previous ${oldAction} idea. EVE is now ${newAction}. ${newTrade.reason || current.setup?.reason || ''}`.trim(),
        key:`trade:cancel:${oldAction}->${newAction}`, priority:3, cooldownMs:45000,
      };
    }
    if (actionable(newAction) && (oldAction !== newAction || geometryChanged(oldTrade, newTrade, current.market?.atr))) {
      return {
        text:`Micky, EVE's trade is now ${newAction}. Entry ${formatPrice(newTrade.entry)}, stop ${formatPrice(newTrade.stop)}, target ${formatPrice(newTrade.target)}.${newTrade.risk_reward ? ` About ${Number(newTrade.risk_reward).toFixed(1)} R.` : ''}`,
        key:`trade:${newAction}:${Math.round(number(newTrade.entry))}:${Math.round(number(newTrade.stop))}:${Math.round(number(newTrade.target))}`,
        priority:3, cooldownMs:45000,
      };
    }

    const oldBias = String(previous.bias?.overall || 'neutral').toLowerCase();
    const newBias = String(current.bias?.overall || 'neutral').toLowerCase();
    if (oldBias !== newBias) {
      return {
        text:`Micky, my overall bias has changed from ${oldBias} to ${newBias}. Confidence is ${current.bias?.confidence ?? 'unknown'} out of 100. ${current.setup?.reason || ''}`.trim(),
        key:`bias:${oldBias}->${newBias}`, priority:2, cooldownMs:90000,
      };
    }

    for (const kind of ['demand','supply']) {
      const before = zoneRelation(previous, kind);
      const now = zoneRelation(current, kind);
      if (before.relation !== 'in' && now.relation === 'in' && now.zone) {
        return {
          text:`Micky, price has entered EVE's best ${kind} zone from ${formatPrice(now.zone.low)} to ${formatPrice(now.zone.high)}. I am watching for confirmation before treating it as a trade.`,
          key:`zone:${kind}:in:${Math.round(number(now.zone.low))}:${Math.round(number(now.zone.high))}`,
          priority:2, cooldownMs:180000,
        };
      }
    }

    return null;
  }

  function renderState(state, allowSpeak = true) {
    const health = contextHealth(state);
    const displayState = health.valid || state?.__display_fail_closed === true
      ? state
      : failClosedState(state, health.reason);
    const previousState = lastState;
    lastState = displayState;
    state = displayState;
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
    byId('ltConfidence').textContent = `Bias confidence ${bias.confidence ?? '—'}/100 · not win rate`;
    byId('ltOpinion').textContent = state.opinion || 'Micky, I am watching.';
    const market = state.market || {};
    byId('ltSession').textContent = label(market.session);
    byId('ltRegime').textContent = label(market.regime);
    byId('ltMagnet').textContent = formatPrice(market.magnet);
    const tradeAction = String(state.trade?.action || 'WAIT').toUpperCase();
    byId('ltSetup').textContent = ['NO TRADE',''].includes(tradeAction) ? 'WAIT' : tradeAction;
    byId('ltSetupGate').textContent = `Setup gate: ${state.setup?.status || 'WATCHING'}`;
    byId('ltMarketLine').innerHTML = [
      `ATR ${formatPrice(market.atr)}`,
      `12-bar ${formatPct(market.return_12_pct)}`,
      `48-bar ${formatPct(market.return_48_pct)}`,
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

    // One authoritative browser snapshot feeds every sub-card inside EVE'S VIEW.
    // Extensions must consume this event instead of independently polling /live-trader,
    // otherwise the user can see values from different market instants on one card.
    window.__eveLiveTraderState = state;
    window.__eveLiveTraderStateSequence = Number(window.__eveLiveTraderStateSequence || 0) + 1;
    window.dispatchEvent(new CustomEvent('eve:live-trader-state', {
      detail: {
        state,
        sequence: window.__eveLiveTraderStateSequence,
        rendered_at: new Date().toISOString(),
      },
    }));

    if (allowSpeak && previousState && byId('ltSpeakChanges')?.checked && view.classList.contains('active')) {
      const announcement = marketChangeAnnouncement(previousState, state);
      if (announcement && speak(announcement.text, announcement)) {
        appendMessage('assistant', announcement.text, true);
      }
    }
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
      renderState(failClosedState(lastState, `API failure: ${error.message}`), false);
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
      if (byId('ltSpeakReplies').checked) {
        speak(payload.reply, {key:`reply:${Date.now()}`, priority:3, cooldownMs:0, interrupt:true});
      }
    } catch (error) {
      appendMessage('assistant', `Micky, I could not answer that because the Live Trader service returned: ${error.message}`);
    }
  }

  function enforceFreshness() {
    if (!lastState || lastState.__display_fail_closed === true) return;
    const health = contextHealth(lastState);
    if (!health.valid) {
      renderState(failClosedState(lastState, `freshness watchdog: ${health.reason}`), false);
    }
  }

  function startPolling() {
    clearInterval(pollTimer);clearInterval(learningTimer);clearInterval(staleWatchdogTimer);
    refreshLiveTrader(false);refreshLearning();loadConversation();
    pollTimer = setInterval(()=>refreshLiveTrader(true),2500);
    learningTimer = setInterval(refreshLearning,30000);
    staleWatchdogTimer = setInterval(enforceFreshness,5000);
  }

  window.addEventListener('focus', enforceFreshness);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) enforceFreshness();
  });

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
