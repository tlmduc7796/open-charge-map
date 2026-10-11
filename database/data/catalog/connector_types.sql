-- catalog.connector_types: 2 dòng, sắp theo order_by trong tables.toml.
-- Cột kiểm toán (created_at/updated_at/ingested_at) không xuất; DB tự điền lúc nạp.

INSERT INTO public.connector_types (code, display_name, current_type) VALUES
    ('CCS2', 'CCS2', 'DC'),
    ('TYPE2', 'Type2', 'AC');
