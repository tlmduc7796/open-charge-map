-- vehicles.vehicle_connectors — chuẩn cổng mà mỗi mẫu xe sạc được (quan hệ n–n).

CREATE TABLE public.vehicle_connectors (
    vehicle_model_id uuid NOT NULL REFERENCES public.vehicle_models(id) ON DELETE CASCADE,
    connector_code   text NOT NULL REFERENCES public.connector_types(code),
    CONSTRAINT pk_vehicle_connectors PRIMARY KEY (vehicle_model_id, connector_code)
);
