"""EVE Evolution Discovery Lab backend."""

# Install research-data guards before services import their source/fabric classes.
from app.services import data_quality_guard as _data_quality_guard  # noqa: F401

# Install the bounded fairness extension before app.main imports orchestrator_v3.
from app.services import fair_lineage_scheduler as _fair_lineage_scheduler  # noqa: F401
