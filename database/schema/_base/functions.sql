-- Hàm dùng chung. Thân hàm plpgsql được kiểm tra lúc chạy, nên có thể tham chiếu bảng tạo sau.

-- Trigger: tự cập nhật cột updated_at khi UPDATE.
CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- Tạo (nếu chưa có) partition tháng của một bảng history, tên `<bảng>_YYYY_MM`, biên theo UTC.
-- Idempotent. Phải gọi TRƯỚC khi chèn dữ liệu của tháng đó, nếu không dòng sẽ rơi vào partition
-- DEFAULT và việc tạo partition tháng sau đó sẽ lỗi.
CREATE FUNCTION public.ensure_month_partition(p_parent regclass, p_month date) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_start date := date_trunc('month', p_month::timestamp)::date;
    v_name  text := (SELECT relname FROM pg_class WHERE oid = p_parent)
                    || '_' || to_char(v_start, 'YYYY_MM');
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
        v_name,
        p_parent,
        v_start::timestamp AT TIME ZONE 'UTC',
        (v_start + interval '1 month')::timestamp AT TIME ZONE 'UTC'
    );
    RETURN v_name;
END;
$$;

-- Trạng thái trạm TẠI thời điểm p_at: lấy bucket mới nhất của station_occupancy_5m có
-- bucket_at <= p_at. Cùng cột và cùng quy tắc với view station_status_current (view chính là
-- station_status_at(now())), dùng để xem lại một thời điểm bất kỳ của dữ liệu đã nạp.
--
--   total_ports       số cổng active của catalog
--   operational_ports cổng hoạt động báo trong bucket (không vượt total_ports)
--   occupied_ports    cổng đang dùng (không vượt operational_ports)
--   available_ports   operational - occupied;  offline_ports = total - operational
--   unknown_ports     = total_ports khi trạm CHƯA có bucket nào (<= p_at), ngược lại 0
-- Độ cũ của bucket (reported_at so với p_at) do backend đánh giá lúc đọc.
CREATE FUNCTION public.station_status_at(p_at timestamptz) RETURNS TABLE (
    station_id        uuid,
    station_code      text,
    total_ports       integer,
    operational_ports integer,
    occupied_ports    integer,
    available_ports   integer,
    offline_ports     integer,
    unknown_ports     integer,
    occupancy_ratio   numeric,
    queue_length      integer,
    reported_at       timestamptz
)
    LANGUAGE plpgsql STABLE
    AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    WITH latest AS (
        SELECT
            s.id AS l_station_id,
            s.code AS l_station_code,
            COALESCE(pc.n_ports, 0) AS l_total_ports,
            o.bucket_at AS l_bucket_at,
            o.operational_ports AS l_reported_operational,
            o.occupied_ports AS l_reported_occupied,
            o.queue_length AS l_queue_length
        FROM public.stations s
        LEFT JOIN (
            SELECT p.station_id, count(*)::integer AS n_ports
            FROM public.ports p
            WHERE p.is_active
            GROUP BY p.station_id
        ) pc ON pc.station_id = s.id
        LEFT JOIN LATERAL (
            SELECT b.bucket_at, b.operational_ports, b.occupied_ports, b.queue_length
            FROM public.station_occupancy_5m b
            WHERE b.station_id = s.id AND b.bucket_at <= p_at
            ORDER BY b.bucket_at DESC
            LIMIT 1
        ) o ON true
    ), capped AS (
        SELECT
            l.*,
            CASE
                WHEN l.l_bucket_at IS NULL THEN 0
                ELSE LEAST(l.l_reported_operational, l.l_total_ports)::integer
            END AS c_operational
        FROM latest l
    )
    SELECT
        c.l_station_id,
        c.l_station_code,
        c.l_total_ports,
        c.c_operational,
        CASE
            WHEN c.l_bucket_at IS NULL THEN 0
            ELSE LEAST(c.l_reported_occupied, c.c_operational)::integer
        END,
        CASE
            WHEN c.l_bucket_at IS NULL THEN 0
            ELSE c.c_operational - LEAST(c.l_reported_occupied, c.c_operational)::integer
        END,
        CASE
            WHEN c.l_bucket_at IS NULL THEN 0
            ELSE c.l_total_ports - c.c_operational
        END,
        CASE WHEN c.l_bucket_at IS NULL THEN c.l_total_ports ELSE 0 END,
        CASE
            WHEN c.c_operational = 0 THEN NULL
            ELSE LEAST(c.l_reported_occupied, c.c_operational)::numeric / c.c_operational
        END,
        c.l_queue_length::integer,
        c.l_bucket_at
    FROM capped c;
