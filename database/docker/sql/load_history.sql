-- Nạp NGUYÊN file CSV occupancy (tháng 9 + tháng 10/2026) vào station_occupancy_5m.
-- Chạy bởi docker/initdb/30-simulator-history.sh bằng superuser.
--
-- Biến psql:  csv_path  đường dẫn CSV trong container (cột như bảng, trừ id và queue_length)
--
-- Không neo theo giờ máy, không dịch ngày, không cắt "tương lai": mọi bucket trong CSV được nạp đúng
-- thời điểm của nó. Backend dùng đồng hồ demo (PUT /api/v1/demo-clock) để chọn "bây giờ" nằm trong
-- khoảng dữ liệu này và chỉ đọc bucket <= thời điểm đó.
--
-- Bảng trung bình station_occupancy_profile KHÔNG tính ở đây: nó phụ thuộc thời điểm demo nên backend
-- tự tính (refresh_station_occupancy_profile(..., p_now)) lúc khởi động và mỗi lần đổi giờ.

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

\echo '  CSV:' :sim_rows 'dòng,' :sim_start '->' :sim_end

-- Tạo partition tháng (biên UTC) cho cả khoảng dữ liệu TRƯỚC khi chèn: dòng rơi vào partition
-- DEFAULT sẽ làm việc tạo partition tháng đó sau này bị lỗi.
\o /dev/null
SELECT public.ensure_month_partition(parent, month::date)
FROM (VALUES ('public.station_occupancy_5m'::regclass),
             ('public.port_status_history'::regclass)) AS parents(parent)
CROSS JOIN generate_series(
    date_trunc('month', :'sim_start'::timestamptz AT TIME ZONE 'UTC'),
    date_trunc('month', :'sim_end'::timestamptz AT TIME ZONE 'UTC'),
    interval '1 month'
) AS month;
\o

INSERT INTO public.station_occupancy_5m
    (station_id, bucket_at, total_ports, operational_ports, occupied_ports)
SELECT s.station_id, s.bucket_at, s.total_ports, s.operational_ports, s.occupied_ports
FROM sim_stage s;

SELECT count(*) AS loaded FROM public.station_occupancy_5m \gset
\echo '  Đã nạp' :loaded 'dòng vào station_occupancy_5m'

-- Phải nạp đủ: lệch nghĩa là có dòng bị bỏ (trạm không tồn tại gây lỗi FK nên không tới đây) hoặc
-- bảng đã có sẵn dữ liệu trước lần nạp này.
SELECT (:loaded::bigint <> :sim_rows::bigint) AS count_mismatch
\gset
\if :count_mismatch
    \echo 'LỖI: số dòng nạp' :loaded 'khác số dòng CSV' :sim_rows
    SELECT 1 / 0;
\endif

-- Trạng thái hiện tại của trạm KHÔNG cần ghi thêm: backend đọc bucket mới nhất <= "bây giờ" của
-- station_occupancy_5m qua hàm station_status_at. port_status giữ nguyên (seed 'unknown').

COMMIT;

ANALYZE public.station_occupancy_5m;
