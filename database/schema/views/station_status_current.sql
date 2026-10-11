-- views.station_status_current — trạng thái hiện tại của trạm, lấy từ bucket MỚI NHẤT của
-- history.station_occupancy_5m (số cổng đang dùng của trạm, gửi về mỗi 5 phút). Không cần biết cổng
-- cụ thể nào đang bận, nên port_status không tham gia.
-- Backend đọc view này (kiểm tra ở validate_database).
--
--   total_ports       số cổng active của catalog
--   operational_ports cổng hoạt động báo trong bucket (không vượt total_ports)
--   occupied_ports    cổng đang dùng (không vượt operational_ports)
--   available_ports   operational - occupied
--   offline_ports     total - operational
--   unknown_ports     = total_ports khi trạm CHƯA có bucket nào, ngược lại 0
--
-- Trạm chưa có bucket: operational = occupied = available = offline = 0 và unknown = total.
-- Độ cũ của bucket (reported_at) do backend đánh giá lúc đọc. queue_length lấy từ bucket (có thể NULL).

CREATE VIEW public.station_status_current AS
WITH latest AS (
    SELECT
        s.id AS station_id,
        s.code AS station_code,
        COALESCE(pc.total_ports, 0) AS total_ports,
        o.bucket_at,
        o.operational_ports AS reported_operational,
        o.occupied_ports AS reported_occupied,
        o.queue_length
    FROM public.stations s
    LEFT JOIN (
        SELECT station_id, count(*)::integer AS total_ports
        FROM public.ports
        WHERE is_active
        GROUP BY station_id
    ) pc ON pc.station_id = s.id
    LEFT JOIN LATERAL (
        SELECT b.bucket_at, b.operational_ports, b.occupied_ports, b.queue_length
        FROM public.station_occupancy_5m b
        WHERE b.station_id = s.id
        ORDER BY b.bucket_at DESC
        LIMIT 1
    ) o ON true
), capped AS (
    SELECT
        l.*,
        CASE
            WHEN l.bucket_at IS NULL THEN 0
            ELSE LEAST(l.reported_operational, l.total_ports)::integer
        END AS operational_ports
    FROM latest l
)
SELECT
    c.station_id,
    c.station_code,
    c.total_ports,
    c.operational_ports,
    CASE
        WHEN c.bucket_at IS NULL THEN 0
        ELSE LEAST(c.reported_occupied, c.operational_ports)::integer
    END AS occupied_ports,
    CASE
        WHEN c.bucket_at IS NULL THEN 0
        ELSE c.operational_ports - LEAST(c.reported_occupied, c.operational_ports)::integer
    END AS available_ports,
    CASE
        WHEN c.bucket_at IS NULL THEN 0
        ELSE c.total_ports - c.operational_ports
    END AS offline_ports,
    CASE WHEN c.bucket_at IS NULL THEN c.total_ports ELSE 0 END AS unknown_ports,
    CASE
        WHEN c.operational_ports = 0 THEN NULL
        ELSE LEAST(c.reported_occupied, c.operational_ports)::numeric / c.operational_ports
    END AS occupancy_ratio,
    c.queue_length::integer AS queue_length,
    c.bucket_at AS reported_at
FROM capped c;
