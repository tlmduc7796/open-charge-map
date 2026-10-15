-- forecast.predictions — một dòng (slot) cho mỗi trạm × mốc dự báo 5–30 phút.
-- Seed chỉ tạo sẵn station_id và horizon_min; mọi giá trị dự báo để NULL cho tới khi backend
-- ghi (UPDATE tại chỗ, không lưu lịch sử các lượt chạy).
-- Ràng buộc chỉ kiểm tra khi giá trị đã có (NULL luôn hợp lệ).

CREATE TABLE public.predictions (
    station_id                uuid NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    horizon_min               smallint NOT NULL,
    run_at                    timestamptz,
    predicted_occupancy_ratio numeric(7, 6),
    operational_ports_at_run  smallint,
    wait_probability          numeric(7, 6),      -- P(W>0)
    mean_wait_minutes         numeric(8, 2),      -- E[W]
    p90_wait_minutes          numeric(8, 2),      -- W90
    prediction_source         public.prediction_source,
    model_version             text,
    updated_at                timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_predictions PRIMARY KEY (station_id, horizon_min),
    CONSTRAINT ck_predictions_supported_horizon CHECK (horizon_min IN (5, 10, 15, 20, 25, 30)),
    CONSTRAINT ck_predictions_operational_nonnegative
        CHECK (operational_ports_at_run IS NULL OR operational_ports_at_run >= 0),
    CONSTRAINT ck_predictions_occupancy_ratio
        CHECK (predicted_occupancy_ratio IS NULL OR predicted_occupancy_ratio BETWEEN 0 AND 1),
    CONSTRAINT ck_predictions_no_ratio_when_offline
        CHECK (operational_ports_at_run IS NULL OR operational_ports_at_run > 0
            OR predicted_occupancy_ratio IS NULL),
    CONSTRAINT ck_predictions_wait_probability
        CHECK (wait_probability IS NULL OR wait_probability BETWEEN 0 AND 1),
    CONSTRAINT ck_predictions_mean_wait_nonnegative
        CHECK (mean_wait_minutes IS NULL OR mean_wait_minutes >= 0),
    CONSTRAINT ck_predictions_p90_wait_nonnegative
        CHECK (p90_wait_minutes IS NULL OR p90_wait_minutes >= 0),
    CONSTRAINT ck_predictions_p90_after_mean CHECK (
        mean_wait_minutes IS NULL OR p90_wait_minutes IS NULL
        OR p90_wait_minutes >= mean_wait_minutes
    ),
    CONSTRAINT ck_predictions_model_version_nonempty
        CHECK (model_version IS NULL OR char_length(trim(model_version)) > 0)
);

CREATE TRIGGER predictions_set_updated_at BEFORE UPDATE ON public.predictions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
