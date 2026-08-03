const state = { dashboard: {}, candidates: [], lineages: [], mutations: [], packages: [], candidateFilter: 'all' };
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const fmt = new Intl.NumberFormat('en-GB');
const num = (value, digits=2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

async function api(path) {
  const response = await fetch(`/api${path}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

function setHealth(ok, message='Railway worker') {
  $('#healthDot').classList.toggle('ok', ok);
  $('#healthText').textContent = ok ? 'Online' : 'Offline';
  $('#workerText').textContent = message;
}

function metric(label, value, note='') {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
}

function sourceImportCount(event) {
  const direct = Number(event?.details?.imported);
  if (Number.isFinite(direct)) return direct;
  const match = String(event?.message || '').match(/(?:Imported|\+)([\d,]+).*snapshot/i);
  return match ? Number(match[1].replaceAll(',', '')) : 0;
}

function compactEvents(events) {
  const sourceEvents = events.filter(event => event.component === 'source_bridge');
  if (sourceEvents.length <= 1) return events;
  const latest = sourceEvents[0];
  const total = sourceEvents.reduce((sum, event) => sum + sourceImportCount(event), 0);
  const summary = {
    ...latest,
    message: `Source bridge advanced ${sourceEvents.length} times in this activity window · ${fmt.format(total)} snapshots imported · latest ${latest.message || ''}`
  };
  let inserted = false;
  return events.flatMap(event => {
    if (event.component !== 'source_bridge') return [event];
    if (inserted) return [];
    inserted = true;
    return [summary];
  });
}

function conditionLabel(condition={}) {
  const type = condition.type || '';
  const labels = {
    direction_matches_trend12: 'candle = trend12',
    direction_opposes_trend12: 'candle ≠ trend12',
    alignment_abs_min: `alignment ≥ ${condition.min}`,
    alignment_matches_direction: 'alignment = candle',
    alignment_opposes_direction: 'alignment ≠ candle',
    return_3_abs_min: `|3-bar return| ≥ ${condition.threshold}%`,
    return_3_matches_direction: '3-bar return = candle',
    impulse_1_vs_3: `1-bar impulse ≥ ${condition.ratio}× 3-bar`,
    close_location_extreme: `close in outer ${Math.round(Number(condition.edge||0)*100)}%`,
    wick_body_ratio_min: `wick ≥ ${condition.ratio}× body`,
    trend12_trend48_agree: 'trend12 = trend48',
  };
  return labels[type] || String(type).replaceAll('_',' ');
}

function valueText(value) {
  if (Array.isArray(value)) return value.map(item => typeof item === 'object' ? conditionLabel(item) : String(item)).join(', ');
  if (value && typeof value === 'object') return Object.entries(value).map(([key,val]) => `${key}: ${valueText(val)}`).join(' · ');
  return String(value ?? '—');
}

function renderOverview() {
  const d = state.dashboard;
  const runtime = d.runtime || {};
  $('#workerStatus').textContent = runtime.last_error ? 'SAFE FAILURE' : (runtime.autonomous_enabled ? 'AUTONOMOUS' : 'PAUSED');
  $('#lastAction').textContent = runtime.last_action || 'Waiting for first cycle';
  $('#lastError').textContent = runtime.last_error || '';
  $('#metrics').innerHTML = [
    metric('Source snapshots', fmt.format(d.source_snapshots || 0), 'read-only EVE copy'),
    metric('Strategies tested', fmt.format(d.candidates_tested || 0), `${fmt.format(d.candidates_queued || 0)} queued`),
    metric('Surviving ideas', fmt.format((d.candidates_promising||0)+(d.candidates_validated||0)+(d.candidates_elite||0)), 'promising or stronger'),
    metric('Active lineages', fmt.format(d.lineages_active || 0), 'mutating champions'),
    metric('Mutations promoted', fmt.format(d.mutations_promoted || 0), `${fmt.format(d.mutations_tested || 0)} tested`),
    metric('MT5 packages', fmt.format(d.mt5_packages || 0), 'downloadable .mq5'),
  ].join('');
  const top = d.top_lineage;
  $('#topLineage').className = `feature-card${top ? '' : ' empty'}`;
  $('#topLineage').innerHTML = top ? `<strong>${esc(top.name)}</strong><p>Generation ${esc(top.generation)} · fitness ${num(top.champion_fitness)} · ${esc(top.champion_result_status || 'active')}</p><small>${esc(top.last_result || '')}</small>` : 'No lineage has survived yet.';
  const events = compactEvents(Array.isArray(d.recent_events) ? d.recent_events : []);
  $('#events').innerHTML = events.length ? events.map(event => `<div class="event ${esc(event.level)}"><time>${new Date(event.created_at).toLocaleString('en-GB')}</time><span>${esc(event.component)}</span><b>${esc(event.message)}</b></div>`).join('') : '<div class="empty-state">No activity recorded yet. The first source bridge cycle will appear here.</div>';
  $('#dataRows').textContent = `${fmt.format(d.source_snapshots || 0)} snapshots`;
  $('#dataRange').textContent = d.source_from ? `${new Date(d.source_from).toLocaleDateString('en-GB')} → ${new Date(d.source_to).toLocaleDateString('en-GB')}` : 'Waiting for source sync.';
}

function ruleTags(rules={}) {
  const s=rules.schedule||{}, e=rules.environment||{}, r=rules.risk||{}, entry=rules.entry||{};
  const tags = [
    rules.family === 'composed_signal' ? 'independent recipe' : rules.family?.replaceAll('_',' '),
    s.everyday_target ? 'everyday target' : `${(s.weekdays||[]).length} weekdays`,
    (s.sessions||[]).join(', ') || ((s.hours_utc||[]).length===24 ? 'all day' : `${(s.hours_utc||[]).join(',')} UTC`),
    ...((entry.conditions||[]).map(conditionLabel)),
    `direction ${String(entry.direction_rule||'').replaceAll('_',' ')}`,
    `trend12 ${e.trend_12||'any'}`, `stop ${r.stop_atr} ATR`, `target ${r.target_atr} ATR`, `hold ${r.max_hold_minutes}m`
  ].filter(Boolean);
  return tags.map(tag=>`<span>${esc(tag)}</span>`).join('');
}

function candidateCard(item) {
  return `<article class="card">
    <div class="card-top"><div><p class="eyebrow">${esc((item.family||'strategy').replaceAll('_',' '))}</p><h3>${esc(item.name)}</h3></div><span class="badge ${esc(item.result_status||item.status)}">${esc((item.result_status||item.status||'queued').toUpperCase())}</span></div>
    <p>${esc(item.hypothesis || item.evidence?.summary || '')}</p>
    <div class="stat-row"><div class="stat"><span>Locked PF</span><strong>${num(item.profit_factor)}</strong></div><div class="stat"><span>Expectancy</span><strong>${num(item.expectancy_r,3)}R</strong></div><div class="stat"><span>Trades</span><strong>${fmt.format(item.trades_total||0)}</strong></div><div class="stat"><span>Stability</span><strong>${num(item.stability_score,0)}%</strong></div></div>
    <div class="rules">${ruleTags(item.rules)}</div>
  </article>`;
}

function renderCandidates() {
  const items = state.candidates.filter(item => state.candidateFilter==='all' || item.result_status===state.candidateFilter);
  $('#candidateList').innerHTML = items.length ? items.map(candidateCard).join('') : '<div class="empty-state">No strategies in this filter yet.</div>';
}

function renderLineages() {
  $('#lineageList').innerHTML = state.lineages.length ? state.lineages.map(item => `<article class="card"><div class="card-top"><div><p class="eyebrow">${esc((item.family||'family').replaceAll('_',' '))}</p><h3>${esc(item.name)}</h3></div><span class="badge ${esc(item.champion_result_status||'promising')}">GEN ${esc(item.generation)}</span></div><p>${esc(item.last_result || 'Active lineage')}</p><div class="stat-row"><div class="stat"><span>Champion fitness</span><strong>${num(item.champion_fitness)}</strong></div><div class="stat"><span>Status</span><strong>${esc(item.champion_result_status||'active')}</strong></div><div class="stat"><span>Generation</span><strong>${esc(item.generation)}</strong></div><div class="stat"><span>State</span><strong>${esc(item.status)}</strong></div></div><div class="rules">${ruleTags(item.champion_rules)}</div></article>`).join('') : '<div class="empty-state">Lineages appear after independent candidates survive their first chronological test.</div>';
}

function renderMutations() {
  const completed = state.mutations.filter(item => item.status === 'complete').slice(0, 30);
  $('#mutationList').innerHTML = completed.length ? completed.map(item => {
    const gene = item.mutation_gene || 'rule';
    const change = item.changes?.[gene] || {};
    const result = item.promoted ? 'promoted' : (item.result_status || 'rejected');
    return `<article class="card mutation-card">
      <div class="card-top"><div><p class="eyebrow">GEN ${esc(item.generation)} · ${esc(gene.replaceAll('_',' '))}</p><h3>${esc(item.name)}</h3></div><span class="badge ${item.promoted ? 'elite' : 'rejected'}">${item.promoted ? 'PROMOTED' : 'REJECTED'}</span></div>
      <div class="change-grid"><div><span>Before</span><strong>${esc(valueText(change.from))}</strong></div><div class="change-arrow">→</div><div><span>After</span><strong>${esc(valueText(change.to))}</strong></div></div>
      <p>${esc(item.selection_reason || 'Mutation completed.')}</p>
      <div class="stat-row"><div class="stat"><span>Fitness Δ</span><strong>${num(item.fitness_delta)}</strong></div><div class="stat"><span>Validation expectancy Δ</span><strong>${num(item.validation_expectancy_delta,3)}R</strong></div><div class="stat"><span>Validation PF Δ</span><strong>${num(item.validation_pf_delta,2)}</strong></div><div class="stat"><span>Result</span><strong>${esc(result)}</strong></div></div>
    </article>`;
  }).join('') : '<div class="empty-state">Mutation comparisons will appear here after the first lineage survives and creates children.</div>';
}

function renderPackages() {
  $('#packageList').innerHTML = state.packages.length ? state.packages.map(item => `<article class="card"><div class="card-top"><div><p class="eyebrow">${esc((item.family||'strategy').replaceAll('_',' '))}</p><h3>${esc(item.strategy_name)}</h3></div><span class="badge elite">READY FOR MT5</span></div><p>Frozen version ${esc(item.version)} · SHA-256 ${esc((item.sha256||'').slice(0,16))}… · ${fmt.format(item.size_bytes || 0)+' bytes'}</p><div class="download-row"><a class="download" href="/api/packages/${encodeURIComponent(item.id)}/download">Download package</a><a class="download secondary" href="/api/packages/${encodeURIComponent(item.id)}/mq5">Download .mq5</a></div></article>`).join('') : '<div class="empty-state">No strategy has passed every promotion gate yet. That is normal—the lab is designed to reject most ideas.</div>';
}

async function refresh() {
  try {
    const [dashboard, candidates, lineages, mutations, packages] = await Promise.all([
      api('/dashboard'), api('/candidates?limit=150'), api('/lineages?limit=100'), api('/mutations?limit=100'), api('/packages?limit=100')
    ]);
    state.dashboard=dashboard; state.candidates=candidates.items||[]; state.lineages=lineages.items||[]; state.mutations=mutations.items||[]; state.packages=packages.items||[];
    renderOverview(); renderCandidates(); renderLineages(); renderMutations(); renderPackages(); setHealth(true, dashboard.runtime?.last_action || 'Autonomous worker');
  } catch (error) {
    console.error(error); setHealth(false, error.message); $('#lastError').textContent=error.message;
  }
}

function switchView(view) {
  $$('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.view===view));
  $$('.view').forEach(section=>section.classList.toggle('active',section.id===`view-${view}`));
  $('#pageTitle').textContent = $(`.nav-item[data-view="${view}"] b`).textContent;
  location.hash=view;
}

$$('.nav-item').forEach(button=>button.addEventListener('click',()=>switchView(button.dataset.view)));
$$('[data-refresh]').forEach(button=>button.addEventListener('click',refresh));
$$('[data-candidate-filter]').forEach(button=>button.addEventListener('click',()=>{ state.candidateFilter=button.dataset.candidateFilter; $$('[data-candidate-filter]').forEach(x=>x.classList.toggle('active',x===button)); renderCandidates(); }));
setInterval(()=>$('#clock').textContent=new Date().toLocaleTimeString('en-GB',{timeZone:'UTC'}),1000);
setInterval(refresh,30000);
switchView(location.hash.replace('#','') || 'overview');
refresh();
