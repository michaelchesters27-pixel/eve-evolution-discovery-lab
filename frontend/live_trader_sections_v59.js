(() => {
  const VERSION = 'eve-live-trader-sections-v78';
  if (window.__eveLiveTraderSectionsV78) return;
  window.__eveLiveTraderSectionsV78 = true;

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
    #view-live-trader .lt-section-fixed-grid{align-items:stretch}
    #view-live-trader [data-lt-host="zones"]>.lt-card{min-width:0}
    #view-live-trader [data-lt-host="zones"] .lt-zones{min-height:240px}
    #view-live-trader [data-lt-host="zones"] .lt-zone{box-sizing:border-box;min-height:72px}
    #view-live-trader #ltZoneRetracePanel,#view-live-trader #ltZoneRetraceResearchPanel{width:100%;box-sizing:border-box}
    #view-live-trader .lt-academy-nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0 0 16px;padding:8px;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.02)}
    #view-live-trader .lt-academy-btn{appearance:none;border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.025);color:#aebbb6;border-radius:9px;padding:9px 10px;font:inherit;font-size:11px;font-weight:800;cursor:pointer}
    #view-live-trader .lt-academy-btn.active{border-color:#3aa77f;color:#fff;background:#122e25}
    #view-live-trader .lt-academy-page{display:none;min-width:0}
    #view-live-trader .lt-academy-page.active{display:block}
    #view-live-trader .lt-academy-page>.lt-card{margin-bottom:14px}
    #view-live-trader .lt-academy-empty{border:1px dashed rgba(255,255,255,.10);border-radius:12px;padding:16px;color:#8fa19b;font-size:12px}
    @media(max-width:780px){
      #view-live-trader .lt-section-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
      #view-live-trader .lt-section-btn{width:100%;padding:10px 8px}
      #view-live-trader .lt-academy-nav{grid-template-columns:repeat(2,minmax(0,1fr))}
    }
  `;
  document.head.appendChild(style);

  const sectionDefs = [
    {key:'overview', label:'Overview', eyebrow:'LIVE TRADER', title:'Current market picture'},
    {key:'trade', label:'Trade', eyebrow:'EXECUTION', title:'Current trade setup'},
    {key:'zones', label:'Zones', eyebrow:'LOCATION', title:'Supply and demand zones'},
    {key:'structure', label:'Structure', eyebrow:'MARKET MAP', title:'Bias structure and liquidity'},
    {key:'learning', label:'Learning', eyebrow:'SPECIALIST', title:'Zone retracement learning'},
    {key:'academy', label:'Academy / Performance', eyebrow:'EVIDENCE', title:'Research and measured performance'},
    {key:'chat', label:'Talk to EVE', eyebrow:'EVE', title:'Live trading conversation'},
  ];

  const academyDefs = [
    {key:'performance', label:'Performance'},
    {key:'research', label:'Research'},
    {key:'intelligence', label:'Intelligence'},
    {key:'news', label:'News / Risk'},
  ];

  function closestCard(id){return document.getElementById(id)?.closest('.lt-card') || null;}
  function pageFor(view, key){return view.querySelector(`.lt-section-page[data-lt-page="${key}"]`);}

  function ensureHost(page, key, className = '') {
    if (!page) return null;
    let host = page.querySelector(`[data-lt-host="${key}"]`);
    if (host) return host;
    host = document.createElement('div');
    host.dataset.ltHost = key;
    host.className = className;
    page.appendChild(host);
    return host;
  }

  function place(node, parent) {
    if (!node || !parent || node.parentElement === parent) return false;
    parent.appendChild(node);
    return true;
  }

  function ensureAcademyLayout(page) {
    if (!page) return {};
    let nav = page.querySelector('.lt-academy-nav');
    let pages = page.querySelector('.lt-academy-pages');
    if (!nav || !pages) {
      nav = document.createElement('div');
      nav.className = 'lt-academy-nav';
      nav.setAttribute('role','tablist');
      nav.setAttribute('aria-label','Academy and performance sections');
      pages = document.createElement('div');
      pages.className = 'lt-academy-pages';

      academyDefs.forEach((def, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'lt-academy-btn' + (index === 0 ? ' active' : '');
        button.dataset.ltAcademy = def.key;
        button.textContent = def.label;
        button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
        nav.appendChild(button);

        const panel = document.createElement('div');
        panel.className = 'lt-academy-page' + (index === 0 ? ' active' : '');
        panel.dataset.ltAcademyPage = def.key;
        pages.appendChild(panel);
      });

      nav.addEventListener('click', event => {
        const button = event.target.closest('.lt-academy-btn');
        if (!button) return;
        const key = button.dataset.ltAcademy;
        nav.querySelectorAll('.lt-academy-btn').forEach(item => {
          const active = item.dataset.ltAcademy === key;
          item.classList.toggle('active', active);
          item.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        pages.querySelectorAll('.lt-academy-page').forEach(panel => panel.classList.toggle('active', panel.dataset.ltAcademyPage === key));
      });

      page.append(nav, pages);
    }

    const result = {};
    academyDefs.forEach(def => { result[def.key] = pages.querySelector(`[data-lt-academy-page="${def.key}"]`); });
    return result;
  }

  function reconcile(view) {
    const overview = pageFor(view, 'overview');
    const trade = pageFor(view, 'trade');
    const zones = pageFor(view, 'zones');
    const structure = pageFor(view, 'structure');
    const learning = pageFor(view, 'learning');
    const academy = pageFor(view, 'academy');
    const chat = pageFor(view, 'chat');
    if (!overview || !trade || !zones || !structure || !learning || !academy || !chat) return;

    const zoneHost = ensureHost(zones, 'zones', 'lt-grid lt-section-fixed-grid');
    const structureHost = ensureHost(structure, 'structure', 'lt-grid lt-section-fixed-grid');
    const academyPages = ensureAcademyLayout(academy);

    // Overview is intentionally short: live market + EVE's current view only.
    const hero = view.querySelector('.lt-hero');
    if (hero) place(hero, overview);

    // Trade is the current locked/potential trade only.
    place(closestCard('ltTradeAction'), trade);

    // Zones is the single owner of demand/supply cards.
    place(closestCard('ltDemand'), zoneHost);
    place(closestCard('ltSupply'), zoneHost);

    // Structure owns timeframe bias, liquidity levels and the active market-event readout.
    place(closestCard('ltTimeframes'), structureHost);
    place(closestCard('ltLevels'), structureHost);
    place(document.getElementById('ltMarketEventCard'), structure);

    // Learning is deliberately simple and current-policy only.
    place(document.getElementById('ltZoneRetracePanel'), learning);

    // Academy is split so evidence is readable instead of one enormous scroll.
    place(document.getElementById('ltWeeklyOutcomesCard'), academyPages.performance);
    place(document.getElementById('ltZoneRetraceResearchPanel'), academyPages.research);
    place(closestCard('ltLearning'), academyPages.research);
    place(document.getElementById('ltIntelligenceCard'), academyPages.intelligence);
    place(document.getElementById('ltExecutionIntelligenceCard'), academyPages.intelligence);
    place(document.getElementById('ltNewsCard'), academyPages.news);

    // Conversation is isolated from every analytical panel.
    place(closestCard('ltConversation'), chat);

    // Anything injected late beside the hero is evidence/admin content, not Overview content.
    [...overview.children].forEach(node => {
      if (node.classList?.contains('lt-section-title') || node.classList?.contains('lt-hero')) return;
      if (node.classList?.contains('lt-card') || node.classList?.contains('lt-grid')) place(node, academyPages.research);
    });

    view.querySelectorAll('.lt-section-page .lt-grid:empty,.live-trader-shell .lt-grid:empty').forEach(node => node.remove());
  }

  function build(){
    const view = document.getElementById('view-live-trader');
    const shell = view?.querySelector('.live-trader-shell');
    if (!view || !shell || view.dataset.sectionsV78 === VERSION) return false;
    view.dataset.sectionsV78 = VERSION;

    const nav = document.createElement('div');
    nav.className = 'lt-section-nav';
    nav.setAttribute('role','tablist');
    nav.setAttribute('aria-label','Live Trader sections');

    const pagesHost = document.createElement('div');
    pagesHost.className = 'lt-section-pages';

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
    });

    shell.parentElement?.insertBefore(nav, shell);
    shell.parentElement?.insertBefore(pagesHost, shell);

    reconcile(view);

    // The original shell is only a bootstrap container. No card is allowed to remain orphaned there.
    const academyPages = ensureAcademyLayout(pageFor(view, 'academy'));
    [...shell.children].forEach(node => {
      if (node.classList?.contains('lt-grid') && !node.querySelector('.lt-card')) {
        node.remove();
        return;
      }
      if (node.classList?.contains('lt-hero')) {
        place(node, pageFor(view, 'overview'));
        return;
      }
      if (node.querySelector?.('.lt-card') || node.classList?.contains('lt-card') || node.classList?.contains('lt-grid')) {
        place(node, academyPages.research);
      }
    });
    shell.remove();
    reconcile(view);

    function activate(key){
      nav.querySelectorAll('.lt-section-btn').forEach(btn => {
        const active = btn.dataset.ltSection === key;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      pagesHost.querySelectorAll('.lt-section-page').forEach(page => page.classList.toggle('active', page.dataset.ltPage === key));
      reconcile(view);
    }

    nav.addEventListener('click', event => {
      const button = event.target.closest('.lt-section-btn');
      if (!button) return;
      activate(button.dataset.ltSection || 'overview');
    });

    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        reconcile(view);
      });
    });
    observer.observe(view, {childList:true, subtree:true});

    setInterval(() => reconcile(view), 5000);
    return true;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (build() || attempts > 60) clearInterval(timer);
  }, 250);
  build();
})();
