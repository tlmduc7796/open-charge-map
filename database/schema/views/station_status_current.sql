-- views.station_status_current — trạng thái hiện tại của trạm tổng hợp từ port_status.
-- Backend đọc view này (kiểm tra ở validate_database). Cổng chưa có dòng port_status, hoặc có
-- status 'unknown', được tính là unknown. queue_length luôn NULL: demo chưa lưu hàng đợi.

CREATE VIEW public.station_status_current AS
WITH counts AS (
    SELECT
        p.station_id,
        count(*) FILTER (WHERE p.is_active)::integer AS total_ports,
        count(*) FILTER (
            WHERE p.is_active AND ps.status IN ('available', 'charging')
        )::integer AS operational_ports,
        count(*) FILTER (WHERE p.is_active AND ps.status = 'charging')::integer AS occupied_ports,
        count(*) FILTER (WHERE p.is_active AND ps.status = 'available')::integer AS available_ports,
        count(*) FILTER (WHERE p.is_active AND ps.status = 'out_of_service')::integer AS offline_ports,
        count(*) FILTER (
            WHERE p.is_active AND (ps.status = 'unknown' OR ps.port_id IS NULL)
        )::integer AS unknown_ports,
        max(ps.reported_at) AS port_status_reported_at
    FROM public.ports p
    LEFT JOIN public.port_status ps ON ps.port_id = p.id
    GROUP BY p.station_id
)
SELECT
    s.id AS station_id,
    s.code AS station_code,
    COALESCE(c.total_ports, 0) AS total_ports,
    COALESCE(c.operational_ports, 0) AS operational_ports,
    COALESCE(c.occupied_ports, 0) AS occupied_ports,
    COALESCE(c.available_ports, 0) AS available_ports,
    COALESCE(c.offline_ports, 0) AS offline_ports,
    COALESCE(c.unknown_ports, 0) AS unknown_ports,
    CASE
        WHEN COALESCE(c.operational_ports, 0) = 0 THEN NULL
        ELSE c.occupied_ports::numeric / c.operational_ports
    END AS occupancy_ratio,
    NULL::integer AS queue_length,
    c.port_status_reported_at AS reported_at
FROM public.stations s
LEFT JOIN counts c ON c.station_id = s.id;
