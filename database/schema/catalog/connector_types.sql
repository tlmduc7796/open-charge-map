-- catalog.connector_types — danh mục chuẩn cổng sạc (CCS2, TYPE2, GB/T...).
-- Được tham chiếu bởi ports và vehicle_connectors.

CREATE TABLE public.connector_types (
    code         text PRIMARY KEY,
    display_name text NOT NULL,
    current_type public.current_type NOT NULL,
    CONSTRAINT ck_connector_types_code_nonempty CHECK (char_length(trim(code)) > 0)
);
