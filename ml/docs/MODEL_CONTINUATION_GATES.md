# Model continuation gates

## Current runnable paths

- **Occupancy XGBoost:** canonical occupancy → frozen features → direct
  `+5…+60` regression.  Compare persistence/daily/weekly on validation first.
- **RDM quantile XGBoost:** canonical session telemetry →
  `remaining_port_release_min = disconnect_at - observed_at`.  It returns
  P10/P50/P90 candidates for Monte Carlo DES after calibration/replay review.
- **Aggregate Markov:** connector-aware port state only; it is an explicit
  fallback when detailed port/session/queue input is unavailable.

## LSTM occupancy: do not forget, but do not enable early

The implementation remains in `train_lstm_markov.py` with a 12-lag input,
target-time calendar/profile branch, twelve `+5…+60` occupancy-ratio outputs,
and `SmoothL1` regression loss.  It is not a binary sigmoid/BCE classifier.

Enable its schema profile only after all of these are true:

1. Occupancy snapshots have a documented regular cadence, timezone and
   missing/outage policy across enough stations and peak periods.
2. The exact feature dataset has passed leakage/freshness validation and can
   be produced at inference time.
3. XGBoost plus persistence/daily/weekly baselines have been compared with the
   same temporal/rolling-origin splits.
4. The LSTM is selected on validation by per-horizon MAE/RMSE and calibration,
   then evaluated once on a new test window.
5. A release/rollback and runtime feature-serving plan exists.

## RDM LSTM and Transformer

RDM LSTM needs dense, ordered power/energy telemetry plus a missing-data mask;
it must beat quantile XGBoost on the same session-level temporal split.  The
Transformer remains research-only until multi-station context has a live
source and the simpler models demonstrate a material limitation.
