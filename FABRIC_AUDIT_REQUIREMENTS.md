# Fabric audit gates

The every-M5 dataset must not become the scientist's primary research source merely because the backfill reached the latest candle.

Before cutover, EVE must prove:

- zero higher-timeframe look-ahead violations (`completed_at <= M5 decision_time`);
- exact M30 construction from six M5 constituents;
- high M15/M30/H1/H4/D1 coverage outside unavoidable source gaps;
- measured M1 coverage, with the known early-history gap reported rather than hidden;
- complete forward labels for the historical portion excluding the intentionally incomplete live tail;
- feature parity on overlapping 15-minute timestamps for fields inherited from the production learning foundation;
- stable row ordering and unique `(symbol, snapshot_interval, source_interval, candle_time)` identity.

A failed audit keeps Scientist v2 on the current 15-minute source and records the reason. Automatic trading remains disabled regardless of audit outcome.
