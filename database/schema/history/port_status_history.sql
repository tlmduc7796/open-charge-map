-- history.port_status_history — nhật ký mỗi lần cổng đổi trạng thái (append-only).
-- Partition theo tháng trên changed_at; thêm partition mới trước khi dữ liệu tháng đó xuất hiện.

CREATE TABLE public.port_status_history (
    id                uuid NOT NULL DEFAULT gen_random_uuid(),
    port_id           uuid NOT NULL REFERENCES public.ports(id) ON DELETE CASCADE,
    status            public.port_status_value NOT NULL,
    changed_at        timestamptz NOT NULL,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_port_status_history PRIMARY KEY (id, changed_at),
    CONSTRAINT uq_port_status_history_port_time UNIQUE (port_id, changed_at)
) PARTITION BY RANGE (changed_at);

CREATE INDEX ix_port_status_history_changed_at ON public.port_status_history (changed_at);

CREATE TABLE public.port_status_history_2026_09 PARTITION OF public.port_status_history
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');
CREATE TABLE public.port_status_history_2026_10 PARTITION OF public.port_status_history
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
CREATE TABLE public.port_status_history_2026_11 PARTITION OF public.port_status_history
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
