(() => {
  const VERSION = 'eve-live-trader-sections-v59';
  if (window.__eveLiveTraderSectionsV59) return;
  window.__eveLiveTraderSectionsV59 = true;

  const style = document.createElement('style');
  style.textContent = `
    #view-live-trader .lt-section-nav{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 20px;padding:10px;border:1px solid rgba(255,255,255,.08);border-radius:14px;background:rgba(255,255,255,.025)}
    #view-live-trader .lt-section-btn{appearance:none;border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.035);color:#c9d3cf;border-radius:10px;padding:10px 14px;font:inherit;font-size:12px;font-weight:800;letter-spacing:.04em;cursor:pointer;min-height:42px}
    #view-live-trader .lt-section-btn.active{background:#173d31;border-color:#3aa77f;color:#fff}
    #view-live-trader .lt-section-btn:focus-visible{outline:2px solid #55d6a7;outline-offset:2px}
    #view-live-trader .lt-section-page{display:none;min-width:0}
    #view-live-trader .lt-section-page.active{display:block}
    #view-live-trader .lt-section-page>.lt-card,#view-live-trader .lt-section-page>.lt-grid,#view-live-trader .lt-section-page>.lt-hero{margin-bottom:16px}
    #view-live-trader .lt-section-title{margin:0 0 14px;padding:2px 2px 10px;border-bottom:1px solid rgba(255,255,255,.08)}
    #view-live-trader .lt-section-title h3{margin:3px 0 0;font-size:20px}
    #view-live-trader #ltZoneRetracePanel{width:100%;box-sizing:border-box}
    #view-live-trader #ltZoneRetracePanel .lt-status-row{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px!important}
    #view-live-trader #ltZoneRetracePanel .lt-status{min-width:0!important;word-break:normal!important;overflow-wrap:break-word!important}
    #view-live-trader #ltZoneRetracePanel .lt-status span,#view-live-trader #ltZoneRetracePanel .lt-status small{word-break:normal!important;overflow-wrap:break-word!important;white-space:normal!important}
    #view-live-trader #ltZoneRetracePanel .lt-status strong{font-size:18px}
    @media(max-width:780px){
      #view-live-trader .lt-section-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
      #view-live-trader .lt-section-btn{width:100%;padding:10px 8px}
      #view-live-trader #ltZoneRetracePanel .lt-status-row{grid-template-columns:1fr!important}
    }
  `;
  document.head.appendChild(style);

  const sectionDefs = [
    {key:'overview', label:'Overview', eyebrow:'LIVE TRADER', title:'Current market picture'},
    {key:'trade', label:'Trade', eyebrow:'EXECUTION', title:'Current trade setup'},
    {key:'zones', label:'Zones', eyebrow:'LOCATION', title:'Supply and demand zones'},
    {key:'structure', label:'Structure', eyebrow:'MARKET MAP', title:'Bias structure and liquidity'},
    {key:'learning', label:'Learning', eyebrow:'SPECIALIST', title:'Zone retracement learning'},
    {key:'academy', label:'Academy / Performance', eyebrow:'EVIDENCE', title:'Historical and measured learning'},
    {key:'chat', label:'Talk to EVE', eyebrow:'EVE', title:'Live trading conversation'},
  ];

  function closestCard(id){return document.getElementById(id)?.closest('.lt-card') || null;}
  function closestGrid(id){return document.getElementById(id)?.closest('.lt-grid') || null;}
  function moveUnique(page, nodes, seen){
    nodes.filter(Boolean).forEach(node => {
      if (seen.has(node)) return;
      seen.add(node);
      page.appendChild(node);
    });
  }

  function build(){
    const view = document.getElementById('view-live-trader');
    const shell = view?.querySelector('.live-trader-shell');
    if (!view || !shell || view.dataset.sectionsV59 === VERSION) return false;
    view.dataset.sectionsV59 = VERSION;

    const nav = document.createElement('div');
    nav.className = 'lt-section-nav';
    nav.setAttribute('role','tablist');
    nav.setAttribute('aria-label','Live Trader sections');

    const pagesHost = document.createElement('div');
    pagesHost.className = 'lt-section-pages';
    const pages = {};

    sectionDefs.forEach((def, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'lt-section-btn' + (index === 0 ? ' active' : '');
      button.dataset.ltSection = def.key;
      button.setAttribute('role','tab');
      button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
      button.textContent = def.label;
      nav.appendChild(button);

      const page = document.createElement('section');
      page.className = 'lt-section-page' + (index === 0 ? ' active' : '');
      page.dataset.ltPage = def.key;
      page.setAttribute('role','tabpanel');
      page.innerHTML = `<div class="lt-section-title"><p class="eyebrow">${def.eyebrow}</p><h3>${def.title}</h3></div>`;
      pagesHost.appendChild(page);
      pages[def.key] = page;
    });

    shell.parentElement?.insertBefore(nav, shell);
    shell.parentElement?.insertBefore(pagesHost, shell);

    const seen = new Set();

    moveUnique(pages.overview, [view.querySelector('.lt-hero')], seen);
    moveUnique(pages.trade, [closestCard('ltTradeAction')], seen);
    moveUnique(pages.zones, [closestGrid('ltDemand')], seen);
    moveUnique(pages.structure, [closestGrid('ltTimeframes'), closestCard('ltMarketLine')], seen);
    moveUnique(pages.learning, [document.getElementById('ltZoneRetracePanel')], seen);
    moveUnique(pages.academy, [closestCard('ltLearning')], seen);
    moveUnique(pages.chat, [closestCard('ltConversation')], seen);

    [...shell.children].forEach(node => {
      if (!seen.has(node)) pages.overview.appendChild(node);
    });
    shell.remove();

    function activate(key){
      nav.querySelectorAll('.lt-section-btn').forEach(btn => {
        const active = btn.dataset.ltSection === key;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      pagesHost.querySelectorAll('.lt-section-page').forEach(page => page.classList.toggle('active', page.dataset.ltPage === key));
    }

    nav.addEventListener('click', event => {
      const button = event.target.closest('.lt-section-btn');
      if (!button) return;
      activate(button.dataset.ltSection || 'overview');
    });

    const observer = new MutationObserver(() => {
      const panel = document.getElementById('ltZoneRetracePanel');
      if (panel && !pages.learning.contains(panel)) pages.learning.appendChild(panel);
    });
    observer.observe(view, {childList:true, subtree:true});

    return true;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (build() || attempts > 60) clearInterval(timer);
  }, 250);
  build();
})();