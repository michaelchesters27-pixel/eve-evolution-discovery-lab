# EVE Evolution Discovery Lab v2.0 — Project Specification

## Permanent boundary

### Project 1: EVE Algo Lab

Production platform for MT5 EA fleets, telemetry, heartbeat, trades, waiting reasons, results and live forward testing. Discovery Lab must not modify its code, database records or runtime behaviour.

### Project 2: EVE Evolution Discovery Lab

Independent research platform. It may read approved historical tables from Project 1. It writes only to its own Supabase database. It never sends trading instructions and Project 1 never depends on it.

## v2 research contract

### Selection evidence

Development and validation data may be used to reject candidates, compare descendants and select a lineage champion.

### Protected evidence

Confirmation and final holdout data must not contribute to mutation fitness. They are opened only after a promoted lineage reaches the configured maturity threshold. Once opened, that lineage is retired regardless of outcome.

### Execution contract

Selection replay must be conservative and must never allow overlapping positions. Finalist M1 replay must resolve actual bar-by-bar exits. The research engine and generated EA must agree on:

- bullish and bearish candle-body magnitude
- signal timing
- one open position at a time
- cooldown and maximum-hold configuration
- stop-first handling when stop and target are both reachable
- symbol, source-candle interval and chart timeframe

### Final promotion

A strategy can be frozen only when all configured final gates pass, including:

- confirmation trade-count, profit-factor and expectancy gates
- holdout trade-count and performance gates
- robustness tests
- deterministic Monte Carlo stress
- M1 execution replay with cost profiles

Passing historical research does not authorise live trading. It authorises generation of a trading-disabled MT5 source package for compilation and demo forward testing.

## Persistent research record

Discovery Supabase stores:

- imported source snapshots
- candidate hypotheses and failures
- mutation lineages and descendants
- mutation memory
- dataset version and integrity version
- one-time final evidence
- M1 replay evidence
- frozen survivors
- Trading Passports
- generated MT5 packages
- system activity

## Generated package contract

Each package contains:

- `.mq5` source
- immutable frozen rules
- validation report
- Trading Passport in JSON and text form
- manifest
- SHA-256 checksums
- operator README

The EA has trading disabled by default. Optional Algo Lab heartbeat settings are present but inactive until configured after import into Project 1.

## Current limitation

Version 2.0 is not the Ask EVE natural-language research interface. Its strategy grammar remains controlled and human-defined. It prepares safe data, evidence, timeframe and package contracts required for the future research-question engine.
