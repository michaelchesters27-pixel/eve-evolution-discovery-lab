"""EVE Evolution Discovery Lab backend."""

# Install research-data guards before services import their source/fabric classes.
from app.services import data_quality_guard as _data_quality_guard  # noqa: F401

# Install compact research observations and bounded Evidence Miner working memory
# before Scientist/backtest modules bind their helper functions.
from app.services import memory_guard_v1 as _memory_guard_v1  # noqa: F401
# Preserve expanded obs_* debug fields only for small synthetic/operator inputs;
# the six-year production fabric remains compact.
from app.services import memory_guard_compat_v1 as _memory_guard_compat_v1  # noqa: F401

# Install the bounded fairness extension before app.main imports orchestrator_v3.
from app.services import fair_lineage_scheduler as _fair_lineage_scheduler  # noqa: F401

# Install independent, generalised Live Trader learning before app.main imports LiveTrader.
from app.services import live_trader_learning_v2 as _live_trader_learning_v2  # noqa: F401
# Tighten episode identity so zone-ID churn cannot manufacture independent samples.
from app.services import live_trader_learning_v21 as _live_trader_learning_v21  # noqa: F401
# Generalise structural families while weighting session/regime/momentum context.
from app.services import live_trader_learning_v22 as _live_trader_learning_v22  # noqa: F401
# Match feed freshness to Twelve Data's minute-stamped production cadence.
from app.services import live_trader_feed_guard as _live_trader_feed_guard  # noqa: F401
# Add sweep/reclaim, fake-out and accepted-break semantics to execution and learning.
from app.services import live_trader_market_events_v23 as _live_trader_market_events_v23  # noqa: F401
# Load the richer causal trend features used by the v2.4 bias engine.
from app.services import live_trader_feature_feed_v24 as _live_trader_feature_feed_v24  # noqa: F401
# Upgrade directional reasoning and exact-horizon learning semantics.
from app.services import live_trader_intelligence_v24 as _live_trader_intelligence_v24  # noqa: F401
# Let mature poor-performing families veto live candidates while shadow-scoring them.
from app.services import live_trader_learning_governor_v25 as _live_trader_learning_governor_v25  # noqa: F401
# Audit hardening: stable learning namespace, source-M1 outcome paths and feed-policy socket health.
from app.services import live_trader_audit_hardening_v26 as _live_trader_audit_hardening_v26  # noqa: F401
# Expose permanent-learning progress separately from current-family calibration.
from app.services import live_trader_learning_visibility_v27 as _live_trader_learning_visibility_v27  # noqa: F401
# Lock one published trade campaign at a time and follow it through trigger to terminal outcome.
from app.services import live_trader_trade_lock_v28 as _live_trader_trade_lock_v28  # noqa: F401
# Preserve pure execution-engine semantics while the campaign lock remains runtime-only.
from app.services import live_trader_trade_lock_compat_v29 as _live_trader_trade_lock_compat_v29  # noqa: F401
# Keep forward learning broker-hours clean while learning continuously from six years of causal history.
from app.services import live_trader_historical_learning_v29 as _live_trader_historical_learning_v29  # noqa: F401
# Run Historical Academy alongside Live Trader and keep provider transport separate from tradability.
from app.services import live_trader_historical_runtime_v30 as _live_trader_historical_runtime_v30  # noqa: F401
# Preserve pure-strategy and earlier audit/lock regression contracts through the latest runtime wrappers.
from app.services import live_trader_historical_compat_v31 as _live_trader_historical_compat_v31  # noqa: F401
# Discover source-M1 history boundary and avoid recording unscorable pre-M1 historical episodes.
from app.services import live_trader_historical_m1_coverage_v32 as _live_trader_historical_m1_coverage_v32  # noqa: F401
# Publish an evidence-based intelligence index and persist its progress over time.
from app.services import live_trader_intelligence_indicator_v33 as _live_trader_intelligence_indicator_v33  # noqa: F401
# Freeze XAU/USD across IC Markets' daily metals rollover/maintenance window as well as weekends.
from app.services import live_trader_metals_hours_v34 as _live_trader_metals_hours_v34  # noqa: F401
# Add manually-entered USD red-folder economic-news protection for Live Trader.
from app.services import live_trader_red_folder_news_v35 as _live_trader_red_folder_news_v35  # noqa: F401
# Fail closed until the operator explicitly confirms each Sunday-Saturday news calendar was checked.
from app.services import live_trader_red_folder_news_confirmation_v36 as _live_trader_red_folder_news_confirmation_v36  # noqa: F401
# Support Forex Factory ALL/Tentative red-folder macro-risk events without inventing a release time.
from app.services import live_trader_red_folder_all_day_v37 as _live_trader_red_folder_all_day_v37  # noqa: F401
# Count real locked-campaign outcomes by week and persist one post-trade execution review per finished campaign.
from app.services import live_trader_trade_outcomes_v38 as _live_trader_trade_outcomes_v38  # noqa: F401
# Enforce pre-entry invalidation in causal scoring and revalidate the historical execution ledger.
from app.services import live_trader_execution_integrity_v39 as _live_trader_execution_integrity_v39  # noqa: F401
# Keep v39's revalidation gates live-runtime-only for deterministic research/unit helpers.
from app.services import live_trader_execution_integrity_compat_v40 as _live_trader_execution_integrity_compat_v40  # noqa: F401
# Match LIMIT-order replay sequencing to the actual locked campaign state machine and restart revalidation.
from app.services import live_trader_execution_sequence_v41 as _live_trader_execution_sequence_v41  # noqa: F401
