-- config.app_config — cấu hình key/value chỉnh được mà không cần phát hành lại
-- (ngưỡng re-plan, bán kính gần trạm, cửa sổ planned-arrival...). Không có khóa ngoại.

CREATE TABLE public.app_config (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_app_config_key_nonempty CHECK (char_length(trim(key)) > 0)
);
