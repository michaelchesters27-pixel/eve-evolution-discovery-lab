(() => {
  const VERSION = 'eve-live-trader-audit-ui-v67';
  if (window.__eveLiveTraderAuditUiV67) return;
  window.__eveLiveTraderAuditUiV67 = true;

  function repairSectionPlacement() {
    const view = document.getElementById('view-live-trader');
    if (!view) return;
    const overview = view.querySelector('[data-lt-page="overview"]');
    const structure = view.querySelector('[data-lt-page="structure"]');
    const hero = overview?.querySelector('.lt-hero');
    const liveMarketCard = document.getElementById('ltPrice')?.closest('.lt-card');

    if (overview && hero && liveMarketCard && !hero.contains(liveMarketCard)) {
      hero.insertBefore(liveMarketCard, hero.firstChild);
    }
    if (structure && liveMarketCard && structure.contains(liveMarketCard) && hero) {
      hero.insertBefore(liveMarketCard, hero.firstChild);
    }
  }

  async function refreshSpecialistFromLearningApi() {
    const panel = document.getElementById('ltZoneRetracePanel');
    if (!panel || typeof api !== 'function') return;
    try {
      const learning = await api('/live-trader/learning');
      const data = learning?.zone_retrace_specialist || {};
      const body = document.getElementById('ltZrBody');
      const health = document.getElementById('ltZrHealth');
      if (!body || !health) return;

      const fmt = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-GB') : '—';
      const r = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(3)}R` : '—';
      const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
      const time = value => value ? new Date(value).toLocaleString('en-GB', {dateStyle:'short', timeStyle:'medium'}) : '—';
      const last = data.last_cycle_at ? new Date(data.last_cycle_at).getTime() : 0;
      const fresh = Boolean(last && Date.now() - last <= 10 * 60 * 1000);
      const needsRescore = data.live_policy_expectancy_verified === false && data.live_policy_rescore_status === 'required';
      const status = data.status === 'error' ? 'ERROR' : needsRescore ? 'LIVE RESCORE REQUIRED' : fresh ? 'LEARNING ACTIVE' : 'STALE';
      health.textContent = status;
      health.className = `badge ${status === 'LEARNING ACTIVE' ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;

      const evidence = data.research_execution_evidence || data.execution_evidence || {};
      const auditedScope = data.evidence_scope === 'independent_pullback_only' || data.evidence_scope === 'pullback_only';
      const row = (name, item = {}) => `<div class="lt-status"><span>${name}</span><strong>${r(item.expectancy_per_opportunity_r)}</strong><small>${fmt(item.triggered)} triggered / ${fmt(item.opportunities)} opportunities · ${pct(item.trigger_rate)} trigger rate</small></div>`;
      body.innerHTML = `
        <div class="lt-status-row">
          <div class="lt-status"><span>Audited completed cycles</span><strong>${fmt(data.cycle_count)}</strong><small>Accurate since ${time(data.cycle_counter_accurate_since)}</small></div>
          <div class="lt-status"><span>Independent retracement episodes</span><strong>${fmt(data.relevant_episodes)}</strong></div>
          <div class="lt-status"><span>Research target</span><strong>${Number(data.research_target_r || 2.2).toFixed(1)}R</strong><small>Immediate decision-price challenger</small></div>
          <div class="lt-status"><span>Live target cap</span><strong>${Number(data.live_target_cap_r || 1.5).toFixed(1)}R</strong><small>Zone retrace + M5/M15 confirmation</small></div>
          <div class="lt-status"><span>Evidence scope</span><strong>${auditedScope ? 'Independent pullbacks only' : 'CHECK FILTER'}</strong></div>
          <div class="lt-status"><span>Live-policy expectancy</span><strong>${data.live_policy_expectancy_verified ? 'VERIFIED' : 'NOT VERIFIED'}</strong><small>${data.live_policy_rescore_status === 'required' ? 'Targeted causal M1 rescore required' : ''}</small></div>
        </div>
        <div style="margin-top:14px"><p class="eyebrow">RESEARCH BASELINE — NOT LIVE PROMOTION</p></div>
        <div class="lt-status-row">
          ${row('Immediate market (research)', evidence.market)}
          ${row('Pullback limit (research)', evidence.pullback_limit)}
          ${row('Confirmation stop (research)', evidence.confirmation_stop)}
        </div>
        <div class="lt-status-row" style="margin-top:12px">
          <div class="lt-status"><span>Research best execution</span><strong>${String(data.research_best_execution || data.best_execution || '—').replaceAll('_',' ')}</strong></div>
          <div class="lt-status"><span>Live promoted execution</span><strong>${data.live_promoted_execution ? String(data.live_promoted_execution).replaceAll('_',' ') : 'NONE — RESCORE REQUIRED'}</strong></div>
        </div>
        ${needsRescore ? `<p class="lt-invalidation">The historical comparison enters at the decision price and uses a 2.2R target. Live Trader waits for the zone, requires M5/M15 confirmation and caps the target at 1.5R. The research result cannot promote a live execution until that exact contract is replayed.</p>` : ''}
        ${data.legacy_cycle_count != null ? `<p class="muted" style="font-size:11px;margin-top:12px">Pre-hardening cycle headline preserved for audit only: ${fmt(data.legacy_cycle_count)}. It is not included in the audited completed-cycle counter.</p>` : ''}`;
    } catch (_) {
      // Leave the previous visible values in place. The base panel will still mark
      // genuinely stale main-state data as stale.
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
