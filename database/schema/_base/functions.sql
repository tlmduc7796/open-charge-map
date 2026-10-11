-- Hàm trigger dùng chung: tự cập nhật cột updated_at khi UPDATE.

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;
