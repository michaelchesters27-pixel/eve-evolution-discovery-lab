(() => {
  const VERSION = 'eve-live-zone-retrace-ui-v58';
  const STALE_MS = 10 * 60 * 1000;
  let timer = null;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const fmt = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-GB') : '—';
  const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
  const r = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(3)}R` : '—';
  const time = value => value ? new Date(value).toLocaleString('en-GB', {dateStyle:'short', timeStyle:'medium'}) : '—';
  const label = value => String(value || 'not enough evidence').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());

  function ensurePanel() {
    let panel = document.getElementById('ltZoneRetracePanel');
    if (panel) return panel;
    const learning = document.getElementById('ltLearning');
    const hostCard = learning?.closest('.lt-card');
    if (!hostCard) return null;

    panel = document.createElement('article');
    panel.className = 'lt-card';
    panel.id = 'ltZoneRetracePanel';
    panel.dataset.version = VERSION;
    panel.innerHTML = `
      <div class="panel-head">
        <div><p class="eyebrow">ZONE RETRACEMENT SPECIALIST</p><h3>Real strategy learning activity</h3></div>
        <span class="badge" id="ltZrHealth">LOADING</span>
      </div>
      <div id="ltZrBody" class="lt-learning"><div class="lt-empty">Waiting for the first real specialist evaluation cycle.</div></div>
      <p class="muted" style="font-size:11px;margin-top:12px">Live entry rule: bias → retracement → supply/demand zone → M5/M15 confirmation → market execution. Breakout chasing and blind limit entries are blocked while EVE compares execution methods in the Historical Academy.</p>`;
    hostCard.parentElement?.insertBefore(panel, hostCard);
    return panel;
  }

  function executionCard(name, item = {}) {
    return `<div class="lt-status" style="min-width:0">
      <span>${esc(name)}</span>
      <strong>${esc(r(item.expectancy_per_opportunity_r))}</strong>
      <small>${esc(fmt(item.triggered))} triggered / ${esc(fmt(item.opportunities))} opportunities · trigger ${esc(pct(item.trigger_rate))}</small>
    </div>`;
  }

  function render(data = {}) {
    if (!ensurePanel()) return;
    const health = document.getElementById('ltZrHealth');
    const body = document.getElementById('ltZrBody');
    const last = data.last_cycle_at ? new Date(data.last_cycle_at).getTime() : 0;
    const fresh = last && (Date.now() - last <= STALE_MS);
    const status = data.status === 'error' ? 'ERROR' : fresh ? 'LEARNING ACTIVE' : 'STALE';
    health.textContent = status;
    health.className = `badge ${status === 'LEARNING ACTIVE' ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;

    const evidence = data.execution_evidence || {};
    body.innerHTML = `
      <div class="lt-status-row">
        <div class="lt-status"><span>Real evaluation cycles</span><strong>${esc(fmt(data.cycle_count))}</strong></div>
        <div class="lt-status"><span>Last specialist cycle</span><strong>${esc(time(data.last_cycle_at))}</strong></div>
        <div class="lt-status"><span>Rows evaluated this cycle</span><strong>${esc(fmt(data.rows_evaluated))}</strong></div>
        <div class="lt-status"><span>Relevant zone episodes</span><strong>${esc(fmt(data.relevant_episodes))}</strong></div>
      </div>
      <div style="margin-top:14px"><p class="eyebrow">ENTRY METHOD COMPARISON</p></div>
      <div class="lt-status-row">
        ${executionCard('Market after confirmation', evidence.market)}
        ${executionCard('Pullback limit', evidence.pullback_limit)}
        ${executionCard('Confirmation stop', evidence.confirmation_stop)}
      </div>
      <div class="lt-status-row" style="margin-top:12px">
        <div class="lt-status"><span>Best current execution</span><strong>${esc(label(data.best_execution))}</strong></div>
        <div class="lt-status"><span>Evidence-qualified candidate</span><strong>${esc(label(data.promoted_execution))}</strong></div>
      </div>
      ${data.last_error ? `<p class="lt-invalidation">${esc(data.last_error)}</p>` : ''}`;
  }

  async function refresh() {
    try {
      const state = await api('/live-trader');
      render(state?.zone_retrace_learning || state?.learning?.zone_retrace_specialist || {});
    } catch (error) {
      render({status:'error', last_error:String(error?.message || error)});
    }
  }

  function start() {
    ensurePanel();
    refresh();
    clearInterval(timer);
    timer = setInterval(refresh, 30000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();