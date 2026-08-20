const eveIntelligenceState = { audit: {}, scientist: {} };

const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
const DEFAULT_DEV_GATES = { trades: 120, profit_factor: 1.03, expectancy_r: 0.01, positive_year_rate: 0.50 };

function gateLabel(value) {
  const labels = {
    development_sample: 'Development sample too small',
    development_profit_factor: 'Development PF below gate',
    development_expectancy: 'Development expectancy below gate',
    development_year_stability: 'Development yearly stability below gate',
    validation_sample: 'Validation sample too small',
    validation_edge: 'Validation edge too weak',
    rolling_stability: 'Rolling stability failed',
    parameter_neighbourhood: 'Parameter robustness failed',
    monte_carlo_confidence: 'Monte Carlo confidence failed'
  };
  return labels[String(value || '')] || human(value || 'unknown gate');
}

function developmentEvidence(hypothesis) {
  const metrics = hypothesis.development_metrics || {};
  const persisted = (hypothesis.evidence || {}).development || {};
  const thresholds = persisted.thresholds || DEFAULT_DEV_GATES;
  let failed = Array.isArray(persisted.failed_gates) ? [...persisted.failed_gates] : [];
  if (!failed.length && String(hypothesis.state || '').toLowerCase() === 'rejected_development') {
    if (Number(metrics.trades || 0) < Number(thresholds.trades ?? DEFAULT_DEV_GATES.trades)) failed.push('development_sample');
    if (Number(metrics.profit_factor || 0) < Number(thresholds.profit_factor ?? DEFAULT_DEV_GATES.profit_factor)) failed.push('development_profit_factor');
    if (Number(metrics.expectancy_r || 0) < Number(thresholds.expectancy_r ?? DEFAULT_DEV_GATES.expectancy_r)) failed.push('development_expectancy');
    if (Number(metrics.positive_year_rate || 0) < Number(thresholds.positive_year_rate ?? DEFAULT_DEV_GATES.positive_year_rate)) failed.push('development_year_stability');
  }
  const reason = persisted.plain_reason || (failed.length ? failed.map(gateLabel).join(' · ') : 'Development gates passed.');
  return { metrics, thresholds, failed, reason };
}

