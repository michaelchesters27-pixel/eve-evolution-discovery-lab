(() => {
  const VERSION = 'eve-live-zone-retrace-ui-v75';
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
      <div id="ltZrBody" class="lt-learning"><div class="lt-empty">Waiting for specialist evidence.</div></div>
      <p class="muted" style="font-size:11px;margin-top:12px">Live rule: bias → retracement → supply/demand zone → M5/M15 confirmation → market execution. Historical learning uses causal M1 as an execution proxy; forward Live Trader campaigns are still required before the strategy can be called proven live.</p>`;
    hostCard.parentElement?.insertBefore(panel, hostCard);
    return panel;
  }

  function executionCard(name, item = {}) {
    return `<div class="lt-status" style="min-width:0"><span>${esc(name)}</span><strong>${esc(r(item.expectancy_per_opportunity_r))}</strong><small>${esc(fmt(item.triggered))} triggered / ${esc(fmt(item.opportunities))} opportunities · trigger ${esc(pct(item.trigger_rate))}</small></div>`;
  }

  function render(data = {}) {
    if (!ensurePanel()) return;
    const health = document.getElementById('ltZrHealth');
    const body = document.getElementById('ltZrBody');
    const academy = data.current_policy_academy || {};
    const lastValue = academy.last_cycle_at || data.last_cycle_at;
    const last = lastValue ? new Date(lastValue).getTime() : 0;
    const fresh = Boolean(last && Date.now() - last <= STALE_MS);
    const proxyVerified = data.historical_policy_proxy_verified === true || data.live_policy_expectancy_verified === true;
    const proxyCandidate = data.historical_policy_proxy_candidate_execution || null;
    const status = data.status === 'error' ? 'ERROR'
      : proxyCandidate ? 'HISTORICAL M1 CANDIDATE'
      : proxyVerified ? 'M1 PROXY VERIFIED'
      : academy.academy_version && !academy.caught_up ? 'M1 PROXY SCANNING'
      : fresh ? 'LEARNING ACTIVE'
      : 'STALE';
    health.textContent = status;
    health.className = `badge ${['HISTORICAL M1 CANDIDATE','M1 PROXY VERIFIED','LEARNING ACTIVE'].includes(status) ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;

    const evidence = data.research_execution_evidence || data.execution_evidence || {};
    body.innerHTML = `
      <div class="lt-status-row">
        <div class="lt-status"><span>Archive rows scanned</span><strong>${esc(fmt(academy.rows_scanned))}</strong><small>${esc(time(academy.cursor_time))}</small></div>
        <div class="lt-status"><span>Current-policy opportunities</span><strong>${esc(fmt(academy.opportunities_found))}</strong></div>
        <div class="lt-status"><span>Confirmed M1-proxy entries</span><strong>${esc(fmt(academy.triggered))}</strong></div>
        <div class="lt-status"><span>Causal M1 expectancy</span><strong>${esc(r(academy.expectancy_per_opportunity_r))}</strong></div>
        <div class="lt-status"><span>Historical candidate</span><strong>${esc(proxyCandidate ? label(proxyCandidate) : 'Not qualified')}</strong></div>
        <div class="lt-status"><span>Forward live proof</span><strong>REQUIRED</strong></div>
      </div>
      <div style="margin-top:14px"><p class="eyebrow">OLDER RESEARCH BASELINE</p></div>
      <div class="lt-status-row">
        ${executionCard('Immediate market (research)', evidence.market)}
        ${executionCard('Pullback limit (research)', evidence.pullback_limit)}
        ${executionCard('Confirmation stop (research)', evidence.confirmation_stop)}
      </div>
      <div class="lt-status-row" style="margin-top:12px">
        <div class="lt-status"><span>Research best</span><strong>${esc(label(data.research_best_execution || data.best_execution))}</strong><small>${Number(data.research_target_r || 2.2).toFixed(1)}R baseline</small></div>
        <div class="lt-status"><span>Live strategy proven</span><strong>NO</strong><small>Historical M1 is not tick-exact</small></div>
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