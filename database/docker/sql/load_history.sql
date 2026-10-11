-- Nạp lịch sử occupancy từ simulator vào history.station_occupancy_5m và tính bảng trung bình.
-- Chạy bởi docker/initdb/30-simulator-history.sh bằng superuser.
--
-- Biến psql:  csv_path      đường dẫn CSV trong container (cột như bảng, trừ id và queue_length)
--             history_days  số ngày lịch (giờ VN) cần nạp, tính cả hôm nay
--
-- Neo thời gian: lấy các bucket từ 00:00 (giờ VN) của ngày `hôm nay - (history_days - 1)` đến bucket 5
-- phút hiện tại. Nếu "bây giờ" nằm sau dữ liệu simulator thì dịch cả chuỗi tiến theo BỘI SỐ 7 NGÀY
-- để giữ đúng thứ trong tuần. Bucket ở tương lai không được nạp.

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

SELECT count(*) AS sim_rows, min(bucket_at) AS sim_start, max(bucket_at) AS sim_end
FROM sim_stage \gset

SELECT date_bin(interval '5 minutes', now(), TIMESTAMPTZ '2001-01-01 00:00:00+00') AS now_bucket
\gset

SELECT ((date_trunc('day', :'now_bucket'::timestamptz AT TIME ZONE 'Asia/Ho_Chi_Minh')
         - make_interval(days => :history_days - 1)) AT TIME ZONE 'Asia/Ho_Chi_Minh') AS win_start
\gset

SELECT 7 * GREATEST(
           0,
           ceil(extract(epoch FROM (:'now_bucket'::timestamptz - :'sim_end'::timestamptz)) / 604800)
       )::integer AS shift_days
\gset

SELECT (:'win_start'::timestamptz - make_interval(days => :shift_days)) < :'sim_start'::timestamptz
       AS too_short
\gset

\echo '  CSV:' :sim_rows 'dòng,' :sim_start '->' :sim_end
\echo '  Cửa sổ nạp:' :win_start '->' :now_bucket '(dịch' :shift_days 'ngày)'

\if :too_short
    \echo 'LỖI: dữ liệu simulator không đủ' :history_days 'ngày trước' :now_bucket
    \echo '     (bắt đầu từ' :sim_start '). Sinh lại simulator với khoảng ngày dài hơn.'
    SELECT 1 / 0;
\endif

-- Tạo partition tháng cho cửa sổ nạp và tháng kế tiếp, trước khi chèn dữ liệu.
\o /dev/null
SELECT public.ensure_month_partition(parent, month::date)
FROM (VALUES ('public.station_occupancy_5m'::regclass),
             ('public.port_status_history'::regclass)) AS parents(parent)
CROSS JOIN generate_series(
    date_trunc('month', :'win_start'::timestamptz AT TIME ZONE 'UTC'),
    date_trunc('month', :'now_bucket'::timestamptz AT TIME ZONE 'UTC') + interval '1 month',
    interval '1 month'
) AS month;
\o

INSERT INTO public.station_occupancy_5m
    (station_id, bucket_at, total_ports, operational_ports, occupied_ports)
SELECT s.station_id,
       s.bucket_at + make_interval(days => :shift_days),
       s.total_ports,
       s.operational_ports,
       s.occupied_ports
FROM sim_stage s
WHERE s.bucket_at + make_interval(days => :shift_days)
      BETWEEN :'win_start'::timestamptz AND :'now_bucket'::timestamptz;

SELECT count(*) AS loaded FROM public.station_occupancy_5m \gset
\echo '  Đã nạp' :loaded 'dòng vào station_occupancy_5m'

-- Trạng thái hiện tại của trạm KHÔNG cần ghi thêm: view station_status_current đọc bucket mới nhất
-- của station_occupancy_5m vừa nạp ở trên. port_status giữ nguyên (seed 'unknown').

SELECT public.refresh_station_occupancy_profile(:history_days) AS profile_cells \gset
\echo '  Bảng trung bình:' :profile_cells 'ô (trạm x thứ x bước 5 phút)'

COMMIT;

ANALYZE public.station_occupancy_5m;
ANALYZE public.station_occupancy_profile;
