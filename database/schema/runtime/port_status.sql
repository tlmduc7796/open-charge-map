-- runtime.port_status — trạng thái HIỆN TẠI của từng cổng (tuỳ chọn), đúng một dòng mỗi cổng.
-- Seed tạo sẵn mỗi cổng với status = 'unknown'; reported_at để NULL cho tới khi backend ghi.
-- Ghi bởi POST /api/v1/internal/port-status và job đánh dấu stale.
--
-- Bảng này KHÔNG quyết định số cổng trống của trạm: trạng thái trạm lấy từ
-- history.station_occupancy_5m (số cổng đang dùng, gửi về mỗi 5 phút) qua view
-- station_status_current. port_status chỉ là chi tiết từng cổng nếu sau này có nguồn.

CREATE TABLE public.port_status (
    port_id             uuid PRIMARY KEY REFERENCES public.ports(id) ON DELETE CASCADE,
    status              public.port_status_value NOT NULL,
    session_started_at  timestamptz,
    estimated_finish_at timestamptz,
    reported_at         timestamptz,                -- thời điểm nguồn báo; NULL = chưa báo
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_port_status_finish_after_start CHECK (
        session_started_at IS NULL OR estimated_finish_at IS NULL
        OR estimated_finish_at >= session_started_at
    )
);
