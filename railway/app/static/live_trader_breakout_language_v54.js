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

  function normalizeLiveTrader() {
    normalizeNode(document.getElementById('view-live-trader'));
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
    const observer = new MutationObserver(() => normalizeLiveTrader());
    observer.observe(view, {childList: true, subtree: true, characterData: true});
    normalizeLiveTrader();
  }

  installVoiceBoundary();
  const voiceTimer = setInterval(() => {
    if (installVoiceBoundary()) clearInterval(voiceTimer);
  }, 250);
  setTimeout(() => clearInterval(voiceTimer), 15000);
})();
