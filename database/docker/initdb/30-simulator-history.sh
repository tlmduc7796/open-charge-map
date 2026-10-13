#!/bin/sh
# Nạp nguyên file CSV occupancy (tháng 9 + tháng 10/2026) vào station_occupancy_5m một lần lúc
# initdb. Xem docker/sql/load_history.sql.
#
#   HISTORY_REQUIRED=1 (mặc định): bắt buộc nạp CSV khớp đúng catalog hiện tại; thiếu file hoặc dữ
#                                  liệu không khớp (station_id không tồn tại) thì dừng container.
#   HISTORY_REQUIRED=0           : bỏ qua hẳn bước nạp lịch sử (kể cả khi CSV tồn tại), tiếp tục với
#                                  station_occupancy_5m rỗng. Dùng khi catalog và CSV demo đang lệch
#                                  nhau (vd. đang sửa dở danh sách trạm) và chưa cần dữ liệu lịch sử.
(
set -eu

CSV="${HISTORY_CSV:-/sim/station_occupancy_5m.csv}"

echo "== Lịch sử occupancy từ CSV =="
if [ "${HISTORY_REQUIRED:-1}" = "0" ]; then
    echo "WARNING: HISTORY_REQUIRED=0, bỏ qua nạp lịch sử occupancy (station_occupancy_5m sẽ rỗng)" >&2
    exit 0
fi

if [ ! -f "$CSV" ]; then
    echo "  Không thấy $CSV" >&2
    echo "  CSV tháng 9-10 nằm trong git: database/fixtures/simulator/station_occupancy_5m.csv" >&2
    echo "  (tạo lại từ simulator: python scripts/trim_occupancy_csv.py --months 9 10 --year 2026)" >&2
    echo "ERROR: thiếu dữ liệu lịch sử (đặt HISTORY_REQUIRED=0 để bỏ qua)" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v csv_path="$CSV" -f /docker/sql/load_history.sql
)
