# Project specification

## Goal

Autonomously find a diverse portfolio of robust XAUUSD bots, including strategies with broad weekday availability, without forcing any individual bot to trade every day.

## Selection doctrine

- Development data may be used to create and mutate rules.
- Validation data selects children over parents.
- Locked data is unseen until rules are fixed and can veto catastrophic behaviour.
- Recent data checks relevance to the latest market regime.
- Frozen rules never change. Better children become new versions.

## Learning doctrine

The system gets smarter through `mutation_memory`:

- Every mutation attempt is recorded by family and gene.
- Promotion rate and average fitness delta create a mutation score.
- Future lineages prefer genes with positive evidence in the same family.
- A preferred gene still has to pass all tests.

## Promotion gates

A frozen strategy requires sufficient validation and locked trades, positive validation and locked expectancy, acceptable recent behaviour, walk-forward stability and parameter-neighbour robustness.

## MT5 output

The package includes executable strategy logic in MQL5 source form. The generated EA computes schedule, session, trend, compression, alignment, candle shape, ATR risk, maximum hold, cooldown, spread guard and daily-loss protection inside MT5.
