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
    .lt-zone-decision-note{margin:4px 0 0;font-size:9px;line-height:1.4;color:#c2d6cc}
    .lt-zone-decision-tfs{margin-top:5px;font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
    @keyframes eve-zone-pulse{0%,100%{transform:scale(.9);opacity:.72}50%{transform:scale(1.14);opacity:1}}
    .lt-session-outlook-flip{margin:8px 0 0;color:var(--muted);font-size:10px;line-height:1.45}
    .lt-session-outlook-note{margin:8px 0 0;padding-top:8px;border-top:1px solid var(--line);color:var(--muted);font-size:9px}
    @media(max-width:760px){.lt-session-structure{grid-template-columns:1fr}}
    @media(prefers-reduced-motion:reduce){.lt-zone-decision-arrow{animation:none}}
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
      ? `${oneMove} on both 1H and 4H`
      : oneMove === 'Flat' && fourMove === 'Flat'
        ? 'Flat on both 1H and 4H'
        : 'Mixed';
    const rest = text.replace(match[0], '').trim();

    return `1H Momentum: ${oneMove} ${safe(pct(oneHour))} ${arrowFor(oneHour)}<br>` +
      `4H Momentum: ${fourMove} ${safe(pct(fourHour))} ${arrowFor(fourHour)}<br>` +
      `Momentum read: ${safe(read)}` +
      (rest ? `<br>${safe(rest)}` : '');
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
      kindLower:kind,
      side,
      quality:selected.quality,
      inZone,
      note:inZone
        ? `Price is inside current ${kind}. EVE is now judging whether the zone rejects or breaks.`
        : `Wait for price to retrace ${travel} into this current ${kind} area, then look for ${action}.`,
    };
  }

  function timeframeDirection(state, key) {
    const item = state?.bias?.timeframes?.[key];
    if (item && typeof item === 'object') return String(item.direction || '').toLowerCase();
    return String(item || '').toLowerCase();
  }

  function zoneDecision(state, direction, retrace) {
    if (!retrace?.inZone) return null;

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

    if (confirmed) {
      return {
        tone:desired,
        arrow:desiredArrow,
        title:`${desired.toUpperCase()} REJECTION CONFIRMED`,
        note:`EVE's live zone-retracement strategy has confirmed the ${side}.`,
        m5,
        m15,
      };
    }

    if (m5 === desired && m15 === desired) {
      return {
        tone:desired,
        arrow:desiredArrow,
        title:'REJECTION BUILDING',
        note:`M5 and M15 are aligned ${desired} while price is in ${zoneName}. Evidence is building, but EVE has not confirmed the ${side} yet.`,
        m5,
        m15,
      };
    }

    if (m5 === opposite && m15 === opposite) {
      return {
        tone:opposite,
        arrow:oppositeArrow,
        title:`${opposite.toUpperCase()} BREAK BUILDING`,
        note:`M5 and M15 are aligned ${opposite} while price is in ${zoneName}. The zone may fail. Do not take the ${side} while this remains.`,
        m5,
        m15,
      };
    }

    return {
      tone:'undecided',
      arrow:'↕',
      title:'UNDECIDED — WAIT',
      note:`M5 and M15 do not agree yet. EVE cannot tell whether ${zoneName} will reject or break. Wait.`,
      m5,
      m15,
    };
  }

  function zoneDecisionHtml(decision, retrace) {
    if (!decision) return '';
    const tfLabel = value => ['bullish','bearish','neutral'].includes(value) ? value.toUpperCase() : 'UNKNOWN';
    return `
      <div class="lt-zone-decision ${safe(decision.tone)}">
        <div class="lt-zone-decision-arrow" aria-hidden="true">${safe(decision.arrow)}</div>
        <div>
          <div class="lt-zone-decision-kicker">PRICE IS IN ${safe(retrace.kind)} · ZONE DECISION</div>
          <div class="lt-zone-decision-title">${safe(decision.title)}</div>
          <p class="lt-zone-decision-note">${safe(decision.note)}</p>
          <div class="lt-zone-decision-tfs">M5 ${safe(tfLabel(decision.m5))} · M15 ${safe(tfLabel(decision.m15))}</div>
        </div>
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
      bosText = 'WAITING CONFIRMATION';
      bosClass = 'waiting';
      bosNote = 'A CHoCH occurred after the previous BOS.';
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
      bosText,
      bosClass,
      bosNote,
      chochText,
      chochClass,
      chochNote,
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
    const retraceHtml = retrace ? `
      <div class="lt-session-outlook-retrace">
        <div class="lt-session-outlook-retrace-head"><span>${safe(retrace.title)}</span><small>LIVE · AUTO-UPDATING</small></div>
        <div class="lt-session-outlook-retrace-range ${safe(direction)}">${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}</div>
        <div class="lt-session-outlook-retrace-meta">CURRENT ${safe(retrace.kind)}${retrace.quality == null ? '' : ` · QUALITY ${safe(Math.round(retrace.quality))}/100`}</div>
        <p class="lt-session-outlook-retrace-note">${safe(retrace.note)}</p>
        ${zoneDecisionHtml(decision, retrace)}
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
      <p class="lt-session-outlook-reasons">${momentumReasonsHtml(reasons)}</p>
      ${structureHtml}
      ${retraceHtml}
      <p class="lt-session-outlook-flip">${safe(flip)}</p>
      <p class="lt-session-outlook-note">Trade bias: ${safe(tradeBias)} · BOS/CHoCH, retrace and zone-decision information are display guidance only. Only EVE's existing live trade state can confirm a trade.</p>`;
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