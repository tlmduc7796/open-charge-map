# DES + residual-duration integration

For the active implementation order—frontend deterministic Queue Lab, then
Monte Carlo DES, then ACN-Data/RDM—see
[`QUEUE_LAB_DES_ROADMAP.md`](QUEUE_LAB_DES_ROADMAP.md). This document remains
the contract and safety boundary for DES/RDM.

## Decision boundary

The system has two wait-time modes. They are not competing models and must not
silently overwrite each other.

| Mode | When it may be used | Result |
|---|---|---|
| Aggregate queue estimate | Historical/current station status is available, but not the lifecycle of every port/session | XGBoost occupancy forecast plus Markov/Erlang-C produces a probability-oriented wait estimate. This is the current MVP path. |
| Discrete-event simulation (DES) | A fresh snapshot provides every port's state, connector compatibility, confirmed queue and a remaining duration for every charging session | A deterministic estimate of when the requesting vehicle can start charging. |

If the required DES fields are missing, the system must retain the aggregate
estimate. It must never invent a precise-looking DES time from a station-wide
average session duration.

## Model outputs and the final product output

The models are components, not a chain in which every model consumes the last
model's answer. Each adds a different piece of evidence.

```text
Station telemetry / user app / camera / external context
                    |
      +-------------+------------------+
      |                                |
occupancy forecasting             session-duration forecasting
XGBoost -> later LSTM/Transformer RDM ML -> later DL sequence model
      |                                |
probability / occupancy at ETA    remaining minutes per active session
      |                                |
      +--------- queue / DES ----------+
                    |
       waiting time, start-time distribution, uncertainty flags
                    |
  compatibility + route + charging energy/time + safety constraints
                    |
        ranked station recommendation for one vehicle
```

The user-facing response should ultimately contain:

```json
{
  "station_id": "...",
  "recommended": true,
  "estimated_arrival_at": "...",
  "estimated_charge_start_at": "...",
  "estimated_wait_min": 12,
  "estimated_charge_min": 24,
  "estimated_departure_at": "...",
  "confidence": "medium",
  "wait_method": "discrete_event_simulation",
  "reason_codes": ["CCS2_COMPATIBLE", "LIVE_PORT_TELEMETRY"],
  "caveats": ["UNOBSERVED_ARRIVALS_EXCLUDED"]
}
```

The existing recommendation endpoint already returns most of this: candidate
station, route/ETA inputs, compatibility, predicted occupancy, estimated wait,
charging time, rank and flags. The new DES endpoint supplies the more precise
`estimated_charge_start_at` and `estimated_wait_min` only when it has a valid
telemetry snapshot. Wiring that result into the ranking is a future promotion
step after a live freshness and accuracy evaluation; it is intentionally not
automatic today.

## What each model does

| Component | Input | Output | Use now / later |
|---|---|---|---|
| Persistence / XGBoost occupancy | occupancy history (then calendar/weather/traffic) | occupancy at t+5, t+10, t+15 | current safe fallback / first ML MVP |
| Markov | observed occupancy transitions | release and arrival transition probabilities | later probabilistic wait distribution; never reverse-solve transitions from a desired stationary probability |
| Erlang-C | arrival rate, service rate, number of working ports | probability of waiting and expected aggregate wait | active MVP fallback when individual sessions are unavailable |
| RDM | live session state: elapsed time, delivered kWh, power, SoC, target, vehicle/connector | remaining minutes for one live charging session | provider duration first; ML/DL only after completed session data is reviewed |
| DES | per-port state, RDM/provider duration, physically confirmed queue, connector compatibility | projected time a compatible port becomes available | implemented as a telemetry-gated backend adapter |
| LSTM / Transformer | longer multi-station temporal sequences and approved context | better occupancy, arrivals or session-duration estimates, plus uncertainty | experimental scaling path, not a prerequisite for DES |
| Recommendation / safety layer | all forecasts plus route, SoC, compatibility and hard constraints | ranked stations, reasons and caveats | current application layer |

## Realtime sources are evidence with different reliability

1. **Station operator/OCPP/API** is the source of truth for port state,
   session start/end, faults and energy. It is required for reliable DES.
2. **A user app** can provide route ETA, current GPS (only with explicit
   consent), SoC/range and an intent to charge. It improves arrival forecasting,
   but an intent is not a confirmed queue entry. Keep it as `PlannedArrival`
   with a calibrated `arrival_probability`, expiry, cancellation and arrival
   confirmation.
3. **Camera/vision** may measure physical queue length and arrivals from users
   who do not use the app. Treat it as a supplemental observation: it needs a
   privacy impact review, retention policy, false-positive monitoring and a
   reconciliation rule with the station operator's state. It should not identify
   a person or replace station session records.

This is why accepting some uncertainty is correct: the system should show an
honest wider interval or fall back to Erlang-C rather than reserving a port for
someone who may never arrive.

## Implemented telemetry contract

`PUT /realtime/stations/{station_id}/telemetry` accepts a simulator snapshot or
a future station-provider adapter. It stores only in-memory demo state.
`POST /realtime/stations/{station_id}/simulate-wait` calculates the deterministic
DES result for a requester's compatible connector types.

Each port reports `available`, `charging` or `offline`. A charging port needs a
`session_id`; its remaining duration comes from
`reported_remaining_port_release_min`, or—only after a reviewed artifact is deployed—a
Residual Duration Model. The duration means until physical port release: a
vehicle may have reached `doneChargingTime` but still occupy the port until its
`disconnectTime`. Queue entries represent vehicles physically confirmed
at the station and carry a connector requirement and expected duration.

The result always carries these safety flags:

- `CONFIRMED_QUEUE_ONLY`: app intentions are not assumed to be a physical queue.
- `UNOBSERVED_ARRIVALS_EXCLUDED`: a snapshot cannot see cars that arrive later.
- `SNAPSHOT_ADVANCED_WITHOUT_NEW_TELEMETRY`: evaluation is later than the latest
  snapshot, so a fresh feed is needed for operational use.

## RDM training gate

`ml/src/train_residual_duration.py` currently prints the required data contract
and refuses `--execute` because the session domain is still unapproved. The
required ground truth is the eventual physical port-release timestamp
(`disconnectTime` for ACN-Data), not the last non-zero charging-current time
(`doneChargingTime`). The label at observation time is:

```text
remaining_port_release_min = disconnect_at - observation_timestamp
```

Rows from one session must never appear in both train and test. Compare a
candidate RDM against provider-reported duration and a station/connector median;
measure MAE by elapsed-session bucket, connector, power band and station. Only
then can an approved RDM fill a missing provider duration for DES.

## Promotion checklist

1. Build the frontend simulator against the telemetry endpoint; it can add cars
   to a confirmed queue and change each physical port state without pretending it
   is a real station feed.
2. Validate station adapter/OCPP field mappings, ordering, duplicate events,
   time zones and a freshness SLA.
3. Calibrate app arrival probability from planned, cancelled, expired and
   actually-arrived events; do not hard-code it as 1.0.
4. Benchmark DES and aggregate wait estimates against observed queue/start times.
5. Add an approved RDM artifact, monitoring and rollback. Then evaluate whether
   DES can replace Erlang-C for fresh live recommendations, station by station.
