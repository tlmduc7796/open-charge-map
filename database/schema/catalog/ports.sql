-- catalog.ports — cổng sạc vật lý của trạm (chuẩn, công suất tối đa).
-- `label` là nhãn dự án ổn định, không phải mã do nhà vận hành cấp.

CREATE TABLE public.ports (
    id             uuid PRIMARY KEY,
    station_id     uuid NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    connector_code text NOT NULL REFERENCES public.connector_types(code),
    external_id    text,
    label          text NOT NULL,
    max_power_kw   numeric(8, 2) NOT NULL,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ports_station_label UNIQUE (station_id, label),
    CONSTRAINT ck_ports_positive_power CHECK (max_power_kw > 0),
    CONSTRAINT ck_ports_label_nonempty CHECK (char_length(trim(label)) > 0)
);

CREATE INDEX ix_ports_station_id ON public.ports (station_id);

CREATE TRIGGER ports_set_updated_at BEFORE UPDATE ON public.ports
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
