-- catalog.stations — trạm sạc, một dòng mỗi trạm (dữ liệu tĩnh).
-- `code` là mã ổn định dùng trong backend/fixture (vd. ST_VF_LA_VELA).

CREATE TABLE public.stations (
    id            uuid PRIMARY KEY,
    code          text NOT NULL UNIQUE,
    name          text NOT NULL,
    address       text NOT NULL,
    operator_name text,
    location      geography(Point, 4326) NOT NULL,
    opening_hours jsonb,                       -- null/'null' = chưa rõ; "24/7"; {"always_open": true}
    access_level  public.access_level NOT NULL,
    access_note   text,
    is_active     boolean NOT NULL DEFAULT true,  -- false = ẩn khỏi bản đồ và gợi ý
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_stations_code_nonempty CHECK (char_length(trim(code)) > 0),
    CONSTRAINT ck_stations_name_nonempty CHECK (char_length(trim(name)) > 0)
);

CREATE INDEX ix_stations_location_gist ON public.stations USING gist (location);

CREATE TRIGGER stations_set_updated_at BEFORE UPDATE ON public.stations
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
