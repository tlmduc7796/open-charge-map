-- history.station_occupancy_profile — occupancy trung bình của trạm theo (thứ trong tuần, bước 5 phút).
-- Bảng dẫn xuất: tính từ station_occupancy_5m bằng public.refresh_station_occupancy_profile(); có thể
-- xoá và tính lại bất cứ lúc nào. Dùng để dự báo xa hơn khung 30 phút khi mô hình ML không còn hiệu lực.
--
--   day_of_week: 0 = Thứ Hai … 6 = Chủ nhật (khớp ml/features.py), theo giờ Asia/Ho_Chi_Minh.
--   step_time:   0..287 = (giờ*60 + phút)/5 theo giờ Asia/Ho_Chi_Minh.
--   sample_count nhỏ (ví dụ 4 tuần → ~4 mẫu mỗi ô) nghĩa là mean_ratio nhiễu; station_mean_ratio
--   là giá trị kéo về khi làm mượt.

CREATE TABLE public.station_occupancy_profile (
    station_id         uuid NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    day_of_week        smallint NOT NULL,
    step_time          smallint NOT NULL,
    sample_count       integer NOT NULL,
    mean_ratio         numeric(7, 6) NOT NULL,
    station_mean_ratio numeric(7, 6) NOT NULL,
    computed_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_station_occupancy_profile PRIMARY KEY (station_id, day_of_week, step_time),
    CONSTRAINT ck_profile_day_of_week CHECK (day_of_week BETWEEN 0 AND 6),
    CONSTRAINT ck_profile_step_time CHECK (step_time BETWEEN 0 AND 287),
    CONSTRAINT ck_profile_sample_count CHECK (sample_count > 0),
    CONSTRAINT ck_profile_mean_ratio CHECK (mean_ratio BETWEEN 0 AND 1),
    CONSTRAINT ck_profile_station_mean_ratio CHECK (station_mean_ratio BETWEEN 0 AND 1)
);
