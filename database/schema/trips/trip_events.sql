-- trips.trip_events — nhật ký sự kiện của hành trình (đổi tuyến, chấp nhận/từ chối trạm...).

CREATE TABLE public.trip_events (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id    uuid NOT NULL REFERENCES public.trips(id) ON DELETE CASCADE,
    type       text NOT NULL,
    payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_trip_events_type CHECK (
        type IN ('reroute', 'station_suggested', 'station_accepted', 'station_declined',
                 'battery_corrected', 'arrived_station', 'arrived', 'cancelled')
    )
);

CREATE INDEX ix_trip_events_trip_created ON public.trip_events (trip_id, created_at);
