# EVE Evolution Discovery Lab v2.1

EVE Evolution Discovery Lab is the isolated research system connected to EVE Algo Lab.

- **EVE Algo Lab is production and remains unchanged.**
- **Discovery Lab is research only.** It reads historical evidence, creates candidates, tests them, mutates survivors and generates MT5 source packages.
- Discovery Lab never places trades and EVE Algo Lab never depends on it.

## What v2.1 adds

Version 2.1 completes **Phase 1 — Strategy Profiling Gate**.

A strategy can no longer appear as a usable MT5 package with blank guidance. Before download, EVE must know and record:

- market and chart timeframe
- configured operating window
- strongest and weakest observed session
- strongest and weakest market regime
- strongest observed weekday and UTC hour when the sample is sufficient
- use conditions and avoid conditions
- risk limits, dataset version and evidence source
- confidence score, final research status and M1 replay status

The Trading Passport is checked for completeness in both the worker and the download API. An incomplete or failed profile cannot be downloaded.

## Legacy package recovery

Packages created before v2.1 are not trusted automatically and are not filled with guessed values.

After the v2.1 migration, EVE processes one legacy package at a time:

1. recover the linked frozen strategy rules
2. re-run current final research
3. run current M1 execution replay
4. build and verify the Trading Passport
5. rebuild and unlock the package only if every current gate passes

A legacy survivor that fails current standards remains recorded but its download is blocked with a clear reason.

## Research integrity inherited from v2.0

- Selection and mutation use development and validation only.
- Confirmation and final holdout are opened once for a mature finalist.
- Finalists must pass M1 execution replay.
- Simulated entries follow one-position-at-a-time semantics.
- Every result is tied to an immutable dataset fingerprint.
- Trading is OFF by default in generated EAs.
- Research data and package downloads require the Discovery admin token by default.

## Current research scope

The deployed source remains **XAU/USD M5 source candles sampled as 15-minute research market states**, unless a matching dataset is configured. M1 is currently used for finalist execution replay, not yet for independent M1 hypothesis discovery.

Natural-language **Ask EVE** is not included in this release. Phase 1 establishes the package and profiling rules it will rely on.

## Repository layout

- `frontend/` — Netlify operator interface
- `railway/` — FastAPI API and autonomous worker
- `supabase/` — database migrations
- `SUPABASE_SETUP.sql` — complete fresh database setup
- `SUPABASE_UPDATE_v2.1.sql` — required update for an existing v2.0 database
- `DEPLOYMENT_GUIDE.md` — exact deployment order
- `RELEASE_NOTES_v2.1.md` — complete change record

## Validation

The release is checked with:

- 28 Python backend tests
- frontend structure test
- Netlify proxy test
- JavaScript syntax validation
- Python bytecode compilation
- generated package and Trading Passport validation

MetaEditor compilation and MT5 demo forward testing remain mandatory for every generated `.mq5` file.
