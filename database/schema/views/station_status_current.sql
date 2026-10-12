-- views.station_status_current — trạng thái hiện tại của trạm, lấy từ bucket MỚI NHẤT của
-- history.station_occupancy_5m (số cổng đang dùng của trạm). Không cần biết cổng cụ thể nào đang
-- bận, nên port_status không tham gia.
-- Backend đọc view này (kiểm tra ở validate_database) cho "mới nhất theo giờ máy"; còn việc xem
-- trạng thái tại một thời điểm demo bất kỳ dùng hàm public.station_status_at(p_at) (xem
-- schema/_base/functions.sql), đây chỉ là station_status_at(now()).
--
--   total_ports       số cổng active của catalog
--   operational_ports cổng hoạt động báo trong bucket (không vượt total_ports)
--   occupied_ports    cổng đang dùng (không vượt operational_ports)
--   available_ports   operational - occupied
--   offline_ports     total - operational
--   unknown_ports     = total_ports khi trạm CHƯA có bucket nào, ngược lại 0
--
-- Trạm chưa có bucket: operational = occupied = available = offline = 0 và unknown = total.
-- Độ cũ của bucket (reported_at) do backend đánh giá lúc đọc. queue_length lấy từ bucket (có thể NULL).

CREATE VIEW public.station_status_current AS
SELECT
    station_id,
    station_code,
    total_ports,
    operational_ports,
    occupied_ports,
    available_ports,
    offline_ports,
    unknown_ports,
    occupancy_ratio,
    queue_length,
    reported_at
FROM public.station_status_at(now());
