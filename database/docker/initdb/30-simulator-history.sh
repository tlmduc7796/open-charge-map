#!/bin/sh
# Nạp HISTORY_DAYS ngày lịch sử occupancy từ simulator, tính bảng trung bình theo (trạm, thứ, bước)
# và đặt trạng thái cổng ban đầu khớp bucket cuối cùng. Xem docker/sql/load_history.sql.
#
#   HISTORY_REQUIRED=1 (mặc định): thiếu file CSV thì dừng container với thông báo rõ.
#   HISTORY_REQUIRED=0           : cảnh báo rồi tiếp tục với lịch sử rỗng.
(
set -eu

CSV="${HISTORY_CSV:-/sim/station_occupancy_5m.csv}"
DAYS="${HISTORY_DAYS:-30}"

echo "== Lịch sử từ simulator ($DAYS ngày) =="
if [ ! -f "$CSV" ]; then
    echo "  Không thấy $CSV" >&2
    echo "  Sinh dữ liệu trước:  cd simulator && python -m script run && python -m script occupancy" >&2
    if [ "${HISTORY_REQUIRED:-1}" = "1" ]; then
        echo "ERROR: thiếu dữ liệu lịch sử (đặt HISTORY_REQUIRED=0 để bỏ qua)" >&2
        exit 1
    fi
    echo "WARNING: HISTORY_REQUIRED=0, tiếp tục với station_occupancy_5m rỗng" >&2
    exit 0
fi

psql -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v csv_path="$CSV" -v history_days="$DAYS" -f /docker/sql/load_history.sql
)
