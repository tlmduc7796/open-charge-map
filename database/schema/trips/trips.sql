-- trips.trips — hành trình ẩn danh (không gắn người dùng). Truy cập bằng bearer token:
-- chỉ lưu SHA-256 của token trong auth_token_hash (64 ký tự hex).
-- route_version tăng mỗi lần đổi tuyến; declined_station_ids là các trạm đã từ chối.

CREATE TABLE public.trips (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mode                 text NOT NULL,                  -- find_station | route
    vehicle_model_id     uuid NOT NULL REFERENCES public.vehicle_models(id),
    origin               geography(Point, 4326) NOT NULL,
    destination          geography(Point, 4326),         -- null khi mode = find_station
    start_battery_pct    numeric(5, 2) NOT NULL,
    station_id           uuid REFERENCES public.stations(id) ON DELETE SET NULL,
    route                geography(LineString, 4326),
    route_version        integer NOT NULL DEFAULT 0,
    phase                text NOT NULL DEFAULT 'to_station',
    planned              jsonb NOT NULL DEFAULT '{}'::jsonb,   -- ETA từng đoạn lúc bắt đầu
    last_reroute_at      timestamptz,
    declined_station_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
    created_at           timestamptz NOT NULL DEFAULT now(),
    ended_at             timestamptz,
    auth_token_hash      text,
    CONSTRAINT ck_trips_mode CHECK (mode IN ('find_station', 'route')),
    CONSTRAINT ck_trips_phase CHECK (
        phase IN ('to_station', 'at_station', 'to_destination', 'arrived', 'cancelled')
    ),
    CONSTRAINT ck_trips_start_battery CHECK (start_battery_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_trips_route_version CHECK (route_version >= 0),
    CONSTRAINT ck_trips_destination_matches_mode CHECK (
        (mode = 'find_station' AND destination IS NULL)
        OR (mode = 'route' AND destination IS NOT NULL)
    ),
    CONSTRAINT ck_trips_end_after_create CHECK (ended_at IS NULL OR ended_at >= created_at),
    CONSTRAINT ck_trips_auth_token_hash_nonempty
        CHECK (auth_token_hash IS NULL OR char_length(auth_token_hash) = 64)
);

CREATE INDEX ix_trips_vehicle_created ON public.trips (vehicle_model_id, created_at);
CREATE INDEX ix_trips_station_created ON public.trips (station_id, created_at);
