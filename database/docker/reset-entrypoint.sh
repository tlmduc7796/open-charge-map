#!/bin/sh
# Entrypoint bọc ngoài docker-entrypoint.sh của image postgres.
#
# Mặc định (RESET_ON_START=1) xoá sạch nội dung PGDATA trước khi khởi động. Entrypoint chính thức
# thấy thư mục rỗng nên chạy lại initdb và mọi script trong /docker-entrypoint-initdb.d — nghĩa là
# MỖI lần container khởi động (up --force-recreate, restart, start) database được dựng lại từ đầu.
# Đặt RESET_ON_START=0 để giữ dữ liệu giữa các lần khởi động.
set -eu

PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ "${RESET_ON_START:-1}" = "1" ]; then
    if [ -d "$PGDATA" ]; then
        echo "[reset] RESET_ON_START=1: xoá dữ liệu trong $PGDATA"
        find "$PGDATA" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    fi
else
    echo "[reset] RESET_ON_START=0: giữ nguyên dữ liệu trong $PGDATA"
fi

exec docker-entrypoint.sh "$@"
