(() => {
  const view = document.getElementById('view-live-trader');
  if (!view || document.getElementById('ltNewsCard')) return;

  const safe = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const UK_ZONE = 'Europe/London';
  let latestState = null;
  let latestNews = null;
  let previousStatus = null;
  let busy = false;

  const style = document.createElement('style');
  style.textContent = `
    .lt-news-card{margin-top:14px;border-color:#6f472e!important}
    .lt-news-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}
    .lt-news-head h3{margin:2px 0 0}.lt-news-head p{margin:6px 0 0;color:var(--muted);font-size:10px;line-height:1.5;max-width:690px}
    .lt-news-pill{border:1px solid #6f472e;border-radius:999px;padding:7px 11px;font-size:9px;font-weight:900;letter-spacing:.08em;white-space:nowrap;color:#f1b580}
    .lt-news-pill.blackout{border-color:#a34141;color:#ff9292;background:#1c0b0b}.lt-news-pill.clear{border-color:#38664c;color:var(--green)}
    .lt-news-form{display:grid;grid-template-columns:135px 145px 115px minmax(210px,1fr) auto;gap:9px;margin-top:14px}
    .lt-news-form label{display:flex;flex-direction:column;gap:5px;font-size:8px;color:var(--muted)}
    .lt-news-form input,.lt-news-form select{width:100%;box-sizing:border-box;border:1px solid var(--line);background:#06100b;color:var(--text);border-radius:9px;padding:10px;font:inherit;outline:none}
    .lt-news-form input:focus,.lt-news-form select:focus{border-color:#528b67}.lt-news-form input:disabled{opacity:.45}
    .lt-news-add{align-self:end;border:1px solid #6f472e;background:#20130b;color:#f2bd8d;border-radius:9px;padding:10px 13px;font-weight:800;cursor:pointer;white-space:nowrap}
    .lt-news-add:disabled,.lt-news-remove:disabled{opacity:.45;cursor:wait}
    .lt-news-guidance{margin:9px 0 0;color:#a9c4b6;font-size:9px;line-height:1.55}
    .lt-news-next{margin-top:14px;border:1px solid var(--line);background:#06100b;border-radius:11px;padding:12px;display:flex;justify-content:space-between;gap:14px;align-items:center}
    .lt-news-next.blackout{border-color:#a34141;background:#180a0a}.lt-news-next span,.lt-news-next small{display:block}.lt-news-next span{font-size:8px;color:var(--muted)}.lt-news-next strong{display:block;margin-top:3px;font-size:14px}.lt-news-next small{margin-top:4px;color:#a9c4b6;font-size:9px}
    .lt-news-countdown{text-align:right;white-space:nowrap}.lt-news-countdown b{display:block;font-size:18px;color:#f1b580}.lt-news-countdown small{font-size:8px}
    .lt-news-list{margin-top:12px;display:grid;gap:7px}.lt-news-row{border:1px solid var(--line);background:#06100b;border-radius:10px;padding:10px;display:grid;grid-template-columns:145px 1fr auto auto;gap:10px;align-items:center}
    .lt-news-time span,.lt-news-name small{display:block;font-size:8px;color:var(--muted)}.lt-news-time b,.lt-news-name strong{display:block;margin-top:2px;font-size:10px}.lt-news-class{font-size:8px;font-weight:900;border:1px solid #8a4a35;color:#f1b580;border-radius:999px;padding:5px 7px;white-space:nowrap}.lt-news-class.major,.lt-news-class.all-day{border-color:#a34141;color:#ff9292}
    .lt-news-remove{border:1px solid var(--line);background:transparent;color:#c8d8cf;border-radius:8px;padding:7px 9px;font-size:9px;cursor:pointer}.lt-news-empty{border:1px dashed var(--line);border-radius:10px;padding:14px;color:var(--muted);font-size:10px}
    .lt-news-error{margin-top:10px;color:#ff9292;font-size:9px;min-height:14px}
    @media(max-width:900px){.lt-news-form{grid-template-columns:1fr 1fr}.lt-news-form label:nth-child(4),.lt-news-add{grid-column:1/-1}}
    @media(max-width:760px){.lt-news-row{grid-template-columns:1fr auto}.lt-news-time,.lt-news-name{grid-column:1}.lt-news-class,.lt-news-remove{grid-column:2}.lt-news-next{align-items:flex-start}.lt-news-countdown b{font-size:14px}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('article');
  card.id = 'ltNewsCard';
  card.className = 'lt-card lt-news-card';
  card.innerHTML = `
    <div class="lt-news-head">
      <div><p class="eyebrow">WEEKLY RED-FOLDER NEWS</p><h3>High-impact gold news protection</h3><p>Every Sunday, copy the timed USD RED events from Forex Factory. If a RED macro event is shown as All/Tentative with no exact time, choose All day / no exact time instead of inventing a release time.</p></div>
      <span class="lt-news-pill" id="ltNewsStatus">LOADING</span>
    </div>
    <form class="lt-news-form" id="ltNewsForm">
      <label>Date<input type="date" id="ltNewsDate" required></label>
      <label>Timing<select id="ltNewsTiming"><option value="timed">Exact UK time</option><option value="all_day">All day / no exact time</option></select></label>
      <label>Exact UK time<input type="time" id="ltNewsTime" required></label>
      <label>Event name<input type="text" id="ltNewsName" maxlength="180" placeholder="e.g. Core PCE Price Index m/m" required></label>
      <button class="lt-news-add" id="ltNewsAdd" type="submit">Add RED event</button>
    </form>
    <p class="lt-news-guidance">Timed USD RED: standard 30 min before → 15 min after; CPI/PCE/NFP/FOMC/rate/Powell 45 min before → 30 min after. All-day/Tentative RED macro risk: full UK calendar day. Pending ideas are suspended; triggered trades keep their exact locked stop and target.</p>
    <div id="ltNewsNext"></div>
    <div class="lt-news-list" id="ltNewsList"><div class="lt-news-empty">Waiting for EVE's manual news calendar.</div></div>
    <div class="lt-news-error" id="ltNewsError"></div>
  `;

  const intelligence = document.getElementById('ltIntelligenceCard');
  const hero = view.querySelector('.lt-hero');
  if (intelligence) intelligence.insertAdjacentElement('afterend', card);
  else if (hero) hero.insertAdjacentElement('afterend', card);
  else view.querySelector('.live-trader-shell')?.prepend(card);

  const byId = id => document.getElementById(id);

  function ukParts(value) {
    if (!value) return {date:'—', time:'—'};
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return {date:'—', time:'—'};
    return {
      date: d.toLocaleDateString('en-GB', {timeZone:UK_ZONE, weekday:'short', day:'2-digit', month:'short'}),
      time: d.toLocaleTimeString('en-GB', {timeZone:UK_ZONE, hour:'2-digit', minute:'2-digit'}),
    };
  }

  function isAllDay(event) {
    return String(event?.event_class || '') === 'all_day' || event?.all_day === true;
  }

  function blackoutText(event) {
    if (isAllDay(event)) return 'FULL UK CALENDAR DAY';
    const start = ukParts(event?.blackout_start);
    const end = ukParts(event?.blackout_end);
    return `${start.time}–${end.time} UK`;
  }

  function countdownText(minutes) {
    if (!Number.isFinite(Number(minutes))) return '—';
    const value = Number(minutes);
    if (value < 0) return 'NOW';
    if (value < 1) return '<1 min';
    if (value < 60) return `${Math.round(value)} min`;
    const hours = Math.floor(value / 60);
    const mins = Math.round(value % 60);
    return `${hours}h ${mins}m`;
  }

  function eventRow(event) {
    const stamp = ukParts(event.scheduled_at);
    const allDay = isAllDay(event);
    const major = String(event.event_class || '') === 'major';
    const policy = allDay ? 'full UK calendar day' : major ? '45 before / 30 after' : '30 before / 15 after';
    const currency = String(event.currency || 'USD');
    return `<div class="lt-news-row">
      <div class="lt-news-time"><span>${safe(stamp.date)}</span><b>${allDay ? 'ALL DAY' : `${safe(stamp.time)} UK`}</b></div>
      <div class="lt-news-name"><strong>${safe(event.event_name)}</strong><small>${safe(currency)} RED · ${safe(policy)}${allDay ? '' : ` · blackout ${safe(blackoutText(event))}`}</small></div>
      <span class="lt-news-class ${allDay ? 'all-day' : major ? 'major' : ''}">${allDay ? 'ALL DAY' : major ? 'MAJOR' : 'HIGH'}</span>
      <button class="lt-news-remove" type="button" data-news-remove="${safe(event.event_id)}">Remove</button>
    </div>`;
  }

  function maybeSpeak(news, state) {
    const status = String(news?.status || 'unavailable');
    if (status === 'blackout' && previousStatus !== 'blackout' && window.eveLiveVoice?.say) {
      const activeList = news.active_events || [];
      const events = activeList.map(item => item.event_name).filter(Boolean).join(' and ') || 'high-impact macro news';
      const hasAllDay = activeList.some(isAllDay);
      const end = ukParts(news.active_window_end).time;
      const activeTrade = String(state?.trade?.campaign_status || '').toLowerCase() === 'active';
      const riskLabel = hasAllDay ? 'all-day red-folder macro risk' : 'red-folder USD news protection';
      const text = activeTrade
        ? `Micky, ${riskLabel} is active for ${events}. Your triggered campaign stays locked to its published stop and target.`
        : `Micky, ${riskLabel} is active for ${events}. No new gold trade until ${hasAllDay ? 'the next UK calendar day' : `${end} UK time`}.`;
      window.eveLiveVoice.say(text, {
        key:`news:blackout:${(news.active_event_ids || []).join(',')}`,
        priority:3,
        cooldownMs:3600000,
      });
    }
    previousStatus = status;
  }

  function render(news, state = latestState) {
    latestNews = news || {};
    latestState = state || latestState;
    const status = String(latestNews.status || 'unavailable');
    const pill = byId('ltNewsStatus');
    pill.className = `lt-news-pill ${status}`;
    pill.textContent = status === 'blackout' ? 'NEWS BLACKOUT' : status === 'armed' ? 'ARMED' : status === 'clear' ? 'CLEAR' : status === 'week_unconfirmed' ? 'WEEK NOT CONFIRMED' : 'CALENDAR UNAVAILABLE';

    const nextBox = byId('ltNewsNext');
    if (status === 'unavailable') {
      nextBox.innerHTML = `<div class="lt-news-next blackout"><div><span>FAIL-SAFE</span><strong>Red-folder calendar unavailable</strong><small>EVE will not publish a new XAU/USD trade until the calendar can be confirmed again.</small></div><div class="lt-news-countdown"><b>BLOCKED</b><small>closed-safe</small></div></div>`;
    } else if (status === 'blackout') {
      const active = (latestNews.active_events || [])[0] || {};
      const allDay = isAllDay(active);
      const stamp = ukParts(active.scheduled_at);
      const end = ukParts(latestNews.active_window_end);
      const campaign = String(latestState?.trade?.campaign_status || '').toLowerCase();
      const handling = campaign === 'active' ? 'Triggered trade remains locked to its published SL/TP.' : campaign === 'pending' ? 'Pending campaign is suspended and its validity clock is paused.' : 'No new XAU/USD trade can be published.';
      const timing = allDay ? `${safe(stamp.date)} · ALL DAY macro risk` : `${safe(stamp.time)} UK release · blackout ends ${safe(end.time)} UK`;
      nextBox.innerHTML = `<div class="lt-news-next blackout"><div><span>${allDay ? 'ALL-DAY RED-FOLDER MACRO RISK' : 'HIGH-IMPACT USD NEWS ACTIVE'}</span><strong>${safe(active.event_name || 'Red-folder event')}</strong><small>${timing}. ${safe(handling)}</small></div><div class="lt-news-countdown"><b>BLACKOUT</b><small>${allDay ? 'full UK day' : 'news protection'}</small></div></div>`;
    } else if (latestNews.next_event) {
      const event = latestNews.next_event;
      const allDay = isAllDay(event);
      const stamp = ukParts(event.scheduled_at);
      nextBox.innerHTML = `<div class="lt-news-next"><div><span>NEXT RED-FOLDER EVENT</span><strong>${safe(event.event_name)}</strong><small>${safe(stamp.date)} · ${allDay ? 'ALL DAY' : `${safe(stamp.time)} UK · blackout ${safe(blackoutText(event))}`}</small></div><div class="lt-news-countdown"><b>${allDay ? 'ALL DAY' : safe(countdownText(latestNews.minutes_to_next_event))}</b><small>${allDay ? 'macro risk' : 'until release'}</small></div></div>`;
    } else {
      nextBox.innerHTML = `<div class="lt-news-next"><div><span>NEWS CALENDAR</span><strong>No upcoming red-folder events loaded</strong><small>Enter timed USD RED events plus any relevant RED All/Tentative macro events from Forex Factory.</small></div><div class="lt-news-countdown"><b>CLEAR</b><small>no blackout loaded</small></div></div>`;
    }

    const events = (latestNews.events || []).filter(item => item?.event_id);
    byId('ltNewsList').innerHTML = events.length ? events.map(eventRow).join('') : '<div class="lt-news-empty">No upcoming red-folder events are loaded. Enter timed USD RED rows and relevant RED All/Tentative macro events from Forex Factory.</div>';
    maybeSpeak(latestNews, latestState);
  }

  function syncTimingMode() {
    const allDay = byId('ltNewsTiming')?.value === 'all_day';
    const timeInput = byId('ltNewsTime');
    if (timeInput) {
      timeInput.disabled = allDay;
      timeInput.required = !allDay;
      if (allDay) timeInput.value = '';
    }
    const add = byId('ltNewsAdd');
    if (add) add.textContent = allDay ? 'Add ALL-DAY RED event' : 'Add RED event';
  }

  async function submitEvent(event) {
    event.preventDefault();
    if (busy) return;
    const date = byId('ltNewsDate').value;
    const timing = byId('ltNewsTiming').value;
    const time = byId('ltNewsTime').value;
    const name = byId('ltNewsName').value.trim();
    if (!date || !name || (timing !== 'all_day' && !time)) return;
    busy = true;
    byId('ltNewsAdd').disabled = true;
    byId('ltNewsError').textContent = '';
    try {
      const message = timing === 'all_day'
        ? `__EVE_NEWS_ADD_ALL_DAY__|${date}|${name}`
        : `__EVE_NEWS_ADD__|${date}|${time}|${name}`;
      const result = await api('/live-trader/chat', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message}),
      });
      if (!result?.ok) throw new Error(result?.answer || 'EVE could not save that event.');
      byId('ltNewsName').value = '';
      render(result.news_risk || latestNews, latestState);
    } catch (error) {
      byId('ltNewsError').textContent = `Could not save event: ${error.message}`;
    } finally {
      busy = false;
      byId('ltNewsAdd').disabled = false;
    }
  }

  async function removeEvent(eventId, button) {
    if (busy || !eventId) return;
    busy = true;
    if (button) button.disabled = true;
    byId('ltNewsError').textContent = '';
    try {
      const result = await api('/live-trader/chat', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message:`__EVE_NEWS_REMOVE__|${eventId}`}),
      });
      if (!result?.ok) throw new Error(result?.answer || 'EVE could not remove that event.');
      render(result.news_risk || {}, latestState);
    } catch (error) {
      byId('ltNewsError').textContent = `Could not remove event: ${error.message}`;
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  byId('ltNewsTiming')?.addEventListener('change', syncTimingMode);
  byId('ltNewsForm')?.addEventListener('submit', submitEvent);
  byId('ltNewsList')?.addEventListener('click', event => {
    const button = event.target.closest('[data-news-remove]');
    if (button) removeEvent(button.dataset.newsRemove, button);
  });
  syncTimingMode();

  // Reuse Historical Academy's existing 5-second Live Trader refresh rather than
  // adding another Netlify request loop.
  window.eveLiveNewsRender = (state, summary) => {
    latestState = state || latestState;
    render(state?.news_risk || summary?.news_risk || latestNews || {}, latestState);
  };
})();
