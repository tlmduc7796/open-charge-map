-- Extension PostgreSQL mà schema cần. Chạy đầu tiên.
--   postgis  : kiểu geography/geometry, chỉ mục GIST, ST_DWithin cho lọc trạm theo hành lang.
--   pgcrypto : gen_random_uuid() cho các khóa tự sinh.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
