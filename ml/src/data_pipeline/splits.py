"""Leakage-safe temporal split policies shared by every model dataset."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TemporalSplitConfig:
    """Inclusive train/validation end times; anything newer is the test window."""

    train_end: str | pd.Timestamp
    validation_end: str | pd.Timestamp

    def __post_init__(self) -> None:
        train_end = pd.Timestamp(self.train_end)
        validation_end = pd.Timestamp(self.validation_end)
        if train_end.tzinfo is None or validation_end.tzinfo is None:
            raise ValueError("Temporal split boundaries require explicit timezones")
        if train_end >= validation_end:
            raise ValueError("train_end must be before validation_end")

    @property
    def train_end_utc(self) -> pd.Timestamp:
        return pd.Timestamp(self.train_end).tz_convert("UTC")

    @property
    def validation_end_utc(self) -> pd.Timestamp:
        return pd.Timestamp(self.validation_end).tz_convert("UTC")


def assign_temporal_split(
    frame: pd.DataFrame,
    config: TemporalSplitConfig,
    *,
    timestamp_column: str = "observed_at",
) -> pd.DataFrame:
    """Assign strict chronological train/val/test labels without random rows."""
    if timestamp_column not in frame:
        raise ValueError(f"Missing split timestamp column {timestamp_column!r}")
    result = frame.copy()
    timestamp = pd.to_datetime(result[timestamp_column], utc=True, errors="raise")
    result["split"] = "test"
    result.loc[timestamp <= config.validation_end_utc, "split"] = "val"
    result.loc[timestamp <= config.train_end_utc, "split"] = "train"
    if not {"train", "val", "test"}.issubset(set(result["split"])):
        raise ValueError("Temporal split needs at least one row in train, val and test")
    return result


def assign_session_temporal_split(
    sessions: pd.DataFrame,
    observations: pd.DataFrame,
    config: TemporalSplitConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split all telemetry rows of a session by its eventual disconnect time.

    Censored sessions retain their canonical rows but are deliberately excluded
    from point-regression labels.  A future survival-model builder can use them
    with ``is_censored`` and ``censoring_at`` instead of pretending they ended.
    """
    required_sessions = {"session_id", "disconnect_at", "is_censored"}
    required_observations = {"session_id", "observed_at"}
    if missing := required_sessions - set(sessions.columns):
        raise ValueError(f"Sessions miss columns: {sorted(missing)}")
    if missing := required_observations - set(observations.columns):
        raise ValueError(f"Observations miss columns: {sorted(missing)}")
    # Canonical source products normally have no split.  Gold products retain
    # one for audit, but this function owns the split assignment and must not
    # merge duplicate ``split_x/split_y`` columns back into observations.
    sessions = sessions.drop(columns=["split"], errors="ignore")
    observations = observations.drop(columns=["split"], errors="ignore")
    labels = sessions.loc[
        ~sessions["is_censored"].astype(bool), ["session_id", "disconnect_at"]
    ].copy()
    labels = assign_temporal_split(labels, config, timestamp_column="disconnect_at")
    session_split = sessions.merge(labels[["session_id", "split"]], on="session_id", how="left")
    observation_split = observations.merge(
        labels[["session_id", "split"]], on="session_id", how="inner"
    )
    if observation_split["split"].isna().any():  # defensive: inner join should prevent this.
        raise ValueError("Every labelled observation must receive exactly one split")
    grouped = observation_split.groupby("session_id")["split"].nunique()
    if (grouped != 1).any():
        raise ValueError("A session cannot span multiple model splits")
    return session_split, observation_split
