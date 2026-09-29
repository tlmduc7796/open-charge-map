# Phase 03 — UrbanEV Preprocessing & Temporal Split Validation Report

**Result:** `PASS`
**Validation Date:** `2026-09-27 04:56:26 UTC`
**Source Archive:** `UrbanEVDataset.zip` (SHA-256: `9d3f0aec34434546d082509efcdeeaea116eaa841701cc5854a9b62a27881a79`)

## 1. Summary Metrics
- **Selected Stations:** 50
- **Total Records:** 2,606,400 rows
- **Temporal Resolution:** 5 minutes
- **Processed Artifact:** `urbanev_processed.parquet` (11.68 MB)
- **Execution Time:** 13.34s

## 2. Temporal Split Distribution
| Split | Records | Range | Mean Occupancy | Std Occupancy |
|---|---|---|---|---|
| **Train** | 1,972,800 | `2022-09-01 00:00:00` → `2023-01-15 23:55:00` | 0.2723 | 0.2614 |
| **Validation** | 230,400 | `2023-01-16 00:00:00` → `2023-01-31 23:55:00` | 0.2279 | 0.2368 |
| **Test** | 403,200 | `2023-02-01 00:00:00` → `2023-02-28 23:55:00` | 0.2517 | 0.2595 |

## 3. Exit Gate Invariants
- [x] Preprocessing runs reproducibly from raw via single command.
- [x] Zero temporal leakage between train/val/test (`train_max < val_min < test_min`).
- [x] `occupied_ports >= 0` for all 100% rows.
- [x] `occupied_ports <= total_ports` for all 100% rows.
- [x] Target `occupancy_ratio` is strictly bounded in `[0.0, 1.0]`.
- [x] No queue, synthetic wait, price, weather, or POI features included.
- [x] Scaler/normalization not required for target as ratio is inherently normalized in [0, 1].
- [x] `split_manifest.json` and `preprocessing_meta.json` generated and committed.
