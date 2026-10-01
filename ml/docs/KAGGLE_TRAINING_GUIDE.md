# Kaggle training guide — UrbanEV source benchmark

> **Current decision:** do not run the optional LSTM section as the next step.
> The current UrbanEV residual-XGBoost result remains exploratory; active work
> is Queue Lab, then Monte Carlo DES, then ACN/RDM. See
> [`QUEUE_LAB_DES_ROADMAP.md`](QUEUE_LAB_DES_ROADMAP.md).

This guide records a completed source-domain occupancy benchmark, not a Vietnam
deployment model. The residual-XGBoost result is exploratory only: do not deploy
it, and do not run the LSTM section. Keep the Kaggle dataset and notebook private
unless the UrbanEV licence allows public redistribution.

## 1. Prepare two private Kaggle datasets

Create `ocm-ml-code` containing a zip with `ml/`, `shared/`, and
`pyproject.toml` from this repository. Create `ocm-urbanev-processed` containing
only `urbanev_processed.parquet` from `ml/data/processed/urbanev/`. Attach both datasets to a
new Python notebook.

## 2. Configure the notebook

In Settings, select GPU only for the LSTM experiment; XGBoost can start on CPU.
Use a GPU-enabled session for LSTM and verify it with `torch.cuda.is_available()`.
Kaggle saves notebook output under `/kaggle/working`; write every generated
artifact there.

## 3. First cells

Set the two paths to the actual dataset slugs shown in the Notebook Input pane.

```python
from pathlib import Path
import os, shutil, zipfile

CODE_ZIP = Path("/kaggle/input/ocm-ml-code/open-charge-map-ml-code.zip")
DATASET = Path("/kaggle/input/ocm-urbanev-processed/urbanev_processed.parquet")
REPO = Path("/kaggle/working/open-charge-map")

zipfile.ZipFile(CODE_ZIP).extractall(REPO)
os.environ["PYTHONPATH"] = str(REPO)
assert DATASET.is_file()
```

Check packages before installing anything. If a required package is missing,
enable Internet in the notebook settings only long enough to run the install.

```python
!python -c "import xgboost, pandas, pyarrow; print(xgboost.__version__)"
!python -m pip install -q -r /kaggle/working/open-charge-map/ml/requirements.txt
```

## 4. Build the one frozen seasonal feature dataset

```python
!PYTHONPATH=/kaggle/working/open-charge-map python /kaggle/working/open-charge-map/ml/src/build_feature_dataset.py \
  --occupancy /kaggle/input/ocm-urbanev-processed/urbanev_processed.parquet \
  --profile seasonal \
  --output /kaggle/working/occupancy_features_seasonal.parquet
```

This produces the feature parquet, its metadata, and its frozen seasonal profile.
Keep the three files together. Do not build a second seasonal profile during
training.

## 5. Train the first candidate: residual XGBoost

```python
!PYTHONPATH=/kaggle/working/open-charge-map python /kaggle/working/open-charge-map/ml/src/train_occupancy.py \
  --dataset /kaggle/working/occupancy_features_seasonal.parquet \
  --artifact-dir /kaggle/working/xgb-urbanev-source \
  --prediction-mode residual_to_persistence \
  --execute
```

Read `occupancy_model_meta.json`. For every +5...+60 horizon, compare `xgboost`
with `persistence` and `seasonal_naive` on the test split. This candidate learns
only the residual over persistence, so it does not need to relearn the strongest
short-horizon baseline. A model that does not win meaningfully and consistently
stops here; do not move to LSTM merely because Kaggle provides a GPU.

## 6. Preserve and register results

```python
shutil.make_archive("/kaggle/working/urbanev-source-run", "zip", "/kaggle/working")
```

Use **Save & Run All** so the full notebook run and output are versioned. Download
`urbanev-source-run.zip`, then add the metrics JSON to
`ml/results/occupancy/exploratory/` and fill in `kaggle_run_metadata.json` with
the exact Kaggle notebook version, input dataset version and code commit. Do not
create a serving model bundle from this run.
