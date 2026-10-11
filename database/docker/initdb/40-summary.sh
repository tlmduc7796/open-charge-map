#!/bin/sh
# In tóm tắt trạng thái database sau khi nạp (không thay đổi gì).
(
set -eu
psql -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\echo '== Tóm tắt =='
SELECT 'stations' AS item, count(*)::text AS value FROM public.stations
UNION ALL SELECT 'ports', count(*)::text FROM public.ports
UNION ALL SELECT 'station_occupancy_5m rows', count(*)::text FROM public.station_occupancy_5m
UNION ALL SELECT 'occupancy từ', coalesce(min(bucket_at)::text, '-') FROM public.station_occupancy_5m
UNION ALL SELECT 'occupancy đến', coalesce(max(bucket_at)::text, '-') FROM public.station_occupancy_5m
UNION ALL SELECT 'station_occupancy_profile cells', count(*)::text FROM public.station_occupancy_profile
UNION ALL SELECT 'ports occupied (bucket mới nhất)', coalesce(sum(occupied_ports), 0)::text
    FROM public.station_status_current
UNION ALL SELECT 'ports available (bucket mới nhất)', coalesce(sum(available_ports), 0)::text
    FROM public.station_status_current;
SQL
)
