#!/bin/sh
# Tạo schema rồi nạp seed (catalog, xe, trạng thái cổng ban đầu, slot dự báo) theo database/tables.toml.
# Chạy trong /docker-entrypoint-initdb.d dưới quyền superuser. Có thể được thực thi hoặc `source`,
# nên toàn bộ nằm trong subshell và trạng thái thoát của nó là trạng thái của script.
(
set -eu

PLAN=/tmp/manifest.plan
PSQL="psql -v ON_ERROR_STOP=1 --quiet --username $POSTGRES_USER --dbname $POSTGRES_DB"

awk -f /docker/manifest-plan.awk /db/tables.toml > "$PLAN"
[ -s "$PLAN" ] || { echo "ERROR: không đọc được kế hoạch từ /db/tables.toml" >&2; exit 1; }

apply_file() {
    $PSQL --single-transaction -f "$1"
    echo "  ok  ${1#/db/}"
}

echo "== Schema =="
while read -r kind a b c d; do
    case "$kind" in
        BASE|VIEW) apply_file "/db/schema/$a.sql" ;;
        TABLE) apply_file "/db/schema/$b/$a.sql" ;;
    esac
done < "$PLAN"

echo "== Seed =="
while read -r kind a b c d; do
    [ "$kind" = "TABLE" ] || continue
    case "$c" in
        sql) apply_file "/db/data/$b/$a.sql" ;;
        csv)
            file="/db/bulk/$a.csv"
            columns=$(head -n 1 "$file" | tr -d '\r' | sed 's/[^,]*/"&"/g')
            $PSQL --single-transaction \
                -c "\copy public.$a ($columns) FROM '$file' WITH (FORMAT csv, HEADER true)"
            echo "  ok  ${file#/db/}"
            ;;
    esac
done < "$PLAN"

echo "== Đối chiếu số dòng với tables.toml =="
bad=0
while read -r kind a b c d; do
    [ "$kind" = "TABLE" ] || continue
    actual=$($PSQL -tA -c "SELECT count(*) FROM public.$a")
    if [ "$actual" != "$d" ]; then
        echo "  FAIL $a: kỳ vọng $d, thực tế $actual" >&2
        bad=1
    fi
done < "$PLAN"
[ "$bad" = "0" ] || { echo "ERROR: số dòng không khớp tables.toml" >&2; exit 1; }
echo "  ok  mọi bảng khớp tables.toml"
)