function hypothesisCard(hypothesis) {
  const state = String(hypothesis.state || 'observed').toLowerCase();
  const dev = developmentEvidence(hypothesis);
  const selection = ((hypothesis.evidence || {}).selection || {});
  const validation = selection.validation || {};
  const selectionFailed = Array.isArray(selection.failed_gates) ? selection.failed_gates : [];
  const hasSelection = Object.keys(validation).length > 0 || selectionFailed.length > 0;
  const stageMetrics = hasSelection ? validation : dev.metrics;
  const stageName = hasSelection ? 'Validation' : 'Development';
  let reason = '';
  if (state === 'rejected_selection') {
    reason = selection.plain_reason || (selectionFailed.length ? selectionFailed.map(gateLabel).join(' · ') : 'Selection gates rejected this candidate.');
  } else if (state === 'rejected_development') {
    reason = dev.reason;
  } else if (state === 'queued_for_selection') {
    reason = 'Development gates passed. Waiting for sealed selection validation.';
  } else if (selection.plain_reason) {
    reason = selection.plain_reason;
  }

  const reasonTags = state === 'rejected_selection' ? selectionFailed : state === 'rejected_development' ? dev.failed : [];
  const tinySample = !hasSelection && Number(dev.metrics.trades || 0) < Number(dev.thresholds.trades ?? DEFAULT_DEV_GATES.trades);
  const scoreNote = tinySample && Number(hypothesis.development_score || 0) > 100
    ? 'High ranking score came from a tiny sample; EVE correctly rejected it on the hard sample gate.'
    : 'Development score is a ranking number only. Hard gates decide whether an idea advances.';

  return `<article class="card"><div class="card-top"><div><h3>${esc(hypothesis.hypothesis_key || 'Scientist hypothesis')}</h3><p>${esc(hypothesis.hypothesis || 'No hypothesis description recorded.')}</p></div>${badge(hypothesis.state || 'observed')}</div>${stats([
    [`${stageName} trades`, fmt.format(stageMetrics.trades || 0)],
    [`${stageName} PF`, num(stageMetrics.profit_factor, 3)],
    [`${stageName} expectancy`, `${num(stageMetrics.expectancy_r, 3)}R`],
    ['Positive years', pct(stageMetrics.positive_year_rate)],
    ['Development score', num(hypothesis.development_score, 3)]
  ])}${reasonTags.length ? `<div class="rules">${reasonTags.map(x => `<span>${esc(gateLabel(x))}</span>`).join('')}</div>` : ''}${reason ? `<p><b>${state.startsWith('rejected') ? 'Why rejected:' : 'Status:'}</b> ${esc(reason.replace(/^Failed:\s*/i, ''))}</p>` : ''}<small>${esc(scoreNote)}</small></article>`;
}

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
  const auditedRows = Number(audit.rows || 0);
  const builtRows = Number(audit.fabric_rows_total || audit.rows || runtime.dataset_rows || 0);
  const labelledRows = Number(audit.fabric_rows_complete || runtime.dataset_rows || audit.rows || 0);

  const summary = $('#fabricSummary');
  if (summary) {
    const statusClass = activeFabric || ready ? 'ok' : building ? 'warn' : audit.last_error ? 'bad' : 'warn';
    const title = activeFabric ? 'SCIENTIST V2 ACTIVE ON EVERY-M5 FABRIC' : ready ? 'READY FOR SCIENTIST CUTOVER' : building ? 'BUILDING SIX-YEAR M5 FABRIC' : audit.last_error ? 'FABRIC NEEDS ATTENTION' : 'AUDITING FABRIC';
    const message = activeFabric
      ? `Scientist v2 is authorised to research the every-M5 multi-timeframe fabric. New scientist hypotheses are tied to the 5-minute dataset and cannot be validated on the legacy 15-minute dataset.`
      : ready
        ? 'Every hard integrity gate has passed. The new every-M5 multi-timeframe dataset is eligible for controlled scientist cutover.'
        : building
          ? `${fmt.format(builtRows)} M5 research states built so far. Scientist v2 remains on the trusted legacy dataset until the audit passes.`
          : (audit.last_error || 'Waiting for the next fabric audit result.');
    summary.innerHTML = `<div><span class="status-orb ${statusClass}"></span><div><p class="eyebrow">FABRIC STATUS</p><h3>${esc(title)}</h3><p>${esc(message)}</p></div></div><small>${esc(audit.last_time ? `Built through ${dateText(audit.last_time)}` : 'No completed fabric timestamp yet')}</small>`;
  }

  const metrics = $('#fabricMetrics');
  if (metrics) {
    const scientistDatasetValue = activeFabric ? 'ACTIVE M5' : ready ? 'READY' : 'LEGACY';
    const scientistDatasetNote = activeFabric
      ? `${fmt.format(labelledRows)} fully labelled M5 states eligible for Scientist research`
      : ready
        ? 'all gates passed; awaiting runtime activation'
        : 'legacy 15-minute dataset remains active';
    metrics.innerHTML = [
      ['M5 states built', fmt.format(builtRows), `${fmt.format(labelledRows)} fully labelled · ${fmt.format(auditedRows)} integrity-audited`],
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
      check('M5 primary state', builtRows > 0, `${fmt.format(builtRows)} built · ${fmt.format(labelledRows)} fully labelled for research`),
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
      check('Enough history', Boolean(gates.enough_history), `${fmt.format(auditedRows)} integrity-audited · ${fmt.format(labelledRows)} fully labelled`),
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
    const interaction = runtime.interaction_memory || {};
    const families = Array.isArray(director.families) ? director.families : [];
    const strongest = director.strongest_families || [];
    const weakest = director.weakest_families || [];
    const researchMode = strongest.length ? 'Evidence-guided' : 'Exploration';
    const leadingFamily = strongest.length ? strongest.map(human).join(', ') : 'None proven yet';
    directorBox.className = `feature-card ${families.length ? '' : 'empty'}`;
    if (families.length) {
      directorBox.innerHTML = `<div class="card-top"><div><h3>${esc(runtime.research_director_version || director.version || 'EVE Research Director')}</h3><p>${esc(director.policy || 'Evidence-weighted research allocation')}</p></div>${badge('active')}</div>${stats([
        ['Memory used', fmt.format(director.memory_features || memoryFeatures)],
        ['Families tracked', fmt.format(families.length)],
        ['Feature pairs learned', fmt.format(interaction.interactions || 0)],
        ['Research mode', researchMode],
        ['Leading family', leadingFamily],
        ['Weakest', weakest.length ? weakest.map(human).join(', ') : 'None yet']
      ])}<div class="rules">${families.slice(0, 8).map(x => `<span>${esc(`${human(x.family)} · score ${num(x.evidence_score,2)} · ${fmt.format(x.trials || 0)} trials`)}</span>`).join('')}</div><p>${strongest.length ? 'Repeated positive evidence is now steering more research budget, while an exploration floor remains active.' : 'No family has earned a positive leadership signal yet. EVE is deliberately staying in exploration mode instead of pretending weak evidence is a winner.'}</p>`;
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
    setHealth(true, `Scientist v2 · Every M5 · ${fmt.format(labelledRows)} labelled states`);
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
    hypothesisBox.innerHTML = hypotheses.length ? hypotheses.slice(0, 8).map(hypothesisCard).join('') : '<div class="empty-state">No autonomous scientist hypotheses have been recorded yet.</div>';
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
