-- Kiểu enum dùng chung. Thêm giá trị mới = sửa file này rồi tạo lại database.

-- Mức truy cập của trạm.
CREATE TYPE public.access_level AS ENUM ('public', 'customers', 'private', 'unknown');

-- Dòng điện của chuẩn cổng.
CREATE TYPE public.current_type AS ENUM ('AC', 'DC');

-- Trạng thái của một cổng sạc.
CREATE TYPE public.port_status_value AS ENUM ('available', 'charging', 'out_of_service', 'unknown');

-- Nguồn dự báo occupancy; 'default' dùng cho giá trị demo cố định trước khi tích hợp model.
CREATE TYPE public.prediction_source AS ENUM ('persistence', 'model', 'default');
