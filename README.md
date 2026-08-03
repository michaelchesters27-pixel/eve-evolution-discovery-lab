# EVE Evolution Discovery Lab v1.0

A separate autonomous strategy-discovery platform for XAUUSD. It reads completed market-state snapshots from the existing EVE Algo Lab, stores its own local copy in a new Supabase project, composes genuinely different strategy families, evolves survivors through controlled mutation, performs chronological and walk-forward validation, freezes qualifying rules and creates downloadable MT5 `.mq5` packages.

## It does not modify the existing EVE project

The source adapter in `railway/app/services/repository.py` exposes GET operations only. All candidates, mutations, failures, lineages, frozen strategies and MT5 packages are written to the Discovery Lab's separate Supabase project.

The source service-role credential is technically privileged, so it must remain only in Railway. It is never sent to Netlify or the browser. The application code contains no source write method.

## Autonomous pipeline

1. **Source bridge** — copies completed `market_learning_snapshots` from the original EVE database.
2. **Controlled composer** — builds valid strategies from six independent families.
3. **Chronological test** — separates development, validation, locked and recent data.
4. **Walk-forward evidence** — measures year-by-year survival.
5. **Controlled mutation** — changes one gene at a time.
6. **Mutation memory** — records which genes help each family and biases future experiments.
7. **Robustness gate** — tests neighbouring stop and target values.
8. **Freeze** — hashes immutable rules that pass every gate.
9. **MT5 generator** — produces a ZIP with `.mq5`, frozen rules, validation report, manifest and checksums.

## Strategy families

- Momentum continuation
- Multi-timeframe alignment continuation
- Pullback continuation
- Volatility breakout
- Mean reversion
- Candle reversal

Schedules, sessions, weekdays, months, trends, compression, alignment, direction rules, stops, targets, hold times and cooldowns are composed and evolved independently.

## Safety

- Generated EAs have `InpEnableTrading=false` by default.
- Packages are labelled for MetaEditor compilation and demo forward testing only.
- Most candidates are expected to be rejected.
- The historical outcome engine is conservative when both stop and target could have been reached.
- The final `.mq5` must still be compiled in MetaEditor and forward-tested on MT5 demo.

See `DEPLOYMENT_GUIDE.md` for the exact setup order.
