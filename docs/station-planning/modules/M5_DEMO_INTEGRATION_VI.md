# M5 — Demo data, tích hợp và nghiệm thu

## Prompt giao việc

Bạn phụ trách ráp demo station recommendation và xác minh end-to-end theo `../IMPLEMENTATION_PLAN_VI.md` + `SHARED_CONTRACT_VI.md`. Phối hợp M1–M4, không tạo thuật toán hoặc schema cạnh tranh với module owner.

## Mục tiêu

Tạo kịch bản demo nhỏ, tái lập ở một pilot extent TP.HCM; kết nối dữ liệu, API, engine và UI; đảm bảo giới hạn dữ liệu được nói rõ với người xem.

## Task nhỏ

1. **Demo narrative:** chọn một câu hỏi cụ thể (ví dụ so sánh candidate ở vùng dân cư, hành lang liên tỉnh hoặc điểm đến du lịch) và pilot scope có geometry/nguồn.
2. **Seed scenario:** tạo 2–5 candidate, catalog trạm lân cận, demand cells/proxy và một thiếu dữ liệu có chủ đích như grid capacity. Tất cả synthetic phải gắn nhãn.
3. **End-to-end:** chạy scenario qua API và UI; xác minh cùng candidate IDs, versions, units, ranks, reason codes và warnings.
4. **Sensitivity:** đổi một đầu vào (coverage target, weight profile hoặc scenario demand) và thể hiện output thay đổi; không gán probability cho low/base/high.
5. **Acceptance checklist:** kiểm tra pass/fail/conditional/unknown; missing finance; no feasible candidates; candidate ranking comparison; partial pilot label; provenance; driver flow.
6. **Demo reset:** tài liệu hóa cách nạp/reset seed/demo clock để người khác trình diễn lại.
7. **Presenter notes:** câu chuyện người dùng, insight, giới hạn, dữ liệu nào cần xin từ doanh nghiệp để tiến tới demo thật.

## Không thuộc module

- Sửa công thức/hard constraints/API contract một mình.
- Nâng synthetic thành observed hoặc ghi số liệu giả thành kết quả TP.HCM.
- Thêm bảng DB persistent chỉ để demo.
- Khẳng định lợi nhuận, coverage toàn thành phố hoặc grid readiness khi chưa có bằng chứng.

## Acceptance

- Demo chạy lặp lại được từ hướng dẫn ngắn.
- Tất cả số liệu demo có nguồn/status và pilot extent rõ.
- Người xem giải thích được vì sao một site được xếp cao/thấp và còn cần khảo sát gì.
- Đổi scenario tạo delta giải thích được.
- Luồng app cũ được kiểm tra không hồi quy.

## Handoff

Bàn giao kịch bản demo, seed/reset guide, checklist kết quả, known limitations và nội dung cần nói trong phần trình bày.
