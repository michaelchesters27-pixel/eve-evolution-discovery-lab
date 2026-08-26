(() => {
  if (window.eveSessionOutlookV55) return;
  window.eveSessionOutlookV55 = true;

  const style = document.createElement('style');
  style.textContent = `
    .lt-session-outlook{margin-top:14px;border:1px solid #28563d;background:#06100b;border-radius:13px;padding:13px}
    .lt-session-outlook-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
    .lt-session-outlook-head span{display:block;font-size:9px;color:var(--muted);letter-spacing:.09em;text-transform:uppercase}
    .lt-session-outlook-direction{font-size:30px;font-weight:900;line-height:1;margin-top:5px;letter-spacing:-.02em}
    .lt-session-outlook-direction.bullish{color:var(--green)}
    .lt-session-outlook-direction.bearish{color:var(--red)}
    .lt-session-outlook-confidence{font-size:18px;font-weight:900;white-space:nowrap}
    .lt-session-outlook-meta{margin-top:7px;color:#a9c4b6;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
    .lt-session-outlook-reasons{margin:10px 0 0;color:#c2d6cc;font-size:11px;line-height:1.5}
    .lt-session-outlook-retrace{margin-top:11px;border:1px solid var(--line);border-radius:11px;padding:11px;background:#08140f}
    .lt-session-outlook-retrace-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .lt-session-outlook-retrace-head span{font-size:9px;font-weight:900;letter-spacing:.08em;color:#b8d1c4}
    .lt-session-outlook-retrace-head small{font-size:8px;color:var(--muted)}
    .lt-session-outlook-retrace-range{font-size:21px;font-weight:900;line-height:1.15;margin-top:5px}
    .lt-session-outlook-retrace-range.bullish{color:var(--green)}
    .lt-session-outlook-retrace-range.bearish{color:var(--red)}
    .lt-session-outlook-retrace-meta{margin-top:5px;font-size:9px;color:#a9c4b6;text-transform:uppercase;letter-spacing:.04em}
    .lt-session-outlook-retrace-note{margin:6px 0 0;font-size:10px;line-height:1.45;color:#c2d6cc}
    .lt-session-outlook-flip{margin:8px 0 0;color:var(--muted);font-size:10px;line-height:1.45}
    .lt-session-outlook-note{margin:8px 0 0;padding-top:8px;border-top:1px solid var(--line);color:var(--muted);font-size:9px}
  `;
  document.head.appendChild(style);

  let timer = null;

  function safe(value) {
    return String(value ?? '').replace(/[&<>'\"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[ch]));
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function fmt(value) {
    const parsed = number(value);
    return parsed == null ? '—' : parsed.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
  }

  function retracePlan(state, direction) {
    const price = number(state?.price);
    const zones = state?.zones || {};
    const kind = direction === 'bearish' ? 'supply' : 'demand';
    const side = direction === 'bearish' ? 'SELL' : 'BUY';
    const zonesForSide = Array.isArray(zones[kind]) ? zones[kind] : [];
    if (price == null || !zonesForSide.length) return null;

    const candidates = zonesForSide
      .map(zone => ({
        zone,
        low:number(zone?.low),
        high:number(zone?.high),
        quality:number(zone?.quality),
      }))
      .filter(item => item.low != null && item.high != null && item.high >= item.low);

    const containing = candidates.find(item => item.low <= price && price <= item.high);
    let selected = containing || null;
    if (!selected && direction === 'bearish') {
      selected = candidates
        .filter(item => item.low > price)
        .sort((a,b) => a.low - b.low)[0] || null;
    }
    if (!selected && direction === 'bullish') {
      selected = candidates
        .filter(item => item.high < price)
        .sort((a,b) => b.high - a.high)[0] || null;
    }
    if (!selected) return null;

    const inZone = selected.low <= price && price <= selected.high;
    const action = direction === 'bearish' ? 'bearish rejection' : 'bullish rejection';
    const travel = direction === 'bearish' ? 'up' : 'down';
    return {
      title:`RETRACE BEFORE ${side}`,
      low:selected.low,
      high:selected.high,
      kind:kind.toUpperCase(),
      quality:selected.quality,
      inZone,
      note:inZone
        ? `Price is already inside current ${kind}. Wait for ${action} before acting.`
        : `Wait for price to retrace ${travel} into this current ${kind} area, then look for ${action}.`,
    };
  }

  function ensurePanel() {
    const view = document.getElementById('view-live-trader');
    if (!view) return null;
    let panel = document.getElementById('ltSessionOutlookPanel');
    if (panel) return panel;
    const biasCard = document.getElementById('ltBias')?.closest('.lt-card');
    if (!biasCard) return null;
    panel = document.createElement('div');
    panel.id = 'ltSessionOutlookPanel';
    panel.className = 'lt-session-outlook';
    const statusRow = biasCard.querySelector('.lt-status-row');
    if (statusRow) statusRow.insertAdjacentElement('beforebegin', panel);
    else biasCard.appendChild(panel);
    return panel;
  }

  function render(state) {
    const panel = ensurePanel();
    if (!panel) return;
    const outlook = state?.session_outlook || state?.market?.session_outlook || {};
    const direction = String(outlook.direction || '').toLowerCase();
    if (!['bullish','bearish'].includes(direction)) {
      panel.innerHTML = '<span>SESSION OUTLOOK</span><div class="lt-session-outlook-meta">Building directional opinion…</div>';
      return;
    }
    const confidence = Number(outlook.confidence || 51);
    const conviction = String(outlook.conviction || (confidence <= 57 ? 'slight' : confidence <= 66 ? 'moderate' : confidence <= 76 ? 'clear' : 'strong'));
    const session = String(outlook.session_label || outlook.session || 'current').replaceAll('_',' ');
    const reasons = Array.isArray(outlook.reasons) ? outlook.reasons.filter(Boolean).slice(0,2) : [];
    const flip = String(outlook.flip_text || '');
    const tradeBias = String(state?.bias?.overall || 'neutral').toUpperCase();
    const retrace = retracePlan(state, direction);
    const retraceHtml = retrace ? `
      <div class="lt-session-outlook-retrace">
        <div class="lt-session-outlook-retrace-head"><span>${safe(retrace.title)}</span><small>LIVE · AUTO-UPDATING</small></div>
        <div class="lt-session-outlook-retrace-range ${safe(direction)}">${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}</div>
        <div class="lt-session-outlook-retrace-meta">CURRENT ${safe(retrace.kind)}${retrace.quality == null ? '' : ` · QUALITY ${safe(Math.round(retrace.quality))}/100`}</div>
        <p class="lt-session-outlook-retrace-note">${safe(retrace.note)}</p>
      </div>` : `
      <div class="lt-session-outlook-retrace">
        <div class="lt-session-outlook-retrace-head"><span>RETRACE BEFORE ${direction === 'bearish' ? 'SELL' : 'BUY'}</span><small>LIVE · AUTO-UPDATING</small></div>
        <p class="lt-session-outlook-retrace-note">No valid current ${direction === 'bearish' ? 'supply above price' : 'demand below price'} yet. EVE will fill this automatically when one is available.</p>
      </div>`;

    panel.innerHTML = `
      <div class="lt-session-outlook-head">
        <div><span>SESSION OUTLOOK</span><div class="lt-session-outlook-direction ${safe(direction)}">${safe(direction.toUpperCase())}</div></div>
        <div class="lt-session-outlook-confidence">${safe(confidence)}/100</div>
      </div>
      <div class="lt-session-outlook-meta">${safe(conviction)} lean · ${safe(session)} session</div>
      <p class="lt-session-outlook-reasons">${safe(reasons.join(' '))}</p>
      ${retraceHtml}
      <p class="lt-session-outlook-flip">${safe(flip)}</p>
      <p class="lt-session-outlook-note">Trade bias: ${safe(tradeBias)} · Retrace level is session guidance only until EVE's hardened trade gate allows an order.</p>`;
  }

  async function refresh() {
    const view = document.getElementById('view-live-trader');
    if (!view || !view.classList.contains('active')) return;
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
  if (document.getElementById('view-live-trader')?.classList.contains('active')) start();
})();
