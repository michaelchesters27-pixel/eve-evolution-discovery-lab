(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltExecutionIntelligenceCard')) return;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const human = value => String(value ?? 'unknown').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
  const rText = value => value == null || !Number.isFinite(Number(value)) ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}R`;
  const confidenceText = value => value == null ? 'Building' : `${Math.round(number(value))}/100`;
  const dateText = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB', {timeZone:'Europe/London', day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'});
  };

  const style = document.createElement('style');
  style.textContent = `
    .lt-exec-card{margin-top:14px;border-color:#4f644f!important}.lt-exec-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
    .lt-exec-head h3{margin:2px 0 0;font-size:22px}.lt-exec-head p{margin:6px 0 0;color:var(--muted);font-size:10px;line-height:1.5;max-width:720px}
    .lt-exec-mode{border:1px solid #6b7348;border-radius:999px;padding:7px 11px;font-size:9px;font-weight:900;letter-spacing:.08em;color:#d9c989;white-space:nowrap}
    .lt-exec-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.lt-exec-stat{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:11px}
    .lt-exec-stat span,.lt-exec-stat strong{display:block}.lt-exec-stat span{font-size:8px;color:var(--muted)}.lt-exec-stat strong{font-size:16px;margin-top:4px}
    .lt-exec-list{display:grid;gap:9px;margin-top:12px}.lt-exec-row{border:1px solid var(--line);background:#06100b;border-radius:11px;padding:11px}
    .lt-exec-row-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.lt-exec-row-head span{font-size:8px;color:var(--muted)}.lt-exec-row-head strong{display:block;font-size:11px;margin-top:3px}
    .lt-exec-diagnosis{font-size:11px;font-weight:900;color:var(--green);text-align:right}.lt-exec-diagnosis.loss{color:#ffb06b}
    .lt-exec-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;margin-top:9px}.lt-exec-cell{border:1px solid #20362b;border-radius:8px;padding:8px;background:#07110b}
    .lt-exec-cell span,.lt-exec-cell b{display:block}.lt-exec-cell span{font-size:7px;color:var(--muted)}.lt-exec-cell b{font-size:10px;margin-top:3px}
    .lt-exec-lesson{font-size:9px;line-height:1.55;color:#b7cdbf;margin:9px 0 0;border-top:1px solid var(--line);padding-top:8px}
    .lt-exec-evidence{margin-top:8px;font-size:8px;color:var(--muted);line-height:1.5}.lt-exec-evidence b{color:var(--text)}
    .lt-exec-empty{margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:12px;color:var(--muted);font-size:9px;line-height:1.55}
    .lt-exec-policy{margin:11px 0 0;font-size:9px;color:var(--muted);line-height:1.5}
    @media(max-width:900px){.lt-exec-grid{grid-template-columns:repeat(3,1fr)}.lt-exec-stats{grid-template-columns:1fr 1fr}}
    @media(max-width:560px){.lt-exec-grid{grid-template-columns:1fr 1fr}.lt-exec-row-head{display:block}.lt-exec-diagnosis{text-align:left;margin-top:6px}.lt-exec-head{display:block}.lt-exec-mode{display:inline-block;margin-top:8px}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('article');
  card.id = 'ltExecutionIntelligenceCard';
  card.className = 'lt-card lt-exec-card';
  card.innerHTML = `
    <div class="lt-exec-head">
      <div><p class="eyebrow">POST-TRADE FORENSICS</p><h3>EXECUTION INTELLIGENCE</h3><p>EVE now separates the market thesis from the execution. Finished campaigns are replayed through a bounded causal M1 window so she can learn whether the issue was direction, timing, stop/target geometry, setup age, or simply a normal loss.</p></div>
      <span class="lt-exec-mode">DIAGNOSTIC ONLY</span>
    </div>
    <div class="lt-exec-stats" id="ltExecStats"></div>
    <div class="lt-exec-list" id="ltExecList"></div>
    <p class="lt-exec-policy" id="ltExecPolicy">Waiting for completed-campaign forensic evidence.</p>
  `;

  const iq = document.getElementById('ltIntelligenceCard');
  const trade = view.querySelector('.lt-trade-card');
  if (iq) iq.insertAdjacentElement('afterend', card);
  else if (trade) trade.insertAdjacentElement('afterend', card);
  else view.querySelector('.live-trader-shell')?.prepend(card);

  let timer = null;

  function strongestDiagnosis(counts) {
    const items = Object.entries(counts || {});
    if (!items.length) return 'Building';
    items.sort((a,b) => number(b[1]) - number(a[1]));
    return human(items[0][0]);
  }

  function render(execution) {
    const stats = document.getElementById('ltExecStats');
    const list = document.getElementById('ltExecList');
    const policy = document.getElementById('ltExecPolicy');
    if (!stats || !list || !policy) return;

    if (!execution || execution.available === false) {
      stats.innerHTML = '<div class="lt-exec-stat"><span>STATUS</span><strong>Unavailable</strong></div>';
      list.innerHTML = `<div class="lt-exec-empty">${safe(execution?.error || 'Execution Intelligence is temporarily unavailable.')}</div>`;
      return;
    }

    stats.innerHTML = [
      ['Forensic reviews', number(execution.reviews_enriched).toLocaleString('en-GB')],
      ['Waiting for full path', number(execution.reviews_pending).toLocaleString('en-GB')],
      ['Most common finding', strongestDiagnosis(execution.diagnosis_counts)],
      ['Mode', execution.diagnostic_only ? 'Observe only' : 'Unknown'],
    ].map(([name,value]) => `<div class="lt-exec-stat"><span>${safe(name)}</span><strong>${safe(value)}</strong></div>`).join('');

    const recent = Array.isArray(execution.recent) ? execution.recent.slice(0,6) : [];
    if (!recent.length) {
      list.innerHTML = '<div class="lt-exec-empty">No completed campaign has a full forensic path yet. EVE waits for the complete post-trade observation window rather than judging a trade too early.</div>';
    } else {
      list.innerHTML = recent.map(item => {
        const fx = item.forensics || {};
        const diagnosis = fx.diagnosis || {};
        const path = fx.path || {};
        const split = fx.confidence_split || {};
        const forward = split.forward_evidence || {};
        const proxy = fx.proxy_challengers || {};
        const historical = fx.historical_family_challengers || {};
        const maturity = fx.entry_maturity || {};
        const lossClass = String(item.outcome || '').toLowerCase() === 'lost' ? 'loss' : '';
        const challenger = historical.dominant_best_challenger || proxy.best_proxy || 'Building';
        return `<div class="lt-exec-row">
          <div class="lt-exec-row-head">
            <div><span>${safe(dateText(item.completed_at))}</span><strong>${safe(String(item.outcome || '').toUpperCase())} · Campaign ${safe(String(item.campaign_id || '').slice(0,8))}</strong></div>
            <div class="lt-exec-diagnosis ${lossClass}">${safe(human(diagnosis.primary || 'analysing'))}</div>
          </div>
          <div class="lt-exec-grid">
            <div class="lt-exec-cell"><span>THESIS</span><b>${safe(human(diagnosis.thesis || 'unknown'))}</b></div>
            <div class="lt-exec-cell"><span>ENTRY MATURITY</span><b>${safe(confidenceText(maturity.score))}</b></div>
            <div class="lt-exec-cell"><span>BEST MOVE</span><b>${safe(rText(path.mfe_r))}</b></div>
            <div class="lt-exec-cell"><span>ADVERSE MOVE</span><b>${safe(rText(path.mae_r == null ? null : -number(path.mae_r)))}</b></div>
            <div class="lt-exec-cell"><span>AFTER FINISH</span><b>${safe(rText(path.post_completion_best_r))}</b></div>
            <div class="lt-exec-cell"><span>FORWARD PROOF</span><b>${safe(confidenceText(split.forward_proven))}</b></div>
          </div>
          <div class="lt-exec-evidence"><b>Entry:</b> ${safe(human(diagnosis.entry_timing || 'unknown'))} · <b>Stop:</b> ${safe(human(diagnosis.stop || 'unknown'))} · <b>Target:</b> ${safe(human(diagnosis.target || 'unknown'))} · <b>Best challenger evidence:</b> ${safe(human(challenger))} · <b>Forward samples:</b> ${safe(number(forward.samples))} across ${safe(number(forward.days))} day(s).</div>
          <p class="lt-exec-lesson">${safe(diagnosis.lesson || 'Forensic lesson is still building.')}</p>
        </div>`;
      }).join('');
    }
    policy.textContent = execution.policy || 'Execution Intelligence is diagnostic only and cannot rewrite live rules automatically.';
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const summary = await api('/live-trader/learning');
      render(summary.execution_intelligence || {});
    } catch (error) {
      render({available:false,error:`Could not read Execution Intelligence: ${error.message}`});
    }
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 15000);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (view.classList.contains('active')) start();
})();
