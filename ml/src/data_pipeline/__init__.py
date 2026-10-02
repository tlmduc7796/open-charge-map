"""Data-first contracts, adapters, splitters and builders for ML experiments.

Source adapters turn a vendor dataset into canonical facts.  Dataset builders
then create model-specific supervised rows.  No model is allowed to consume a
vendor-specific CSV directly.
"""

from .adapters import normalize_acn_sessions, normalize_occupancy_source
from .contracts import (
    CANONICAL_OCCUPANCY_COLUMNS,
    CANONICAL_SESSION_COLUMNS,
    CANONICAL_TELEMETRY_COLUMNS,
)
from .splits import TemporalSplitConfig, assign_session_temporal_split, assign_temporal_split

__all__ = [
    "CANONICAL_OCCUPANCY_COLUMNS",
    "CANONICAL_SESSION_COLUMNS",
    "CANONICAL_TELEMETRY_COLUMNS",
    "TemporalSplitConfig",
    "assign_session_temporal_split",
    "assign_temporal_split",
    "normalize_acn_sessions",
    "normalize_occupancy_source",
]
