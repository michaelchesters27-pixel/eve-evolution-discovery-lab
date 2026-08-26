(() => {
  const VERSION = 'eve-live-trader-audit-ui-v73';
  if (window.__eveLiveTraderAuditUiV73) return;
  window.__eveLiveTraderAuditUiV73 = true;

  function repairSectionPlacement() {
    const view = document.getElementById('view-live-trader');
    if (!view) return;
    const overview = view.querySelector('[data-lt-page="overview"]');
    const structure = view.querySelector('[data-lt-page="structure"]');
    const hero = overview?.querySelector('.lt-hero');
    const liveMarketCard = document.getElementById('ltPrice')?.closest('.lt-card');
    if (overview && hero && liveMarketCard && !hero.contains(liveMarketCard)) hero.insertBefore(liveMarketCard, hero.firstChild);
    if (structure && liveMarketCard && structure.contains(liveMarketCard) && hero) hero.insertBefore(liveMarketCard, hero.firstChild);
  }

  async function refreshSpecialistFromLearningApi() {
    const panel = document.getElementById('ltZoneRetracePanel');
    if (!panel || typeof api !== 'function') return;
    try {
      const learning = await api('/live-trader/learning');
      const data = learning?.zone_retrace_specialist || {};
      const academy = data.current_policy_academy || learning?.zone_retrace_current_policy_academy || {};
      const body = document.getElementById('ltZrBody');
      const health = document.getElementById('ltZrHealth');
      if (!body || !health) return;

      const fmt = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-GB') : '—';
      const r = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(3)}R` : '—';
      const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
      const time = value => value ? new Date(value).toLocaleString('en-GB', {dateStyle:'short', timeStyle:'medium'}) : '—';
      const label = value => String(value || '—').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
      const opportunities = Number(academy.opportunities_found || 0);
      const scorable = Number(academy.scorable_opportunities || 0);
      const coverage = opportunities > 0 ? scorable / opportunities : null;
      const academyScanning = Boolean(academy.academy_version && !academy.caught_up);
      const verified = data.live_policy_expectancy_verified === true;
      const promoted = Boolean(data.live_promoted_execution);
      const last = academy.last_cycle_at || data.last_cycle_at;
      const lastMs = last ? new Date(last).getTime() : 0;
      const fresh = Boolean(lastMs && Date.now() - lastMs <= 10 * 60 * 1000);
      const status = data.status === 'error' ? 'ERROR'
        : promoted ? 'LIVE ENTRY QUALIFIED'
        : verified ? 'LIVE POLICY VERIFIED'
        : academyScanning ? 'CURRENT POLICY SCANNING'
        : fresh ? 'LEARNING ACTIVE'
        : 'STALE';
      health.textContent = status;
      health.className = `badge ${['LIVE ENTRY QUALIFIED','LIVE POLICY VERIFIED','LEARNING ACTIVE'].includes(status) ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;

      const liveEvidence = data.live_policy_execution_evidence?.market_after_zone_confirmation || {};
      const researchEvidence = data.research_execution_evidence || data.execution_evidence || {};
      const researchRow = (name, item = {}) => `<div class="lt-status"><span>${name}</span><strong>${r(item.expectancy_per_opportunity_r)}</strong><small>${fmt(item.triggered)} triggered / ${fmt(item.opportunities)} opportunities · ${pct(item.trigger_rate)} trigger rate</small></div>`;

      body.innerHTML = `
        <div><p class="eyebrow">CURRENT LIVE POLICY ACADEMY</p></div>
        <div class="lt-status-row">
          <div class="lt-status"><span>Archive rows scanned</span><strong>${fmt(academy.rows_scanned)}</strong><small>Cursor ${time(academy.cursor_time)}</small></div>
          <div class="lt-status"><span>Current-policy opportunities</span><strong>${fmt(academy.opportunities_found)}</strong><small>Found only after today's bias, session and ranked-zone gates</small></div>
          <div class="lt-status"><span>Scorable opportunities</span><strong>${fmt(academy.scorable_opportunities)}</strong><small>${coverage == null ? 'Waiting for opportunities' : `${pct(coverage)} causal coverage`}</small></div>
          <div class="lt-status"><span>Confirmed entries</span><strong>${fmt(academy.triggered)}</strong><small>${pct(academy.trigger_rate)} trigger rate</small></div>
          <div class="lt-status"><span>Exact live-policy expectancy</span><strong>${r(academy.expectancy_per_opportunity_r)}</strong><small>${academy.caught_up ? 'Archive scan caught up' : 'Still scanning — not final evidence'}</small></div>
          <div class="lt-status"><span>Promotion status</span><strong>${promoted ? label(data.live_promoted_execution) : 'NOT PROMOTED'}</strong><small>${verified ? 'Evidence coverage verified' : 'Promotion remains blocked until archive and thresholds pass'}</small></div>
        </div>
        <p class="muted" style="font-size:11px;margin-top:12px">Live contract under test: current structural bias → London window → best ranked demand/supply → retracement → M5/M15 confirmation → market entry → production stop geometry → ${Number(data.live_target_cap_r || 1.5).toFixed(1)}R target cap. Historical red-folder news is not credited because a complete six-year news archive is unavailable; the live news gate still fails closed.</p>

        <div style="margin-top:18px"><p class="eyebrow">OLDER RESEARCH BASELINE — NOT LIVE PROMOTION</p></div>
        <div class="lt-status-row">
          ${researchRow('Immediate market (research)', researchEvidence.market)}
          ${researchRow('Pullback limit (research)', researchEvidence.pullback_limit)}
          ${researchRow('Confirmation stop (research)', researchEvidence.confirmation_stop)}
        </div>
        <div class="lt-status-row" style="margin-top:12px">
          <div class="lt-status"><span>Independent old pullbacks</span><strong>${fmt(data.relevant_episodes)}</strong><small>Compatibility/research sample only</small></div>
          <div class="lt-status"><span>Research target</span><strong>${Number(data.research_target_r || 2.2).toFixed(1)}R</strong><small>Immediate decision-price model</small></div>
          <div class="lt-status"><span>Research best</span><strong>${label(data.research_best_execution || data.best_execution)}</strong></div>
          <div class="lt-status"><span>Promotion authority</span><strong>CURRENT POLICY ACADEMY</strong><small>${data.current_policy_academy_version || 'v71'}</small></div>
        </div>
        ${data.legacy_cycle_count != null ? `<p class="muted" style="font-size:11px;margin-top:12px">Pre-hardening cycle headline preserved for audit only: ${fmt(data.legacy_cycle_count)}. It is not included in the audited completed-cycle counter.</p>` : ''}`;
    } catch (_) {
      // Keep the previous visible values; stale state remains visibly stale.
    }
  }

  let attempts = 0;
  const boot = setInterval(() => {
    attempts += 1;
    repairSectionPlacement();
    if (document.getElementById('ltZoneRetracePanel')) refreshSpecialistFromLearningApi();
    if (attempts >= 40) clearInterval(boot);
  }, 500);

  setInterval(() => {
    repairSectionPlacement();
    refreshSpecialistFromLearningApi();
  }, 30000);
})();
