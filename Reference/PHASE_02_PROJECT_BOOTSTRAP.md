# Smart EV Journey — Phase 02 — Project Bootstrap

**Phase:** 02 / 11  
**Depends on:** Phase 01  
**Primary outcome:** Repository chạy được ở trạng thái skeleton với cấu hình, dependency và test baseline ổn định.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Khởi tạo codebase sau khi data contract và dữ liệu MVP đã ổn định. Không implement business logic lớn trong phase này.

## 2. Suggested Structure

```text
smart-ev-journey/
├── backend/
│   ├── app/
│   ├── tests/
│   └── requirements.txt
├── frontend/
├── ml/
│   ├── src/
│   ├── notebooks/
│   ├── artifacts/
│   └── tests/
├── data/
├── scripts/
├── docs/
├── .env.example
├── .gitignore
├── AGENTS.md
└── README.md
```

## 3. Tasks

- Dùng Python 3.12 và bootstrap backend bằng FastAPI.
- Bootstrap frontend bằng React + TypeScript + Vite; dùng Leaflet cho bản đồ.
- Tạo config loader cho:
  - routing API key;
  - data paths;
  - model artifact paths;
  - demo mode.
- Tạo logging cơ bản.
- Tạo test runner.
- Tạo formatting/lint configuration.
- Tạo `.env.example`; không commit API key thật.
- Tạo health-check command/API tối thiểu.
- Tạo script kiểm tra data paths tồn tại.
- Ghi hướng dẫn chạy local trong README.

## 4. Deliverables

- Repository skeleton.
- Dependency files.
- Environment template.
- Backend health endpoint.
- Frontend placeholder page.
- Test command.
- Bootstrap README.

## 5. Exit Gate

- [x] Fresh `.venv` và frontend dependency install có thể setup từ README/lockfile.
- [x] Backend start thành công bằng Uvicorn.
- [x] Frontend start thành công bằng Vite.
- [x] Health endpoint trả HTTP `200` và `status=ok`.
- [x] Test command chạy thành công với 6 tests.
- [x] Không có secret/API key thật trong source; `.env` được ignore.
- [x] Data-path validation tìm đúng 12 dataset/artifact từ Phase 00–01.

**Exit Gate result:** `PASS` — 2026-09-25. Chi tiết tại `data/validation/phase2_bootstrap_report.md`.

## 5.1 Kết quả thực tế

- Backend: FastAPI `0.141.1`, Uvicorn `0.52.0`, Python `3.12`.
- Frontend: React `19.3.0`, Vite `7.3.6`, TypeScript `5.9.3`, Leaflet `1.9.4`.
- Config loader hỗ trợ app environment, log level, demo mode, Goong key, data directory và model artifact path.
- Dependency frontend được khóa bằng `pnpm-lock.yaml`; build script chỉ allow-list `esbuild` trong `pnpm-workspace.yaml`.
- Gate đã chạy: backend tests, backend Ruff, frontend ESLint, TypeScript/Vite production build và HTTP smoke tests.
