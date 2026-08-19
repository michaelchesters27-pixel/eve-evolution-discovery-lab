# EVE Multi-Timeframe Observation Fabric

The Discovery Lab is moving from 15-minute research anchors to an isolated every-M5 research foundation.

## Timeframes

Every completed M5 decision may carry causal context from:

- M1 — five one-minute bars inside the completed M5 signal candle, used for path/microstructure descriptors.
- M5 — primary research/trigger candle.
- M15 — latest fully completed stored M15 candle.
- M30 — derived exactly from six consecutive stored M5 candles.
- H1 — latest fully completed stored H1 candle.
- H4 — latest fully completed stored H4 candle.
- D1 — latest fully completed stored daily candle.

## No-look-ahead rule

A signal M5 candle stamped 10:35 becomes actionable at 10:40. At 10:40, an H1 candle stamped 10:00 is still open and is forbidden. EVE receives the most recent H1 candle whose completion time is less than or equal to 10:40.

The same rule applies to M15, M30, H4 and D1. M1 context is restricted to the five M1 bars that make up the already completed M5 signal candle.

Forward M5 candles are used only to build outcome labels (5/15/30/60/240 minute outcomes). They never participate in feature or context generation.

## Deployment strategy

The existing 15-minute scientist remains active while `m5_research_snapshots` is backfilled in the isolated Discovery Supabase. The new builder is resumable via `fabric_build_state` and processes bounded calendar chunks so Railway restarts do not lose progress.

The scientist will not switch to the every-M5 fabric until:

1. the historical backfill is caught up;
2. coverage and missing-data rates are audited;
3. M1/M15/M30/H1/H4/D1 timestamps pass causal checks;
4. a sample of generated M5 features is compared against the production feature definitions;
5. research tests pass on the new dataset.

Automatic trading remains disabled. This fabric is research infrastructure.
