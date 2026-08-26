(() => {
  const VERSION = 'eve-live-trader-audit-ui-v75';
  if (window.__eveLiveTraderAuditUiV75) return;
  window.__eveLiveTraderAuditUiV75 = true;

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
      const proxyVerified = data.historical_policy_proxy_verified === true || data.live_policy_expectancy_verified === true;
      const proxyCandidate = data.historical_policy_proxy_candidate_execution || null;
      const last = academy.last_cycle_at || data.last_cycle_at;
      const lastMs = last ? new Date(last).getTime() : 0;
      const fresh = Boolean(lastMs && Date.now() - lastMs <= 10 * 60 * 1000);
      const status = data.status === 'error' ? 'ERROR'
        : proxyCandidate ? 'HISTORICAL M1 CANDIDATE'
        : proxyVerified ? 'M1 PROXY VERIFIED'
        : academyScanning ? 'M1 PROXY SCANNING'
        : fresh ? 'LEARNING ACTIVE'
        : 'STALE';
      health.textContent = status;
      health.className = `badge ${['HISTORICAL M1 CANDIDATE','M1 PROXY VERIFIED','LEARNING ACTIVE'].includes(status) ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;

      const researchEvidence = data.research_execution_evidence || data.execution_evidence || {};
      const researchRow = (name, item = {}) => `<div class="lt-status"><span>${name}</span><strong>${r(item.expectancy_per_opportunity_r)}</strong><small>${fmt(item.triggered)} triggered / ${fmt(item.opportunities)} opportunities · ${pct(item.trigger_rate)} trigger rate</small></div>`;

      body.innerHTML = `
        <div><p class="eyebrow">CURRENT-POLICY HISTORICAL ACADEMY</p></div>
        <div class="lt-status-row">
          <div class="lt-status"><span>Archive rows scanned</span><strong>${fmt(academy.rows_scanned)}</strong><small>Cursor ${time(academy.cursor_time)}</small></div>
          <div class="lt-status"><span>Current-policy opportunities</span><strong>${fmt(academy.opportunities_found)}</strong><small>Found after today's bias, session and ranked-zone gates</small></div>
          <div class="lt-status"><span>Scorable opportunities</span><strong>${fmt(academy.scorable_opportunities)}</strong><small>${coverage == null ? 'Waiting for opportunities' : `${pct(coverage)} causal M1 coverage`}</small></div>
          <div class="lt-status"><span>Confirmed entries</span><strong>${fmt(academy.triggered)}</strong><small>${pct(academy.trigger_rate)} trigger rate</small></div>
          <div class="lt-status"><span>Causal M1 policy expectancy</span><strong>${r(academy.expectancy_per_opportunity_r)}</strong><small>${academy.caught_up ? 'Archive scan caught up' : 'Still scanning — not final evidence'}</small></div>
          <div class="lt-status"><span>Historical candidate</span><strong>${proxyCandidate ? label(proxyCandidate) : 'NOT QUALIFIED'}</strong><small>${proxyVerified ? 'Historical proxy coverage verified' : 'Thresholds cannot be finalized until archive scan is complete'}</small></div>
          <div class="lt-status"><span>Tick-exact historical proof</span><strong>NO</strong><small>M1 OHLC is the finest historical execution source</small></div>
          <div class="lt-status"><span>Forward live validation</span><strong>REQUIRED</strong><small>No historical proxy can declare the live strategy proven</small></div>
        </div>
        <p class="muted" style="font-size:11px;margin-top:12px">Historical policy proxy: completed M5 structural state → London window → best ranked demand/supply → retracement → M5/M15 confirmation → causal M1 market-entry proxy → production stop geometry → ${Number(data.live_target_cap_r || 1.5).toFixed(1)}R target cap. M1 cannot reveal intraminute tick order, so ambiguous same-minute outcomes are scored conservatively stop-first. Historical red-folder news is not credited because a complete six-year calendar is unavailable; the live news gate still fails closed.</p>

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
          <div class="lt-status"><span>Historical candidate authority</span><strong>CURRENT-POLICY ACADEMY</strong><small>${data.current_policy_academy_version || 'v71'} · causal M1 proxy</small></div>
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
