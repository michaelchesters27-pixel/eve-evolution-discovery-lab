# EVE Evolution Discovery Lab v2.0

## Research Integrity Foundation

Released: 4 August 2026

### Critical research corrections

- Corrected bearish candle-body handling by using absolute body size.
- Prevented overlapping historical positions with a conservative maximum-hold entry lock; finalists are then resolved bar by bar on M1.
- Removed confirmation and holdout performance from mutation fitness.
- Replaced the old data split with development, validation, confirmation and final holdout stages.
- Retires a lineage immediately after final holdout exposure so protected evidence cannot be reused for breeding.
- Added content-addressed dataset fingerprints and a named research-integrity version.
- Renamed/rebuilt yearly evidence as anchored forward validation rather than overstating it as strategy refitting.

### Robustness and execution

- Added broader stop/target neighbour tests.
- Added deterministic Monte Carlo stress evidence.
- Added explicit execution-cost profiles.
- Added M1 replay for finalists using Project 1's historical `market_candles` data.
- M1 replay uses first available M1 open after the research signal and conservative stop-first handling.

### Strategy and lineage records

- Symbol, source-candle interval and strategy timeframe are now explicit research properties.
- Candidate, mutation, lineage and survivor records store dataset version and research stage.
- Final lineage evidence and holdout-opened time are persisted.
- Mutation comparisons explicitly record that holdout was not used for selection.

### Trading Passports

- Every frozen survivor receives a Trading Passport.
- Passports state market, timeframe, operating window, best/worst observed conditions, use/avoid guidance, risk limits and final evidence.
- Packages include both JSON and readable text passport files.

### MT5 generation

- Generated EAs use the strategy's configured MT5 timeframe rather than a hardcoded M5 value.
- Candle calculations match the corrected research engine.
- Trading remains disabled by default.
- Optional EVE Algo Lab-compatible heartbeat inputs are included but disabled until configured.
- Package manifests explicitly require MetaEditor compilation and demo forward testing.

### Security and operating interface

- Source database access is isolated behind a GET-only repository class.
- A restricted `SOURCE_SUPABASE_READ_ONLY_KEY` is preferred; the old service-role key is now only an optional migration fallback.
- Research APIs, package metadata and downloads require the Discovery admin token by default.
- Replaced deployment instructions in the application with Data Health.
- Added genuine worker-cycle and research-integrity status.
- Renamed New Strategies to Research Experiments.
- Clarified that MT5 packages are documented final survivors, not proven live-profit bots.

### Database migration

- Upgraded the source-snapshot primary key so M1, M5 and later timeframe datasets cannot overwrite one another.

Run `SUPABASE_UPDATE_v2.0.sql` in the separate Discovery Lab Supabase project before deploying the code.

### Deliberately not included

The natural-language Ask EVE workspace is not included in v2.0. This release establishes trustworthy evidence, timeframe, execution and package contracts first. Ask EVE should be the next product layer built on this foundation.
