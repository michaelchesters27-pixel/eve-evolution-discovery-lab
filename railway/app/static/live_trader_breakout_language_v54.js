(() => {
  if (window.eveBreakoutLanguageV54) return;
  window.eveBreakoutLanguageV54 = true;

  function normalizeText(value) {
    return String(value ?? '')
      .replace(/possible bullish fake[- ]?out/gi, 'possible failed bearish breakout')
      .replace(/possible bearish fake[- ]?out/gi, 'possible failed bullish breakout')
      .replace(/bullish fake[- ]?out/gi, 'failed bearish breakout')
      .replace(/bearish fake[- ]?out/gi, 'failed bullish breakout')
      .replace(/not treating it as a fake[- ]?out right now/gi, 'treating the breakout as holding right now')
      .replace(/not treating it as a fake[- ]?out yet/gi, 'treating the breakout as holding for now')
      .replace(/no active sweep \/ fake[- ]?out/gi, 'NO ACTIVE SWEEP / BREAKOUT FAILURE')
      .replace(/possible fake[- ]?out/gi, 'Possible')
      .replace(/fake[- ]?out/gi, 'breakout failure');
  }

  function normalizeNode(root) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const next = normalizeText(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
  }

  function cleanPresentation() {
    const view = document.getElementById('view-live-trader');
    if (!view) return;
    view.classList.add('lt-clean-layout');
    view.querySelectorAll('.lt-manual-warning').forEach(warning => warning.remove());
    normalizeNode(view);

    // IMPORTANT: this language/presentation boundary must never move cards.
    // Section ownership belongs exclusively to live_trader_sections_v59.js.
    const zoneGrid = [...view.querySelectorAll('.lt-grid')].find(grid =>
      grid.querySelector('#ltDemand') && grid.querySelector('#ltSupply')
    );
    if (zoneGrid) zoneGrid.classList.add('lt-zone-grid');
  }

  function installVoiceBoundary() {
    const voice = window.eveLiveVoice;
    if (!voice || typeof voice.say !== 'function' || voice.__breakoutLanguageV54) return false;
    const original = voice.say.bind(voice);
    voice.say = (text, options) => original(normalizeText(text), options);
    voice.__breakoutLanguageV54 = true;
    return true;
  }

  const view = document.getElementById('view-live-trader');
  if (view) {
    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        cleanPresentation();
      });
    });
    observer.observe(view, {childList:true, subtree:true, characterData:true});
    cleanPresentation();
  }

  installVoiceBoundary();
  const voiceTimer = setInterval(() => {
    if (installVoiceBoundary()) clearInterval(voiceTimer);
  }, 250);
  setTimeout(() => clearInterval(voiceTimer), 15000);
})();
