# Notebooks are review and experiment front ends

Keep notebooks thin: import/call modules in `ml/src`, show data audits, charts,
and experiment results. Do not duplicate preprocessing, feature engineering, or
training loops in notebook cells.

Included review notebooks:

1. `01_data_audit.ipynb` — provenance, schema, missingness and temporal split.
2. `02_xgboost_baseline.ipynb` — call `build_feature_dataset.py` and
   `train_occupancy.py`; chart baseline metrics.
3. `03_lstm_markov.ipynb` — call `train_lstm_markov.py`; inspect calibration and
   use `markov_wait.py` to explain the resulting wait distribution.
4. `04_transformer_foundation.ipynb` — inspect Transformer and provider-gated
   foundation plans; it does not trigger training.
