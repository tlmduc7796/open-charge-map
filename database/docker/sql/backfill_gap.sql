-- Điền lấp các bucket 5 phút còn thiếu của station_occupancy_5m từ CSV simulator.
-- Chạy bởi docker/feeder-entrypoint.sh mỗi lần feeder khởi động (idempotent).
--
-- Vì sao: model dự báo cần 12 bucket liên tiếp cách nhau đúng 5 phút. Khi stack bị dừng (máy ngủ,
-- tắt Docker) bảng có một khoảng trống và backend rơi về `persistence` (cờ HISTORY_UNAVAILABLE) cho
-- tới khi feeder tích đủ 12 bucket mới, khoảng 1 giờ. Điền lấp xong thì model dùng được ngay.
--
-- Biến psql:  csv_path      đường dẫn CSV trong container POSTGRES (COPY chạy phía server)
--             history_days  số ngày lịch (giờ VN) gần nhất cần phủ kín, tính cả hôm nay
--
-- Bucket nguồn của bucket đích T giống database/docker/sql/load_history.sql và simulator/script/
-- feed.py: nếu T nằm trong khoảng của CSV thì lấy đúng T, nếu không thì dịch theo BỘI SỐ 7 NGÀY tới
-- bucket gần nhất nằm trong khoảng (cùng thứ, cùng giờ). Dòng đã có không bị ghi đè; dữ liệu do
-- feeder gửi tới là nguồn thật hơn.
--
-- Đây là dữ liệu synthetic được điền, không phải số đo thực tế.

\set ON_ERROR_STOP on
SET timezone = 'UTC';

BEGIN;

CREATE TEMP TABLE sim_stage (
    station_id        uuid NOT NULL,
    bucket_at         timestamptz NOT NULL,
    total_ports       integer NOT NULL,
    operational_ports integer NOT NULL,
    occupied_ports    integer NOT NULL
) ON COMMIT DROP;

COPY sim_stage FROM :'csv_path' WITH (FORMAT csv, HEADER true);

SELECT min(bucket_at) AS sim_start, max(bucket_at) AS sim_end FROM sim_stage \gset

SELECT date_bin(interval '5 minutes', now(), TIMESTAMPTZ '2001-01-01 00:00:00+00') AS now_bucket
\gset

SELECT ((date_trunc('day', :'now_bucket'::timestamptz AT TIME ZONE 'Asia/Ho_Chi_Minh')
         - make_interval(days => :history_days - 1)) AT TIME ZONE 'Asia/Ho_Chi_Minh') AS win_start
\gset

-- Partition tháng cho cửa sổ điền lấp (cùng cách load_history.sql).
\o /dev/null
SELECT public.ensure_month_partition('public.station_occupancy_5m'::regclass, month::date)
FROM generate_series(
    date_trunc('month', :'win_start'::timestamptz AT TIME ZONE 'UTC'),
    date_trunc('month', :'now_bucket'::timestamptz AT TIME ZONE 'UTC'),
    interval '1 month'
) AS month;
\o

WITH stations AS (
    SELECT DISTINCT station_id FROM sim_stage
), targets AS (
    SELECT st.station_id,
           g.bucket_at AS target_at,
           CASE
               WHEN g.bucket_at > :'sim_end'::timestamptz
                   THEN g.bucket_at - make_interval(days => 7 * ceil(
                       extract(epoch FROM (g.bucket_at - :'sim_end'::timestamptz)) / 604800
                   )::integer)
               WHEN g.bucket_at < :'sim_start'::timestamptz
                   THEN g.bucket_at + make_interval(days => 7 * ceil(
                       extract(epoch FROM (:'sim_start'::timestamptz - g.bucket_at)) / 604800
                   )::integer)
               ELSE g.bucket_at
           END AS source_at
    FROM stations st
    CROSS JOIN generate_series(
        :'win_start'::timestamptz, :'now_bucket'::timestamptz, interval '5 minutes'
    ) AS g(bucket_at)
), inserted AS (
    INSERT INTO public.station_occupancy_5m
        (station_id, bucket_at, total_ports, operational_ports, occupied_ports)
    SELECT t.station_id, t.target_at, s.total_ports, s.operational_ports, s.occupied_ports
    FROM targets t
    JOIN sim_stage s ON s.station_id = t.station_id AND s.bucket_at = t.source_at
    ON CONFLICT (station_id, bucket_at) DO NOTHING
    RETURNING 1
)
SELECT count(*) AS filled FROM inserted \gset

\echo '  Điền lấp' :filled 'bucket (cửa sổ' :win_start '->' :now_bucket ')'

COMMIT;

ANALYZE public.station_occupancy_5m;
