from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_red_folder_all_day_v37 as all_day
from app.services import live_trader_session_outlook_v55 as outlook

COMPAT_VERSION = "eve-live-session-outlook-compat-v1"

# Keep the repository's established newest-wrapper alias contract. The original
# v37 function is still captured inside v55 as its delegate, so red-folder
# commands retain their existing behavior while ordinary questions can use the
# new Session Outlook answer path.
all_day._answer_v37 = outlook._answer_v55
core.LiveTrader.answer = outlook._answer_v55  # type: ignore[method-assign]
