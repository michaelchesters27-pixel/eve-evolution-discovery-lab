(() => {
  if (window.eveSessionCopyV81) return;
  window.eveSessionCopyV81 = true;

  function applySessionCopy() {
    const panel = document.getElementById('ltSessionOutlookPanel');
    const direction = String(panel?.querySelector('.lt-session-outlook-direction')?.textContent || '').trim().toLowerCase();
    const flip = panel?.querySelector('.lt-session-outlook-flip');
    if (!flip || !['bullish', 'bearish'].includes(direction)) return;

    const text = String(flip.textContent || '').trim();
    const label = direction === 'bullish' ? 'Bullish' : 'Bearish';
    const zone = direction === 'bullish' ? 'demand' : 'supply';

    const levelMatch = text.match(/^I would seriously consider flipping (bullish|bearish) if price (loses|reclaims) ([\d,.]+) and M15\/M5 structure stays (bullish|bearish)\.$/i);
    if (levelMatch) {
      flip.textContent = `${label} plan stays valid while price retraces toward ${zone}. Cancel it only if price ${levelMatch[2].toLowerCase()} ${levelMatch[3]} AND M15 + M5 remain ${levelMatch[4].toLowerCase()}.`;
      return;
    }

    const structureMatch = text.match(/^I would flip (bullish|bearish) if M15\/M5 structure and momentum both turn (bullish|bearish)\.$/i);
    if (structureMatch) {
      flip.textContent = `${label} plan stays valid unless M15 + M5 structure and momentum both turn ${structureMatch[2].toLowerCase()}.`;
    }
  }

  let queued = false;
  const queueApply = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      applySessionCopy();
    });
  };

  new MutationObserver(queueApply).observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  queueApply();
})();
