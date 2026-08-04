# EVE Evolution Discovery Lab v2.0

EVE Evolution Discovery Lab is the isolated research system connected to EVE Algo Lab.

- **EVE Algo Lab is production.** It remains unchanged.
- **Discovery Lab is research.** It reads historical evidence, composes strategies, tests them, mutates survivors and generates MT5 source packages.
- Discovery Lab never places trades and is not a dependency of Algo Lab.

## What v2.0 changes

Version 2.0 is the **Research Integrity Foundation**. It corrects the parts of v1.1 that could make a backtest disagree with the generated EA or allow protected evidence to influence evolution.

The research lifecycle is now:

1. Compose a strategy hypothesis.
2. Test on development data.
3. Select and mutate using validation data only.
4. Promote a mature lineage to one final examination.
5. Open confirmation and final holdout once.
6. Replay finalist entries against M1 candles with execution-cost stress.
7. Retire the lineage after the holdout is opened, whether it passes or fails.
8. Generate an MT5 package only for a final survivor.

## Main safeguards

- Absolute candle-body calculations match MT5 for bullish and bearish candles.
- Historical selection prevents overlapping positions with a conservative maximum-hold lock; finalist M1 replay resolves actual exits bar by bar.
- Confirmation and holdout evidence are excluded from mutation fitness.
- Final holdout exposure is recorded and cannot be reused by the same lineage.
- Every result is tied to a content-addressed dataset fingerprint.
- Monte Carlo and wider parameter-neighbour stress are recorded.
- Finalists must pass M1 execution replay before freezing.
- Source access is implemented through a GET-only repository adapter.
- A restricted source credential can replace the legacy service-role credential.
- Generated EAs are trading-disabled by default and include optional Algo Lab-compatible heartbeat inputs.
- Research results and package downloads require the Discovery admin token by default.

## Trading Passports

Every generated package contains a Trading Passport stating:

- market and chart timeframe
- operating session or hours
- conditions in which the strategy should be used
- conditions in which it should be avoided
- spread limit and risk settings
- validation, confirmation and holdout evidence
- M1 replay status
- compilation and demo-forward-testing requirements

## Current research scope

The deployed historical snapshot source remains **XAU/USD, M5 source candles sampled as 15-minute research states** unless a matching source dataset is made available. Version 2.0 stores source interval separately, prevents different timeframes from overwriting one another, refuses to label M5 evidence as an M1 strategy, and performs M1 execution replay for finalists.

It does **not yet** provide the natural-language **Ask EVE** workspace or genuine M1 hypothesis discovery. Those should be built on this corrected foundation rather than added to the compromised v1.1 validation process.

## Repository layout

- `frontend/` — Netlify operator interface
- `railway/` — FastAPI API and autonomous research worker
- `supabase/` — Discovery Lab database migrations
- `SUPABASE_SETUP.sql` — complete fresh-database setup
- `SUPABASE_UPDATE_v2.0.sql` — upgrade for an existing v1/v1.1 Discovery database
- `DEPLOYMENT_GUIDE.md` — exact replacement and deployment order
- `PROJECT_SPEC.md` — system boundaries and research rules
- `RELEASE_NOTES_v2.0.md` — full release record

## Validation

The included release was checked with:

- 23 Python backend tests
- 2 frontend/Netlify structural tests
- Python bytecode compilation
- generated-package structure and MQ5 source validation

MetaEditor compilation still must be performed on every generated `.mq5` file before demo forward testing.
