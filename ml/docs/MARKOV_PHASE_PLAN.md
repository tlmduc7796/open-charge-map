# Phase 05 — LSTM + calibrated Markov wait distribution

> **Current status:** deferred. The active delivery order is deterministic
> frontend Queue Lab, Monte Carlo DES, then ACN-Data/RDM. Read
> [`QUEUE_LAB_DES_ROADMAP.md`](QUEUE_LAB_DES_ROADMAP.md) for that order; this
> document preserves the Markov design for the later aggregate-only fallback.

Markov is a probability layer for wait time, not a replacement for occupancy
forecasting and not a residual-duration model. It belongs **after Phase 04**
(the seasonal XGBoost benchmark) and alongside the Hybrid LSTM experiment.

## Phase sequence

1. **Phase 04** — Build the frozen seasonal dataset and establish whether the
   direct XGBoost occupancy model beats persistence and seasonal-naive on an
   untouched temporal test set.
2. **Phase 05A** — Train/evaluate the Hybrid LSTM with that exact same frozen
   feature dataset and temporal split. It predicts occupancy at +5...+60 min.
3. **Phase 05B** — Train a transition head/calibrator on the same training
   interval. At each five-minute step it estimates `P(full -> available)` and
   `P(available -> full)`, conditioned on the observed compatible-port state
   and approved context. `markov_wait.py` then converts those probabilities to
   `probability_wait_zero` and a wait-time distribution.
4. **Phase 05C** — Backtest the full distribution on the untouched test range:
   occupancy MAE/RMSE plus Brier score/reliability for wait-zero and calibration
   of the first-available-time distribution. Only then consider API serving.

## How LSTM and Markov connect

The LSTM's occupancy head and the Markov transition head share the same history
encoder, but predict different quantities. The former predicts how busy a
station is; the latter predicts how a compatible port changes state. The API
uses the LSTM/XGBoost occupancy result for aggregate capacity and the calibrated
Markov result for uncertainty. Neither output is fed into the other as a fake
label.

UrbanEV can support a **source-domain proxy** using `occupied_ports ==
total_ports` as `full`. It cannot produce a production compatible-port label,
queue order, or session duration. A Vietnam release therefore needs per-port
connector status, or at minimum compatible occupied/operational-port counts.
