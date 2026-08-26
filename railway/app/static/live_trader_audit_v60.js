(() => {
  const VERSION = 'eve-live-trader-ui-integrity-v78';
  if (window.__eveLiveTraderUiIntegrityV78) return;
  window.__eveLiveTraderUiIntegrityV78 = true;

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
