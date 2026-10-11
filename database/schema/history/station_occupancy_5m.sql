-- history.station_occupancy_5m — occupancy của trạm theo bucket 5 phút (chuỗi thời gian).
-- Là nguồn dữ liệu huấn luyện/dự báo; backend hiện chưa đọc bảng này.
-- Partition theo tháng trên bucket_at. Dữ liệu lớn nên nằm ở bulk/*.csv, không phải data/*.sql.

CREATE TABLE public.station_occupancy_5m (
    id                uuid NOT NULL DEFAULT gen_random_uuid(),
    station_id        uuid NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    bucket_at         timestamptz NOT NULL,
    total_ports       smallint NOT NULL,
    operational_ports smallint NOT NULL,
    occupied_ports    smallint NOT NULL,
    queue_length      integer,
    CONSTRAINT pk_station_occupancy_5m PRIMARY KEY (id, bucket_at),
    CONSTRAINT uq_occupancy_station_bucket UNIQUE (station_id, bucket_at),
    CONSTRAINT ck_occupancy_total_positive CHECK (total_ports > 0),
    CONSTRAINT ck_occupancy_operational_nonnegative CHECK (operational_ports >= 0),
    CONSTRAINT ck_occupancy_occupied_nonnegative CHECK (occupied_ports >= 0),
    CONSTRAINT ck_occupancy_operational_within_total CHECK (operational_ports <= total_ports),
    CONSTRAINT ck_occupancy_occupied_within_operational CHECK (occupied_ports <= operational_ports),
    CONSTRAINT ck_occupancy_queue CHECK (queue_length IS NULL OR queue_length >= 0),
    CONSTRAINT ck_occupancy_five_minute_bucket CHECK (
        EXTRACT(SECOND FROM bucket_at) = 0
        AND MOD(EXTRACT(MINUTE FROM bucket_at)::integer, 5) = 0
    )
) PARTITION BY RANGE (bucket_at);

CREATE INDEX ix_station_occupancy_5m_station_bucket
    ON public.station_occupancy_5m (station_id, bucket_at);

CREATE TABLE public.station_occupancy_5m_2026_09 PARTITION OF public.station_occupancy_5m
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');
CREATE TABLE public.station_occupancy_5m_2026_10 PARTITION OF public.station_occupancy_5m
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
CREATE TABLE public.station_occupancy_5m_2026_11 PARTITION OF public.station_occupancy_5m
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
