const state = { dashboard: {}, dataHealth: {}, candidates: [], lineages: [], mutations: [], packages: [], candidateFilter: 'all' };
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const fmt = new Intl.NumberFormat('en-GB');
const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const num = (value, digits=2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
const dateText = value => value ? new Date(value).toLocaleString('en-GB', {timeZone:'UTC', dateStyle:'medium', timeStyle:'short'}) + ' UTC' : '—';

let tokenPromptPromise = null;
async function adminToken(force=false) {
  if (!force) {
    const saved=sessionStorage.getItem('eveDiscoveryAdminToken')||'';
    if (saved) return saved;
    if (tokenPromptPromise) return tokenPromptPromise;
  }
  tokenPromptPromise=Promise.resolve(prompt(force ? 'The token was rejected. Enter the Discovery Lab ADMIN_TOKEN again:' : 'Enter the Discovery Lab ADMIN_TOKEN to unlock the private research operating system:')||'')
    .then(token=>{ if(token) sessionStorage.setItem('eveDiscoveryAdminToken',token); return token; })
    .finally(()=>{ tokenPromptPromise=null; });
  return tokenPromptPromise;
}

async function api(path, options={}) {
  let token=await adminToken();
  if (!token) throw new Error('Discovery Lab remains locked until ADMIN_TOKEN is entered.');
  const headers=new Headers(options.headers||{});headers.set('X-Admin-Token',token);
  let response=await fetch(`/api${path}`, { cache: 'no-store', ...options, headers });
  if (response.status===401) {
    sessionStorage.removeItem('eveDiscoveryAdminToken');
    token=await adminToken(true);
    if (!token) throw new Error('Discovery Lab remains locked.');
    headers.set('X-Admin-Token',token);
    response=await fetch(`/api${path}`, { cache: 'no-store', ...options, headers });
  }
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

function setHealth(ok, text='Railway worker') {
  $('#healthDot').classList.toggle('ok', ok);
  $('#healthDot').classList.toggle('bad', !ok);
  $('#healthText').textContent = ok ? 'Research online' : 'Research offline';
  $('#workerText').textContent = text;
}

function metric(label, value, note='') {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
}

function badge(value) {
  const text = String(value || 'unknown');
  return `<span class="badge ${esc(text.toLowerCase())}">${esc(text.replaceAll('_',' '))}</span>`;
}

function stats(items) {
  return `<div class="stat-row">${items.map(([label,value]) => `<div class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('')}</div>`;
}

function compactEvents(events=[]) {
  const source = events.filter(e => e.component === 'source_bridge');
  if (source.length < 2) return events;
  const imported = source.reduce((sum, e) => sum + Number(e?.details?.imported || 0), 0);
  const summary = {...source[0], message:`Source bridge advanced ${source.length} times · ${fmt.format(imported)} market states imported · latest ${source[0].message || ''}`};
  let used=false;
  return events.flatMap(e => e.component !== 'source_bridge' ? [e] : used ? [] : (used=true,[summary]));
}

function renderOverview() {
  const d=state.dashboard, r=d.runtime || {};
  const runtimeHealthy = !r.last_error && Boolean(r.last_successful_cycle_at || r.cycle_count === 0);
  setHealth(runtimeHealthy, `${r.research_timeframe || '—'} from ${r.source_candle_interval || '—'} candles · ${r.source_credential_mode || 'credential unknown'}`);
  $('#workerStatus').textContent = r.last_error ? 'SAFE FAILURE' : r.autonomous_enabled ? 'AUTONOMOUS' : 'PAUSED';
  $('#workerStatus').className = `status-pill ${r.last_error ? 'error' : ''}`;
  $('#lastAction').textContent = r.last_action || 'Waiting for first cycle';
  $('#lastCycle').textContent = r.last_successful_cycle_at ? `Last successful cycle ${dateText(r.last_successful_cycle_at)}` : 'No successful cycle reported yet';
  $('#lastError').textContent = r.last_error || '';
  $('#metrics').innerHTML = [
    ['Market states',fmt.format(d.snapshots||0),'local research copy'],
    ['Experiments',fmt.format(d.candidates_tested||0),'selection tests complete'],
    ['Active lineages',fmt.format(d.lineages_active||0),'still breeding'],
    ['Finalised',fmt.format(d.lineages_finalised||0),'holdout opened once'],
    ['Promoted mutations',fmt.format(d.mutations_promoted||0),'selection winners'],
    ['MT5 packages',fmt.format(d.mt5_packages||0),'final survivors']
  ].map(x=>metric(...x)).join('');
  $('#integrityStrip').innerHTML = [
    ['Selection data only','Development and validation breed strategies',true],
    ['Final holdout sealed','Opened once for a mature finalist',true],
    ['M1 execution replay',r.m1_replay_enabled ? 'Mandatory before freezing' : 'Disabled — no strategy can freeze',Boolean(r.m1_replay_enabled)],
    ['Production writes',r.production_write_surface === 'none' ? 'None' : r.production_write_surface,r.production_write_surface === 'none']
  ].map(([title,body,ok])=>`<div class="integrity ${ok?'ok':'bad'}"><span>${ok?'✓':'!'}</span><div><b>${esc(title)}</b><small>${esc(body)}</small></div></div>`).join('');
  const line=d.top_lineage;
  $('#topLineage').className=`feature-card ${line?'':'empty'}`;
  $('#topLineage').innerHTML=line ? `<div class="card-top"><div><h3>${esc(line.name)}</h3><p>${esc(line.family)} · ${esc(line.symbol||'XAU/USD')} ${esc(line.timeframe||'M5')}</p></div>${badge(line.status)}</div>${stats([['Generation',line.generation??0],['Fitness',num(line.champion_fitness)],['Selection',line.champion_result_status||'—'],['Final',line.final_result_status||'not opened']])}<p>${esc(line.last_result||'')}</p>` : 'No lineage has survived selection yet.';
  const events=compactEvents(d.recent_events||[]);
  $('#events').innerHTML=events.length ? events.map(e=>`<div class="event ${esc(e.level)}"><time>${esc(dateText(e.created_at).replace(' UTC',''))}</time><span>${esc(e.component)}</span><b>${esc(e.message)}</b></div>`).join('') : '<div class="empty-state">No research activity recorded yet.</div>';
}

function rulesSummary(item) {
  const rules=item.rules||{}, schedule=rules.schedule||{}, risk=rules.risk||{}, market=rules.market||{};
  const hours=(schedule.hours_utc||[]).length ? `${Math.min(...schedule.hours_utc)}:00–${Math.max(...schedule.hours_utc)+1}:00 UTC` : (schedule.sessions||[]).join(', ') || 'all sessions';
  return [market.symbol||item.symbol||'XAU/USD', market.timeframe||item.timeframe||'M5', rules.family||item.family, hours, `SL ${risk.stop_atr??'—'} ATR`, `TP ${risk.target_atr??'—'} ATR`];
}

function renderCandidates() {
  const filter=state.candidateFilter;
  const items=state.candidates.filter(x => filter==='all' || x.result_status===filter || x.status===filter);
  $('#candidateList').innerHTML=items.length ? items.map(item=>{
    const validation=item.metrics?.validation||{};
    const sealed=Boolean(item.metrics?.holdout?.sealed);
    return `<article class="card"><div class="card-top"><div><h3>${esc(item.name)}</h3><p>${esc(item.hypothesis||'No hypothesis recorded.')}</p></div>${badge(item.result_status||item.status)}</div>${stats([['Market',`${item.symbol||'XAU/USD'} ${item.timeframe||'M5'}`],['Validation PF',num(validation.profit_factor)],['Expectancy',`${num(validation.expectancy_r,3)}R`],['Trades',fmt.format(validation.trades||0)]])}<div class="rules">${rulesSummary(item).map(x=>`<span>${esc(x)}</span>`).join('')}</div><div class="evidence-note ${sealed?'sealed':''}"><b>${sealed?'Holdout sealed':'Final evidence opened'}</b><span>${sealed?'This experiment cannot see confirmation or final holdout while being selected.':'This record contains final-stage evidence.'}</span></div><p class="decision">${esc(item.evidence?.decision?.plain_reason||item.error||'Awaiting research.')}</p><small class="dataset">${esc(item.dataset_version||'dataset not assigned')}</small></article>`;
  }).join('') : '<div class="empty-state">No experiments match this filter.</div>';
}

function pretty(value) { return typeof value === 'string' ? value : JSON.stringify(value); }
function renderEvolution() {
  $('#lineageList').innerHTML=state.lineages.length ? state.lineages.map(x=>`<article class="card lineage"><div class="card-top"><div><h3>${esc(x.name)}</h3><p>${esc(x.family)} · ${esc(x.symbol||'XAU/USD')} ${esc(x.timeframe||'M5')}</p></div>${badge(x.status)}</div>${stats([['Generation',x.generation??0],['Champion fitness',num(x.champion_fitness)],['Selection',x.champion_result_status||'—'],['Final',x.final_result_status||'not opened']])}<div class="timeline"><span class="done">Seed</span><span class="done">Selection</span><span class="${Number(x.generation)>0?'done':''}">Mutation</span><span class="${x.holdout_opened_at?'done':''}">Final holdout</span><span class="${x.final_result_status==='validated'||x.final_result_status==='elite'?'done':''}">Survivor</span></div><p>${esc(x.last_result||'No lineage decision recorded.')}</p><small class="dataset">${esc(x.dataset_version||'dataset not assigned')}</small></article>`).join('') : '<div class="empty-state">No active or retired lineage exists yet.</div>';
  $('#mutationList').innerHTML=state.mutations.length ? state.mutations.map(x=>{
    const change=x.changes?.[x.mutation_gene]||{};
    return `<article class="card mutation-card"><div class="card-top"><div><h3>${esc(x.name)}</h3><p>${esc(x.selection_reason||'Awaiting selection decision.')}</p></div>${badge(x.promoted?'promoted':x.result_status||x.status)}</div><div class="change-grid"><div><span>Parent</span><strong>${esc(pretty(change.from))}</strong></div><div class="change-arrow">→</div><div><span>Child</span><strong>${esc(pretty(change.to))}</strong></div></div>${stats([['Gene',x.mutation_gene||'—'],['Fitness Δ',num(x.fitness_delta)],['Expectancy Δ',`${num(x.validation_expectancy_delta,3)}R`],['Holdout used',x.holdout_used_for_selection?'YES':'NO']])}</article>`;
  }).join('') : '<div class="empty-state">No mutation decisions recorded yet.</div>';
}

function passportRows(passport={}) {
  const use=(passport.use_when||[]).map(x=>`<li>${esc(x)}</li>`).join('') || '<li>Not specified</li>';
  const avoid=(passport.avoid_when||[]).map(x=>`<li>${esc(x)}</li>`).join('') || '<li>Not specified</li>';
  return `<div class="passport"><div class="passport-head"><span>TRADING PASSPORT</span><strong>${esc(passport.market||'—')} · ${esc(passport.primary_timeframe||'—')}</strong></div><div class="passport-grid"><div><span>Attach to</span><b>${esc(passport.attach_chart||`${passport.market||'—'} ${passport.primary_timeframe||'—'}`)}</b></div><div><span>Operating window</span><b>${esc(passport.operating_window||'Not specified')}</b></div><div><span>Best session</span><b>${esc(passport.best_session||'Not established')}</b></div><div><span>Confidence</span><b>${esc(passport.confidence_score??'—')}/100</b></div></div><div class="use-grid"><div><h4>Use when</h4><ul>${use}</ul></div><div><h4>Avoid when</h4><ul>${avoid}</ul></div></div></div>`;
}

async function downloadFile(path, fallbackName) {
  let token=await adminToken();
  if (!token) return;
  let response=await fetch(`/api${path}`,{headers:{'X-Admin-Token':token}});
  if (response.status===401) {
    sessionStorage.removeItem('eveDiscoveryAdminToken');
    token=await adminToken(true);
    if (!token) return;
    response=await fetch(`/api${path}`,{headers:{'X-Admin-Token':token}});
  }
  if (!response.ok) { alert(`Download failed: ${response.status} ${await response.text()}`); return; }
  const blob=await response.blob();
  const disposition=response.headers.get('content-disposition')||'';
  const match=disposition.match(/filename="?([^";]+)"?/i);
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=match?.[1]||fallbackName;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),5000);
}

function renderPackages() {
  $('#packageList').innerHTML=state.packages.length ? state.packages.map(x=>{
    const p=x.trading_passport||{}, manifest=x.manifest||{};
    return `<article class="card package-card"><div class="card-top"><div><h3>${esc(x.strategy_name)}</h3><p>${esc(x.family)} · package v${esc(x.version||'2.0')}</p></div>${badge(manifest.compile_status||'compile required')}</div>${passportRows(p)}${stats([['M1 replay',manifest.m1_replay_status||'—'],['Dataset',manifest.dataset_version||'—'],['Size',`${num((x.size_bytes||0)/1024,1)} KB`],['Trading default',manifest.trading_default||'OFF']])}<div class="download-row"><button class="download" data-download="/packages/${esc(x.id)}/download" data-name="${esc(x.file_name||'EVE-MT5.zip')}">Download full package</button><button class="download secondary" data-download="/packages/${esc(x.id)}/mq5" data-name="${esc(manifest.mq5_file||'EVE_Discovery.mq5')}">MQ5 source</button></div></article>`;
  }).join('') : '<div class="empty-state">No strategy has passed final holdout and M1 replay yet.</div>';
  $$('[data-download]').forEach(btn=>btn.addEventListener('click',()=>downloadFile(btn.dataset.download,btn.dataset.name)));
}

function check(label, value, detail) { return `<div class="check ${value?'ok':'bad'}"><span>${value?'✓':'!'}</span><div><b>${esc(label)}</b><small>${esc(detail)}</small></div></div>`; }
function renderDataHealth() {
  const h=state.dataHealth, r=h.runtime||{};
  $('#snapshotDefinition').textContent=h.snapshot_definition||'One completed research market state, not a raw tick.';
  $('#dataHealthSummary').innerHTML=`<div><span class="status-orb ${h.status==='healthy'?'ok':h.status==='attention'?'warn':'bad'}"></span><div><p class="eyebrow">DATA STATUS</p><h3>${esc(String(h.status||'unknown').toUpperCase())}</h3><p>${fmt.format(h.snapshots||0)} market states from ${dateText(h.snapshot_from)} to ${dateText(h.snapshot_to)}</p></div></div><small>Latest immutable version: ${esc(h.latest_dataset_version||'created when the next test completes')}</small>`;
  $('#dataMetrics').innerHTML=[
    ['Market states',fmt.format(h.snapshots||0),'completed research anchors'],
    ['Outcomes complete',`${num(h.outcome_completion_percent,2)}%`,`${fmt.format(h.completed_outcomes||0)} rows`],
    ['Markets',fmt.format(h.symbol_count||0),(h.symbols||[]).join(', ')||'none'],
    ['Snapshot intervals',fmt.format(h.snapshot_interval_count||0),(h.snapshot_intervals||[]).join(', ')||'none'],
    ['Source intervals',fmt.format(h.source_interval_count||0),(h.source_intervals||[]).join(', ')||'none'],
    ['Feature versions',fmt.format(h.feature_version_count||0),(h.feature_versions||[]).join(', ')||'none']
  ].map(x=>metric(...x)).join('');
  const datasets=h.datasets||[];
  $('#datasetList').innerHTML=datasets.length ? datasets.map(d=>`<div class="dataset"><div><b>${esc(d.symbol)} · ${esc(d.snapshot_interval)}</b><span>Source ${esc(d.source_interval)}</span></div><strong>${fmt.format(d.rows||0)}</strong><small>${dateText(d.from_time)} → ${dateText(d.to_time)}</small></div>`).join('') : '<div class="empty-state">No source data imported yet.</div>';
  const readOnly=r.source_credential_mode==='read_only_key';
  $('#boundaryStatus').innerHTML=`${check('Application write surface',r.production_write_surface==='none','SourceRepository exposes GET operations only.')}${check('Database credential',readOnly,readOnly?'Dedicated read-only source key is active.':'Legacy service-role key is still configured. Add SOURCE_SUPABASE_READ_ONLY_KEY to enforce the boundary at database level.')}${check('Separate research database',true,'Candidates, mutations, failures and packages stay in Discovery Supabase.')}`;
  $('#qualityChecks').innerHTML=[
    check('Forward outcomes complete',Number(h.incomplete_outcomes||0)===0,`${fmt.format(h.incomplete_outcomes||0)} incomplete rows`),
    check('ATR features usable',Number(h.invalid_atr_rows||0)===0,`${fmt.format(h.invalid_atr_rows||0)} invalid ATR rows`),
    check('Feature versions recorded',Number(h.missing_feature_version_rows||0)===0,`${fmt.format(h.missing_feature_version_rows||0)} missing feature versions`),
    check('Research timeframe matches evidence',Boolean(r.research_timeframe&&r.source_candle_interval),`${r.research_timeframe||'—'} strategies use ${r.source_candle_interval||'—'} source candles; Railway refuses mismatched settings.`),
    check('M1 execution replay enabled',Boolean(r.m1_replay_enabled),r.m1_replay_enabled?'Required before a bot can freeze.':'No package can be promoted while disabled.'),
    check('Private research API',Boolean(r.research_api_requires_admin),r.research_api_requires_admin?'ADMIN_TOKEN required for research data.':'Research results are publicly readable.'),
    check('Protected downloads',Boolean(r.package_downloads_require_admin),r.package_downloads_require_admin?'ADMIN_TOKEN required.':'Package downloads are public.')
  ].join('');
}

async function refresh() {
  try {
    const [dashboard,candidates,lineages,mutations,packages,dataHealth]=await Promise.all([
      api('/dashboard'),api('/candidates?limit=100'),api('/lineages?limit=100'),api('/mutations?limit=100'),api('/packages?limit=100'),api('/data-health')
    ]);
    state.dashboard=dashboard;state.candidates=candidates.items||[];state.lineages=lineages.items||[];state.mutations=mutations.items||[];state.packages=packages.items||[];state.dataHealth=dataHealth;
    renderOverview();renderCandidates();renderEvolution();renderPackages();renderDataHealth();
  } catch (error) {
    setHealth(false,'API unavailable');$('#lastError').textContent=error.message;
  }
}

$$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{
  $$('.nav-item').forEach(x=>x.classList.toggle('active',x===btn));
  $$('.view').forEach(x=>x.classList.toggle('active',x.id===`view-${btn.dataset.view}`));
  $('#pageTitle').textContent=btn.querySelector('b').textContent;
}));
$$('[data-candidate-filter]').forEach(btn=>btn.addEventListener('click',()=>{
  $$('[data-candidate-filter]').forEach(x=>x.classList.toggle('active',x===btn));state.candidateFilter=btn.dataset.candidateFilter;renderCandidates();
}));
$$('[data-refresh]').forEach(btn=>btn.addEventListener('click',refresh));
setInterval(()=>{$('#clock').textContent=new Date().toLocaleTimeString('en-GB',{timeZone:'UTC',hour12:false});},1000);
refresh();setInterval(refresh,45000);
