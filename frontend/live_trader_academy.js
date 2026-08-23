(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltHistoricalAcademy')) return;

  const safe = value => String(value ?? '').replace(/[&<>'\"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[ch]));
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
    .lt-regrade{margin-top:13px;border:1px solid #38664c;background:#06100b;border-radius:12px;padding:12px}
    .lt-regrade.attention{border-color:#a34141;background:#180a0a}
    .lt-regrade.complete{border-color:#4b9a68;background:#07150d}
    .lt-regrade-head{display:flex;justify-content:space-between;gap:12px;align-items:center}
    .lt-regrade-head b{font-size:10px;letter-spacing:.08em;color:var(--green)}
    .lt-regrade-pill{font-size:8px;font-weight:900;letter-spacing:.06em;border:1px solid #38664c;border-radius:999px;padding:5px 8px;color:var(--green);white-space:nowrap}
    .lt-regrade.attention .lt-regrade-pill{border-color:#a34141;color:#ff9292}.lt-regrade.complete .lt-regrade-pill{border-color:#4b9a68;color:#82efaa}
    .lt-regrade-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:10px}
    .lt-regrade-grid>div{border:1px solid var(--line);border-radius:9px;padding:9px;background:#050d09}
    .lt-regrade-grid span,.lt-regrade-grid strong{display:block}.lt-regrade-grid span{font-size:8px;color:var(--muted)}.lt-regrade-grid strong{font-size:13px;margin-top:3px}
    .lt-regrade-progress{margin-top:10px;height:7px;border-radius:999px;background:#0b1c12;overflow:hidden}.lt-regrade-progress>i{display:block;height:100%;background:var(--green);width:0;transition:width .4s ease}
    .lt-regrade-note{font-size:9px;line-height:1.5;color:#a9c4b6;margin:8px 0 0}
    .lt-market-closed-banner{display:none;margin:0 0 14px;border:1px solid #725b22;background:#171307;border-radius:12px;padding:12px 14px;color:#e8d99d;font-size:11px;line-height:1.55}
    .lt-market-closed-banner.show{display:block}
    .lt-feed.market-closed{border-color:#725b22!important;color:#e8d99d!important}
    @media(max-width:760px){.lt-academy-grid,.lt-regrade-grid{grid-template-columns:1fr 1fr}}
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
    <div class="lt-regrade" id="ltExecutionRegrade">
      <div class="lt-regrade-head"><b>EXECUTION REVALIDATION</b><span class="lt-regrade-pill" id="ltExecutionRegradeStatus">STARTING</span></div>
      <div class="lt-regrade-grid" id="ltExecutionRegradeGrid"></div>
      <div class="lt-regrade-progress"><i id="ltExecutionRegradeBar"></i></div>
      <p class="lt-regrade-note" id="ltExecutionRegradeNote">EVE is loading the corrected execution-evidence audit.</p>
    </div>
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

  function renderExecutionRegrade(summary, historicalEpisodes) {
    const regrade = summary?.execution_integrity || {};
    const box = document.getElementById('ltExecutionRegrade');
    const pill = document.getElementById('ltExecutionRegradeStatus');
    const grid = document.getElementById('ltExecutionRegradeGrid');
    const note = document.getElementById('ltExecutionRegradeNote');
    const bar = document.getElementById('ltExecutionRegradeBar');
    if (!box || !pill || !grid || !note || !bar) return;

    const checked = number(regrade.rows_checked);
    const regraded = number(regrade.rows_regraded);
    const outcomeChanges = number(regrade.outcome_changes);
    const challengerChanges = number(regrade.challenger_changes);
    const total = Math.max(number(historicalEpisodes), checked, 1);
    const progress = Math.min(100, Math.max(0, (checked / total) * 100));
    const completed = regrade.completed === true || regrade.ready === true;
    const error = String(regrade.last_error || '').trim();

    box.classList.toggle('attention', Boolean(error));
    box.classList.toggle('complete', completed && !error);
    pill.textContent = error ? 'ATTENTION' : completed ? 'COMPLETE — VERIFIED' : 'RUNNING — CLOSED-SAFE';
    grid.innerHTML = [
      ['Episodes checked', `${checked.toLocaleString('en-GB')} / ${total.toLocaleString('en-GB')}`],
      ['Paths regraded', regraded.toLocaleString('en-GB')],
      ['EVE outcomes corrected', outcomeChanges.toLocaleString('en-GB')],
      ['Challenger corrections', challengerChanges.toLocaleString('en-GB')],
    ].map(([name,value]) => `<div><span>${safe(name)}</span><strong>${safe(value)}</strong></div>`).join('');
    bar.style.width = `${completed ? 100 : progress.toFixed(1)}%`;

    if (error) {
      note.textContent = `Execution revalidation hit an error and remains closed-safe: ${error}`;
    } else if (completed) {
      note.textContent = `COMPLETE — EXECUTION EVIDENCE VERIFIED. The corrected execution rules have been applied through the historical ledger. Final cursor: ${dateText(regrade.cursor_time)}.`;
    } else if (!checked) {
      note.textContent = 'EVE is starting the corrected six-year execution revalidation. New replacement trades remain closed-safe until this verification completes.';
    } else {
      note.textContent = `Revalidation has reached ${dateText(regrade.cursor_time)} (${progress.toFixed(1)}%). EVE is checking original executions and challengers against the corrected causal M1 rules. New replacement trades remain closed-safe until complete.`;
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
    renderExecutionRegrade(summary, episodes);
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
