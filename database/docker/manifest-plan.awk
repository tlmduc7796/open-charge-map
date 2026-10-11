# Đọc database/tables.toml và in kế hoạch nạp theo đúng thứ tự áp dụng:
#   BASE  <đường dẫn schema, không .sql>
#   TABLE <tên bảng> <nhóm> <load: sql|csv|none> <số dòng kỳ vọng>
#   VIEW  <đường dẫn schema, không .sql>
# Thứ tự in: mọi BASE, rồi các TABLE theo thứ tự khai báo, rồi mọi VIEW — như
# database/scripts/_dbtools.py (Manifest.schema_files). Chỉ hiểu đúng định dạng đơn giản của file.

function quoted(line, label,    out) {
    while (match(line, /"[^"]*"/)) {
        out = substr(line, RSTART + 1, RLENGTH - 2)
        if (label == "base") base[++nbase] = out
        else views[++nviews] = out
        line = substr(line, RSTART + RLENGTH)
    }
}

function value(line,    v) {
    if (match(line, /"[^"]*"/)) return substr(line, RSTART + 1, RLENGTH - 2)
    sub(/^[^=]*=[ \t]*/, "", line)
    sub(/[ \t\r]+$/, "", line)
    return line
}

function flush() {
    if (name != "") {
        tables[++ntables] = name " " group " " (load == "" ? "sql" : load) " " (rows == "" ? 0 : rows)
    }
    name = ""; group = ""; load = ""; rows = ""
}

/^[ \t]*#/ { next }
/^[ \t]*\[\[table\]\]/ { flush(); in_array = ""; in_table = 1; next }
in_array != "" {
    quoted($0, in_array)
    if ($0 ~ /\]/) in_array = ""
    next
}
!in_table && /^[ \t]*base[ \t]*=/ { in_array = "base"; quoted($0, "base"); if ($0 ~ /\]/) in_array = ""; next }
!in_table && /^[ \t]*views[ \t]*=/ { in_array = "views"; quoted($0, "views"); if ($0 ~ /\]/) in_array = ""; next }
in_table && /^name[ \t]*=/ { name = value($0); next }
in_table && /^group[ \t]*=/ { group = value($0); next }
in_table && /^load[ \t]*=/ { load = value($0); next }
in_table && /^rows[ \t]*=/ { rows = value($0); next }

END {
    flush()
    for (i = 1; i <= nbase; i++) print "BASE " base[i]
    for (i = 1; i <= ntables; i++) print "TABLE " tables[i]
    for (i = 1; i <= nviews; i++) print "VIEW " views[i]
}
