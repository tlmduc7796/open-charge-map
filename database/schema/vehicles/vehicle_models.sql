-- vehicles.vehicle_models — hồ sơ mẫu xe (pin, mức tiêu hao, công suất sạc tối đa).
-- Trường số để null khi hãng chưa công bố (backend dùng giả định mặc định). Xe giả lập có
-- market = 'DEMO'.

CREATE TABLE public.vehicle_models (
    id                        uuid PRIMARY KEY,
    code                      text NOT NULL UNIQUE,
    brand                     text NOT NULL,
    model                     text NOT NULL,
    variant                   text,
    model_year                smallint,
    market                    text NOT NULL,
    battery_kwh               numeric(8, 2),       -- dung lượng pin khả dụng
    consumption_kwh_per_100km numeric(8, 3),
    max_ac_kw                 numeric(8, 2),
    max_dc_kw                 numeric(8, 2),
    is_active                 boolean NOT NULL DEFAULT true,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_vehicle_models_code_nonempty CHECK (char_length(trim(code)) > 0),
    CONSTRAINT ck_vehicle_models_brand_nonempty CHECK (char_length(trim(brand)) > 0),
    CONSTRAINT ck_vehicle_models_model_nonempty CHECK (char_length(trim(model)) > 0),
    CONSTRAINT ck_vehicle_models_market_nonempty CHECK (char_length(trim(market)) > 0),
    CONSTRAINT ck_vehicle_models_year CHECK (model_year IS NULL OR model_year BETWEEN 2000 AND 2200),
    CONSTRAINT ck_vehicle_models_battery_positive CHECK (battery_kwh IS NULL OR battery_kwh > 0),
    CONSTRAINT ck_vehicle_models_consumption_positive
        CHECK (consumption_kwh_per_100km IS NULL OR consumption_kwh_per_100km > 0),
    CONSTRAINT ck_vehicle_models_ac_positive CHECK (max_ac_kw IS NULL OR max_ac_kw > 0),
    CONSTRAINT ck_vehicle_models_dc_positive CHECK (max_dc_kw IS NULL OR max_dc_kw > 0)
);

CREATE TRIGGER vehicle_models_set_updated_at BEFORE UPDATE ON public.vehicle_models
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
