(() => {
  const EVIDENCE_REFRESH_MS = 30000;
  const EVIDENCE_FRESH_HOURS = 6;

  function ensureEvidencePanel() {
    let panel = document.getElementById('evidenceMinerPanel');
    if (panel) return panel;
    const hypotheses = document.getElementById('scientistHypotheses');
    const hypothesisPanel = hypotheses?.closest('article.panel');
    if (!hypothesisPanel) return null;
    panel = document.createElement('article');
    panel.className = 'panel';
    panel.id = 'evidenceMinerPanel';
    panel.innerHTML = `
      <div class="panel-head">
        <div>
          <p class="eyebrow">EVIDENCE MINER</p>
          <h3>What the market data itself is telling EVE</h3>
        </div>
      </div>
      <div id="evidenceMinerSummary" class="feature-card empty">Loading mined market evidence.</div>
      <div id="evidenceMinerSignals" class="cards"></div>`;
    hypothesisPanel.parentNode.insertBefore(panel, hypothesisPanel);
    return panel;
  }

  function evidenceFeatureLabel(value) {
    const key = String(value || '');
    const simple = {
      'condition:break_prior_12_low': 'Break prior 12-bar low',
      'condition:break_prior_12_high': 'Break prior 12-bar high',
      'condition:prev_day_low_sweep_reclaim': 'Previous-day low sweep reclaim',
      'condition:prev_day_high_sweep_reclaim': 'Previous-day high sweep reclaim',
      'schedule:session:london': 'London session',
      'schedule:session:new_york': 'New York session',
      'schedule:session:asia': 'Asia session',
      'schedule:session:off_session': 'Off-session',
      'environment:regime:trend_up': 'Uptrend regime',
      'environment:regime:trend_down': 'Downtrend regime',
      'environment:regime:compression': 'Compression regime',
      'environment:regime:high_volatility': 'High-volatility regime',
      'environment:regime:range': 'Range regime'
    };
    if (simple[key]) return simple[key];
    const rangeLow = key.match(/^condition:range_position_low:max=([\d.]+)$/);
    if (rangeLow) return `Range position low ≤ ${rangeLow[1]}`;
    const rangeHigh = key.match(/^condition:range_position_high:min=([\d.]+)$/);
    if (rangeHigh) return `Range position high ≥ ${rangeHigh[1]}`;
    const expansion = key.match(/^condition:range_expansion_min:min=([\d.]+)$/);
    if (expansion) return `Range expansion ≥ ${expansion[1]}`;
    const alignment = key.match(/^condition:alignment_abs_min:min=([\d.]+)$/);
    if (alignment) return `Alignment strength ≥ ${alignment[1]}`;
    return human(key.replace(/^condition:/, '').replace(/^environment:/, '').replace(/^schedule:/, ''));
  }

  function significance(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    if (n === 0) return '< 1e-12';
    if (n < 0.0001) return n.toExponential(1);
    return n.toFixed(4);
  }

  function signedPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${n >= 0 ? '+' : ''}${n.toFixed(4)}%`;
  }

  function latestTimestamp(items) {
    let latest = null;
    for (const item of items) {
      const value = item?.updated_at ? new Date(item.updated_at) : null;
      if (value && Number.isFinite(value.getTime()) && (!latest || value > latest)) latest = value;
    }
    return latest;
  }

  function renderEvidenceMiner(payload) {
    ensureEvidencePanel();
    const summary = document.getElementById('evidenceMinerSummary');
    const cards = document.getElementById('evidenceMinerSignals');
    if (!summary || !cards) return;

    const items = Array.isArray(payload?.items) ? payload.items : [];
    const runtime = payload?.runtime || {};
    const miner = runtime.evidence_miner || {};
    const signalRows = items.filter(x => String(x.status || '').toLowerCase() === 'signal');
    const verifiedSignals = signalRows.filter(x => Number(x.q_value) <= 0.10 && Number(x.year_stability) >= 0.60);
    const correctionPending = signalRows.filter(x => !(Number(x.q_value) <= 0.10 && Number(x.year_stability) >= 0.60));
    const latest = latestTimestamp(items);
    const ageHours = latest ? (Date.now() - latest.getTime()) / 3600000 : Infinity;
    const rescanDue = correctionPending.length > 0 || ageHours >= EVIDENCE_FRESH_HOURS;
    const horizons = Array.isArray(miner.horizons) && miner.horizons.length ? miner.horizons : [15, 30, 60, 120, 240];
    const signalsReported = Math.max(Number(miner.signals || 0), signalRows.length);
    const scannedFeatures = Number(miner.features_screened || 0);
    const tests = Number(miner.single_tests || 0) + Number(miner.pair_tests || 0);

    summary.className = 'feature-card';
    summary.innerHTML = `<div class="card-top"><div><h3>${esc(miner.version || runtime.evidence_miner_version || 'eve-evidence-miner-v1')}</h3><p>Development-only anomaly mining. These are clues for hypothesis generation, not validated strategies or trade signals.</p></div>${badge(rescanDue ? 'attention' : 'active')}</div>${stats([
      ['Anomalies recorded', fmt.format(signalsReported)],
      ['Stored gate verified', `${fmt.format(verifiedSignals.length)} / ${fmt.format(signalRows.length)}`],
      ['Features screened', scannedFeatures ? fmt.format(scannedFeatures) : '85'],
      ['Statistical tests', tests ? fmt.format(tests) : '578'],
      ['Horizons', horizons.map(x => `${x}m`).join(' · ')],
      ['Scientist use', 'Research priors only']
    ])}<p>${rescanDue ? `<b>Correction rescan due:</b> ${fmt.format(correctionPending.length)} stored signal${correctionPending.length === 1 ? '' : 's'} ${correctionPending.length ? 'are being withheld from this display until their corrected q-values are rewritten.' : 'are due for the scheduled evidence refresh.'}` : '<b>Evidence store fresh:</b> every displayed anomaly currently passes the stored false-discovery and cross-year stability gates.'}</p><small>${latest ? esc(`Evidence last written ${dateText(latest.toISOString())}`) : 'Waiting for the first Evidence Miner write.'}</small>`;

    const strongest = [...verifiedSignals]
      .sort((a, b) => Number(b.evidence_score || 0) - Number(a.evidence_score || 0))
      .slice(0, 6);

    cards.innerHTML = strongest.length ? strongest.map(item => {
      const features = Array.isArray(item.feature_keys) ? item.feature_keys : [];
      const direction = String(item.direction || 'flat').toUpperCase();
      return `<article class="card"><div class="card-top"><div><h3>${esc(`${direction} anomaly · ${item.horizon_minutes || '—'} min`)}</h3><p>${esc(features.map(evidenceFeatureLabel).join(' + ') || 'Market condition')}</p></div>${badge('mined signal')}</div>${stats([
        ['Occurrences', fmt.format(item.sample_count || 0)],
        ['Forward effect', signedPct(item.effect_pct)],
        ['Year stability', pct(item.year_stability)],
        ['FDR q-value', significance(item.q_value)],
        ['Evidence score', num(item.evidence_score, 3)],
        ['Direction', direction]
      ])}<div class="rules">${features.map(x => `<span>${esc(evidenceFeatureLabel(x))}</span>`).join('')}</div><p><b>What this means:</b> the forward return distribution after this condition differed from the development-data baseline often enough and consistently enough to earn further investigation.</p><small>Not validated. Scientist may use this only as a hypothesis-generation prior; sealed validation, confirmation and holdout remain untouched.</small></article>`;
    }).join('') : '<div class="empty-state">No evidence row is currently safe to display as a statistically verified mined anomaly. EVE will repopulate this after the corrected scan.</div>';
  }

  async function refreshEvidenceMinerPanel() {
    ensureEvidencePanel();
    try {
      const payload = await api('/scientist/evidence?limit=100');
      renderEvidenceMiner(payload || {});
    } catch (error) {
      const summary = document.getElementById('evidenceMinerSummary');
      if (summary) {
        summary.className = 'feature-card empty';
        summary.textContent = `Evidence Miner unavailable: ${error.message}`;
      }
    }
  }

  refreshEvidenceMinerPanel();
  setInterval(refreshEvidenceMinerPanel, EVIDENCE_REFRESH_MS);
  document.querySelectorAll('[data-intelligence-refresh]').forEach(btn => btn.addEventListener('click', refreshEvidenceMinerPanel));
})();
