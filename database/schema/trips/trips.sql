-- trips.trips — nhật ký mỗi lần người dùng bấm "Chỉ đường" (chuyển sang Google Maps), ẩn danh.
-- Mỗi dòng so sánh trạm hệ thống đề xuất tốt nhất (hạng 1) với trạm người dùng thực sự chọn.
-- destination là NULL khi mode = find_station (chỉ có điểm bắt đầu).
-- created_at do backend ghi theo demo clock.

CREATE TABLE public.trips (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mode                   text NOT NULL,                  -- find_station | route
    vehicle_model_id       uuid NOT NULL REFERENCES public.vehicle_models(id),
    origin                 geography(Point, 4326) NOT NULL,
    destination            geography(Point, 4326),         -- null khi mode = find_station
    start_battery_pct      numeric(5, 2) NOT NULL,
    recommended_station_id uuid REFERENCES public.stations(id) ON DELETE SET NULL,  -- hạng 1 hệ thống đề xuất
    actual_station_id      uuid REFERENCES public.stations(id) ON DELETE SET NULL,  -- trạm người dùng bấm Chỉ đường
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_trips_mode CHECK (mode IN ('find_station', 'route')),
    CONSTRAINT ck_trips_start_battery CHECK (start_battery_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_trips_destination_matches_mode CHECK (
        (mode = 'find_station' AND destination IS NULL)
        OR (mode = 'route' AND destination IS NOT NULL)
    )
);

CREATE INDEX ix_trips_vehicle_created ON public.trips (vehicle_model_id, created_at);
CREATE INDEX ix_trips_actual_station_created ON public.trips (actual_station_id, created_at);
CREATE INDEX ix_trips_recommended_station_created ON public.trips (recommended_station_id, created_at);
