(() => {
  const VERSION = 'eve-live-zone-retrace-ui-v76';
  const STALE_MS = 10 * 60 * 1000;
  let timer = null;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const fmt = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-GB') : '—';
  const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
  const r = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(3)}R` : '—';
  const date = value => value ? new Date(value).toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'}) : '—';
  const label = value => String(value || 'not qualified').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
  const byId = id => document.getElementById(id);
  const set = (id, value) => { const el = byId(id); if (el) el.textContent = value; };

  function ensureStyle() {
    if (document.getElementById('ltZrStableStyle')) return;
    const style = document.createElement('style');
    style.id = 'ltZrStableStyle';
    style.textContent = `
      #ltZoneRetracePanel .lt-zr-summary{margin:0 0 14px;color:#aebbb6;font-size:13px;line-height:1.55;min-height:40px}
      #ltZoneRetracePanel .lt-zr-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      #ltZoneRetracePanel .lt-zr-metric{border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:12px;min-width:0;min-height:92px;box-sizing:border-box;background:rgba(255,255,255,.025)}
      #ltZoneRetracePanel .lt-zr-metric span{display:block;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#8fa19b;min-height:25px}
      #ltZoneRetracePanel .lt-zr-metric strong{display:block;margin-top:5px;font-size:20px;line-height:1.1;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
      #ltZoneRetracePanel .lt-zr-metric small{display:block;margin-top:7px;color:#93a29d;line-height:1.35;min-height:16px}
      #ltZoneRetracePanel .lt-zr-proof{margin-top:12px;padding:11px 12px;border:1px solid rgba(255,255,255,.08);border-radius:10px;font-size:12px;color:#b8c4c0}
      #ltZoneRetraceResearchPanel .lt-zr-research-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      #ltZoneRetraceResearchPanel .lt-zr-research-item{border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px;min-height:105px;box-sizing:border-box;background:rgba(255,255,255,.02)}
      #ltZoneRetraceResearchPanel .lt-zr-research-item span{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#8fa19b;min-height:28px}
      #ltZoneRetraceResearchPanel .lt-zr-research-item strong{display:block;font-size:18px;margin-top:5px;font-variant-numeric:tabular-nums}
      #ltZoneRetraceResearchPanel .lt-zr-research-item small{display:block;margin-top:7px;color:#93a29d;line-height:1.35}
      @media(max-width:980px){#ltZoneRetracePanel .lt-zr-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:780px){#ltZoneRetracePanel .lt-zr-grid,#ltZoneRetraceResearchPanel .lt-zr-research-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensurePanels() {
    ensureStyle();
    const learning = byId('ltLearning');
    const hostCard = learning?.closest('.lt-card');
    if (!hostCard) return null;

    let current = byId('ltZoneRetracePanel');
    if (!current) {
      current = document.createElement('article');
      current.className = 'lt-card';
      current.id = 'ltZoneRetracePanel';
      current.dataset.version = VERSION;
      current.innerHTML = `
        <div class="panel-head">
          <div><p class="eyebrow">ZONE RETRACEMENT SPECIALIST</p><h3>What EVE is learning now</h3></div>
          <span class="badge warning" id="ltZrHealth">LOADING</span>
        </div>
        <p class="lt-zr-summary">EVE is scanning old market data using the same bias, session, zone and confirmation rules she uses now.</p>
        <div class="lt-zr-grid">
          <div class="lt-zr-metric"><span>History scanned</span><strong id="ltZrRows">—</strong><small id="ltZrCursor">Through —</small></div>
          <div class="lt-zr-metric"><span>Valid retracement setups</span><strong id="ltZrOpportunities">—</strong><small>Passed today's initial gates</small></div>
          <div class="lt-zr-metric"><span>Causal M1 coverage</span><strong id="ltZrCoverage">—</strong><small id="ltZrScorable">— scorable</small></div>
          <div class="lt-zr-metric"><span>Confirmed entries</span><strong id="ltZrEntries">—</strong><small id="ltZrTriggerRate">— trigger rate</small></div>
          <div class="lt-zr-metric"><span>Historical M1 result</span><strong id="ltZrExpectancy">—</strong><small>Per valid opportunity</small></div>
          <div class="lt-zr-metric"><span>Historical candidate</span><strong id="ltZrCandidate">Not qualified</strong><small>Forward live proof still required</small></div>
        </div>
        <div class="lt-zr-proof"><b>Live rule:</b> bias → retracement → best supply/demand zone → M5/M15 confirmation → market execution. Historical M1 is a proxy only; live campaigns are the final proof.</div>
        <p class="lt-invalidation" id="ltZrError" style="display:none"></p>`;
      hostCard.parentElement?.insertBefore(current, hostCard);
    }

    let research = byId('ltZoneRetraceResearchPanel');
    if (!research) {
      research = document.createElement('article');
      research.className = 'lt-card';
      research.id = 'ltZoneRetraceResearchPanel';
      research.dataset.version = VERSION;
      research.innerHTML = `
        <div class="panel-head">
          <div><p class="eyebrow">OLDER RESEARCH BASELINE</p><h3>Earlier execution comparison</h3></div>
          <span class="badge">RESEARCH ONLY</span>
        </div>
        <p class="muted" style="font-size:12px;margin:0 0 14px">These figures are useful research, but they used the older immediate-entry / 2.2R framework. They do not prove the current live retracement entry.</p>
        <div class="lt-zr-research-grid" id="ltZrResearchGrid"></div>
        <div class="lt-zr-research-grid" style="margin-top:10px">
          <div class="lt-zr-research-item"><span>Research best</span><strong id="ltZrResearchBest">—</strong><small id="ltZrResearchTarget">2.2R baseline</small></div>
          <div class="lt-zr-research-item"><span>Live strategy proven</span><strong>NO</strong><small>Forward Live Trader campaigns are required.</small></div>
          <div class="lt-zr-research-item"><span>Use of this panel</span><strong>CONTEXT</strong><small>Keep it separate from current-policy learning.</small></div>
        </div>`;
      hostCard.parentElement?.insertBefore(research, hostCard);
    }

    return {current, research};
  }

  function executionCard(name, item = {}) {
    return `<div class="lt-zr-research-item"><span>${esc(name)}</span><strong>${esc(r(item.expectancy_per_opportunity_r))}</strong><small>${esc(fmt(item.triggered))} triggered / ${esc(fmt(item.opportunities))} opportunities · ${esc(pct(item.trigger_rate))} trigger</small></div>`;
  }

  function render(data = {}) {
    if (!ensurePanels()) return;
    const academy = data.current_policy_academy || {};
    const lastValue = academy.last_cycle_at || data.last_cycle_at;
    const last = lastValue ? new Date(lastValue).getTime() : 0;
    const fresh = Boolean(last && Date.now() - last <= STALE_MS);
    const proxyVerified = data.historical_policy_proxy_verified === true || data.live_policy_expectancy_verified === true;
    const proxyCandidate = data.historical_policy_proxy_candidate_execution || null;
    const scanning = Boolean(academy.academy_version && !academy.caught_up);
    const status = data.status === 'error' ? 'ERROR'
      : proxyCandidate ? 'HISTORICAL CANDIDATE'
      : proxyVerified ? 'HISTORY CHECKED'
      : scanning ? 'SCANNING HISTORY'
      : fresh ? 'LEARNING ACTIVE'
      : 'STALE';

    const health = byId('ltZrHealth');
    if (health) {
      health.textContent = status;
      health.className = `badge ${['HISTORICAL CANDIDATE','HISTORY CHECKED','LEARNING ACTIVE'].includes(status) ? 'success' : status === 'ERROR' ? 'error' : 'warning'}`;
    }

    const opportunities = Number(academy.opportunities_found || 0);
    const scorable = Number(academy.scorable_opportunities || 0);
    const coverage = opportunities > 0 ? scorable / opportunities : 0;

    set('ltZrRows', fmt(academy.rows_scanned));
    set('ltZrCursor', `Through ${date(academy.cursor_time)}`);
    set('ltZrOpportunities', fmt(opportunities));
    set('ltZrCoverage', pct(coverage));
    set('ltZrScorable', `${fmt(scorable)} scorable`);
    set('ltZrEntries', fmt(academy.triggered));
    set('ltZrTriggerRate', `${pct(academy.trigger_rate)} trigger rate`);
    set('ltZrExpectancy', r(academy.expectancy_per_opportunity_r));
    set('ltZrCandidate', proxyCandidate ? label(proxyCandidate) : 'Not qualified');

    const error = byId('ltZrError');
    if (error) {
      error.textContent = data.last_error || '';
      error.style.display = data.last_error ? '' : 'none';
    }

    const evidence = data.research_execution_evidence || data.execution_evidence || {};
    const grid = byId('ltZrResearchGrid');
    if (grid) grid.innerHTML = [
      executionCard('Immediate market', evidence.market),
      executionCard('Pullback limit', evidence.pullback_limit),
      executionCard('Confirmation stop', evidence.confirmation_stop),
    ].join('');
    set('ltZrResearchBest', label(data.research_best_execution || data.best_execution));
    set('ltZrResearchTarget', `${Number(data.research_target_r || 2.2).toFixed(1)}R baseline`);
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
    ensurePanels();
    refresh();
    clearInterval(timer);
    timer = setInterval(refresh, 30000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();