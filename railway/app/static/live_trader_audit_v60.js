(() => {
  const VERSION = 'eve-live-trader-ui-integrity-v79';
  if (window.__eveLiveTraderUiIntegrityV79) return;
  window.__eveLiveTraderUiIntegrityV79 = true;

  const style = document.createElement('style');
  style.textContent = `
    #view-live-trader .lt-legacy-chat-note{margin:0 0 12px;padding:9px 11px;border:1px solid rgba(255,255,255,.08);border-radius:9px;color:#8fa19b;font-size:10px;line-height:1.4;background:rgba(255,255,255,.02)}
    #view-live-trader .lt-zone{contain:layout paint}
  `;
  document.head.appendChild(style);

  const legacyPatterns = [
    /preferred execution is\s+(?:buy|sell)\s+(?:stop|limit)/i,
    /\b(?:buy|sell)\s+(?:stop|limit)\s*:\s*entry/i,
    /prove the breakout before getting (?:long|short)/i,
  ];

  const ZONE_MIN_HOLD_MS = 20000;
  const ZONE_ABSOLUTE_GAIN_ATR = 0.35;
  const ZONE_RELATIVE_RATIO = 0.70;
  const zoneSelection = {
    demand:{key:null,switchedAt:0},
    supply:{key:null,switchedAt:0},
  };

  const finite = (value, fallback = null) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const zoneKey = (kind, zone = {}) => String(zone.id || `${kind}|${zone.origin_time || ''}|${finite(zone.low, '')}|${finite(zone.high, '')}`);
  const zoneInside = zone => String(zone?.status || '').toUpperCase() === 'IN ZONE';
  const zoneDistance = zone => Math.max(0, finite(zone?.distance_atr, 999));

  function stabilizeZoneList(kind, source) {
    const zones = Array.isArray(source) ? source.filter(Boolean) : [];
    const memory = zoneSelection[kind];
    if (!memory || !zones.length) {
      if (memory) {
        memory.key = null;
        memory.switchedAt = 0;
      }
      return zones;
    }

    const now = Date.now();
    const candidate = zones[0];
    const candidateKey = zoneKey(kind, candidate);
    let current = memory.key ? zones.find(zone => zoneKey(kind, zone) === memory.key) : null;

    if (!current) {
      memory.key = candidateKey;
      memory.switchedAt = now;
      current = candidate;
    } else if (candidateKey !== memory.key) {
      const currentDistance = zoneDistance(current);
      const candidateDistance = zoneDistance(candidate);
      const absoluteGain = currentDistance - candidateDistance;
      const relativeGain = currentDistance > 0 ? candidateDistance / currentDistance : 1;
      const challengerEntered = zoneInside(candidate) && !zoneInside(current);
      const holdElapsed = now - memory.switchedAt >= ZONE_MIN_HOLD_MS;
      const meaningfullyCloser = absoluteGain >= ZONE_ABSOLUTE_GAIN_ATR || (currentDistance >= 0.5 && relativeGain <= ZONE_RELATIVE_RATIO);

      if (challengerEntered || (holdElapsed && meaningfullyCloser)) {
        memory.key = candidateKey;
        memory.switchedAt = now;
        current = candidate;
      }
    }

    const heldKey = memory.key;
    const held = zones.find(zone => zoneKey(kind, zone) === heldKey) || zones[0];
    return [held, ...zones.filter(zone => zoneKey(kind, zone) !== zoneKey(kind, held))];
  }

  function stabilizeLiveTraderPayload(payload) {
    if (!payload || typeof payload !== 'object' || !payload.zones || typeof payload.zones !== 'object') return payload;
    payload.zones.demand = stabilizeZoneList('demand', payload.zones.demand);
    payload.zones.supply = stabilizeZoneList('supply', payload.zones.supply);
    return payload;
  }

  function installZoneStabilityBoundary() {
    const original = window.api;
    if (typeof original !== 'function' || original.__eveZoneStabilityV79) return false;
    const wrapped = async function(path, options = {}) {
      const payload = await original.call(this, path, options);
      const method = String(options?.method || 'GET').toUpperCase();
      if (String(path || '') === '/live-trader' && method === 'GET') stabilizeLiveTraderPayload(payload);
      return payload;
    };
    wrapped.__eveZoneStabilityV79 = true;
    wrapped.__eveZoneStabilityOriginal = original;
    window.api = wrapped;
    return true;
  }

  function cleanLegacyConversation() {
    const box = document.getElementById('ltConversation');
    if (!box) return;
    let hidden = 0;
    box.querySelectorAll('.lt-msg.assistant').forEach(item => {
      if (item.dataset.legacyChecked === VERSION) {
        if (item.hidden) hidden += 1;
        return;
      }
      item.dataset.legacyChecked = VERSION;
      const text = item.textContent || '';
      if (legacyPatterns.some(pattern => pattern.test(text))) {
        item.hidden = true;
        item.dataset.legacyStrategyReply = 'true';
        hidden += 1;
      }
    });

    let note = box.querySelector('.lt-legacy-chat-note');
    if (hidden > 0 && !note) {
      note = document.createElement('div');
      note.className = 'lt-legacy-chat-note';
      note.textContent = 'Older pre-retracement stop/limit trade replies are archived from this live view.';
      box.prepend(note);
    } else if (hidden === 0 && note) {
      note.remove();
    }
  }

  function tidyLearningZeroState() {
    const entries = document.getElementById('ltZrEntries');
    const expectancy = document.getElementById('ltZrExpectancy');
    if (!entries || !expectancy) return;
    const count = Number(String(entries.textContent || '').replace(/[^0-9.-]/g, ''));
    const note = expectancy.parentElement?.querySelector('small');
    if (Number.isFinite(count) && count === 0) {
      expectancy.textContent = 'No entries yet';
      if (note) note.textContent = 'Waiting for a confirmed entry';
    }
  }

  function run() {
    cleanLegacyConversation();
    tidyLearningZeroState();
  }

  installZoneStabilityBoundary();
  const apiTimer = setInterval(() => {
    if (installZoneStabilityBoundary()) clearInterval(apiTimer);
  }, 250);
  setTimeout(() => clearInterval(apiTimer), 10000);

  const view = document.getElementById('view-live-trader');
  if (!view) return;
  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      run();
    });
  });
  observer.observe(view, {childList:true, subtree:true, characterData:true});
  run();
  setInterval(run, 5000);
})();
