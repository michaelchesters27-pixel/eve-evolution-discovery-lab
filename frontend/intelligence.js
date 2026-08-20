const eveIntelligenceState = { audit: {}, scientist: {} };

const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';

function renderEveIntelligence() {
  const audit = eveIntelligenceState.audit || {};
  const scientist = eveIntelligenceState.scientist || {};
  const runtime = scientist.runtime || scientist.scientist || {};
  const authority = audit.scientist_authority || {};
  const persistent = audit.scientist_persistent_stats || {};
  const coverage = audit.coverage || {};
  const gates = audit.gates || {};
  const causality = audit.causality_violations || {};
  const parity = audit.feature_parity || {};
  const ready = Boolean(audit.ready_for_scientist_cutover);
  const persistedFabricActive = String(authority.active_dataset || '').toLowerCase() === 'every_m5_fabric' && String(authority.status || '').toLowerCase() === 'active';
  const runtimeFabricActive = String(runtime.active_dataset || '').toLowerCase() === 'every_m5_fabric' && String(runtime.dataset_status || '').toLowerCase() === 'active';
  const activeFabric = persistedFabricActive || runtimeFabricActive;
  const building = String(audit.build_status || '').toLowerCase() === 'building';
  const memoryFeatures = Math.max(Number(runtime.memory_features || 0), Number(audit.scientist_memory_features || 0));
  const scienceCycles = Math.max(Number(runtime.science_cycles || 0), Number(persistent.science_cycles || 0));
  const screened = Math.max(Number(runtime.hypotheses_screened || 0), Number(persistent.screened || 0));
  const queued = Math.max(Number(runtime.hypotheses_queued || 0), Number(persistent.queued || 0));
  const lastScienceAt = runtime.last_science_at || persistent.last_science_at || null;
  const cutoverAt = runtime.cutover_at || authority.cutover_at || null;

  const summary = $('#fabricSummary');
  if (summary) {
    const statusClass = activeFabric || ready ? 'ok' : building ? 'warn' : audit.last_error ? 'bad' : 'warn';
    const title = activeFabric ? 'SCIENTIST V2 ACTIVE ON EVERY-M5 FABRIC' : ready ? 'READY FOR SCIENTIST CUTOVER' : building ? 'BUILDING SIX-YEAR M5 FABRIC' : audit.last_error ? 'FABRIC NEEDS ATTENTION' : 'AUDITING FABRIC';
    const message = activeFabric
      ? `Scientist v2 is authorised to research the every-M5 multi-timeframe fabric. New scientist hypotheses are tied to the 5-minute dataset and cannot be validated on the legacy 15-minute dataset.`
      : ready
        ? 'Every hard integrity gate has passed. The new every-M5 multi-timeframe dataset is eligible for controlled scientist cutover.'
        : building
          ? `${fmt.format(audit.rows || 0)} M5 research states built so far. Scientist v2 remains on the trusted legacy dataset until the audit passes.`
          : (audit.last_error || 'Waiting for the next fabric audit result.');
    summary.innerHTML = `<div><span class="status-orb ${statusClass}"></span><div><p class="eyebrow">FABRIC STATUS</p><h3>${esc(title)}</h3><p>${esc(message)}</p></div></div><small>${esc(audit.last_time ? `Built through ${dateText(audit.last_time)}` : 'No completed fabric timestamp yet')}</small>`;
  }

  const metrics = $('#fabricMetrics');
  if (metrics) {
    const scientistDatasetValue = activeFabric ? 'ACTIVE M5' : ready ? 'READY' : 'LEGACY';
    const scientistDatasetNote = activeFabric
      ? `${fmt.format(runtime.dataset_rows || audit.rows || 0)} M5 states under scientist authority`
      : ready
        ? 'all gates passed; awaiting runtime activation'
        : 'legacy 15-minute dataset remains active';
    metrics.innerHTML = [
      ['M5 states', fmt.format(audit.rows || 0), 'every completed M5 observation'],
      ['M1 coverage', pct(coverage.M1), 'microstructure inside each M5'],
      ['HTF coverage', pct(Math.min(Number(coverage.M15 ?? 0), Number(coverage.M30 ?? 0), Number(coverage.H1 ?? 0), Number(coverage.H4 ?? 0), Number(coverage.D1 ?? 0))), 'M15 · M30 · H1 · H4 · D1'],
      ['Feature parity', pct(parity.pass_rate), `${fmt.format(parity.rows_matching || 0)} / ${fmt.format(parity.rows_compared || 0)} matched`],
      ['Look-ahead errors', fmt.format(causality.total || 0), 'must remain exactly zero'],
      ['Scientist dataset', scientistDatasetValue, scientistDatasetNote]
    ].map(x => metric(...x)).join('');
  }

  const fabric = $('#timeframeFabric');
  if (fabric) {
    fabric.innerHTML = [
      check('M1 microstructure', Number(coverage.M1 || 0) >= 0.95, `${pct(coverage.M1)} coverage · five completed M1 bars inside each signal M5`),
      check('M5 primary state', Number(audit.rows || 0) > 0, `${fmt.format(audit.rows || 0)} every-M5 research observations built`),
      check('M15 context', Number(coverage.M15 || 0) >= 0.98, `${pct(coverage.M15)} causal completed-candle coverage`),
      check('M30 context', Number(coverage.M30 || 0) >= 0.98, `${pct(coverage.M30)} coverage · derived from six exact M5 candles`),
      check('H1 context', Number(coverage.H1 || 0) >= 0.98, `${pct(coverage.H1)} completed-candle coverage`),
      check('H4 context', Number(coverage.H4 || 0) >= 0.98, `${pct(coverage.H4)} completed-candle coverage`),
      check('Daily context', Number(coverage.D1 || 0) >= 0.98, `${pct(coverage.D1)} completed-candle coverage`)
    ].join('');
  }

  const gateBox = $('#fabricGates');
  if (gateBox) {
    gateBox.innerHTML = [
      check('Six-year build caught up', Boolean(gates.caught_up), audit.cursor_time ? `Cursor ${dateText(audit.cursor_time)}` : 'Waiting for build cursor'),
      check('Enough history', Boolean(gates.enough_history), `${fmt.format(audit.rows || 0)} rows built; gate requires the minimum research history`),
      check('M1 coverage gate', Boolean(gates.m1_coverage), `${pct(coverage.M1)} · gate requires at least 95%`),
      check('Higher-timeframe coverage', Boolean(gates.higher_timeframe_coverage), 'M15/M30/H1/H4/D1 must each meet the coverage threshold'),
      check('Zero look-ahead', Boolean(gates.zero_lookahead), `${fmt.format(causality.total || 0)} causality violations found`),
      check('Historical outcomes', Boolean(gates.historical_outcomes), `${pct(coverage.historical_outcomes)} completed forward-label coverage`),
      check('Inherited feature parity', Boolean(gates.feature_parity), `${pct(parity.pass_rate)} parity against trusted 15-minute anchors`),
      check('Scientist dataset authority', activeFabric, activeFabric ? `ACTIVE · every-M5 fabric${cutoverAt ? ` · cut over ${dateText(cutoverAt)}` : ''}` : ready ? 'Fabric eligible; waiting for Scientist runtime authority.' : 'Scientist remains on legacy dataset.')
    ].join('');
  }

  const scientistBox = $('#scientistRuntime');
  if (scientistBox) {
    const capabilities = runtime.capabilities || [];
    scientistBox.className = 'feature-card';
    scientistBox.innerHTML = `<div class="card-top"><div><h3>${esc(runtime.version || 'EVE Scientist')}</h3><p>${esc(runtime.observation_version || 'Causal market observation engine')}</p></div>${badge(runtime.last_error ? 'failed' : 'active')}</div>${stats([
      ['Dataset', activeFabric ? 'Every M5' : 'Legacy 15m'],
      ['Science cycles', fmt.format(scienceCycles)],
      ['Screened', fmt.format(screened)],
      ['Queued', fmt.format(queued)],
      ['Memory features', fmt.format(memoryFeatures)]
    ])}<div class="rules">${capabilities.slice(0, 12).map(x => `<span>${esc(human(x))}</span>`).join('')}</div><p>${esc(runtime.last_error || (lastScienceAt ? `Last scientist cycle ${dateText(lastScienceAt)}` : activeFabric ? 'Scientist is active on the every-M5 fabric and working through its next autonomous cycle.' : 'Scientist is active and waiting for its next autonomous cycle.'))}</p>`;
  }

  const directorBox = $('#researchDirector');
  if (directorBox) {
    const director = runtime.research_director || {};
    const families = Array.isArray(director.families) ? director.families : [];
    const strongest = director.strongest_families || [];
    const weakest = director.weakest_families || [];
    directorBox.className = `feature-card ${families.length ? '' : 'empty'}`;
    if (families.length) {
      directorBox.innerHTML = `<div class="card-top"><div><h3>${esc(runtime.research_director_version || director.version || 'EVE Research Director')}</h3><p>${esc(director.policy || 'Evidence-weighted research allocation')}</p></div>${badge('active')}</div>${stats([
        ['Memory used', fmt.format(director.memory_features || memoryFeatures)],
        ['Families tracked', fmt.format(families.length)],
        ['Strongest', strongest.length ? strongest.map(human).join(', ') : 'Exploration'],
        ['Weakest', weakest.length ? weakest.map(human).join(', ') : 'None yet']
      ])}<div class="rules">${families.slice(0, 8).map(x => `<span>${esc(`${human(x.family)} · score ${num(x.evidence_score,2)} · ${fmt.format(x.trials || 0)} trials`)}</span>`).join('')}</div><p>EVE shrinks weak single-trial evidence, follows repeated positive evidence more often, and keeps an exploration floor so it can still discover something new.</p>`;
    } else {
      directorBox.textContent = 'Waiting for the first Research Director cycle on the deployed runtime.';
    }
  }

  const ablationBox = $('#ablationSummary');
  if (ablationBox) {
    const ablation = runtime.ablation || {};
    const checked = Number(ablation.hypotheses_checked || 0);
    const simplified = Number(ablation.hypotheses_simplified || 0);
    const removed = Number(ablation.conditions_removed || 0);
    ablationBox.className = `feature-card ${checked ? '' : 'empty'}`;
    if (checked) {
      ablationBox.innerHTML = `<div class="card-top"><div><h3>${esc(ablation.version || 'Development ablation')}</h3><p>Qualified ideas are simplified before sealed validation.</p></div>${badge('active')}</div>${stats([
        ['Checked', fmt.format(checked)],
        ['Simplified', fmt.format(simplified)],
        ['Conditions removed', fmt.format(removed)],
        ['Sealed data used', 'NO']
      ])}<p>${removed ? `EVE removed ${fmt.format(removed)} condition${removed === 1 ? '' : 's'} that did not earn their place while preserving the development edge.` : 'No condition could be safely removed in the latest cycle.'}</p>`;
    } else {
      ablationBox.textContent = 'Waiting for a qualified hypothesis to reach development-only simplification.';
    }
  }

  if (activeFabric && !audit.last_error) {
    setHealth(true, `Scientist v2 · Every M5 · ${fmt.format(audit.rows || 0)} states`);
  }

  const setups = scientist.live_setups || [];
  const radar = $('#liveRadar');
  if (radar) {
    const interesting = setups.filter(x => ['watching','armed','triggered'].includes(String(x.status || '').toLowerCase())).slice(0, 6);
    radar.innerHTML = interesting.length ? interesting.map(x => `<article class="card"><div class="card-top"><div><h3>${esc(x.name || x.strategy_code || 'Frozen discovery')}</h3><p>${esc(`${x.symbol || 'XAU/USD'} ${x.timeframe || 'M5'} · ${x.matched_conditions || 0}/${x.total_conditions || 0} conditions`)}</p></div>${badge(x.status)}</div>${stats([['Direction', String(x.direction || 'none').toUpperCase()],['Similarity',`${num(x.similarity,1)}%`],['Snapshot',dateText(x.snapshot_time)],['State',human(x.status||'idle')]])}</article>`).join('') : '<div class="empty-state">No validated discovery is WATCHING, ARMED or TRIGGERED right now.</div>';
  }

  const hypotheses = scientist.recent_hypotheses || [];
  const hypothesisBox = $('#scientistHypotheses');
  if (hypothesisBox) {
    hypothesisBox.innerHTML = hypotheses.length ? hypotheses.slice(0, 8).map(x => `<article class="card"><div class="card-top"><div><h3>${esc(x.hypothesis_key || 'Scientist hypothesis')}</h3><p>${esc(x.hypothesis || 'No hypothesis description recorded.')}</p></div>${badge(x.state || 'observed')}</div>${stats([['Development score',num(x.development_score,3)],['Timeframe',x.timeframe||'M5'],['Scientist',x.scientist_version||'—'],['Created',dateText(x.created_at)]])}</article>`).join('') : '<div class="empty-state">No autonomous scientist hypotheses have been recorded yet.</div>';
  }
}

async function refreshEveIntelligence() {
  try {
    const [audit, scientist] = await Promise.all([api('/fabric/audit'), api('/intelligence')]);
    eveIntelligenceState.audit = audit || {};
    eveIntelligenceState.scientist = scientist || {};
    renderEveIntelligence();
  } catch (error) {
    const summary = $('#fabricSummary');
    if (summary) summary.innerHTML = `<div><span class="status-orb bad"></span><div><p class="eyebrow">FABRIC STATUS</p><h3>UNAVAILABLE</h3><p>${esc(error.message)}</p></div></div>`;
  }
}

$$('[data-intelligence-refresh]').forEach(btn => btn.addEventListener('click', refreshEveIntelligence));
refreshEveIntelligence();
setInterval(refreshEveIntelligence, 30000);
