(() => {
  if (window.eveSessionOutlookV55) return;
  window.eveSessionOutlookV55 = true;

  const CARD_INTEGRITY_VERSION = 'eve-live-view-card-integrity-v1';
  const MAX_CONTEXT_LAG_MINUTES = 10;
  const LIVE_ZONE_MAX_DISTANCE_ATR = 1.8;
  const LIVE_ZONE_MIN_QUALITY = 58;
  const ZONE_SL_HUNT_BAND_ATR = 1.25;
  const ZONE_SL_BUFFER_ATR = 0.22;

  const style = document.createElement('style');
  style.textContent = `
    .lt-session-outlook{margin-top:14px;border:1px solid #28563d;background:#06100b;border-radius:13px;padding:13px}
    .lt-session-outlook.invalid{border-color:rgba(255,195,90,.45)}
    .lt-session-outlook-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
    .lt-session-outlook-head span{display:block;font-size:9px;color:var(--muted);letter-spacing:.09em;text-transform:uppercase}
    .lt-session-outlook-direction{font-size:28px;font-weight:900;line-height:1;margin-top:5px;letter-spacing:-.02em}
    .lt-session-outlook-direction.bullish{color:var(--green)}
    .lt-session-outlook-direction.bearish{color:var(--red)}
    .lt-session-outlook-direction.wait{color:var(--amber)}
    .lt-session-outlook-confidence{text-align:right;white-space:nowrap}
    .lt-session-outlook-confidence span{display:block;font-size:8px;color:var(--muted);letter-spacing:.07em}
    .lt-session-outlook-confidence strong{display:block;margin-top:3px;font-size:18px}
    .lt-session-outlook-meta{margin-top:7px;color:#a9c4b6;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
    .lt-session-integrity{margin-top:8px;padding:7px 9px;border:1px solid rgba(80,220,145,.25);border-radius:9px;color:#a9c4b6;font-size:8px;line-height:1.45;letter-spacing:.03em}
    .lt-session-integrity.bad{border-color:rgba(255,195,90,.35);color:var(--amber)}
    .lt-session-authority{margin-top:9px;padding:9px 10px;border:1px solid rgba(255,255,255,.10);border-radius:10px;background:#08140f}
    .lt-session-authority span{display:block;font-size:8px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
    .lt-session-authority strong{display:block;margin-top:4px;font-size:17px}
    .lt-session-authority strong.wait{color:var(--amber)}
    .lt-session-authority strong.buy{color:var(--green)}
    .lt-session-authority strong.sell{color:var(--red)}
    .lt-session-authority small{display:block;margin-top:4px;color:#a9c4b6;font-size:8px;line-height:1.4}
    .lt-session-outlook-reasons{margin:10px 0 0;color:#c2d6cc;font-size:11px;line-height:1.5}
    .lt-session-headwinds{margin:8px 0 0;padding:8px 9px;border-left:2px solid rgba(255,195,90,.55);background:rgba(255,195,90,.035);color:#d8c7a0;font-size:9px;line-height:1.45}
    .lt-session-headwinds b{color:var(--amber);font-size:8px;letter-spacing:.07em}
    .lt-session-structure{margin-top:11px;display:grid;grid-template-columns:1fr 1fr;gap:8px}
    .lt-session-structure-item{border:1px solid var(--line);border-radius:11px;padding:10px;background:#08140f}
    .lt-session-structure-item span{display:block;font-size:8px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
    .lt-session-structure-item strong{display:block;margin-top:5px;font-size:13px}
    .lt-session-structure-item strong.bullish{color:var(--green)}
    .lt-session-structure-item strong.bearish{color:var(--red)}
    .lt-session-structure-item strong.waiting{color:var(--amber)}
    .lt-session-structure-item strong.none{color:var(--muted)}
    .lt-session-structure-item small{display:block;margin-top:4px;font-size:8px;color:var(--muted)}
    .lt-session-structure-summary{grid-column:1/-1;margin:0;padding:0 2px;color:#b8d1c4;font-size:9px;line-height:1.45}
    .lt-session-outlook-retrace{margin-top:11px;border:1px solid var(--line);border-radius:11px;padding:11px;background:#08140f}
    .lt-session-outlook-retrace-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .lt-session-outlook-retrace-head span{font-size:9px;font-weight:900;letter-spacing:.08em;color:#b8d1c4}
    .lt-session-outlook-retrace-head small{font-size:8px;color:var(--muted)}
    .lt-session-outlook-retrace-range{font-size:21px;font-weight:900;line-height:1.15;margin-top:5px}
    .lt-session-outlook-retrace-range.bullish{color:var(--green)}
    .lt-session-outlook-retrace-range.bearish{color:var(--red)}
    .lt-session-outlook-retrace-meta{margin-top:5px;font-size:9px;color:#a9c4b6;text-transform:uppercase;letter-spacing:.04em}
    .lt-session-outlook-retrace-note{margin:6px 0 0;font-size:10px;line-height:1.45;color:#c2d6cc}
    .lt-zone-decision{margin-top:10px;border:1px solid var(--line);border-radius:11px;padding:10px;display:grid;grid-template-columns:48px 1fr;gap:10px;align-items:center;background:#06100b}
    .lt-zone-decision.bullish{border-color:rgba(75,240,150,.48)}
    .lt-zone-decision.bearish{border-color:rgba(255,105,125,.48)}
    .lt-zone-decision.undecided{border-color:rgba(255,195,90,.42)}
    .lt-zone-decision-arrow{font-size:36px;font-weight:900;line-height:1;text-align:center;animation:eve-zone-pulse 1.1s ease-in-out infinite}
    .lt-zone-decision.bullish .lt-zone-decision-arrow,.lt-zone-decision.bullish .lt-zone-decision-title{color:var(--green)}
    .lt-zone-decision.bearish .lt-zone-decision-arrow,.lt-zone-decision.bearish .lt-zone-decision-title{color:var(--red)}
    .lt-zone-decision.undecided .lt-zone-decision-arrow,.lt-zone-decision.undecided .lt-zone-decision-title{color:var(--amber)}
    .lt-zone-decision-kicker{font-size:8px;color:var(--muted);font-weight:900;letter-spacing:.08em;text-transform:uppercase}
    .lt-zone-decision-title{margin-top:3px;font-size:13px;font-weight:900;line-height:1.2}
    .lt-zone-decision-side{margin-top:4px;font-size:11px;font-weight:900;letter-spacing:.05em}
    .lt-zone-decision-range{margin-top:3px;font-size:12px;font-weight:900;color:#e7f4ed;font-variant-numeric:tabular-nums}
    .lt-zone-decision-meta{margin-top:4px;font-size:8px;color:var(--muted);font-weight:800;letter-spacing:.04em;text-transform:uppercase}
    .lt-zone-decision-note{margin:4px 0 0;font-size:9px;line-height:1.4;color:#c2d6cc}
    .lt-zone-decision-tfs{margin-top:5px;font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
    @keyframes eve-zone-pulse{0%,100%{transform:scale(.9);opacity:.72}50%{transform:scale(1.14);opacity:1}}
    .lt-session-outlook-flip{margin:8px 0 0;color:var(--muted);font-size:10px;line-height:1.45}
    .lt-chart-zones{grid-column:1/-1;margin-top:12px;border:1px solid var(--line);border-radius:12px;padding:11px;background:#07130e}
    .lt-chart-zones-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:9px}
    .lt-chart-zones-head strong{font-size:11px;letter-spacing:.07em}
    .lt-chart-zones-head small{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
    .lt-chart-zones-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .lt-chart-zone-column{border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px;background:#06100b}
    .lt-chart-zone-column.buy{border-color:rgba(75,240,150,.22)}
    .lt-chart-zone-column.sell{border-color:rgba(255,105,125,.22)}
    .lt-chart-zone-column h4{margin:0 0 7px;font-size:11px;letter-spacing:.06em}
    .lt-chart-zone-column.buy h4{color:var(--green)}
    .lt-chart-zone-column.sell h4{color:var(--red)}
    .lt-chart-zone-row{padding:7px 0;border-top:1px solid rgba(255,255,255,.055)}
    .lt-chart-zone-row:first-of-type{border-top:0;padding-top:0}
    .lt-chart-zone-price{font-size:13px;font-weight:900;font-variant-numeric:tabular-nums;color:#e7f4ed}
    .lt-chart-zone-meta{margin-top:3px;font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.035em;line-height:1.45}
    .lt-chart-zone-sl{margin-top:5px;padding:6px 7px;border-radius:7px;background:rgba(255,255,255,.025);font-size:9px;line-height:1.45}
    .lt-chart-zone-column.buy .lt-chart-zone-sl strong{color:var(--green)}
    .lt-chart-zone-column.sell .lt-chart-zone-sl strong{color:var(--red)}
    .lt-chart-zone-sl small{display:block;margin-top:2px;color:var(--muted);font-size:8px}
    .lt-chart-zone-empty{font-size:9px;color:var(--muted);line-height:1.45}
    .lt-chart-zones-note{margin-top:8px;font-size:8px;color:var(--muted)}
    .lt-session-outlook-note{margin:8px 0 0;padding-top:8px;border-top:1px solid var(--line);color:var(--muted);font-size:9px}
    @media(max-width:760px){.lt-session-structure,.lt-chart-zones-grid{grid-template-columns:1fr}}
    @media(prefers-reduced-motion:reduce){.lt-zone-decision-arrow{animation:none}}
  `;
  document.head.appendChild(style);

  function safe(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function fmt(value) {
    const parsed = number(value);
    return parsed == null ? '—' : parsed.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
  }

  function utcClock(value) {
    const text = String(value || '');
    return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text) ? `${text.slice(11,16)} UTC` : '—';
  }

  function contextIntegrity(state) {
    const feed = state?.feed || {};
    const dq = state?.bias?.data_quality || {};
    const ctx = state?.live_context_freshness || {};
    const lag = number(ctx.context_lag_minutes ?? dq.live_context_lag_minutes);
    const valid = feed.status === 'live'
      && feed.connected === true
      && ctx.context_valid === true
      && ctx.fresh === true
      && dq.live_context_stale !== true
      && dq.trade_bias_blocked !== true
      && lag != null
      && lag >= 0
      && lag <= MAX_CONTEXT_LAG_MINUTES;

    let reason = '';
    if (feed.status !== 'live' || feed.connected !== true) reason = 'Live price feed is not currently fresh.';
    else if (ctx.context_valid !== true) reason = `M5 context is not validated${ctx.validation_error ? `: ${ctx.validation_error}` : '.'}`;
    else if (ctx.fresh !== true || dq.live_context_stale === true) reason = 'M5/MTF context is stale.';
    else if (dq.trade_bias_blocked === true) reason = 'Trading bias is blocked by data quality.';
    else if (lag == null || lag < 0 || lag > MAX_CONTEXT_LAG_MINUTES) reason = 'Context lag is outside the accepted live range.';

    return {
      valid,
      reason,
      lag,
      tick: ctx.live_tick_at || feed.last_tick_at,
      m5: ctx.effective_latest_m5 || state?.market?.fabric_time,
      decision: ctx.effective_decision_time,
    };
  }

  function momentumReasonsHtml(reasons) {
    const text = reasons.join(' ');
    const match = text.match(/Momentum:\s*12-bar\s*([+-]?\d+(?:\.\d+)?)%,\s*48-bar\s*([+-]?\d+(?:\.\d+)?)%\.?/i);
    if (!match) return safe(text);

    const oneHour = Number(match[1]);
    const fourHour = Number(match[2]);
    const movementFor = value => value > 0 ? 'Rising' : value < 0 ? 'Falling' : 'Flat';
    const arrowFor = value => value > 0 ? '↑' : value < 0 ? '↓' : '→';
    const pct = value => `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
    const oneMove = movementFor(oneHour);
    const fourMove = movementFor(fourHour);
    const read = oneMove === fourMove && oneMove !== 'Flat'
      ? `${oneMove} on both rolling windows`
      : oneMove === 'Flat' && fourMove === 'Flat'
        ? 'Flat on both rolling windows'
        : 'Mixed';
    const rest = text.replace(match[0], '').trim();

    return `Rolling 1H momentum: ${oneMove} ${safe(pct(oneHour))} ${arrowFor(oneHour)}<br>` +
      `Rolling 4H momentum: ${fourMove} ${safe(pct(fourHour))} ${arrowFor(fourHour)}<br>` +
      `Momentum read: ${safe(read)}` +
      (rest ? `<br>${safe(rest)}` : '');
  }

  function zoneDistanceAtr(item, price, atr) {
    const supplied = number(item?.zone?.distance_atr);
    if (supplied != null) return supplied;
    if (item.low <= price && price <= item.high) return 0;
    const distance = price < item.low ? item.low - price : price - item.high;
    return distance / Math.max(atr, 0.01);
  }

  function retracePlan(state, direction) {
    const price = number(state?.price);
    const atr = Math.max(number(state?.market?.atr) || 0, 0.01);
    const biasDirection = String(state?.bias?.overall || 'neutral').toLowerCase();
    const zones = state?.zones || {};
    const kind = direction === 'bearish' ? 'supply' : 'demand';
    const side = direction === 'bearish' ? 'SELL' : 'BUY';
    const zonesForSide = Array.isArray(zones[kind]) ? zones[kind] : [];
    const trade = state?.trade || {};
    const clear = trade?.clear_bias_gate?.clear === true;
    const action = String(trade.action || 'WAIT').toUpperCase();
    const actionable = !['', 'WAIT', 'NO TRADE'].includes(action);

    if (price == null) return {available:false, reason:'Current price is unavailable.'};
    if (biasDirection !== direction) {
      return {available:false, reason:`Session lean is ${direction.toUpperCase()} but trade bias is ${biasDirection.toUpperCase()}. No directional retrace plan is shown while they disagree.`};
    }

    const candidates = zonesForSide
      .map(zone => ({
        zone,
        low:number(zone?.low),
        high:number(zone?.high),
        quality:number(zone?.quality),
      }))
      .filter(item => item.low != null && item.high != null && item.high >= item.low)
      .filter(item => item.zone?.fresh !== false)
      .filter(item => !['BROKEN','INVALID','EXPIRED'].includes(String(item.zone?.status || '').toUpperCase()))
      .filter(item => item.quality == null || item.quality >= LIVE_ZONE_MIN_QUALITY)
      .map(item => ({...item, distanceAtr:zoneDistanceAtr(item, price, atr)}))
      .filter(item => item.distanceAtr <= LIVE_ZONE_MAX_DISTANCE_ATR);

    const containing = candidates.find(item => item.low <= price && price <= item.high);
    let selected = containing || null;
    if (!selected && direction === 'bearish') {
      selected = candidates.filter(item => item.low > price).sort((a,b) => a.low - b.low)[0] || null;
    }
    if (!selected && direction === 'bullish') {
      selected = candidates.filter(item => item.high < price).sort((a,b) => b.high - a.high)[0] || null;
    }
    if (!selected) {
      return {
        available:false,
        reason:`No current ${kind} zone meets the live quality/proximity geometry (quality ≥ ${LIVE_ZONE_MIN_QUALITY}, distance ≤ ${LIVE_ZONE_MAX_DISTANCE_ATR.toFixed(1)} ATR).`,
      };
    }

    const inZone = selected.low <= price && price <= selected.high;
    const actionWord = direction === 'bearish' ? 'bearish rejection' : 'bullish rejection';
    const travel = direction === 'bearish' ? 'up' : 'down';
    const title = actionable
      ? `LIVE ${side} CONTEXT`
      : clear
        ? `RETRACE WATCH FOR ${side}`
        : 'WATCH AREA — NO TRADE YET';
    const note = actionable
      ? `The authoritative live trade state is ${action}. Use the published trade entry/SL/TP, not this display zone, as execution authority.`
      : inZone
        ? `Price is inside current ${kind}. EVE's trade gate has NOT confirmed a ${side}; wait for the authoritative trade action to change.`
        : `Price may retrace ${travel} into this current ${kind} area. It is a watch area only; wait for EVE's authoritative trade state before acting on ${actionWord}.`;

    return {
      available:true,
      title,
      low:selected.low,
      high:selected.high,
      kind:kind.toUpperCase(),
      kindLower:kind,
      side,
      quality:selected.quality,
      distanceAtr:selected.distanceAtr,
      fresh:selected.zone?.fresh === true,
      retests:Math.max(0, Number(selected.zone?.retests || 0)),
      zoneRole:String(selected.zone?.zone_role || 'M5_ONLY'),
      h1Confluence:selected.zone?.h1_confluence === true,
      m15Confluence:selected.zone?.m15_confluence === true,
      inZone,
      note,
    };
  }

  function timeframeDirection(state, key) {
    const item = state?.bias?.timeframes?.[key];
    if (item && typeof item === 'object') return String(item.direction || '').toLowerCase();
    return String(item || '').toLowerCase();
  }

  function zoneDecision(state, direction, retrace) {
    if (!retrace?.available || !retrace.inZone) return null;

    const desired = direction;
    const opposite = direction === 'bullish' ? 'bearish' : 'bullish';
    const m5 = timeframeDirection(state, 'M5');
    const m15 = timeframeDirection(state, 'M15');
    const trade = state?.trade || {};
    const action = String(trade.action || '').toUpperCase();
    const tradeSide = String(trade.side || '').toUpperCase();
    const strategyKey = String(trade.strategy_key || '');
    const executionClass = String(trade.execution_class || '');
    const actionable = !['', 'WAIT', 'NO TRADE'].includes(action);
    const specialistTrade = strategyKey === 'zone_retrace_v1' || executionClass === 'zone_retrace_confirmation';
    const confirmed = actionable && specialistTrade &&
      (tradeSide === retrace.side || action === retrace.side || action.startsWith(retrace.side));

    const desiredArrow = desired === 'bullish' ? '↑' : '↓';
    const oppositeArrow = opposite === 'bullish' ? '↑' : '↓';
    const zoneName = retrace.kindLower;
    const side = retrace.side;

    if (confirmed) return {
      tone:desired, arrow:desiredArrow, title:`${desired.toUpperCase()} REJECTION CONFIRMED`,
      note:`EVE's authoritative live zone-retracement strategy has confirmed the ${side}.`, m5, m15,
    };

    if (m5 === desired && m15 === desired) return {
      tone:desired, arrow:desiredArrow, title:'REJECTION BUILDING — WAIT',
      note:`M5 and M15 are aligned ${desired} while price is in ${zoneName}, but EVE has not confirmed the ${side}.`, m5, m15,
    };

    if (m5 === opposite && m15 === opposite) return {
      tone:opposite, arrow:oppositeArrow, title:`${opposite.toUpperCase()} BREAK BUILDING`,
      note:`M5 and M15 are aligned ${opposite} while price is in ${zoneName}. Do not take the ${side} while this remains.`, m5, m15,
    };

    return {
      tone:'undecided', arrow:'↕', title:'UNDECIDED — WAIT',
      note:`M5 and M15 do not agree yet. EVE has not confirmed the ${side}.`, m5, m15,
    };
  }

  function zoneDecisionHtml(decision, retrace) {
    if (!decision) return '';
    const tfLabel = value => ['bullish','bearish','neutral'].includes(value) ? value.toUpperCase() : 'UNKNOWN';
    const backing = retrace.h1Confluence && retrace.m15Confluence
      ? 'H1 + M15 BACKED'
      : retrace.h1Confluence
        ? 'H1 BACKED'
        : retrace.m15Confluence
          ? 'M15 BACKED'
          : 'M5 ONLY';
    const quality = retrace.quality == null ? 'QUALITY —' : `QUALITY ${Math.round(retrace.quality)}/100`;
    const retests = `${retrace.retests} RETEST${retrace.retests === 1 ? '' : 'S'}`;
    const freshness = retrace.fresh ? 'FRESH' : 'USED';
    return `
      <div class="lt-zone-decision ${safe(decision.tone)}">
        <div class="lt-zone-decision-arrow" aria-hidden="true">${safe(decision.arrow)}</div>
        <div>
          <div class="lt-zone-decision-kicker">PRICE IS IN ${safe(retrace.kind)} · ZONE DECISION</div>
          <div class="lt-zone-decision-title">${safe(decision.title)}</div>
          <div class="lt-zone-decision-side">POTENTIAL ${safe(retrace.side)} ZONE</div>
          <div class="lt-zone-decision-range">${safe(retrace.kind)} ${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}</div>
          <div class="lt-zone-decision-meta">${safe(backing)} · ${safe(quality)} · ${safe(retests)} · ${safe(freshness)}</div>
          <p class="lt-zone-decision-note">${safe(decision.note)}</p>
          <div class="lt-zone-decision-tfs">M5 ${safe(tfLabel(decision.m5))} · M15 ${safe(tfLabel(decision.m15))}</div>
        </div>
      </div>`;
  }

  function reclaimedLiquidityKeysForZoneSl(liquidity) {
    const reclaimed = new Set();
    (liquidity?.market_events || []).forEach(event => {
      const eventClass = String(event?.event_class || '');
      const key = String(event?.level_key || '');
      const isSweep = eventClass.includes('sweep_reclaim') || eventClass.startsWith('failed_breakout');
      if (key && isSweep && event?.reclaimed === true) reclaimed.add(key);
    });
    return reclaimed;
  }

  function zoneSpecificSlReference(state, kind, low, high) {
    const atr = Math.max(number(state?.market?.atr) || 0, 0.01);
    const buffer = Math.max(atr * ZONE_SL_BUFFER_ATR, 0.01);
    const huntBand = atr * ZONE_SL_HUNT_BAND_ATR;
    const liquidity = state?.liquidity || {};
    const buy = kind === 'demand';
    const edge = buy ? low : high;
    const side = buy ? 'below' : 'above';
    const reclaimed = reclaimedLiquidityKeysForZoneSl(liquidity);
    const definitions = buy
      ? [
          ['recent_low','recent low'],
          ['previous_day_low','previous-day low'],
          ['london_low','London low'],
          ['new_york_low','New York low'],
        ]
      : [
          ['recent_high','recent high'],
          ['previous_day_high','previous-day high'],
          ['london_high','London high'],
          ['new_york_high','New York high'],
        ];

    const candidates = [];
    definitions.forEach(([key,label]) => {
      if (reclaimed.has(key)) return;
      const level = number(liquidity?.[key]);
      if (level == null || level <= 0) return;
      const beyond = buy ? level < edge : level > edge;
      const within = Math.abs(level - edge) <= huntBand;
      if (beyond && within) candidates.push({level, label, type:'liquidity'});
    });

    (liquidity?.market_events || []).forEach(event => {
      const eventClass = String(event?.event_class || '');
      const eventSide = String(event?.side || '');
      const isPriorSweep = event?.reclaimed === true &&
        (eventClass.includes('sweep_reclaim') || eventClass.startsWith('failed_breakout'));
      const matchingSide = buy ? eventSide === 'sell_side' : eventSide === 'buy_side';
      const extreme = number(event?.extreme);
      if (!isPriorSweep || !matchingSide || extreme == null || extreme <= 0) return;
      const beyond = buy ? extreme < edge : extreme > edge;
      const within = Math.abs(extreme - edge) <= huntBand;
      if (beyond && within) candidates.push({
        level:extreme,
        label:buy ? 'prior sell-side sweep extreme' : 'prior buy-side sweep extreme',
        type:'sweep',
      });
    });

    if (!candidates.length) {
      return {
        level:buy ? edge - buffer : edge + buffer,
        basis:'ZONE EDGE + ATR BUFFER',
        detail:`No relevant liquidity/sweep level exists within ${ZONE_SL_HUNT_BAND_ATR.toFixed(2)} ATR beyond this zone.`,
        usedSweep:false,
      };
    }

    const anchor = buy
      ? Math.min(...candidates.map(item => item.level))
      : Math.max(...candidates.map(item => item.level));
    const relevant = candidates.filter(item => Math.abs(item.level - anchor) <= 0.001);
    const usedSweep = relevant.some(item => item.type === 'sweep');
    const labels = [...new Set(relevant.map(item => item.label))];
    return {
      level:buy ? anchor - buffer : anchor + buffer,
      basis:usedSweep ? 'SWEEP-PROTECTED STRUCTURAL REF' : 'LIQUIDITY-PROTECTED STRUCTURAL REF',
      detail:`Beyond ${labels.join(' + ')} + ${ZONE_SL_BUFFER_ATR.toFixed(2)} ATR buffer.`,
      usedSweep,
    };
  }

  function chartZoneBacking(zone) {
    if (zone?.h1_confluence === true && zone?.m15_confluence === true) return 'H1 + M15 BACKED';
    if (zone?.h1_confluence === true) return 'H1 BACKED';
    if (zone?.m15_confluence === true) return 'M15 BACKED';
    return 'M5 ONLY';
  }

  function chartZoneRows(state, kind) {
    const price = number(state?.price);
    const chartSource = state?.chart_zones || state?.zones || {};
    const zones = Array.isArray(chartSource?.[kind]) ? chartSource[kind] : [];
    return zones
      .map(zone => {
        const low = number(zone?.low);
        const high = number(zone?.high);
        if (low == null || high == null || high < low) return null;
        const status = String(zone?.status || '').toUpperCase();
        if (['BROKEN','INVALID','EXPIRED'].includes(status)) return null;
        const distance = price == null || (low <= price && price <= high)
          ? 0
          : Math.min(Math.abs(price - low), Math.abs(price - high));
        return {
          low,
          high,
          distance,
          quality:number(zone?.quality),
          retests:Math.max(0, Number(zone?.retests || 0)),
          fresh:zone?.fresh === true,
          backing:chartZoneBacking(zone),
          chartState:String(zone?.chart_state || zone?.status || 'ACTIVE').toUpperCase(),
          slRef:zoneSpecificSlReference(state, kind, low, high),
        };
      })
      .filter(Boolean)
      .sort((a,b) => a.distance - b.distance);
  }

  function chartZoneColumn(state, kind, side) {
    const rows = chartZoneRows(state, kind);
    if (!rows.length) {
      return `<div class="lt-chart-zone-column ${side.toLowerCase()}"><h4>${side} ZONES</h4><div class="lt-chart-zone-empty">No current ${safe(kind)} zones are available from this snapshot.</div></div>`;
    }
    return `
      <div class="lt-chart-zone-column ${side.toLowerCase()}">
        <h4>${side} ZONES</h4>
        ${rows.map((zone, index) => {
          const quality = zone.quality == null ? 'QUALITY —' : `QUALITY ${Math.round(zone.quality)}/100`;
          const retests = `${zone.retests} RETEST${zone.retests === 1 ? '' : 'S'}`;
          const freshness = zone.fresh ? 'FRESH' : 'USED';
          const chartState = zone.chartState === 'UNDER PRESSURE' ? ' · UNDER PRESSURE' : zone.chartState === 'IN ZONE' ? ' · IN ZONE' : '';
          return `
            <div class="lt-chart-zone-row">
              <div class="lt-chart-zone-price">${index + 1}. ${safe(fmt(zone.low))} – ${safe(fmt(zone.high))}</div>
              <div class="lt-chart-zone-meta">${safe(zone.backing)} · ${safe(quality)} · ${safe(retests)} · ${safe(freshness)}${safe(chartState)}</div>
              <div class="lt-chart-zone-sl"><strong>SL REF ${safe(fmt(zone.slRef?.level))}</strong><small>${safe(zone.slRef?.basis || 'STRUCTURAL REF')} · ${safe(zone.slRef?.detail || '')}</small></div>
            </div>`;
        }).join('')}
      </div>`;
  }

  function chartZonesHtml(state) {
    return `
      <div class="lt-chart-zones">
        <div class="lt-chart-zones-head">
          <strong>RELEVANT CHART ZONES</strong>
          <small>SAME SNAPSHOT · NEAREST FIRST</small>
        </div>
        <div class="lt-chart-zones-grid">
          ${chartZoneColumn(state, 'demand', 'BUY')}
          ${chartZoneColumn(state, 'supply', 'SELL')}
        </div>
        <div class="lt-chart-zones-note">For drawing on your chart. These zones stay mapped until EVE's completed-candle invalidation removes them or they genuinely age out of the zone lookback; moving past a proximity threshold or changing rank will not make them disappear. Each SL REF is zone-specific and sweep/liquidity-aware where relevant. Only AUTHORITATIVE TRADE ACTION is execution authority.</div>
      </div>`;
  }


  function structurePlan(outlook) {
    const structure = outlook?.structure || {};
    const bosSupport = String(structure.bos_support || 'none').toLowerCase();
    const waiting = Boolean(structure.bos_waiting_after_choch);
    const bos = structure.bos || {};
    const chochDirection = String(structure.choch_direction || 'none').toLowerCase();
    const choch = structure.choch || {};

    let bosText = 'NONE';
    let bosClass = 'none';
    let bosNote = 'No current-session BOS confirmation.';
    if (waiting) {
      const pending = structure.bos_confirmation || {};
      const pendingDirection = String(pending.direction || chochDirection || '').toLowerCase();
      const pendingLevel = number(pending.level);
      bosText = pendingDirection === 'bullish' || pendingDirection === 'bearish'
        ? `WAITING ${pendingDirection.toUpperCase()} BOS`
        : 'WAITING BOS';
      bosClass = 'waiting';
      if (pendingLevel != null) {
        const relation = pendingDirection === 'bearish' ? 'below' : 'above';
        bosNote = `Next BOS level ${fmt(pendingLevel)} · completed M5 close must finish ${relation} it by max(2% ATR, 0.01)`;
      } else {
        const swing = pendingDirection === 'bearish' ? 'low' : pendingDirection === 'bullish' ? 'high' : 'level';
        bosNote = `CHoCH confirmed · waiting for the next confirmed swing ${swing} before a BOS level exists.`;
      }
    } else if (bosSupport === 'bullish' || bosSupport === 'bearish') {
      bosText = `SUPPORTS ${bosSupport.toUpperCase()}`;
      bosClass = bosSupport;
      bosNote = bos?.level == null ? 'Confirmed by completed M5 close.' : `Break level ${fmt(bos.level)} · completed M5 close`;
    }

    let chochText = 'NONE';
    let chochClass = 'none';
    let chochNote = 'No current-session change of character.';
    if (chochDirection === 'bullish' || chochDirection === 'bearish') {
      chochText = chochDirection.toUpperCase();
      chochClass = chochDirection;
      chochNote = choch?.level == null ? 'Change of character confirmed.' : `Break level ${fmt(choch.level)} · completed M5 close`;
    }

    return {
      bosText, bosClass, bosNote, chochText, chochClass, chochNote,
      summary:String(structure.summary || 'Building current-session M5 structure readout…'),
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
    panel.dataset.integrityVersion = CARD_INTEGRITY_VERSION;
    const statusRow = biasCard.querySelector('.lt-status-row');
    if (statusRow) statusRow.insertAdjacentElement('beforebegin', panel);
    else biasCard.appendChild(panel);
    return panel;
  }

  function authorityHtml(state) {
    const trade = state?.trade || {};
    const action = String(trade.action || 'WAIT').toUpperCase();
    const waiting = action === 'WAIT' || action === 'NO TRADE' || !action;
    const tone = waiting ? 'wait' : action.includes('SELL') ? 'sell' : 'buy';
    const reason = String(trade.reason || state?.setup?.reason || '');
    return `
      <div class="lt-session-authority">
        <span>AUTHORITATIVE TRADE ACTION</span>
        <strong class="${tone}">${safe(waiting ? 'WAIT' : action)}</strong>
        ${reason ? `<small>${safe(reason)}</small>` : ''}
      </div>`;
  }

  function integrityHtml(integrity) {
    if (!integrity.valid) {
      return `<div class="lt-session-integrity bad">DATA CHECK FAILED · ${safe(integrity.reason || 'Live context is not validated.')}</div>`;
    }
    return `<div class="lt-session-integrity">DATA FRESH · SAME SNAPSHOT · M5 ${safe(utcClock(integrity.m5))} · DECISION ${safe(utcClock(integrity.decision))} · LAG ${safe(integrity.lag)}m</div>`;
  }

  function renderInvalid(state, integrity) {
    const panel = ensurePanel();
    if (!panel) return;
    panel.classList.add('invalid');
    panel.innerHTML = `
      <div class="lt-session-outlook-head">
        <div><span>SESSION LEAN</span><div class="lt-session-outlook-direction wait">WAIT — DATA NOT VALID</div></div>
      </div>
      ${integrityHtml(integrity)}
      ${authorityHtml(state)}
      <p class="lt-session-outlook-note">Directional outlook, BOS/CHoCH, retrace zones and stop references must not be trusted until the live-context check is valid again.</p>`;
  }

  function render(state) {
    const panel = ensurePanel();
    if (!panel) return;

    const integrity = contextIntegrity(state);
    if (!integrity.valid) {
      renderInvalid(state, integrity);
      return;
    }

    panel.classList.remove('invalid');
    const outlook = state?.session_outlook || state?.market?.session_outlook || {};
    const direction = String(outlook.direction || '').toLowerCase();
    if (!['bullish','bearish'].includes(direction)) {
      panel.innerHTML = `
        <span>SESSION LEAN</span>
        ${integrityHtml(integrity)}
        ${authorityHtml(state)}
        <div class="lt-session-outlook-meta">No directional session lean is currently available.</div>
        ${chartZonesHtml(state)}`;
      return;
    }

    const confidence = Number(outlook.confidence || 51);
    const conviction = String(outlook.conviction || (confidence <= 57 ? 'slight' : confidence <= 66 ? 'moderate' : confidence <= 76 ? 'clear' : 'strong'));
    const session = String(outlook.session_label || outlook.session || 'current').replaceAll('_',' ');
    const reasons = Array.isArray(outlook.reasons) ? outlook.reasons.filter(Boolean).slice(0,3) : [];
    const headwinds = Array.isArray(outlook.headwinds) ? outlook.headwinds.filter(Boolean).slice(0,2) : [];
    const flip = String(outlook.flip_text || '');
    const tradeBias = String(state?.bias?.overall || 'neutral').toUpperCase();
    const structure = structurePlan(outlook);
    const retrace = retracePlan(state, direction);
    const decision = zoneDecision(state, direction, retrace);

    const structureHtml = `
      <div class="lt-session-structure">
        <div class="lt-session-structure-item">
          <span>BOS SUPPORT · M5</span>
          <strong class="${safe(structure.bosClass)}">${safe(structure.bosText)}</strong>
          <small>${safe(structure.bosNote)}</small>
        </div>
        <div class="lt-session-structure-item">
          <span>CHoCH · M5</span>
          <strong class="${safe(structure.chochClass)}">${safe(structure.chochText)}</strong>
          <small>${safe(structure.chochNote)}</small>
        </div>
        <p class="lt-session-structure-summary">${safe(structure.summary)}</p>
      </div>`;

    const retraceHtml = retrace?.available ? `
      <div class="lt-session-outlook-retrace">
        <div class="lt-session-outlook-retrace-head"><span>${safe(retrace.title)}</span><small>SAME SNAPSHOT · AUTO-UPDATING</small></div>
        <div class="lt-session-outlook-retrace-range ${safe(direction)}">${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}</div>
        <div class="lt-session-outlook-retrace-meta">CURRENT ${safe(retrace.kind)}${retrace.quality == null ? '' : ` · QUALITY ${safe(Math.round(retrace.quality))}/100`} · ${safe(retrace.distanceAtr.toFixed(2))} ATR</div>
        <p class="lt-session-outlook-retrace-note">${safe(retrace.note)}</p>
        ${zoneDecisionHtml(decision, retrace)}
      </div>` : `
      <div class="lt-session-outlook-retrace">
        <div class="lt-session-outlook-retrace-head"><span>NO QUALIFIED RETRACE PLAN</span><small>SAME SNAPSHOT</small></div>
        <p class="lt-session-outlook-retrace-note">${safe(retrace?.reason || 'No qualified current retrace zone is available.')}</p>
      </div>`;

    panel.innerHTML = `
      <div class="lt-session-outlook-head">
        <div><span>SESSION LEAN</span><div class="lt-session-outlook-direction ${safe(direction)}">${safe(direction.toUpperCase())} LEAN</div></div>
        <div class="lt-session-outlook-confidence"><span>LEAN STRENGTH · NOT WIN RATE</span><strong>${safe(confidence)}/100</strong></div>
      </div>
      <div class="lt-session-outlook-meta">${safe(conviction)} lean · ${safe(session)} session</div>
      ${integrityHtml(integrity)}
      ${authorityHtml(state)}
      <p class="lt-session-outlook-reasons">${momentumReasonsHtml(reasons)}</p>
      ${headwinds.length ? `<p class="lt-session-headwinds"><b>HEADWINDS / OPPOSING EVIDENCE</b><br>${safe(headwinds.join(' '))}</p>` : ''}
      ${structureHtml}
      ${retraceHtml}
      ${chartZonesHtml(state)}
      <p class="lt-session-outlook-flip">${safe(flip)}</p>
      <p class="lt-session-outlook-note">Trade bias: ${safe(tradeBias)} · Session lean is an opinion, not a trade signal. BOS/CHoCH and zone guidance are display context. Only AUTHORITATIVE TRADE ACTION above is execution authority.</p>`;
  }

  function consume(event) {
    const state = event?.detail?.state;
    if (state && typeof state === 'object') render(state);
  }

  window.addEventListener('eve:live-trader-state', consume);
  document.querySelector('[data-view="live-trader"]')?.addEventListener('click', () => {
    if (window.__eveLiveTraderState) render(window.__eveLiveTraderState);
  });
  if (window.__eveLiveTraderState) render(window.__eveLiveTraderState);
})();
