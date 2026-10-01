# ML result registry

`results/` is the tracked record of evaluated runs, not a serving-artifact
directory. Keep each experiment under `<problem>/<decision-status>/` with its
metrics JSON and a provenance manifest. Large model binaries stay out of Git.

The current record is `occupancy/exploratory/`: a Shenzhen UrbanEV residual
XGBoost comparison. It is exploratory, is not deployable, and does not authorize
an LSTM run.
