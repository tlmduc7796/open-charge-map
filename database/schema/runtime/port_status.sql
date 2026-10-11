-- runtime.port_status — trạng thái HIỆN TẠI của cổng, đúng một dòng mỗi cổng.
-- Seed tạo sẵn mỗi cổng với status = 'unknown' (chưa biết có bị chiếm hay không);
-- reported_at để NULL cho tới khi backend ghi lần đầu.
-- Ghi bởi POST /api/v1/internal/port-status và job đánh dấu stale.

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
