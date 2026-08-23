(() => {
  let busy = false;

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
      const confirmed = news?.week_confirmed === true;
      const start = prettyDate(news?.week_start);
      const end = prettyDate(news?.week_end);
      row.className = `lt-news-week ${confirmed ? 'confirmed' : ''}`;
      row.innerHTML = confirmed
        ? `<div><b>WEEKLY FOREX FACTORY CHECK CONFIRMED</b><span>${safe(start)} → ${safe(end)} · Timed USD RED and relevant RED All/Tentative macro events checked. EVE's weekly news guard is armed.</span></div><button class="lt-news-confirm" type="button" disabled>CONFIRMED</button>`
        : `<div><b>WEEK NOT CONFIRMED — CLOSED-SAFE</b><span>${safe(start)} → ${safe(end)} · Add every timed USD RED event plus any relevant RED All/Tentative macro event such as Jackson Hole, then confirm the weekly check. EVE will not publish a new gold trade until you confirm.</span></div><button class="lt-news-confirm" id="ltNewsConfirmButton" type="button">Confirm week checked</button>`;

      if (!confirmed) {
        const pill = document.getElementById('ltNewsStatus');
        if (pill) {
          pill.textContent = 'WEEK NOT CONFIRMED';
          pill.className = 'lt-news-pill blackout';
        }
        const nextBox = document.getElementById('ltNewsNext');
        if (nextBox) {
          nextBox.innerHTML = `<div class="lt-news-next blackout"><div><span>WEEKLY SAFETY CHECK REQUIRED</span><strong>Forex Factory red-folder calendar not confirmed</strong><small>Enter all timed USD RED events and relevant RED All/Tentative macro events for this week, then press Confirm week checked. Existing triggered campaigns remain locked, but EVE will not publish a new setup until this is complete.</small></div><div class="lt-news-countdown"><b>BLOCKED</b><small>until confirmed</small></div></div>`;
        }
      }
    }

    window.eveLiveNewsRender = (state, summary) => {
      baseRender(state, summary);
      const news = state?.news_risk || summary?.news_risk || {};
      renderWeek(news);
    };

    row.addEventListener('click', async event => {
      const button = event.target.closest('#ltNewsConfirmButton');
      if (!button || busy) return;
      busy = true;
      button.disabled = true;
      const error = document.getElementById('ltNewsError');
      if (error) error.textContent = '';
      try {
        const result = await api('/live-trader/chat', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({message:'__EVE_NEWS_CONFIRM_WEEK__'}),
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
    });
  }

  boot();
})();
