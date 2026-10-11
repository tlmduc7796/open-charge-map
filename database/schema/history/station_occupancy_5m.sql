-- history.station_occupancy_5m — occupancy của trạm theo bucket 5 phút (chuỗi thời gian).
-- NGUỒN SỰ THẬT của trạng thái trạm: bucket mới nhất của mỗi trạm là số cổng đang dùng hiện tại
-- (view station_status_current). Cũng là nguồn huấn luyện/dự báo và của station_occupancy_profile.
-- Ghi bởi: (1) lúc khởi tạo container, nạp 30 ngày lịch sử từ simulator
-- (database/docker/sql/load_history.sql); (2) backend, POST /api/v1/internal/station-occupancy,
-- mỗi 5 phút một dòng cho mỗi trạm.
--
-- Partition theo tháng trên bucket_at. Partition tháng được tạo bằng
-- public.ensure_month_partition() trước khi ghi (lúc nạp lịch sử và trong
-- DatabaseStationStateRepository.record_occupancy); partition DEFAULT chỉ là lưới an toàn để một
-- lần ghi không bao giờ thất bại vì thiếu partition.

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

CREATE TABLE public.station_occupancy_5m_default PARTITION OF public.station_occupancy_5m DEFAULT;
