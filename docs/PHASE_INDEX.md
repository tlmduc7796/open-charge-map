# Smart EV Journey — Phase Plan Index

Kế hoạch gồm **12 phase (00–11)**. Data completion được hoàn thành trước bootstrap; mỗi phase có Exit Gate bắt buộc.

Để vận hành theo nhịp hackathon, 12 phase được gom thành 5 milestone: **Data** (00, 01, 03-preprocessing), **ML** (04), **Backend** (02, 05–07), **Full-stack** (08–09), và **Demo** (10–11). Exit Gate của từng phase vẫn được giữ.

| Phase | File | Kết quả chính |
|---:|---|---|
| 00 | `PHASE_00_DATA_STATIC_REAL.md` | Static/real-source data hoàn chỉnh |
| 01 | `PHASE_01_DATA_RUNTIME_ML_SOURCE.md` | Runtime/demo data + UrbanEV raw hoàn chỉnh |
| 02 | `PHASE_02_PROJECT_BOOTSTRAP.md` | Repository skeleton chạy được |
| 03 | `PHASE_03_URBANEV_PREPROCESSING.md` | UrbanEV processed + temporal split |
| 04 | `PHASE_04_OCCUPANCY_MODEL.md` | Occupancy model + evaluation + artifact |
| 05 | `PHASE_05_BACKEND_DOMAIN_CORE.md` | Compatibility/reachability/charging core |
| 06 | `PHASE_06_BACKEND_FORECAST_WAIT.md` | Occupancy inference + wait estimator |
| 07 | `PHASE_07_BACKEND_ROUTING_RECOMMENDATION.md` | Routing + recommendation + events |
| 08 | `PHASE_08_FRONTEND_CORE.md` | Map/journey/recommendation UI |
| 09 | `PHASE_09_FULLSTACK_INTEGRATION.md` | End-to-end frontend/backend flow |
| 10 | `PHASE_10_DYNAMIC_DEMO_TESTING.md` | Deterministic scenarios + system tests |
| 11 | `PHASE_11_FINAL_DEMO_RELEASE.md` | Demo hardening + release gate |

## Dependency rule

Phase `N+1` chỉ bắt đầu khi Exit Gate của Phase `N` là `PASS`.

### Ngoại lệ nhánh demo backend-first

Nhánh `demo/backend-first` được phép triển khai Phase 05–09 trước Phase 03–04 để kiểm tra
backend và frontend demo sớm. Các giới hạn bắt buộc:

- Phase 03–04 vẫn ở trạng thái chưa hoàn thành, không được ghi `PASS` giả;
- Phase 05 không phụ thuộc occupancy model nên có thể hoàn thành độc lập;
- khi Phase 06 cần forecast, chỉ dùng predictor persistence/runtime có
  `prediction_source=persistence` cho đến khi artifact Phase 04 được tích hợp;
- Phase 08 phải hiển thị đúng `prediction_source=persistence`, không giả lập model đã train;
- Phase 10–11 có thể đạt `DEMO PASS` với persistence fallback, nhưng không được ghi
  `RELEASE PASS` cho đến khi Phase 03–04 hoàn thành và integration gate được chạy lại.

## Scope guard

MVP không đưa price, service fee, weather, POI, historical energy/volume hoặc cost-based recommendation trở lại nếu chưa có quyết định scope mới.
