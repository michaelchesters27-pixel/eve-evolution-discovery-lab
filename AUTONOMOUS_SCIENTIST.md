# EVE Autonomous Scientist

## Mission

EVE Discovery Lab is not intended to be a strategy-parameter optimiser. Its target state is an autonomous market-research intelligence that:

1. observes historical market states,
2. generates falsifiable hypotheses,
3. rejects weak ideas early,
4. learns which research ingredients repeatedly survive validation,
5. preserves sealed confirmation/final holdout integrity,
6. promotes only robust discoveries into the existing lineage/final/M1 pipeline, and
7. recognises validated discoveries when they reappear in current market data.

## v1 intelligence loop

`IntelligenceDirector` runs beside the existing `DiscoveryOrchestrator`.

### Scientist cycle

- Reads the same isolated Discovery Lab snapshots.
- Calls the existing chronological split.
- **Generates and pre-screens hypotheses on development data only.**
- Never reads confirmation or final holdout outcomes for hypothesis generation.
- Promotes only the best development survivors into the normal `strategy_candidates` selection queue.
- The existing backtest/evolution engine then performs validation, robustness, Monte Carlo, final confirmation/holdout and M1 replay.

### Learning memory

EVE rebuilds `scientist_feature_memory` from completed candidates created by the autonomous scientist.

Only:

- `research_stage = selection`
- validation metrics
- result status from selection

are allowed to influence future hypothesis probabilities.

Confirmation/final holdout metrics are deliberately excluded so successful final exams cannot leak back into future research.

The memory stores performance evidence for:

- condition types and parameter values,
- direction rules,
- session/hour schedules,
- selected environment filters.

Positive features receive more future research budget. Repeatedly weak features receive less. They are not permanently deleted; exploration remains possible.

### Persistent hypothesis memory

Every scientist proposal is written to `scientist_hypotheses`, including development failures.

This is important: EVE must remember dead ends as well as winners.

A proposal can be:

- `rejected_development`
- `queued_for_selection`

The normal Discovery Lab remains responsible for all later research states.

## Live pattern watcher

Every frozen validated strategy is checked against the latest completed research snapshot.

For composed discoveries EVE reports:

- `idle`
- `watching`
- `armed`
- `triggered`

and records:

- current direction,
- condition similarity,
- matched/total conditions,
- latest snapshot time,
- transition events.

Current v1 live recognition intentionally uses the same completed research snapshots as the historical engine. This protects rule parity.

**It is not yet the final real-time execution feed.**

The next live milestone is exact feature parity on every completed M5 bar (and then streaming/intrabar watch state where justified) so EVE can warn before a validated setup is lost.

## API

New endpoints:

- `GET /api/intelligence`
- `GET /api/live-setups`
- `GET /api/scientist/hypotheses`
- `GET /api/scientist/memory`
- `POST /api/admin/run-scientist`
- `POST /api/admin/run-live-watch`

`/health`, `/api/dashboard`, and `/api/data-health` also expose scientist runtime status.

## Environment controls

All have safe defaults:

- `EVE_SCIENTIST_INTERVAL_SECONDS=3600`
- `EVE_LIVE_WATCH_INTERVAL_SECONDS=60`
- `EVE_SCIENTIST_PROPOSALS=36`
- `EVE_SCIENTIST_PROMOTIONS=8`
- `EVE_SCIENTIST_MIN_DEV_TRADES=120`
- `EVE_SCIENTIST_MIN_DEV_PF=1.03`
- `EVE_SCIENTIST_MIN_DEV_EXPECTANCY_R=0.01`

These are research-budget controls, not profitability guarantees.

## Research integrity rules

The autonomous scientist must never:

- learn from final holdout results,
- repeatedly tune a lineage against an opened holdout,
- treat development pre-screening as proof of an edge,
- bypass M1 replay/cost stress,
- silently auto-enable MT5 trading,
- promote a discovery solely because one period looked exceptional.

The existing frozen-strategy and Trading Passport safety gates remain in force.

## Security and validation state

Scientist v1 uses internal Supabase tables with RLS enabled. `anon` and `authenticated` have no table access; the backend `service_role` retains the required access. Worker RPC execution is restricted to `service_role`, and relevant database functions have a fixed `search_path`.

GitHub CI runs the complete Railway pytest suite plus frontend/Netlify JavaScript syntax checks on pushes and pull requests. Scientist v1 passed both jobs before merge.

## Next director milestones

1. Exact coarse-backtest timing parity with M1/live execution.
2. Global final-exam registry/holdout budget across all lineages.
3. Expand the observable grammar: structural swings, liquidity sweeps, prior-day/week levels, displacement, failed breakouts, retracement depth, volatility transitions and multi-candle sequences.
4. Replace IID Monte Carlo with block/stationary bootstrap.
5. Every-M5 Python ↔ MT5 golden-master feature/signal parity.
6. Real-time M5 watcher with `WATCHING → ARMED → TRIGGERED` alerts.
7. Forward-test promotion layer using genuinely new data.
8. Research planner that measures information gain and chooses the next experiment rather than relying primarily on weighted stochastic proposals.

The goal is simple: every day EVE researches should make tomorrow's EVE a better scientist, while the evidence standard for real money gets stricter rather than looser.
