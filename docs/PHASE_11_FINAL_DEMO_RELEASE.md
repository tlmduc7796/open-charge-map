# Smart EV Journey — Phase 11 — Final Demo Hardening & Release

**Phase:** 11 / 11  
**Depends on:** Phase 10  
**Primary outcome:** Có bản demo hackathon có thể setup, reset, chạy và trình bày ổn định.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Đóng scope kỹ thuật, giảm rủi ro demo và chuẩn bị artifact cuối cùng.

## 2. Tasks

### 2.1 Demo script

Viết flow ngắn:

1. chọn vehicle + SOC;
2. nhập journey;
3. xem recommendations;
4. chọn station;
5. kích hoạt congestion/outage;
6. refresh projected wait;
7. show reroute/recommendation change.

### 2.2 Reliability

- Cache mọi route cần thiết.
- Startup check:
  - data files;
  - model artifact;
  - API config;
  - frontend/backend health.
- Add demo reset.
- Add graceful fallback cho external API.
- Freeze dependency versions.

### 2.3 Documentation

README cuối phải có:

- problem statement ngắn;
- scope;
- setup;
- run commands;
- data provenance;
- UrbanEV usage;
- model target = occupancy;
- wait estimation limitation;
- demo instructions.

### 2.4 Claims

Không claim:

- UrbanEV có wait-time ground truth;
- model ML dự đoán wait trực tiếp nếu thực tế không có;
- synthetic queue là dữ liệu thực;
- kết quả Shenzhen đại diện chính xác cho Việt Nam.

Nên ghi rõ:

- occupancy model train/evaluate bằng UrbanEV;
- station/map fields dùng real source khi có;
- queue/events/runtime demo là synthetic;
- wait được estimate từ projected occupancy + runtime queue/service assumptions.

### 2.5 Release artifacts

- source code;
- data contract;
- phase docs;
- model metadata;
- evaluation report;
- demo scenarios;
- final README.

## 3. Exit Gate — Final Release Gate

- [ ] Clean setup từ repository mới thành công.
- [ ] Backend + frontend start bằng documented commands.
- [ ] Model load thành công.
- [ ] Demo reset hoạt động.
- [ ] Ít nhất 3 scenario cốt lõi chạy end-to-end không cần sửa file thủ công.
- [ ] Routing fallback đã được thử.
- [ ] Data provenance được mô tả rõ.
- [ ] Model metrics và limitation được ghi rõ.
- [ ] Không còn feature out-of-scope xuất hiện trong UI/API chính.
- [ ] Không có secret trong repository.
- [ ] Demo script đã dry-run hoàn chỉnh.
- [ ] README đủ để một thành viên khác trong team tự chạy project.

**Final Exit Gate result:** `PASS / FAIL`

> Chỉ khi gate này PASS mới coi MVP/hackathon build là release-ready.
