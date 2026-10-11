-- vehicles.vehicle_models: 1 row (VF 5 Plus only in the current seed).
-- The vehicle_models table remains available for future catalog expansion.

INSERT INTO public.vehicle_models (id, code, brand, model, variant, model_year, market, battery_kwh, consumption_kwh_per_100km, max_ac_kw, max_dc_kw, is_active) VALUES
    ('cb41a9d0-94eb-5232-9ce1-2a3fd71011b2', 'EV_VF5_PLUS', 'VinFast', 'VF 5', 'Plus', NULL, 'VN', 37.23, 11.420, 6.60, 50.00, true);
