-- vehicles.vehicle_models: 18 dòng, sắp theo order_by trong tables.toml.
-- Cột kiểm toán (created_at/updated_at/ingested_at) không xuất; DB tự điền lúc nạp.

INSERT INTO public.vehicle_models (id, code, brand, model, variant, model_year, market, battery_kwh, consumption_kwh_per_100km, max_ac_kw, max_dc_kw, is_active) VALUES
    ('2a9257ce-1690-5ab9-84fc-c38c84d75fc7', 'EC_VAN_VN', 'VinFast', 'EC Van', NULL, NULL, 'VN', 18.23, 10.417, NULL, 24.20, true),
    ('cb41a9d0-94eb-5232-9ce1-2a3fd71011b2', 'EV_VF5_PLUS', 'VinFast', 'VF 5', 'Plus', NULL, 'VN', 37.23, 11.420, 6.60, 50.00, true),
    ('4c0355cb-bf97-5d65-9952-5ea7227486a1', 'EV_VF7_ECO', 'VinFast', 'VF 7', 'Eco', NULL, 'VN', 59.60, 13.545, 7.20, 100.00, true),
    ('ec9805fa-acfe-544c-96fe-d80c0cd80e0e', 'HERIO_GREEN_VN', 'VinFast', 'Herio Green', NULL, NULL, 'VN', 37.23, 11.420, 6.60, 50.00, true),
    ('a2acd9b5-2d7d-5dc9-b975-1e56ac5a5a4a', 'LIMO_GREEN_VN', 'VinFast', 'Limo Green', NULL, NULL, 'VN', 60.13, 13.362, 6.90, 80.00, true),
    ('a77e153b-f28d-5773-acf7-b852b030efc7', 'MINIO_GREEN_VN', 'VinFast', 'Minio Green', NULL, NULL, 'VN', 18.30, 8.714, 3.30, 24.00, true),
    ('3730fc08-22ed-5351-8367-e09bb072c1bf', 'NERIO_GREEN_VN', 'VinFast', 'Nerio Green', NULL, NULL, 'VN', 41.90, 13.151, 6.60, 60.00, true),
    ('a517b448-e671-57b2-8824-5dfccca27914', 'VF3_ECO_VN', 'VinFast', 'VF 3', 'Eco', NULL, 'VN', 18.64, 8.670, NULL, 24.00, true),
    ('77f8b140-65e8-56cd-ad13-48da206ff572', 'VF3_PLUS_VN', 'VinFast', 'VF 3', 'Plus', NULL, 'VN', 18.64, 8.670, NULL, 24.00, true),
    ('fc322ae8-8e15-59df-935e-6caa89d70d72', 'VF6_ECO_VN', 'VinFast', 'VF 6', 'Eco', NULL, 'VN', 59.60, 12.289, 7.20, 100.00, true),
    ('970e1218-930e-58a9-9966-c737a16f7655', 'VF6_PLUS_VN', 'VinFast', 'VF 6', 'Plus', NULL, 'VN', 59.60, 12.957, 7.20, 100.00, true),
    ('3b80cf3f-9a11-5634-a5d1-9d59058cf53b', 'VF7_PLUS_AWD_VN', 'VinFast', 'VF 7', 'Plus AWD', NULL, 'VN', 70.00, 14.925, 7.20, 110.00, true),
    ('dd3abd87-33bc-5afa-851f-a20d1f8e6cc4', 'VF7_PLUS_FWD_VN', 'VinFast', 'VF 7', 'Plus FWD', NULL, 'VN', 70.00, 13.986, 7.20, 110.00, true),
    ('d2af7679-ff3e-5e5b-b235-7b91b200fb17', 'VF8_ECO_VN', 'VinFast', 'VF 8', 'Eco', NULL, 'VN', 87.70, 13.811, 11.00, 149.00, true),
    ('041ef7fe-ecda-5b4d-8389-0cb065c3b658', 'VF8_PLUS_VN', 'VinFast', 'VF 8', 'Plus', NULL, 'VN', 87.70, 18.463, 11.00, 149.00, true),
    ('83afbf3f-6dac-5b37-8e82-8505448d9dfd', 'VF9_ECO_VN', 'VinFast', 'VF 9', 'Eco CATL', NULL, 'VN', 123.00, 19.649, 11.00, NULL, true),
    ('1f55361e-7dd1-5d6a-a02e-6a3bbf74c081', 'VF9_PLUS_VN', 'VinFast', 'VF 9', 'Plus CATL', NULL, 'VN', 123.00, 20.432, 11.00, NULL, true),
    ('125f9227-967f-5833-b97f-5dc29788dc53', 'VF_MPV7_VN', 'VinFast', 'VF MPV 7', NULL, NULL, 'VN', 60.13, 13.362, 6.90, 80.00, true);
