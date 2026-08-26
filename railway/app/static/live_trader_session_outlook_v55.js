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
    .lt-session-outlook-flip{margin:8px 0 0;color:var(--muted);font-size:10px;line-height:1.45}
    .lt-session-outlook-note{margin:8px 0 0;padding-top:8px;border-top:1px solid var(--line);color:var(--muted);font-size:9px}
  `;
  document.head.appendChild(style);

  let timer = null;

  function safe(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
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
    panel.innerHTML = `
      <div class="lt-session-outlook-head">
        <div><span>SESSION OUTLOOK</span><div class="lt-session-outlook-direction ${safe(direction)}">${safe(direction.toUpperCase())}</div></div>
        <div class="lt-session-outlook-confidence">${safe(confidence)}/100</div>
      </div>
      <div class="lt-session-outlook-meta">${safe(conviction)} lean · ${safe(session)} session</div>
      <p class="lt-session-outlook-reasons">${safe(reasons.join(' '))}</p>
      <p class="lt-session-outlook-flip">${safe(flip)}</p>
      <p class="lt-session-outlook-note">Trade bias: ${safe(tradeBias)} · Session outlook does not bypass EVE's hardened trade gate.</p>`;
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
    timer = setInterval(refresh, 5000);
  }

  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', start);
  if (document.getElementById('view-live-trader')?.classList.contains('active')) start();
})();
