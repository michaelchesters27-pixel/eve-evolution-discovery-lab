(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltIntelligenceCard')) return;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const fmtInt = value => Math.round(num(value)).toLocaleString('en-GB');
  const fmtScore = value => num(value).toFixed(1);
  const fmtDelta = value => {
    if (value == null || !Number.isFinite(Number(value))) return 'Building';
    const n = Number(value);
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
  };

  const style = document.createElement('style');
  style.textContent = `
    .lt-iq-card{margin-top:14px;border-color:#38664c!important}
    .lt-iq-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}
    .lt-iq-head h3{margin:2px 0 0;font-size:22px}.lt-iq-head p{margin:6px 0 0;color:var(--muted);font-size:10px;line-height:1.5;max-width:670px}
    .lt-iq-level{border:1px solid var(--line);border-radius:999px;padding:7px 11px;font-size:9px;font-weight:900;letter-spacing:.08em;white-space:nowrap;color:var(--green)}
    .lt-iq-main{display:grid;grid-template-columns:180px 1fr;gap:18px;align-items:center}
    .lt-iq-ring{--iq-deg:0deg;width:154px;height:154px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--green) var(--iq-deg),#102019 0);position:relative;margin:auto}
    .lt-iq-ring:after{content:'';position:absolute;inset:10px;border-radius:50%;background:#07110d;border:1px solid var(--line)}
    .lt-iq-ring-inner{position:relative;z-index:1;text-align:center}.lt-iq-ring-inner strong{display:block;font-size:36px;line-height:1}.lt-iq-ring-inner span{display:block;font-size:10px;color:var(--muted);margin-top:5px}
    .lt-iq-components{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
    .lt-iq-component{border:1px solid var(--line);background:#06100b;border-radius:12px;padding:12px}
    .lt-iq-component-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.lt-iq-component span{font-size:9px;color:var(--muted)}.lt-iq-component strong{font-size:18px}
    .lt-iq-bar{height:6px;border-radius:99px;background:#102019;overflow:hidden;margin-top:9px}.lt-iq-bar i{display:block;height:100%;background:var(--green);border-radius:99px}
    .lt-iq-trend{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px}
    .lt-iq-trend>div,.lt-iq-evidence>div{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:10px}.lt-iq-trend span,.lt-iq-evidence span{display:block;font-size:8px;color:var(--muted)}.lt-iq-trend b,.lt-iq-evidence b{display:block;margin-top:4px;font-size:14px}
    .lt-iq-evidence{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:14px}
    .lt-iq-explain{font-size:10px;line-height:1.6;color:#b7cdbf;margin:13px 0 0}
    .lt-iq-milestones{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}.lt-iq-milestones h4{font-size:10px;letter-spacing:.08em;margin:0 0 9px;color:var(--green)}
    .lt-iq-milestone{display:grid;grid-template-columns:minmax(140px,1fr) 2fr auto;gap:10px;align-items:center;margin-top:8px}.lt-iq-milestone span{font-size:9px;color:var(--muted)}.lt-iq-milestone b{font-size:9px}.lt-iq-milestone .lt-iq-bar{margin:0}
    .lt-iq-milestone-empty{font-size:9px;color:var(--muted);line-height:1.5;padding:4px 0}
    .lt-iq-disclaimer{font-size:9px;color:var(--muted);margin:12px 0 0;line-height:1.5}
    @media(max-width:760px){.lt-iq-main{grid-template-columns:1fr}.lt-iq-components{grid-template-columns:1fr}.lt-iq-trend{grid-template-columns:1fr 1fr}.lt-iq-evidence{grid-template-columns:1fr 1fr}.lt-iq-milestone{grid-template-columns:1fr auto}.lt-iq-milestone .lt-iq-bar{grid-column:1/-1;grid-row:2}.lt-iq-head{align-items:flex-start}.lt-iq-ring{width:142px;height:142px}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('article');
  card.id = 'ltIntelligenceCard';
  card.className = 'lt-card lt-iq-card';
  card.innerHTML = `
    <div class="lt-iq-head">
      <div><p class="eyebrow">EVE GETTING SMARTER</p><h3>EVE INTELLIGENCE</h3><p>Evidence-based adaptive intelligence index. This measures how capable, experienced and mature EVE's learning system has become.</p></div>
      <span class="lt-iq-level" id="ltIqLevel">CALCULATING</span>
    </div>
    <div class="lt-iq-main">
      <div class="lt-iq-ring" id="ltIqRing"><div class="lt-iq-ring-inner"><strong id="ltIqOverall">—</strong><span>OUT OF 10</span></div></div>
      <div>
        <div class="lt-iq-components" id="ltIqComponents"></div>
        <div class="lt-iq-trend" id="ltIqTrend"></div>
      </div>
    </div>
    <div class="lt-iq-evidence" id="ltIqEvidence"></div>
    <p class="lt-iq-explain" id="ltIqExplain">Reading EVE's learning evidence.</p>
    <div class="lt-iq-milestones"><h4>NEXT INTELLIGENCE MILESTONES</h4><div id="ltIqMilestones"></div></div>
    <p class="lt-iq-disclaimer" id="ltIqMeaning"></p>
  `;

  const hero = view.querySelector('.lt-hero');
  if (hero) hero.insertAdjacentElement('afterend', card);
  else view.querySelector('.live-trader-shell')?.prepend(card);

  let timer = null;

  function component(name, score, note) {
    const width = Math.max(0, Math.min(100, num(score) * 10));
    return `<div class="lt-iq-component"><div class="lt-iq-component-head"><div><span>${safe(name)}</span></div><strong>${safe(fmtScore(score))}</strong></div><div class="lt-iq-bar"><i style="width:${width}%"></i></div><span>${safe(note)}</span></div>`;
  }

  function render(iq) {
    if (!iq || iq.status === 'unavailable') {
      document.getElementById('ltIqLevel').textContent = 'UNAVAILABLE';
      document.getElementById('ltIqExplain').textContent = iq?.error || 'Intelligence evidence is temporarily unavailable.';
      return;
    }
    const overall = num(iq.overall);
    const metrics = iq.metrics || {};
    const trend = iq.trend || {};
    document.getElementById('ltIqOverall').textContent = fmtScore(overall);
    document.getElementById('ltIqLevel').textContent = iq.level || 'LEARNING';
    document.getElementById('ltIqRing').style.setProperty('--iq-deg', `${Math.max(0, Math.min(360, overall * 36))}deg`);
    document.getElementById('ltIqComponents').innerHTML = [
      component('Brain quality', iq.brain, `${iq.architecture_capabilities || 0} verified intelligence mechanisms`),
      component('Experience level', iq.experience, 'Valid forward + historical evidence depth'),
      component('Applied learning', iq.applied_learning, 'Maturity actually able to influence decisions'),
    ].join('');
    document.getElementById('ltIqTrend').innerHTML = [
      ['Since baseline', fmtDelta(trend.since_baseline)],
      ['24 hours', fmtDelta(trend.hours_24)],
      ['7 days', fmtDelta(trend.days_7)],
      ['30 days', fmtDelta(trend.days_30)],
    ].map(([name,value]) => `<div><span>${safe(name)}</span><b>${safe(value)}</b></div>`).join('');
    document.getElementById('ltIqEvidence').innerHTML = [
      ['Forward scored', fmtInt(metrics.forward_scored)],
      ['Historical scored', fmtInt(metrics.historical_scored)],
      ['Challengers tested', fmtInt(metrics.challenger_runs)],
      ['Execution discoveries', fmtInt(metrics.execution_discoveries)],
      ['Mature live families', fmtInt(metrics.mature_forward_families)],
    ].map(([name,value]) => `<div><span>${safe(name)}</span><b>${safe(value)}</b></div>`).join('');
    document.getElementById('ltIqExplain').textContent = iq.explanation || '';
    document.getElementById('ltIqMeaning').textContent = iq.meaning || '';

    const pendingMilestones = (iq.milestones || []).filter(item => item.complete !== true).slice(0,4);
    document.getElementById('ltIqMilestones').innerHTML = pendingMilestones.length
      ? pendingMilestones.map(item => {
          const progress = Math.max(0, Math.min(100, num(item.progress) * 100));
          return `<div class="lt-iq-milestone"><span>${safe(item.label)}</span><div class="lt-iq-bar"><i style="width:${progress}%"></i></div><b>${safe(fmtInt(item.current))} / ${safe(fmtInt(item.target))}</b></div>`;
        }).join('')
      : '<div class="lt-iq-milestone-empty">All current intelligence milestones are complete. EVE will wait for the next evidence-based milestone set rather than inventing progress.</div>';
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const summary = await api('/live-trader/learning');
      render(summary.intelligence || {});
    } catch (error) {
      document.getElementById('ltIqLevel').textContent = 'OFFLINE';
      document.getElementById('ltIqExplain').textContent = `Could not read intelligence index: ${error.message}`;
    }
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 10000);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (view.classList.contains('active')) start();
})();
