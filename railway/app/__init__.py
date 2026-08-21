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
