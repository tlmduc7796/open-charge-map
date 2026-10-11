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

-- Tính lại bảng trung bình station_occupancy_profile từ station_occupancy_5m.
-- Lấy p_days ngày LỊCH địa phương gần nhất, tính cả ngày hôm nay (đang dở); bỏ bucket có
-- operational_ports = 0 (ratio không xác định). Trả về số ô (trạm × thứ × bước) đã ghi.
--   day_of_week: 0 = Thứ Hai … 6 = Chủ nhật; step_time: 0..287 = (giờ*60 + phút)/5, giờ địa phương.
CREATE FUNCTION public.refresh_station_occupancy_profile(
    p_days integer DEFAULT 30,
    p_timezone text DEFAULT 'Asia/Ho_Chi_Minh'
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
    v_start := (date_trunc('day', now() AT TIME ZONE p_timezone)
                - make_interval(days => p_days - 1)) AT TIME ZONE p_timezone;

    WITH src AS (
        SELECT o.station_id,
               EXTRACT(ISODOW FROM o.bucket_at AT TIME ZONE p_timezone)::integer - 1 AS dow,
               EXTRACT(HOUR FROM o.bucket_at AT TIME ZONE p_timezone)::integer * 12
                   + EXTRACT(MINUTE FROM o.bucket_at AT TIME ZONE p_timezone)::integer / 5 AS step,
               o.occupied_ports::numeric / o.operational_ports AS ratio
        FROM public.station_occupancy_5m o
        WHERE o.operational_ports > 0 AND o.bucket_at >= v_start
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