END;
$$;

-- Tính lại bảng trung bình station_occupancy_profile từ station_occupancy_5m.
-- Lấy p_days ngày LỊCH địa phương gần nhất tính tới p_now (cả ngày của p_now, đang dở); chỉ dùng
-- bucket <= p_now để xem lại một thời điểm trong quá khứ không rò rỉ dữ liệu tương lai. Bỏ bucket có
-- operational_ports = 0 (ratio không xác định). Trả về số ô (trạm × thứ × bước) đã ghi.
--   day_of_week: 0 = Thứ Hai … 6 = Chủ nhật; step_time: 0..287 = (giờ*60 + phút)/5, giờ địa phương.
CREATE FUNCTION public.refresh_station_occupancy_profile(
    p_days integer DEFAULT 30,
    p_timezone text DEFAULT 'Asia/Ho_Chi_Minh',
    p_now timestamptz DEFAULT now()
) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_run   timestamptz := clock_timestamp();
    v_start timestamptz;
    v_count integer;
BEGIN
    IF p_days < 1 THEN
        RAISE EXCEPTION 'p_days must be >= 1, got %', p_days;
    END IF;
    v_start := (date_trunc('day', p_now AT TIME ZONE p_timezone)
                - make_interval(days => p_days - 1)) AT TIME ZONE p_timezone;

    WITH src AS (
        SELECT o.station_id,
               EXTRACT(ISODOW FROM o.bucket_at AT TIME ZONE p_timezone)::integer - 1 AS dow,
               EXTRACT(HOUR FROM o.bucket_at AT TIME ZONE p_timezone)::integer * 12
                   + EXTRACT(MINUTE FROM o.bucket_at AT TIME ZONE p_timezone)::integer / 5 AS step,
               o.occupied_ports::numeric / o.operational_ports AS ratio
        FROM public.station_occupancy_5m o
        WHERE o.operational_ports > 0 AND o.bucket_at >= v_start AND o.bucket_at <= p_now
    ), station_mean AS (
        SELECT station_id, avg(ratio) AS mean_ratio FROM src GROUP BY station_id
    ), cells AS (
        SELECT station_id, dow, step, count(*) AS n, avg(ratio) AS mean_ratio
        FROM src
        GROUP BY station_id, dow, step
    )
    INSERT INTO public.station_occupancy_profile
        (station_id, day_of_week, step_time, sample_count, mean_ratio, station_mean_ratio,
         computed_at)
    SELECT c.station_id, c.dow, c.step, c.n, round(c.mean_ratio, 6), round(m.mean_ratio, 6), v_run
    FROM cells c
    JOIN station_mean m USING (station_id)
    ON CONFLICT (station_id, day_of_week, step_time) DO UPDATE SET
        sample_count       = EXCLUDED.sample_count,
        mean_ratio         = EXCLUDED.mean_ratio,
        station_mean_ratio = EXCLUDED.station_mean_ratio,
        computed_at        = EXCLUDED.computed_at;
    GET DIAGNOSTICS v_count = ROW_COUNT;

    DELETE FROM public.station_occupancy_profile WHERE computed_at < v_run;  -- ô không còn mẫu
    RETURN v_count;
END;
$$;
