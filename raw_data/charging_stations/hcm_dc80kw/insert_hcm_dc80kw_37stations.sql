-- 37 trạm sạc mô phỏng thuộc 9 phường.
-- operator_name = VinFast; UUID v5 cố định theo mã EVC.
-- created_at và updated_at sử dụng DEFAULT now().
BEGIN;

INSERT INTO public.stations (
    id, code, name, address, operator_name, location,
    opening_hours, access_level, access_note, is_active
) VALUES
    ('dde84d85-db0d-58e1-8fe9-3e75afa214f3', 'EVC-162', 'EVC-162', 'Điểm sạc EVC-162, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.701775 10.778628)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('addcf910-1244-5a01-8c8b-3b8952a26daa', 'EVC-163', 'EVC-163', 'Điểm sạc EVC-163, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.701744 10.778729)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('0928e317-a723-5bcc-b13b-43491dd7631a', 'EVC-176', 'EVC-176', 'Điểm sạc EVC-176, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.699974 10.787862)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('04f177d1-6b74-5cae-8dee-3e0a5c67c8b5', 'EVC-555', 'EVC-555', 'Điểm sạc EVC-555, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.700569636794 10.7818168586808)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('da9e7c0d-9372-5f96-bdd3-862ecb3e9f86', 'EVC-561', 'EVC-561', 'Điểm sạc EVC-561, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.703693475358 10.7851876192925)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('d2358036-158a-56dd-8d39-240156846f1a', 'EVC-563', 'EVC-563', 'Điểm sạc EVC-563, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.704523661146 10.786489336094)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('d4c25994-56e9-59f3-97e8-72acff325f1c', 'EVC-145', 'EVC-145', 'Điểm sạc EVC-145, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.695198 10.7707)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('49b75eb0-8d0a-5a65-b742-a1900f9d3f20', 'EVC-147', 'EVC-147', 'Điểm sạc EVC-147, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.696243 10.771157)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('c0a039c8-d4f5-566f-91ff-c4f8faf86770', 'EVC-151', 'EVC-151', 'Điểm sạc EVC-151, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.694786 10.773301)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('76128b54-c33a-58fe-ac6b-163a39ca4d49', 'EVC-160', 'EVC-160', 'Điểm sạc EVC-160, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.693748 10.776787)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('bada00f0-1013-56cd-aafe-1ffc823fb1a5', 'EVC-536', 'EVC-536', 'Điểm sạc EVC-536, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.692068448788 10.7648682702448)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('cc6b3af8-1ed6-5173-b340-103bacbec611', 'EVC-171', 'EVC-171', 'Điểm sạc EVC-171, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.69326 10.78681)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('bf3cddfe-d5b3-57ae-825e-62a192ca23db', 'EVC-178', 'EVC-178', 'Điểm sạc EVC-178, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.685471 10.78867)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('804f8e3d-8cd2-502c-a2f1-ea11affa9513', 'EVC-545', 'EVC-545', 'Điểm sạc EVC-545, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.687167640109 10.7749425113168)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('893197e9-9b8d-57f6-9cfb-25fa1c5df884', 'EVC-556', 'EVC-556', 'Điểm sạc EVC-556, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.697485695075 10.7832796090896)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('719fecfc-3c1c-5d0b-bd3d-4608e370f783', 'EVC-560', 'EVC-560', 'Điểm sạc EVC-560, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.690770915871 10.7849583638799)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('e8940e49-90ca-5821-b828-ac9b10cfc329', 'EVC-172', 'EVC-172', 'Điểm sạc EVC-172, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.696068 10.78683)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('8d46fba5-47c5-54be-9859-f5ee53d15131', 'EVC-174', 'EVC-174', 'Điểm sạc EVC-174, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.692787 10.787368)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('41ab2645-6e04-50b1-a2bd-7e0f453b14ba', 'EVC-568', 'EVC-568', 'Điểm sạc EVC-568, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.687403853878 10.7936609336744)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('0bae5d3f-d976-5b35-a59e-90e937fe3cc7', 'EVC-191', 'EVC-191', 'Điểm sạc EVC-191, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.675323 10.79373)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('e7fa9ea4-0f8d-5708-a293-81295014b981', 'EVC-570', 'EVC-570', 'Điểm sạc EVC-570, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.672140713471 10.7974117144045)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('a806ce23-b40f-5f7c-98fd-e19b7d77b1b6', 'EVC-235', 'EVC-235', 'Điểm sạc EVC-235, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.712288 10.811754)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('39d59079-c2e4-5a19-8b22-4b391de5a7dc', 'EVC-239', 'EVC-239', 'Điểm sạc EVC-239, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.710152 10.814146)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('45f96caf-e5fc-5a72-b63b-947c4a032ed4', 'EVC-203', 'EVC-203', 'Điểm sạc EVC-203, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.665123 10.799711)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('636de045-5c00-52ff-8c37-58a6076e465c', 'EVC-207', 'EVC-207', 'Điểm sạc EVC-207, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.665916 10.80058)'), '"07:00 - 22:00"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('32b1093c-a7e1-5956-9baf-08d78cefddb2', 'EVC-218', 'EVC-218', 'Điểm sạc EVC-218, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.667511 10.805397)'), '"05:30 - 20:00"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('bbd21e0c-4f17-525c-9afa-d439cbf47697', 'EVC-194', 'EVC-194', 'Điểm sạc EVC-194, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.720329 10.793915)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('a3a1e19d-6212-5940-a2ed-02d40ae6b0f7', 'EVC-196', 'EVC-196', 'Điểm sạc EVC-196, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.722038 10.794848)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('8ac43470-9e4a-5182-be6e-3fa7a3b41f8f', 'EVC-198', 'EVC-198', 'Điểm sạc EVC-198, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.722412 10.79518)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('faa003bc-f57e-5b2d-b8f5-ea51fda79f23', 'EVC-201', 'EVC-201', 'Điểm sạc EVC-201, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.721497 10.79693)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('643cc09f-fd46-529a-8a39-39696719ff6a', 'EVC-565', 'EVC-565', 'Điểm sạc EVC-565, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.708291968237 10.7891146275633)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('e7aeb0c9-2e06-583b-8b74-a92d4658d5cb', 'EVC-569', 'EVC-569', 'Điểm sạc EVC-569, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.71968 10.796318)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('611c17fd-2e31-5384-9f9b-53e7c962a879', 'EVC-572', 'EVC-572', 'Điểm sạc EVC-572, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.717766649035 10.8001846764198)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('bf449b97-6cc2-5d14-89dc-93d21367f140', 'EVC-573', 'EVC-573', 'Điểm sạc EVC-573, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.71778895 10.80025603)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('943d27e6-7ff9-5a89-a7c0-d302affedab9', 'EVC-251', 'EVC-251', 'Điểm sạc EVC-251, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.732712 10.823867)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('57cc52a0-a91f-52d2-b0c9-5544e2f442bb', 'EVC-263', 'EVC-263', 'Điểm sạc EVC-263, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.742584 10.831631)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true),
    ('e97a5e54-7739-5d9c-ac31-23f6e7b50e2c', 'EVC-600', 'EVC-600', 'Điểm sạc EVC-600, Thành phố Hồ Chí Minh', 'VinFast', ST_GeogFromText('SRID=4326;POINT(106.730634965615 10.8231890719254)'), '"24/7"'::jsonb, 'public', 'Dữ liệu mô phỏng', true);

COMMIT;
