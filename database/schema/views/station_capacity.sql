-- views.station_capacity — số cổng đang hoạt động của trạm, tổng và theo từng chuẩn cổng.

CREATE VIEW public.station_capacity AS
WITH connector_capacity AS (
    SELECT
        p.station_id,
        p.connector_code,
        count(*)::integer AS port_count,
        max(p.max_power_kw) AS max_power_kw
    FROM public.ports p
    WHERE p.is_active
    GROUP BY p.station_id, p.connector_code
),
totals AS (
    SELECT station_id, sum(port_count)::integer AS total_ports
    FROM connector_capacity
    GROUP BY station_id
),
connector_json AS (
    SELECT
        station_id,
        jsonb_object_agg(
            connector_code,
            jsonb_build_object('count', port_count, 'max_power_kw', max_power_kw)
            ORDER BY connector_code
        ) AS connectors
    FROM connector_capacity
    GROUP BY station_id
)
SELECT
    s.id AS station_id,
    s.code AS station_code,
    COALESCE(t.total_ports, 0) AS total_ports,
    COALESCE(cj.connectors, '{}'::jsonb) AS connectors
FROM public.stations s
LEFT JOIN totals t ON t.station_id = s.id
LEFT JOIN connector_json cj ON cj.station_id = s.id;
