(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltTradeSkillCard')) return;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const scoreText = value => num(value).toFixed(1);
  const rText = value => value == null || !Number.isFinite(Number(value)) ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}R`;

  const maturity = document.getElementById('ltIntelligenceCard');
  if (maturity) {
    const eyebrow = maturity.querySelector('.eyebrow');
    const title = maturity.querySelector('h3');
    const intro = maturity.querySelector('.lt-iq-head p:not(.eyebrow)');
    const milestones = maturity.querySelector('.lt-iq-milestones h4');
    if (eyebrow) eyebrow.textContent = 'EVE LEARNING SYSTEM';
    if (title) title.textContent = 'SYSTEM MATURITY';
    if (intro) intro.textContent = 'Architecture, evidence depth and applied-learning maturity. This is not a profitability or trade-skill score.';
    if (milestones) milestones.textContent = 'NEXT MATURITY MILESTONES';
  }

  const style = document.createElement('style');
  style.textContent = `
    .lt-skill-card{margin-top:14px;border-color:#6a4d31!important}
    .lt-skill-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}
    .lt-skill-head h3{margin:2px 0 0;font-size:22px}.lt-skill-head p{margin:6px 0 0;color:var(--muted);font-size:10px;line-height:1.5;max-width:690px}
    .lt-skill-grade{border:1px solid var(--line);border-radius:999px;padding:7px 11px;font-size:9px;font-weight:900;letter-spacing:.08em;white-space:nowrap}
    .lt-skill-main{display:grid;grid-template-columns:150px 1fr;gap:16px;align-items:center;margin-top:16px}
    .lt-skill-score{border:1px solid var(--line);background:#07110d;border-radius:14px;padding:18px;text-align:center}
    .lt-skill-score strong{display:block;font-size:36px;line-height:1}.lt-skill-score span{display:block;font-size:9px;color:var(--muted);margin-top:5px}
    .lt-skill-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
    .lt-skill-grid>div,.lt-skill-shadow{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:10px}
    .lt-skill-grid span,.lt-skill-shadow span{display:block;font-size:8px;color:var(--muted)}.lt-skill-grid b,.lt-skill-shadow b{display:block;margin-top:4px;font-size:14px}
    .lt-skill-shadow{margin-top:12px}.lt-skill-note{font-size:9px;color:var(--muted);line-height:1.55;margin:10px 0 0}
    @media(max-width:760px){.lt-skill-main{grid-template-columns:1fr}.lt-skill-grid{grid-template-columns:1fr 1fr}.lt-skill-head{align-items:flex-start}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('article');
  card.id = 'ltTradeSkillCard';
  card.className = 'lt-card lt-skill-card';
  card.innerHTML = `
    <div class="lt-skill-head">
      <div><p class="eyebrow">REAL FORWARD PERFORMANCE</p><h3>TRADE SKILL</h3><p>This score is deliberately hard to earn. Published forward campaigns count most. Historical and shadow research cannot hide a poor live record.</p></div>
      <span class="lt-skill-grade" id="ltSkillGrade">CALCULATING</span>
    </div>
    <div class="lt-skill-main">
      <div class="lt-skill-score"><strong id="ltSkillScore">—</strong><span>OUT OF 10</span></div>
      <div class="lt-skill-grid" id="ltSkillGrid"></div>
    </div>
    <div class="lt-skill-shadow" id="ltSkillShadow"><span>SHADOW RESEARCH</span><b>Building evidence</b></div>
    <p class="lt-skill-note" id="ltSkillMeaning"></p>
  `;

  if (maturity) maturity.insertAdjacentElement('afterend', card);
  else view.querySelector('.lt-hero')?.insertAdjacentElement('afterend', card);

  let timer = null;

  function render(skill) {
    if (!skill || skill.score == null) {
      document.getElementById('ltSkillGrade').textContent = 'UNAVAILABLE';
      return;
    }
    const shadow = skill.shadow_research || {};
    document.getElementById('ltSkillScore').textContent = scoreText(skill.score);
    document.getElementById('ltSkillGrade').textContent = skill.grade || 'UNPROVEN';
    document.getElementById('ltSkillGrid').innerHTML = [
      ['Published trades', skill.published_triggered ?? 0],
      ['Wins', skill.wins ?? 0],
      ['Losses', skill.losses ?? 0],
      ['Total', rText(skill.total_r)],
      ['Average', rText(skill.average_r)],
    ].map(([label,value]) => `<div><span>${safe(label)}</span><b>${safe(value)}</b></div>`).join('');
    document.getElementById('ltSkillShadow').innerHTML = `<span>SHADOW RESEARCH — NEVER PUBLISHED AS A TRADE</span><b>${safe(shadow.triggered ?? 0)} triggered · ${safe(shadow.wins ?? 0)} wins · ${safe(shadow.losses ?? 0)} losses · ${safe(rText(shadow.total_r))}</b>`;
    document.getElementById('ltSkillMeaning').textContent = skill.meaning || '';
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const summary = await api('/live-trader/learning');
      render(summary.trade_skill || {});
    } catch (error) {
      document.getElementById('ltSkillGrade').textContent = 'OFFLINE';
      document.getElementById('ltSkillMeaning').textContent = `Could not read Trade Skill: ${error.message}`;
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
