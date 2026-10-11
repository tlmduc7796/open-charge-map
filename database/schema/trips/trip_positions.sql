-- trips.trip_positions — các ping GPS của hành trình; backend bỏ qua ping cũ/trùng.

CREATE TABLE public.trip_positions (
    trip_id     uuid NOT NULL REFERENCES public.trips(id) ON DELETE CASCADE,
    recorded_at timestamptz NOT NULL,
    location    geography(Point, 4326) NOT NULL,
    speed_kmh   numeric(8, 2),
    heading     numeric(6, 2),
    battery_pct numeric(5, 2),      -- pin ước tính
    distance_km numeric(10, 3),     -- quãng đường cộng dồn
    CONSTRAINT pk_trip_positions PRIMARY KEY (trip_id, recorded_at),
    CONSTRAINT ck_trip_positions_speed_nonnegative CHECK (speed_kmh IS NULL OR speed_kmh >= 0),
    CONSTRAINT ck_trip_positions_heading CHECK (heading IS NULL OR (heading >= 0 AND heading < 360)),
    CONSTRAINT ck_trip_positions_battery CHECK (battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_trip_positions_distance_nonnegative CHECK (distance_km IS NULL OR distance_km >= 0)
);
