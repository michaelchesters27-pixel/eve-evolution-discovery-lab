(() => {
  const load = (src, done) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = done;
    script.onerror = done;
    document.body.appendChild(script);
  };
  load('live_trader_intelligence_meter_core.js', () =>
    load('live_trader_execution_intelligence.js', () =>
      load('live_trader_safe_stops_v48.js', () =>
        load('live_trader_zone_truth_v49.js', () =>
          load('live_trader_zone_retrace_v58.js', () =>
            load('live_trader_sections_v59.js', () => {})
          )
        )
      )
    )
  );
})();
