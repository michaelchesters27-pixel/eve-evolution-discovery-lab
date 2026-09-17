(() => {
  if (window.__eveLiveCostGuardInstalled) return;
  window.__eveLiveCostGuardInstalled = true;

  const originalFetch = window.fetch.bind(window);
  const memory = new Map();
  const inflight = new Map();
  const stats = { network: 0, cache: 0, stale: 0, backoff: 0, collapsed: 0 };
  const BACKOFF_MS = 60 * 60 * 1000;
  const BACKOFF_KEY = 'eveLiveCostGuard:railwayBackoffUntil';
  let forceStateRefresh = false;
  let railwayBackoffUntil = Number(sessionStorage.getItem(BACKOFF_KEY) || 0);

  const routes = [
    {
      key: 'state',
      path: '/api/live-trader',
      ttlMs: 30 * 1000,
      storageKey: 'eveLiveCostGuard:state:v1',
    },
    {
      key: 'learning',
      path: '/api/live-trader/learning',
      ttlMs: 5 * 60 * 1000,
      storageKey: 'eveLiveCostGuard:learning:v1',
    },
  ];

  function requestMeta(input, init = {}) {
    const method = String(init.method || (input instanceof Request ? input.method : 'GET') || 'GET').toUpperCase();
    const raw = input instanceof Request ? input.url : String(input || '');
    let url;
    try { url = new URL(raw, window.location.origin); } catch (_) { return null; }
    const route = method === 'GET' ? routes.find(item => item.path === url.pathname) : null;
    return route ? { method, url, route } : null;
  }

  function readStored(route) {
    if (memory.has(route.key)) return memory.get(route.key);
    try {
      const raw = localStorage.getItem(route.storageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed.body !== 'string' || !Number.isFinite(Number(parsed.at))) return null;
      const entry = { body: parsed.body, at: Number(parsed.at) };
      memory.set(route.key, entry);
      return entry;
    } catch (_) {
      return null;
    }
  }

  function store(route, body) {
    const entry = { body, at: Date.now() };
    memory.set(route.key, entry);
    try { localStorage.setItem(route.storageKey, JSON.stringify(entry)); } catch (_) {}
    return entry;
  }

  function cachedResponse(route, entry, stale = false, reason = '') {
    let body = entry.body;
    if (route.key === 'state' && stale) {
      try {
        const state = JSON.parse(body);
        const savedAt = new Date(entry.at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        state.feed = { ...(state.feed || {}), connected: false, status: 'stale' };
        state.opinion = `Micky, the dashboard is protecting Railway usage and is showing the last cached market state from ${savedAt}. EVE's engine may still be running in the background, but this screen is not live until the API becomes available again.`;
        state.dashboard_cache = {
          active: true,
          stale: true,
          saved_at: new Date(entry.at).toISOString(),
          reason: reason || 'railway_backoff',
          guard_version: 'eve-live-cost-guard-v1',
        };
        body = JSON.stringify(state);
      } catch (_) {}
    }
    stats[stale ? 'stale' : 'cache'] += 1;
    return new Response(body, {
      status: 200,
      headers: {
        'content-type': 'application/json',
        'cache-control': 'no-store',
        'x-eve-live-cost-guard': stale ? 'stale-cache' : 'fresh-cache',
      },
    });
  }

  function syntheticBackoffResponse() {
    stats.backoff += 1;
    return new Response(JSON.stringify({
      detail: 'Live Trader dashboard API is temporarily paused after Railway reported usage_exceeded. Automatic polling is suppressed to avoid additional Railway usage.',
      error: 'railway_usage_backoff',
      retry_after: new Date(railwayBackoffUntil).toISOString(),
    }), {
      status: 503,
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    });
  }

  async function runNetwork(input, init, meta, previous) {
    stats.network += 1;
    const response = await originalFetch(input, init);

    if (response.ok) {
      const body = await response.clone().text();
      store(meta.route, body);
      if (meta.route.key === 'state') forceStateRefresh = false;
      return response;
    }

    if (response.status === 503 || response.status === 429) {
      let raw = '';
      try { raw = await response.clone().text(); } catch (_) {}
      if (/usage_exceeded|usage exceeded|railway/i.test(raw)) {
        railwayBackoffUntil = Date.now() + BACKOFF_MS;
        sessionStorage.setItem(BACKOFF_KEY, String(railwayBackoffUntil));
        stats.backoff += 1;
        if (previous) return cachedResponse(meta.route, previous, true, 'railway_usage_exceeded');
      }
    }

    return response;
  }

  window.fetch = async function eveCostGuardFetch(input, init = {}) {
    const meta = requestMeta(input, init);
    if (!meta) return originalFetch(input, init);

    const now = Date.now();
    const route = meta.route;
    const previous = readStored(route);

    if (railwayBackoffUntil > now) {
      if (previous) return cachedResponse(route, previous, true, 'railway_usage_backoff');
      return syntheticBackoffResponse();
    }

    if (document.hidden && previous) return cachedResponse(route, previous, true, 'browser_hidden');

    const force = route.key === 'state' && forceStateRefresh;
    if (!force && previous && now - previous.at < route.ttlMs) {
      return cachedResponse(route, previous, false);
    }

    if (inflight.has(route.key)) {
      stats.collapsed += 1;
      const shared = await inflight.get(route.key);
      return shared.clone();
    }

    const task = runNetwork(input, init, meta, previous);
    inflight.set(route.key, task);
    try {
      const response = await task;
      return response.clone();
    } finally {
      inflight.delete(route.key);
    }
  };

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target.closest('#ltRefresh') : null;
    if (target && Date.now() >= railwayBackoffUntil) forceStateRefresh = true;
  }, true);

  window.eveLiveCostGuard = {
    version: 'eve-live-cost-guard-v1',
    stats,
    status: () => ({
      railwayBackoffUntil: railwayBackoffUntil > Date.now() ? new Date(railwayBackoffUntil).toISOString() : null,
      stateCacheAgeSeconds: readStored(routes[0]) ? Math.round((Date.now() - readStored(routes[0]).at) / 1000) : null,
      learningCacheAgeSeconds: readStored(routes[1]) ? Math.round((Date.now() - readStored(routes[1]).at) / 1000) : null,
    }),
  };
})();
