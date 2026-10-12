#!/bin/sh
# Nạp nguyên file CSV occupancy (tháng 9 + tháng 10/2026) vào station_occupancy_5m một lần lúc
# initdb. Xem docker/sql/load_history.sql.
#
#   HISTORY_REQUIRED=1 (mặc định): thiếu file CSV thì dừng container với thông báo rõ.
#   HISTORY_REQUIRED=0           : cảnh báo rồi tiếp tục với lịch sử rỗng.
(
set -eu

CSV="${HISTORY_CSV:-/sim/station_occupancy_5m.csv}"

echo "== Lịch sử occupancy từ CSV =="
if [ ! -f "$CSV" ]; then
    echo "  Không thấy $CSV" >&2
    echo "  CSV tháng 9-10 nằm trong git: database/fixtures/simulator/station_occupancy_5m.csv" >&2
    echo "  (tạo lại từ simulator: python scripts/trim_occupancy_csv.py --months 9 10 --year 2026)" >&2
    if [ "${HISTORY_REQUIRED:-1}" = "1" ]; then
        echo "ERROR: thiếu dữ liệu lịch sử (đặt HISTORY_REQUIRED=0 để bỏ qua)" >&2
        exit 1
    fi
    echo "WARNING: HISTORY_REQUIRED=0, tiếp tục với station_occupancy_5m rỗng" >&2
    exit 0
fi

psql -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v csv_path="$CSV" -f /docker/sql/load_history.sql
)
