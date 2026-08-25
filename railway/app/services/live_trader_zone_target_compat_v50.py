from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_target_guard_v49 as v49

# Earlier safety modules intentionally expose their public wrapper aliases as the
# newest audited runtime trade-idea function. Keep that identity contract intact
# after v49 so regression tests and compatibility imports continue to describe
# the actual production chain rather than a superseded wrapper.
core.LiveTrader._trade_idea = v49._trade_idea_v49  # type: ignore[method-assign]
integrity._trade_idea_v39 = v49._trade_idea_v49
lock._trade_idea_v28 = v49._trade_idea_v49
session_gate._trade_idea_v46 = v49._trade_idea_v49
