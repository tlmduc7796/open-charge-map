#!/bin/sh
set -eu

# CSV occupancy nằm trong git (database/fixtures/simulator) và được mount vào cả postgres lẫn feeder
# ở cùng đường dẫn /sim. Postgres đã nạp nó lúc initdb; feeder chỉ cần nó để phát lại vào backend.
CSV="${HISTORY_CSV:-/sim/station_occupancy_5m.csv}"

if [ ! -f "$CSV" ]; then
    echo "ERROR: thiếu $CSV (mount ./database/fixtures/simulator vào /sim)." >&2
    echo "Tạo lại bằng: python scripts/trim_occupancy_csv.py" >&2
    exit 1
fi
echo "== Dùng CSV occupancy: $CSV =="

history_rows=$(psql -tA -c 'SELECT count(*) FROM public.station_occupancy_5m')
if [ "$history_rows" -eq 0 ]; then
    # Bình thường initdb đã nạp; đây là đường dự phòng khi volume được tạo bởi lần chạy cũ.
    echo "== Nạp lịch sử occupancy vào PostgreSQL =="
    psql -v ON_ERROR_STOP=1 \
        -v csv_path="$CSV" \
        -v history_days="${HISTORY_DAYS:-30}" \
        -f /app/database/docker/sql/load_history.sql
else
    echo "== Đã có $history_rows dòng lịch sử occupancy; giữ nguyên =="
fi

touch /tmp/history-ready

echo "== Chờ backend rồi phát occupancy mỗi 5 phút =="
python - <<'PY'
import time
import urllib.error
import urllib.request

url = "http://backend:8000/health"
while True:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                break
    except (OSError, urllib.error.URLError):
        pass
    time.sleep(2)
PY

exec python -m script feed \
    --csv "$CSV" \
    --api-url "${FEED_API_URL:-http://backend:8000}" \
    --delay-s "${FEED_DELAY_S:-15}"
