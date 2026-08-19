const eveIntelligenceState = { audit: {}, scientist: {} };

const pct = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';

function renderEveIntelligence() {
  const audit = eveIntelligenceState.audit || {};
  const scientist = eveIntelligenceState.scientist || {};
  const runtime = scientist.runtime || scientist.scientist || {};
  const coverage = audit.coverage || {};
  const gates = audit.gates || {};
  const causality = audit.causality_violations || {};
  const parity = audit.feature_parity || {};
  const ready = Boolean(audit.ready_for_scientist_cutover);
  const building = String(audit.build_status || '').toLowerCase() === 'building';

  const summary = $('#fabricSummary');
  if (summary) {
    const statusClass = ready ? 'ok' : building ? 'warn' : audit.last_error ? 'bad' : 'warn';
    const title = ready ? 'READY FOR SCIENTIST CUTOVER' : building ? 'BUILDING SIX-YEAR M5 FABRIC' : audit.last_error ? 'FABRIC NEEDS ATTENTION' : 'AUDITING FABRIC';
    const message = ready
      ? 'Every hard integrity gate has passed. The new every-M5 multi-timeframe dataset is eligible for controlled scientist cutover.'
      : building
        ? `${fmt.format(audit.rows || 0)} M5 research states built so far. Scientist v2 remains on the trusted legacy dataset until the audit passes.`
        : (audit.last_error || 'Waiting for the next fabric audit result.');
    summary.innerHTML = `<div><span class="status-orb ${statusClass}"></span><div><p class="eyebrow">FABRIC STATUS</p><h3>${esc(title)}</h3><p>${esc(message)}</p></div></div><small>${esc(audit.last_time ? `Built through ${dateText(audit.last_time)}` : 'No completed fabric timestamp yet')}</small>`;
  }

  const metrics = $('#fabricMetrics');
  if (metrics) {
    metrics.innerHTML = [
      ['M5 states', fmt.format(audit.rows || 0), 'every completed M5 observation'],
      ['M1 coverage', pct(coverage.M1), 'microstructure inside each M5'],
      ['HTF coverage', pct(Math.min(Number(coverage.M15 ?? 0), Number(coverage.M30 ?? 0), Number(coverage.H1 ?? 0), Number(coverage.H4 ?? 0), Number(coverage.D1 ?? 0))), 'M15 · M30 · H1 · H4 · D1'],
      ['Feature parity', pct(parity.pass_rate), `${fmt.format(parity.rows_matching || 0)} / ${fmt.format(parity.rows_compared || 0)} matched`],
      ['Look-ahead errors', fmt.format(causality.total || 0), 'must remain exactly zero'],
      ['Scientist cutover', ready ? 'READY' : 'LOCKED', ready ? 'all gates passed' : 'legacy dataset remains active']
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
      check('Inherited feature parity', Boolean(gates.feature_parity), `${pct(parity.pass_rate)} parity against trusted 15-minute anchors`)
    ].join('');
  }

  const scientistBox = $('#scientistRuntime');
  if (scientistBox) {
    const capabilities = runtime.capabilities || [];
    scientistBox.className = 'feature-card';
    scientistBox.innerHTML = `<div class="card-top"><div><h3>${esc(runtime.version || 'EVE Scientist')}</h3><p>${esc(runtime.observation_version || 'Causal market observation engine')}</p></div>${badge(runtime.last_error ? 'failed' : 'active')}</div>${stats([
      ['Science cycles', fmt.format(runtime.science_cycles || 0)],
      ['Screened', fmt.format(runtime.hypotheses_screened || 0)],
      ['Queued', fmt.format(runtime.hypotheses_queued || 0)],
      ['Memory features', fmt.format(runtime.memory_features || 0)]
    ])}<div class="rules">${capabilities.slice(0, 12).map(x => `<span>${esc(human(x))}</span>`).join('')}</div><p>${esc(runtime.last_error || (runtime.last_science_at ? `Last scientist cycle ${dateText(runtime.last_science_at)}` : 'Scientist is active and waiting for its next autonomous cycle.'))}</p>`;
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
