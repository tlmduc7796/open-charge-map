# ML data handoff — required reading before enabling DL

The source of truth for proposed domains is
[`Reference/data_gap_analysis.md`](../../Reference/data_gap_analysis.md). It is a
strategy/reference document, not an executable schema. The executable review
surface is [`config/domain_schema.draft.json`](config/domain_schema.draft.json).

## Rule for future agents and contributors

Do not infer a column's meaning from its name, silently fill a missing candidate
feature, or flip an `enabled` flag merely because an artifact exists. First:

1. inspect raw provenance, timezone, cadence, station coverage and privacy
   constraints;
2. edit the domain schema with the chosen fields, joins, data source and
   missing-data policy;
3. build an enriched, versioned dataset with those exact columns;
4. run a temporal data audit; then enable only the intended model profile.

The current draft deliberately disables LSTM-Markov, Transformer and foundation
fine-tuning. This preserves their code/notebooks for team review while making a
premature `--execute` fail visibly instead of training on guessed features.

## Data/model mapping

| Model stage | Minimum approved data |
|---|---|
| XGBoost baseline | occupancy history and capacity only |
| Hybrid LSTM source experiment | occupancy history + frozen target-time seasonal profile |
| LSTM + Markov production candidate | baseline + deployment-region calendar + station context; compatible-port state when available |
| Transformer/STGNN | multi-station temporal data + spatial/POI + weather; traffic only with an approved source |
| Foundation fine-tune | sufficient real station diversity, long history and a benchmark that proves baseline/DL limitations |
