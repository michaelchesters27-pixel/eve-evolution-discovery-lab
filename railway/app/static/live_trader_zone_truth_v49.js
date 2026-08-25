(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || window.eveZoneTruthV49) return;
  window.eveZoneTruthV49 = true;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const fmt = value => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2})
    : '—';

  const style = document.createElement('style');
  style.textContent = `
    .lt-zone.lt-current-zone{outline:1px solid rgba(80,220,145,.55);box-shadow:0 0 0 1px rgba(80,220,145,.10) inset}
    .lt-zone-current-tag{display:inline-block;margin-left:7px;padding:2px 6px;border:1px solid rgba(80,220,145,.45);border-radius:999px;color:var(--green);font-size:8px;font-weight:900;vertical-align:middle}
    .lt-msg.zone-replaced{opacity:.56;border-style:dashed!important}
    .lt-msg.zone-replaced small{color:#d9a45f!important}
    .lt-source-zone-row b{font-size:10px!important}
  `;
  document.head.appendChild(style);

  let best = {demand:null, supply:null};
  let timer = null;

  function zoneId(state, kind) {
    return state?.zones?.[kind]?.[0]?.id || null;
  }

  function zoneLabel(state, kind) {
    const zone = state?.zones?.[kind]?.[0];
    return zone ? `${fmt(zone.low)} to ${fmt(zone.high)}` : 'none';
  }

  function markHistoricalZoneMessages(kind, state) {
    const phrase = `best ${kind} zone`;
    const zone = state?.zones?.[kind]?.[0];
    const currentLow = zone ? fmt(zone.low) : null;
    const currentHigh = zone ? fmt(zone.high) : null;
    document.querySelectorAll('#ltConversation .lt-msg.assistant').forEach(item => {
      const text = item.textContent || '';
      if (!text.toLowerCase().includes(phrase)) return;
      const small = item.querySelector('small');
      if (!small || !small.textContent.toLowerCase().includes('live market update')) return;
      const isCurrent = currentLow && currentHigh && text.includes(currentLow) && text.includes(currentHigh);
      if (isCurrent) {
        item.classList.remove('zone-replaced');
        if (small.textContent.toLowerCase().includes('historical')) small.textContent = 'CURRENT ZONE · Live market update';
        return;
      }
      item.classList.add('zone-replaced');
      small.textContent = 'REPLACED · historical market update';
    });
  }

  function appendReplacement(kind, hasCurrent, state) {
    const box = document.getElementById('ltConversation');
    if (!box) return;
    const item = document.createElement('div');
    item.className = 'lt-msg assistant';
    const text = hasCurrent
      ? `Micky, the previous best ${kind} zone has been replaced. CURRENT best ${kind}: ${zoneLabel(state, kind)}.`
      : `Micky, EVE currently has no ranked ${kind} zone.`;
    item.innerHTML = `${safe(text)}<small>CURRENT ZONE · Live market update</small>`;
    box.appendChild(item);
    box.scrollTop = box.scrollHeight;
    if (document.getElementById('ltSpeakChanges')?.checked && window.eveLiveVoice?.say) {
      window.eveLiveVoice.say(text, {key:`zone-replace:${kind}:${zoneId(state,kind) || 'none'}`, priority:2, cooldownMs:120000});
    }
  }

  function decorateCurrentZones() {
    for (const id of ['ltDemand','ltSupply']) {
      const root = document.getElementById(id);
      if (!root) continue;
      root.querySelectorAll('.lt-zone').forEach((node, index) => {
        node.classList.toggle('lt-current-zone', index === 0);
        node.querySelector('.lt-zone-current-tag')?.remove();
        if (index === 0) {
          const strong = node.querySelector('strong');
          if (strong) strong.insertAdjacentHTML('beforeend', '<span class="lt-zone-current-tag">CURRENT</span>');
        }
      });
    }
  }

  function showSourceZone(state) {
    const grid = document.getElementById('ltOrderGrid');
    if (!grid) return;
    grid.querySelectorAll('.lt-source-zone-row').forEach(node => node.remove());
    const campaign = state?.trade_campaign;
    const source = campaign?.source_zone;
    if (!campaign || !source) return;
    const row = document.createElement('div');
    row.className = 'lt-source-zone-row';
    const kind = source.kind || (campaign.side === 'BUY' ? 'demand' : 'supply');
    const currentId = zoneId(state, kind);
    const status = currentId === source.id ? 'CURRENT' : 'REPLACED';
    row.innerHTML = `<span>Source zone</span><b>${safe(source.id || '—')} · ${safe(status)}</b>`;
    grid.appendChild(row);
  }

  function render(state) {
    decorateCurrentZones();
    showSourceZone(state);
    for (const kind of ['demand','supply']) {
      const current = zoneId(state, kind);
      markHistoricalZoneMessages(kind, state);
      if (best[kind] !== null && current !== best[kind]) {
        appendReplacement(kind, Boolean(current), state);
        markHistoricalZoneMessages(kind, state);
      }
      best[kind] = current;
    }
  }

  async function refresh() {
    if (!view.classList.contains('active')) return;
    try {
      const state = await api('/live-trader');
      render(state);
    } catch (_) {}
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 2500);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (view.classList.contains('active')) start();
})();
