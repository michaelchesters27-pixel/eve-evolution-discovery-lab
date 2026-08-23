(() => {
  let installed = false;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const rText = value => {
    const n = num(value);
    return `${n > 0 ? '+' : ''}${n.toFixed(2)}R`;
  };
  const dateText = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB', {timeZone:'Europe/London', weekday:'short', day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'});
  };

  function install() {
    const newsCard = document.getElementById('ltNewsCard');
    if (!newsCard || typeof window.eveLiveNewsRender !== 'function') {
      setTimeout(install, 100);
      return;
    }
    if (installed || document.getElementById('ltWeeklyOutcomesCard')) return;
    installed = true;

    const style = document.createElement('style');
    style.textContent = `
      .lt-outcomes-card{margin-top:14px;border-color:#315f45!important}.lt-outcome-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}
      .lt-outcome-head h3{margin:2px 0 0}.lt-outcome-head p{margin:6px 0 0;color:var(--muted);font-size:10px;line-height:1.5;max-width:720px}
      .lt-outcome-badge{border:1px solid #315f45;border-radius:999px;padding:7px 11px;font-size:9px;font-weight:900;letter-spacing:.08em;white-space:nowrap;color:var(--green)}
      .lt-outcome-badge.loss{border-color:#913f3f;color:#ff9292}.lt-outcome-badge.flat{border-color:#6f6541;color:#d9c989}
      .lt-outcome-score{display:grid;grid-template-columns:1.2fr repeat(6,minmax(0,1fr));gap:8px;margin-top:14px}.lt-outcome-stat{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:11px}
      .lt-outcome-stat span,.lt-outcome-stat strong{display:block}.lt-outcome-stat span{font-size:8px;color:var(--muted)}.lt-outcome-stat strong{font-size:17px;margin-top:4px}.lt-outcome-stat.primary strong{font-size:24px}
      .lt-outcome-open{margin-top:10px;border:1px solid #4a5a4f;background:#07110b;border-radius:10px;padding:11px;font-size:9px;line-height:1.55}.lt-outcome-open b{color:var(--green)}
      .lt-outcome-list{display:grid;gap:7px;margin-top:10px}.lt-outcome-row{display:grid;grid-template-columns:150px 1fr auto;gap:10px;align-items:center;border:1px solid var(--line);background:#06100b;border-radius:10px;padding:10px}
      .lt-outcome-row span,.lt-outcome-row small{display:block;color:var(--muted);font-size:8px}.lt-outcome-row strong{display:block;font-size:10px;margin-top:2px}.lt-outcome-result{font-size:11px;font-weight:900;white-space:nowrap}.lt-outcome-result.win{color:var(--green)}.lt-outcome-result.loss{color:#ff9292}.lt-outcome-result.neutral{color:#d9c989}
      .lt-outcome-learning{margin-top:10px;border-top:1px solid var(--line);padding-top:10px;color:#a9c4b6;font-size:9px;line-height:1.55}.lt-outcome-learning b{color:var(--text)}
      @media(max-width:900px){.lt-outcome-score{grid-template-columns:repeat(4,1fr)}.lt-outcome-stat.primary{grid-column:span 2}}
      @media(max-width:620px){.lt-outcome-score{grid-template-columns:1fr 1fr}.lt-outcome-stat.primary{grid-column:1/-1}.lt-outcome-row{grid-template-columns:1fr auto}.lt-outcome-row>div:nth-child(2){grid-column:1}.lt-outcome-result{grid-column:2;grid-row:1/3}}
    `;
    document.head.appendChild(style);

    const card = document.createElement('article');
    card.id = 'ltWeeklyOutcomesCard';
    card.className = 'lt-card lt-outcomes-card';
    card.innerHTML = `
      <div class="lt-outcome-head">
        <div><p class="eyebrow">WEEKLY TRADE OUTCOMES</p><h3>Are EVE's locked trades profitable?</h3><p>One result per genuine locked campaign. Wins/losses are measured in R so the counter stays honest even though Live Trader does not know your actual cash stake or broker fill.</p></div>
        <span class="lt-outcome-badge flat" id="ltOutcomeBadge">BUILDING</span>
      </div>
      <div class="lt-outcome-score" id="ltOutcomeStats"></div>
      <div id="ltOutcomeOpen"></div>
      <div class="lt-outcome-list" id="ltOutcomeList"></div>
      <div class="lt-outcome-learning" id="ltOutcomeLearning">Waiting for weekly campaign evidence.</div>
    `;
    newsCard.insertAdjacentElement('afterend', card);

    const baseRender = window.eveLiveNewsRender;
    window.eveLiveNewsRender = (state, summary) => {
      baseRender(state, summary);
      render(summary?.weekly_trade_outcomes || {}, state);
    };
  }

  function render(data, state) {
    const badge = document.getElementById('ltOutcomeBadge');
    const stats = document.getElementById('ltOutcomeStats');
    const openBox = document.getElementById('ltOutcomeOpen');
    const list = document.getElementById('ltOutcomeList');
    const learning = document.getElementById('ltOutcomeLearning');
    if (!badge || !stats || !openBox || !list || !learning) return;

    if (data?.available === false) {
      badge.textContent = 'UNAVAILABLE';
      badge.className = 'lt-outcome-badge loss';
      stats.innerHTML = '<div class="lt-outcome-stat primary"><span>WEEKLY RESULT</span><strong>—</strong></div>';
      learning.textContent = `Could not read weekly trade ledger: ${data.error || 'unknown error'}`;
      return;
    }

    const label = String(data?.result_label || 'FLAT').toUpperCase();
    badge.textContent = label;
    badge.className = `lt-outcome-badge ${label === 'LOSS' ? 'loss' : label === 'FLAT' ? 'flat' : ''}`;
    const winRate = data?.win_rate_pct == null ? '—' : `${num(data.win_rate_pct).toFixed(1)}%`;
    stats.innerHTML = [
      ['NET RESULT', rText(data?.net_r), 'primary'],
      ['Finished', num(data?.triggered_finished).toLocaleString('en-GB'), ''],
      ['Wins', num(data?.wins).toLocaleString('en-GB'), ''],
      ['Losses', num(data?.losses).toLocaleString('en-GB'), ''],
      ['Win rate', winRate, ''],
      ['Invalidated', num(data?.invalidated).toLocaleString('en-GB'), ''],
      ['Expired', num(data?.expired).toLocaleString('en-GB'), ''],
    ].map(([name,value,klass]) => `<div class="lt-outcome-stat ${klass}"><span>${safe(name)}</span><strong>${safe(value)}</strong></div>`).join('');

    const opens = Array.isArray(data?.open) ? data.open : [];
    if (opens.length) {
      const item = opens[0] || {};
      openBox.innerHTML = `<div class="lt-outcome-open"><b>CURRENT LOCKED CAMPAIGN:</b> ${safe(String(item.side || ''))} ${safe(String(item.status || '').toUpperCase())} · entry ${safe(item.entry ?? '—')} · SL ${safe(item.stop ?? '—')} · TP ${safe(item.target ?? '—')} · published ${safe(dateText(item.created_at))}. It does not affect weekly net R until it finishes.</div>`;
    } else {
      openBox.innerHTML = '<div class="lt-outcome-open"><b>NO OPEN CAMPAIGN:</b> EVE is free to search for the next valid setup once all other safety guards allow it.</div>';
    }

    const recent = Array.isArray(data?.recent) ? data.recent : [];
    if (!recent.length) {
      list.innerHTML = '<div class="lt-outcome-open">No triggered trade has finished in this Sunday–Saturday week yet.</div>';
    } else {
      list.innerHTML = recent.map(item => {
        const status = String(item.status || '').toLowerCase();
        const klass = status === 'won' ? 'win' : status === 'lost' ? 'loss' : 'neutral';
        const label = status === 'won' ? 'WIN' : status === 'lost' ? 'LOSS' : status.toUpperCase();
        return `<div class="lt-outcome-row"><div><span>${safe(dateText(item.completed_at))}</span><strong>${safe(String(item.side || ''))} ${safe(String(item.order_type || '').replaceAll('_',' ').toUpperCase())}</strong></div><div><span>Entry ${safe(item.entry ?? '—')} · SL ${safe(item.stop ?? '—')} · TP ${safe(item.target ?? '—')}</span><strong>${safe(item.result || '')}</strong></div><div class="lt-outcome-result ${klass}">${safe(label)} · ${safe(rText(item.realised_r))}</div></div>`;
      }).join('');
    }

    learning.innerHTML = `<b>POST-TRADE LEARNING:</b> ${safe(num(data?.post_trade_reviews))} campaign review(s) stored this week, including ${safe(num(data?.loss_reviews))} losing-trade review(s). Every loss is retained as negative execution evidence, but EVE will not overfit by rewriting her rules from one loss. Repeated independent evidence must mature before it changes confidence/veto behaviour. <b>Net R is strategy performance, not cash P/L.</b>`;
  }

  install();
})();
