(() => {
  const UI_BUILD = '85';
  window.__eveLiveTraderUiBuild = `v${UI_BUILD}`;

  const load = (src, done) => {
    const script = document.createElement('script');
    const join = src.includes('?') ? '&' : '?';
    script.src = `${src}${join}v=${UI_BUILD}`;
    script.dataset.eveUiBuild = UI_BUILD;
    script.onload = done;
    script.onerror = done;
    document.body.appendChild(script);
  };

  load('live_trader_intelligence_meter_core.js', () =>
    load('live_trader_execution_intelligence.js', () =>
      load('live_trader_safe_stops_v48.js', () =>
        load('live_trader_zone_truth_v49.js', () =>
          load('live_trader_zone_retrace_v58.js', () =>
            load('live_trader_sections_v59.js', () =>
              load('live_trader_audit_v60.js', () =>
                load('live_trader_session_copy_v81.js', () =>
                  load('live_trader_zone_decision_tolerance_v82.js', () => {})
                )
              )
            )
          )
        )
      )
    )
  );
})();
