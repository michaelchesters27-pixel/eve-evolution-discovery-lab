(() => {
  let busy = false;
  let latestWeekNews = {};

  function safe(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function prettyDate(value) {
    if (!value) return '—';
    const d = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  }

  function boot() {
    const card = document.getElementById('ltNewsCard');
    if (!card || typeof window.eveLiveNewsRender !== 'function') {
      setTimeout(boot, 100);
      return;
    }
    if (document.getElementById('ltNewsWeekConfirm')) return;

    const style = document.createElement('style');
    style.textContent = `
      .lt-news-week{margin-top:10px;border:1px solid #6f472e;background:#100c08;border-radius:10px;padding:10px 12px;display:flex;justify-content:space-between;gap:12px;align-items:center}
      .lt-news-week.confirmed{border-color:#38664c;background:#07120c}.lt-news-week b,.lt-news-week span{display:block}.lt-news-week b{font-size:10px}.lt-news-week span{font-size:8px;color:var(--muted);margin-top:3px;line-height:1.45}
      .lt-news-confirm{border:1px solid #6f472e;background:#20130b;color:#f2bd8d;border-radius:8px;padding:8px 11px;font-size:9px;font-weight:800;cursor:pointer;white-space:nowrap}.lt-news-week.confirmed .lt-news-confirm{border-color:#38664c;background:#0a1a10;color:var(--green)}.lt-news-confirm:disabled{opacity:.45;cursor:wait}
      .lt-news-attest{display:flex;gap:7px;align-items:flex-start;margin-top:7px;font-size:8px;color:#c8d8cf;line-height:1.45;max-width:760px}.lt-news-attest input{margin-top:2px}
      @media(max-width:760px){.lt-news-week{align-items:flex-start;flex-direction:column}.lt-news-confirm{width:100%}}
    `;
    document.head.appendChild(style);

    const row = document.createElement('div');
    row.id = 'ltNewsWeekConfirm';
    row.className = 'lt-news-week';
    const next = document.getElementById('ltNewsNext');
    if (next) next.insertAdjacentElement('beforebegin', row);
    else card.appendChild(row);

    const baseRender = window.eveLiveNewsRender;

    function renderWeek(news) {
      latestWeekNews = news || {};
      const confirmed = latestWeekNews?.week_confirmed === true;
      const state = String(latestWeekNews?.week_confirmation_state || 'missing');
      const stale = state === 'calendar_changed_since_confirmation';
      const start = prettyDate(latestWeekNews?.week_start);
      const end = prettyDate(latestWeekNews?.week_end);
      const count = Number(latestWeekNews?.current_week_event_count ?? 0);
      row.className = `lt-news-week ${confirmed ? 'confirmed' : ''}`;
      row.innerHTML = confirmed
        ? `<div><b>WEEKLY FOREX FACTORY CHECK CONFIRMED</b><span>${safe(start)} → ${safe(end)} · Exact inventory confirmed: ${count} enabled event${count === 1 ? '' : 's'}. If that inventory changes, EVE automatically blocks again until it is rechecked.</span></div><button class="lt-news-confirm" type="button" disabled>CONFIRMED</button>`
        : `<div><b>${stale ? 'CALENDAR CHANGED — RECONFIRM REQUIRED' : 'WEEK NOT CONFIRMED — CLOSED-SAFE'}</b><span>${safe(start)} → ${safe(end)} · EVE currently has ${count} enabled event${count === 1 ? '' : 's'} for this week. Check the full Sunday–Saturday Forex Factory calendar, enter every timed USD RED event plus relevant RED All/Tentative macro events, then explicitly attest below.</span><label class="lt-news-attest"><input type="checkbox" id="ltNewsAttest">I have checked the full Forex Factory week and entered every relevant event. I confirm EVE's current count of ${count} event${count === 1 ? '' : 's'} is correct.</label></div><button class="lt-news-confirm" id="ltNewsConfirmButton" type="button" disabled>Confirm checked inventory</button>`;

      if (!confirmed) {
        const pill = document.getElementById('ltNewsStatus');
        if (pill) {
          pill.textContent = stale ? 'CALENDAR CHANGED' : 'WEEK NOT CONFIRMED';
          pill.className = 'lt-news-pill blackout';
        }
        const nextBox = document.getElementById('ltNewsNext');
        if (nextBox) {
          nextBox.innerHTML = `<div class="lt-news-next blackout"><div><span>WEEKLY SAFETY CHECK REQUIRED</span><strong>${stale ? 'News inventory changed after confirmation' : 'Forex Factory red-folder calendar not confirmed'}</strong><small>EVE remains closed-safe. A button press alone cannot confirm the week: you must check the source, enter the full event inventory, tick the attestation, and confirm the exact count.</small></div><div class="lt-news-countdown"><b>BLOCKED</b><small>until explicitly checked</small></div></div>`;
        }
      }
    }

    window.eveLiveNewsRender = (state, summary) => {
      baseRender(state, summary);
      const news = state?.news_risk || summary?.news_risk || {};
      renderWeek(news);
    };

    row.addEventListener('change', event => {
      const checkbox = event.target.closest('#ltNewsAttest');
      if (!checkbox) return;
      const button = document.getElementById('ltNewsConfirmButton');
      if (button) button.disabled = !checkbox.checked || busy;
    });

    row.addEventListener('click', async event => {
      const button = event.target.closest('#ltNewsConfirmButton');
      if (!button || busy) return;
      const checkbox = document.getElementById('ltNewsAttest');
      if (!checkbox?.checked) return;
      const expectedCount = Number(latestWeekNews?.current_week_event_count);
      if (!Number.isInteger(expectedCount) || expectedCount < 0) {
        const error = document.getElementById('ltNewsError');
        if (error) error.textContent = 'Could not confirm week: EVE does not have a valid current-week event count.';
        return;
      }
      busy = true;
      button.disabled = true;
      const error = document.getElementById('ltNewsError');
      if (error) error.textContent = '';
      try {
        const message = `__EVE_NEWS_CONFIRM_WEEK__|${expectedCount}|I_HAVE_CHECKED_FOREX_FACTORY|Forex Factory weekly calendar manually checked in EVE`;
        const result = await api('/live-trader/chat', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({message}),
        });
        if (!result?.ok) throw new Error(result?.answer || 'EVE could not confirm the weekly check.');
        renderWeek(result.news_risk || {});
        baseRender({news_risk:result.news_risk}, {news_risk:result.news_risk});
      } catch (exc) {
        if (error) error.textContent = `Could not confirm week: ${exc.message}`;
        button.disabled = false;
      } finally {
        busy = false;
      }
    });;
  }

  function loadTradeOutcomes() {
    if (document.getElementById('ltTradeOutcomeScript')) return;
    const script = document.createElement('script');
    script.id = 'ltTradeOutcomeScript';
    script.src = 'live_trader_trade_outcomes.js';
    document.body.appendChild(script);
  }

  boot();
  loadTradeOutcomes();
})();
