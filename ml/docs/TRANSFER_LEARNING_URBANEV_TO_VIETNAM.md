# UrbanEV (Shenzhen) to Vietnam: transfer-learning protocol

## What the available source dataset can and cannot teach

The downloaded UrbanEV archive is a real 5-minute station-level dataset from
Shenzhen, China, covering 2022-09-01 to 2023-02-28. Its processed station CSVs
provide aggregate `busy`, `idle`, service/electricity prices, fast/slow counts,
`duration` and `volume`. It is appropriate for occupancy forecasting research
and pipeline stress tests. It does **not** expose session IDs, individual-car
SoC, queue order, per-port session lifecycle or a session end timestamp.

Therefore it can support:

- source-domain XGBoost/LSTM/Transformer occupancy experiments;
- a source benchmark for a Vietnamese occupancy model;
- aggregate Markov transition experiments derived from busy/idle history.

It cannot support:

- an honest Residual Duration Model (RDM);
- true per-vehicle DES validation;
- claims about Vietnamese production accuracy.

The upstream UrbanEV project describes the dataset as Shenzhen public-station
data and documents the 5-minute station-level files. See the
[UrbanEV project](https://github.com/IntelligentSystemsLab/UrbanEV) and its
[Dryad record](https://datadryad.org/dataset/doi%3A10.5061/dryad.np5hqc04z).

## Do not call every approach “fine-tuning”

| Model family | Correct transfer operation |
|---|---|
| XGBoost | Train a Chinese source candidate, then train/retrain a Vietnamese candidate; optionally continue the source booster on Vietnam data as an experiment. It is not LLM-style fine-tuning and must compete with Vietnam-only training. |
| LSTM / Transformer | Pretrain sequence encoder on Chinese occupancy, initialize a new target run from those weights, then train and unfreeze on Vietnam data. The output head may need reinitializing. |
| RDM | Do not transfer from UrbanEV: it has no session-level labels. Train only after Vietnam/operator data has completed-session ground truth. |
| DES | Not a trained model. It consumes live port/session/queue facts and, optionally, an approved RDM output. |

## Canonical target contract before any transfer run

Vietnam data must be mapped into a versioned canonical dataset. At minimum each
occupancy observation needs:

```text
timestamp with timezone, observed_at, ingested_at,
station_id, port/connector capacity, busy/idle or occupancy_ratio,
station region, data_source, schema_version
```

For RDM/DES later, add a separate restricted session table with `session_id`,
`port_id`, start/end event, connector, energy/power observations, consent and
retention metadata. Do not mix personally identifiable app information into the
occupancy feature table.

Before mapping, decide explicitly:

- Vietnam timezone and deployment regions; UrbanEV's timestamps and GCJ-02
  coordinates must never be treated as Vietnamese coordinates/time.
- connector and capacity semantics; use `occupied / operational_compatible`
  where that is the user-facing quantity.
- local calendar, public holidays, prices, weather and traffic sources. Do not
  copy Chinese fee, weather, POI or holiday features into Vietnamese inference.
- station downtime, missing data and late/out-of-order event policy.

## Recommended occupancy transfer experiment

```text
1. Freeze and fingerprint UrbanEV source data.
2. Build a Vietnamese-only canonical temporal split:
   Vietnam train -> validation -> untouched later Vietnam test.
3. Fit Vietnamese seasonal profiles from Vietnam-train only.
4. Evaluate on the same Vietnamese test origins:
   persistence, Vietnam seasonal-naive, Vietnam-only XGBoost,
   China-only zero-shot, China-initialized then Vietnam-adapted XGBoost.
5. For DL, compare Vietnam-only vs China-pretrained then Vietnam-adapted
   LSTM/Transformer under the same split, budget and input contract.
6. Promote only a candidate that improves the Vietnam test metrics,
   calibration and per-station capacity checks—not one that merely wins in China.
```

The seasonal profile embedded in a source release must **not** be reused in
Vietnam. Rebuild it from Vietnam training observations because daily/weekday
usage patterns are domain-specific.

## Current pipeline and changes under review

The current ML contract has moved from three horizons to twelve direct
horizons: `+5, +10, …, +60` minutes. The recommended candidate is a direct
XGBoost model per horizon with twelve occupancy lags and the station's frozen
weekday/weekend 5-minute seasonal profile. The backend artifact adapter now
accepts all twelve horizons and calculates seasonal inputs from station ID plus
forecast timestamp.

The seasonal feature has one shared contract: fit its profile from Vietnam-train
only, then use that same frozen profile unchanged for train, validation, test
and online inference. The shared `seasonal_profile` helper is the source of
truth for the smoothing and target-time bucket calculation.

`train_lstm_markov.py` is currently the **Phase 05A hybrid LSTM occupancy
regression** script. It predicts all twelve occupancy horizons but does not yet
emit Markov transition heads. Phase 05B is the separately calibrated Markov
transition contract described in `MARKOV_PHASE_PLAN.md`; it must not be claimed
as trained until compatible-port labels are approved.

## Data quantity decision rule

With only a few weeks of Vietnam data, start with persistence, seasonal-naive
and Vietnam-only XGBoost. Pretraining may help, but it may also cause negative
transfer because Shenzhen's fleet, tariffs, station layout and behavior differ.
With several representative months across station types, run the controlled
comparisons above. Use DL only when it beats the simpler baselines on the later
Vietnam test interval and remains operationally reproducible.
