# Smart EV data platform

Thư mục này tập trung toàn bộ dữ liệu của repository. Bootstrap PostgreSQL/PostGIS dùng
snapshot SQL và hai file xe JSON; backend demo cùng các script thu thập/kiểm tra vẫn đọc
các JSON/KML khác trong `data/`.

## Yêu cầu

- Python 3.12 trở lên;
- Docker Desktop đã chạy và có Docker Compose;
- PowerShell trên Windows.

## Khởi tạo database

Chạy từ thư mục gốc của repository:

```powershell
Set-Location data_platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python scripts\bootstrap_database.py
```

Lệnh cuối thực hiện toàn bộ quy trình:

1. khởi động PostgreSQL/PostGIS bằng `compose.yaml`;
2. chờ database sẵn sàng;
3. chạy Alembic migrations đến revision `0020_path_safe_ids`;
4. nạp `data/bootstrap/current_database.sql` trong một transaction;
5. đối chiếu `data/static/vehicles.json` với `data/demo/vehicles.json` và nạp xe;
6. nạp planned arrivals, arrival rate nền và cửa sổ tính từ fixture runtime/demo;
7. tạo trạng thái cổng, lịch sử ban đầu và metric synthetic cho 86 trạm mới từ
   `data/runtime/station_status.json` của 16 trạm gốc;
8. kiểm tra số row sau khi nạp.

Với database đã bootstrap từ revision cũ, nâng schema và đồng bộ runtime seed mà không
khôi phục lại snapshot tĩnh:

```powershell
Set-Location data_platform
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe scripts\seed_runtime_data.py
Set-Location ..
```

Database mặc định:

```text
host:     127.0.0.1
port:     5433
database: smart_ev_data
user:     smart_ev
password: smart_ev
```

Bootstrap chỉ chạy trên database chưa có dữ liệu nghiệp vụ. Nếu phát hiện row đã tồn tại, script
dừng lại để tránh trộn hoặc ghi đè dữ liệu.

## Dữ liệu sau khi khởi tạo

Snapshot trạm được chụp ngày 04/10/2026; hồ sơ xe được nạp thêm từ hai file JSON khi bootstrap.

| Bảng | Số row | Nội dung |
| --- | ---: | --- |
| `stations` | 102 | 16 trạm master và 86 trạm demo bổ sung |
| `station_external_refs` | 14 | Mã trạm từ nguồn bên ngoài |
| `connector_types` | 4 | CCS2, Type2 và hai chuẩn GB/T dành cho fixture demo |
| `ports` | 826 | Cổng sạc của toàn bộ trạm |
| `port_status` | 826 | 211 trạng thái gốc và 615 trạng thái synthetic cho trạm mới |
| `station_live_metrics` | 102 | 16 metric gốc và 86 metric synthetic cho trạm mới |
| `port_status_history` | 826 | 211 mốc gốc và 615 mốc khởi tạo synthetic |
| `station_occupancy_5m` | 4.624 | Occupancy theo bucket 5 phút |
| `predictions` | 96 | Prediction theo trạm và horizon |
| `station_amenities` | 714 | Bảy amenity cho mỗi trạm |
| `vehicle_models` | 21 | 20 hồ sơ nguồn hãng và một xe synthetic chỉ dành cho demo |
| `vehicle_connectors` | 41 | Quan hệ cổng sạc của 21 xe |
| `planned_arrivals` | 4 | Hai planned, một cancelled và một expired fixture synthetic |
| `station_arrival_rates` | 16 | Arrival rate nền synthetic cho các trạm demo |
| `trips` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `journey_recommendations` | 0 | Response recommendation được ghi cùng trip khi bật journey persistence |
| `station_incidents` | 0 | Báo cáo người dùng có capability token và idempotency key; chờ xác minh vận hành |
| `trip_positions` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trip_events` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `app_config` | 1 | Cửa sổ tính planned-arrival rate, hiện là 15 phút |

Operator review được thực hiện qua `GET /admin/incidents` và `PATCH /admin/incidents/{incident_id}/review` với header `X-Incident-Review-API-Key`. Release cần secret riêng `INCIDENT_REVIEW_API_KEY`. Incident `safety_concern` và `access_problem` ở trạng thái `triaged` sẽ loại trạm khỏi recommendation tới khi được `resolved` hoặc `rejected`; báo cáo `open` không ảnh hưởng. Review không tự sửa telemetry hoặc trạng thái cổng.

Trong 102 trạm có 52 trạm mang `review_status=synthetic` và `is_active=true`. Toàn bộ 714 amenity
là dữ liệu synthetic. Trong 86 trạm mới, 34 trạm có `review_status=verified` đối với thông tin
trạm, nhưng toàn bộ 615 cổng của 86 trạm đều có `data_origin=synthetic`. Trạng thái cổng và
queue được mô phỏng từ 16 bản ghi JSON gốc, gắn `data_origin=synthetic`; nhãn review của trạm
không bị thay đổi. Seeder chỉ bổ sung bản ghi thiếu và có thể chạy lại an toàn.

Để bổ sung trạng thái cho database đã bootstrap trước thay đổi này:

```powershell
Set-Location data_platform
.\.venv\Scripts\python.exe scripts\seed_synthetic_port_statuses.py
```

## Bố cục dữ liệu

```text
data_platform/
├── compose.yaml
├── alembic.ini
├── pyproject.toml
├── data/
│   ├── bootstrap/current_database.sql  # snapshot dùng để khởi tạo DB
│   ├── static/                         # trạm nguồn và 20 hồ sơ xe cho DB
│   ├── demo/                           # fixture backend, gồm 3 xe schema cũ
│   ├── collection/                     # candidate chờ review
│   ├── runtime/                        # trạng thái demo
│   ├── routes/                         # route cache
│   ├── ml/urbanev/                     # nguồn và EDA ML
│   └── validation/                     # báo cáo kiểm tra
├── migrations/
├── scripts/bootstrap_database.py
└── src/data_platform/
```

`current_database.sql`, hai file xe, `runtime/planned_arrivals.json` và
`demo/queue_assumptions.json` được bootstrap tự nạp. Hai xe demo VinFast trùng cấu hình được
gộp với hồ sơ nguồn hãng; xe GB/T synthetic được lưu với `market=DEMO`, `is_active=false`.
Dung lượng pin công bố của BYD đã được nạp; dung lượng khả dụng và công suất AC tối đa chưa được
hãng xác nhận nên không suy đoán. Mức tiêu thụ BYD được suy ra từ dung lượng công bố và tầm chạy
NEDC, có provenance `inferred`. Các mức SOC dự phòng/đích và hiệu suất sạc dùng giả định lập kế
hoạch `synthetic` cho 20 hồ sơ xe. Schema được tạo từ migrations; snapshot không chứa bảng hệ
thống PostGIS.

Để nạp lại xe vào database đã khởi tạo mà không lặp bản ghi:

```powershell
Set-Location data_platform
python scripts\seed_vehicles.py
```

Importer chỉ điền trường số còn `null` và giữ giá trị đang có trong DB. Nếu một cấu hình khớp
nhiều row hiện hữu, importer dừng để kiểm tra thủ công thay vì tự xóa dữ liệu có thể đang được
`trips` tham chiếu.

## Tạo lại database local từ đầu

Lệnh sau xóa toàn bộ Docker volume của database local:

```powershell
docker compose down -v
python scripts\bootstrap_database.py
```

Chỉ chạy khi chắc chắn dữ liệu trong volume không cần giữ lại. Các thay đổi phát sinh sau lần
bootstrap gần nhất sẽ mất nếu chưa được export.

## Encrypted backups, verification, restore, and retention

Release backup CLI commands require `age`. Create an age identity once and keep its private file outside the repository on storage with restricted ACLs. The public recipient can be copied to the scheduled backup command; never copy the private identity to off-host backup storage.

```powershell
$ageDirectory = Join-Path $env:USERPROFILE ".smart-ev"
New-Item -ItemType Directory -Force $ageDirectory | Out-Null
$ageIdentity = Join-Path $ageDirectory "backup.agekey"
age-keygen -o $ageIdentity
$ageRecipient = (Select-String -Path $ageIdentity -Pattern '^# public key:').Line.Split(' ')[3]
```

Create a backup. `pg_dump` streams into `age`; the host only writes the encrypted `.dump.age` archive. The manifest contains the ciphertext checksum and encryption format, never the key.

```powershell
python scripts\backup_database.py create --age-recipient $ageRecipient --age-identity-file $ageIdentity
$archive = Get-ChildItem "$env:USERPROFILE\.smart-ev\backups\postgres\*.dump.age" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
python scripts\backup_database.py verify $archive.FullName --age-identity-file $ageIdentity
```

Copy verified encrypted archives and manifests to independent off-host storage using the organization's approved transfer mechanism. Keep the private identity separately protected and test recovery access.

Restore always creates a new database and refuses an existing target or the source database name. Verification decrypts through a pipe and runs `pg_restore --list`; because archive listing may stop after reading the header, the backup CLI continues draining the decrypted stream to EOF so `age` can verify the complete ciphertext authentication tag. Restore also streams decrypted bytes directly into `pg_restore`, without writing a plaintext dump to disk.

```powershell
$archive = Get-ChildItem "$env:USERPROFILE\.smart-ev\backups\postgres\*.dump.age" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
python scripts\restore_database.py $archive.FullName --target-database smart_ev_restore_check --age-identity-file $ageIdentity
```

Retention removes only managed `.dump`/`.dump.age` archives with matching manifests, after the specified age, and keeps at least `--keep-last` recent backups. Run prune only after the off-host copy has been verified:

```powershell
python scripts\backup_database.py prune --output-dir C:\SecureBackups\SmartEV --older-than-days 30 --keep-last 2
```

On Windows, `scripts/run_release_backup.ps1` performs encrypted creation, local verification, copy of the archive and manifest to an UNC share, verification of the copied set, then publishes the complete set by renaming its staging directory. Register it in Windows Task Scheduler as a daily task running under a dedicated account that can access Docker Compose, the age identity, and the share. Example action arguments: `-NoProfile -File <repo>\scripts\run_release_backup.ps1 -AgeRecipient <public-recipient> -AgeIdentityFile <protected-path> -OffsiteDirectory \\backup-host\smart-ev`. Disable overlapping task instances. The script does not prune backups; prune only after a successful replicated and verified set. Off-site encrypted backups do not provide point-in-time recovery; WAL archiving and a real PostgreSQL restore drill remain operational work.


## Thư mục `trash`

Code phân tích, collector, seed rời, tests, artifacts và tài liệu cũ đã được chuyển vào `trash/`
để có thể phục hồi khi cần. `trash/` bị Git ignore và không tham gia quá trình bootstrap.

## Release Compose migration

`docker compose --env-file .env.release -f compose.release.yaml up --build` runs the release `migrate` one-shot service after PostgreSQL is healthy and starts the API only after migrations complete successfully. This creates/updates the schema only; it intentionally does not run `bootstrap_database.py`, load `current_database.sql`, or seed demo/runtime fixtures. Provision approved operational catalog data separately, then confirm `/health/ready` reports nonzero eligible station and vehicle counts before routing traffic.

Alert delivery runs through the internal Alertmanager service. Set `ALERTMANAGER_WEBHOOK_URL_FILE` to a file path outside source control; the file must contain one HTTPS webhook URL. Compose mounts it as a container secret, and release preflight validates it without printing its contents.

## Nạp catalog vận hành đã duyệt

`station_id` là ID nội bộ dùng trong URL path, không nên lấy trực tiếp từ provider nếu có thể chứa ký tự phân tách. Importer/backend chỉ chấp nhận ID khớp `^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$`; giữ ID gốc của provider trong `provider_station_id`. Planned-arrival ID có cùng quy tắc vì API dùng nó trong path. Migration `0020_path_safe_ids` áp constraint tương ứng trong PostgreSQL.

`import_release_catalog.py` accepts a StationCollection JSON matching the backend station contract and a JSON array of backend Vehicle records. It rejects synthetic station fields/connectors, synthetic vehicles, missing source timestamps, unsupported connectors, and vehicles without a usable charging power or nonempty `source_provider`. Each vehicle must also provide `field_provenance` for battery capacity, usable capacity, AC/DC power, AC/DC connectors, consumption, and each planning default. Each entry requires a nonempty provider and retains its own `origin` and source reference; missing/synthetic provenance is rejected, and `reserve_soc`, `default_target_soc`, and `charging_efficiency` require an `operator_policy` entry with a `policy_id`. Inferred values remain explicitly inferred in PostgreSQL; catalog approval does not rewrite them as observed. Station name/location/connector/amenity provenance records `operator_reviewed`, the reviewer, provider, and source update time. An optional `--port-map` JSON maps each station ID and generated port label (for example `CCS2-1`) to an operator/aggregator port ID. The importer validates labels, nonempty IDs that are unique across active ports at that station, and the 128-character ingest limit, then records mapping review provenance in the port row. Omitted mappings preserve existing external IDs; changing a mapping invalidates current telemetry snapshots while retaining occupancy history. Without an external ID, telemetry must use the stable catalog label. The default is validation/preview only. After reviewing the input, use `--apply --reviewed-by <operator>` to atomically upsert station, port, amenity, vehicle, and connector records; the operator and field provenance are retained. This default supports partial imports and leaves records absent from the files active. If both files are complete snapshots, add `--replace-snapshot`: within the same transaction, previously imported stations belonging to the included providers and previously imported release vehicles absent from the files are marked inactive. Snapshot replacement requires at least one station and one vehicle, preventing empty input from disabling a provider's entire catalog. The JSON output reports how many records were deactivated. Review the preview and confirm source coverage before using this option. A provider station reference already assigned to a different station is rejected instead of being silently reassigned; resolve that mapping explicitly before import. If a station's port topology changes, its current status/queue snapshots and per-port telemetry snapshots are invalidated so they cannot appear fresh against the new catalog; aggregate occupancy history is retained. The importer does not invent runtime status or queue telemetry; a telemetry provider must populate current observations before the station is considered fresh.

Example vehicle field provenance (include all ten keys shown; the remaining source values are omitted here):

```json
{
  "field_provenance": {
    "battery_capacity_kwh": {"origin": "observed", "provider": "manufacturer", "source_ref": "https://manufacturer.example/spec"},
    "usable_battery_kwh": {"origin": "unpublished", "provider": "manufacturer", "source_ref": "https://manufacturer.example/spec"},
    "max_ac_power_kw": {"origin": "observed", "provider": "manufacturer", "source_ref": "https://manufacturer.example/spec"},
    "max_dc_power_kw": {"origin": "observed", "provider": "manufacturer", "source_ref": "https://manufacturer.example/spec"},
    "ac_connectors": {"origin": "observed", "provider": "manufacturer", "source_ref": "https://manufacturer.example/spec"},
    "dc_connectors": {"origin": "inferred", "provider": "manufacturer", "source_ref": "https://manufacturer.example/connector-standard"},
    "consumption_wh_km": {"origin": "inferred", "provider": "catalog-analysis", "source_ref": "https://manufacturer.example/range", "note": "test-cycle estimate"},
    "reserve_soc": {"origin": "operator_policy", "provider": "journey-policy-v1", "policy_id": "journey-policy-v1"},
    "default_target_soc": {"origin": "operator_policy", "provider": "journey-policy-v1", "policy_id": "journey-policy-v1"},
    "charging_efficiency": {"origin": "operator_policy", "provider": "journey-policy-v1", "policy_id": "journey-policy-v1"}
  }
}
```

Set `unpublished` only for a genuinely absent published value (such as unknown usable capacity or charge power); the corresponding numeric value must be null/zero. `operator_policy` is reserved for the three calculation defaults and must point to an approved policy. The example URLs and policy ID are placeholders, not approved release inputs.

Repeated connector types are allowed when a station exposes the same standard at different power levels. The importer assigns one stable, unique port label sequence per normalized connector type, sorted by power, so groups such as two CCS2 power tiers do not collide. The database-backed catalog API preserves each power tier instead of reporting every port at the station's maximum; telemetry must also match the catalog's exact connector counts. Preview validation reports all release eligibility issues it finds before stopping.

Run from the repository root after installing the data-platform package and backend requirements:

With `--apply`, the CLI reads `POSTGRES_PASSWORD` and optional `POSTGRES_HOST_PORT` from
`.env.release` (default port `5433`) and connects to the Compose-published database on loopback.
Set `DATA_PLATFORM_DATABASE_URL` to override that connection for a separately managed database;
the URL is not printed. Applying requires an explicit release URL or a valid `.env.release` file;
the importer does not fall back to the local development database.

```powershell
python data_platform/scripts/import_release_catalog.py `
  --stations C:\SecureInput\stations.reviewed.json `
  --vehicles C:\SecureInput\vehicles.reviewed.json

python data_platform/scripts/import_release_catalog.py `
  --stations C:\SecureInput\stations.reviewed.json `
  --vehicles C:\SecureInput\vehicles.reviewed.json `
  --port-map C:\SecureInput\port-map.reviewed.json `
  --apply --reviewed-by "operator@example.com"

python data_platform/scripts/import_release_catalog.py `
  --stations C:\SecureInput\stations.complete.json `
  --vehicles C:\SecureInput\vehicles.complete.json `
  --apply --replace-snapshot --reviewed-by "operator@example.com"
```

Example `port-map.reviewed.json` (the catalog label is generated deterministically
from the connector group; only include provider IDs that an operator has mapped):

```json
{
  "OPS-001": {
    "CCS2-1": "aggregator-port-7f3a",
    "CCS2-2": "aggregator-port-7f3b"
  }
}
```

Pass this file with `--port-map` in both preview and apply. Unmapped labels keep
their current external ID, if any, and otherwise use the catalog label as the
telemetry ID. Set a mapped label to JSON `null` to explicitly clear its external
ID and return to the label. Re-importing a changed/cleared external ID invalidates
current telemetry snapshots for that station so old port states cannot attach to
the new mapping.

## Kết nối nguồn telemetry vận hành

Backend cung cấp push contract cho adapter của nhà cung cấp; repository chưa gắn với một API telemetry bên thứ ba cụ thể. Sau khi catalog đã được duyệt và import, adapter gửi một snapshot đầy đủ cho mỗi trạm qua `PUT /api/realtime/stations/{station_id}/telemetry`, kèm header `X-Telemetry-API-Key`. Trong triển khai gọi trực tiếp backend thay vì Nginx, bỏ prefix `/api`. Secret phải được đọc từ secret store của adapter, không ghi vào file payload hoặc log.

Aggregator hiện chưa được chọn và telemetry đang dùng trong workspace là mô phỏng. Quy tắc ánh xạ provider-neutral, retry/idempotency, unknown state, queue semantics và checklist kiểm định adapter được duy trì tại [`docs/TELEMETRY_ADAPTER_CONTRACT.md`](../docs/TELEMETRY_ADAPTER_CONTRACT.md). Tài liệu này bổ sung cho payload bên dưới; adapter thật chỉ được triển khai sau khi có tài liệu giao thức và mẫu payload của aggregator.

Payload phải có đúng một phần tử `ports` cho mỗi cổng trong catalog; `port_id` phải khớp chính xác `ports.external_id` đã duyệt hoặc catalog label nếu chưa có external ID; connector trên từng cổng cũng phải khớp catalog, ngoài kiểm tổng theo chuẩn. Có thể nhập provider ID qua `--port-map` khi import catalog. `observed_at` là thời điểm nguồn quan sát, ISO-8601 có timezone, không phải thời điểm adapter gửi. `data_source` chỉ nhận `station_api`, `camera_vision` hoặc `combined` cho dữ liệu vận hành. Mỗi cổng dùng `available`, `charging`, `out_of_service` hoặc `unknown`; `charging` cần `session_id`, và chỉ trạng thái này mới nhận `reported_remaining_port_release_min`.

```json
{
  "station_id": "<reviewed-station-code>",
  "observed_at": "2026-10-09T10:15:00Z",
  "data_source": "station_api",
  "avg_session_duration_min": 35,
  "ports": [
    {
      "port_id": "<stable-provider-port-id-1>",
      "connector_types": ["CCS2"],
      "state": "available"
    },
    {
      "port_id": "<stable-provider-port-id-2>",
      "connector_types": ["CCS2"],
      "state": "charging",
      "session_id": "<provider-session-id>",
      "reported_remaining_port_release_min": 18
    }
  ],
  "queue": []
}
```

`queue: []` chỉ dùng khi nguồn xác nhận hàng chờ đang trống; bỏ hẳn trường `queue` nếu không quan sát được hàng chờ. Không đưa ý định đặt chỗ/planned arrival vào queue. Nếu nguồn không biết trạng thái một cổng, gửi `unknown` thay vì suy đoán `available`. API từ chối snapshot `simulated` trong release, timestamp quá xa tương lai, snapshot cũ hơn bản đã lưu, thiếu cổng hoặc connector không có trong catalog. Gửi lại cùng timestamp chỉ idempotent khi toàn bộ payload giống hệt; một snapshot khác tại cùng timestamp trả conflict. Adapter nên retry bằng payload gốc hoặc đợi quan sát kế tiếp, không sửa payload rồi dùng lại timestamp.

```powershell
$headers = @{
  "X-Telemetry-API-Key" = $env:TELEMETRY_INGEST_API_KEY
  "Content-Type" = "application/json"
}
Invoke-RestMethod -Method Put `
  -Uri "https://<deployment-host>/api/realtime/stations/<reviewed-station-code>/telemetry" `
  -Headers $headers `
  -InFile "C:\SecureInput\station-snapshot.json"
Invoke-RestMethod -Method Get `
  -Uri "https://<deployment-host>/api/health/ready"
```

Health readiness chỉ chuyển sang `ready` khi có ít nhất một trạm eligible với snapshot còn hạn và có cổng vận hành đã biết. Để có observed history liên tục, adapter phải gửi snapshot định kỳ; snapshot tạo bucket occupancy 5 phút, còn khoảng trống không được backfill thành quan sát. Sau khi bắt đầu ingest, theo dõi target API và cảnh báo freshness/history coverage trong Prometheus/Grafana. `/metrics` chỉ mở trên mạng nội bộ của Compose; Nginx chủ ý trả `404` cho `/api/metrics` từ browser/API public. Đây là contract tích hợp; trước cutover phải xác minh mapping port/connector và nhịp gửi với tài liệu nguồn telemetry thật.

## PostgreSQL integration check for provider-reference races

The release-catalog suite includes a two-connection race check for concurrent upserts of the same provider external ID. Run it only against an isolated disposable PostgreSQL database whose user can create and drop schemas; it creates a uniquely named schema and removes it in `finally`. Without `DATA_PLATFORM_TEST_DATABASE_URL`, pytest skips this database-dependent check.

The GitHub Actions release workflow points `DATA_PLATFORM_TEST_DATABASE_URL` at its disposable PostgreSQL/PostGIS service before running the full suite, so this concurrency check runs in CI instead of being skipped.

```powershell
$env:DATA_PLATFORM_TEST_DATABASE_URL = "postgresql+psycopg://<test-user>:<test-password>@127.0.0.1:5433/<isolated-test-db>"
pytest data_platform/tests/test_release_catalog.py -k postgres_concurrent_provider_ref_upserts_keep_one_owner
Remove-Item Env:\DATA_PLATFORM_TEST_DATABASE_URL
```

## Backfill occupancy from persisted telemetry

`backfill_occupancy_history.py` rebuilds five-minute occupancy buckets from `station_telemetry_snapshots` whose source is `station_api`, `camera_vision`, or `combined`. It selects the latest operational snapshot in each bucket and ignores simulated snapshots. Preview is the default. With `--apply`, existing `observed` buckets are preserved; synthetic or inferred buckets may be replaced by observed data. Both range endpoints require a timezone. Work is committed in separate batches of at most 31 days.

```powershell
python data_platform/scripts/backfill_occupancy_history.py `
  --from "2026-09-01T00:00:00Z" `
  --to "2026-10-01T00:00:00Z" `
  --station-code "STATION_CODE"

python data_platform/scripts/backfill_occupancy_history.py `
  --from "2026-09-01T00:00:00Z" `
  --to "2026-10-01T00:00:00Z" `
  --station-code "STATION_CODE" --apply
```

Review the preview and snapshot sources before applying. Backfill only reconstructs data from saved snapshots; it does not invent observations for periods without telemetry.

## Retention cho telemetry

`prune_observation_history.py` previews row counts by default and prunes expired rows from `predictions`, `station_occupancy_5m`, `port_status_history`, and `station_telemetry_snapshots` in bounded transactions. Prediction outputs use the same explicitly approved retention window as their source observation history. The command takes `--older-than-days` because this repository does not define the product/legal retention period. Only apply a period approved for the deployment; the command does not delete journeys, GPS positions, or incident reports. It uses the same local Compose database connection as the catalog importer; set `DATA_PLATFORM_DATABASE_URL` to override it.

```powershell
$approvedDays = [int](Read-Host "Approved telemetry retention in days")

python data_platform/scripts/prune_observation_history.py `
  --older-than-days $approvedDays

python data_platform/scripts/prune_observation_history.py `
  --older-than-days $approvedDays --apply
```

The release Compose stack provides an `observation-retention` worker that runs the approved `--apply` command daily, after a 24-hour initial delay. Set `OBSERVATION_RETENTION_DAYS` only after the deployment's retention period is approved; Compose preflight rejects a missing or out-of-range value. Outside this stack, schedule the reviewed command with the deployment's job scheduler. Keep operation logs and monitor disk usage; PostgreSQL may need vacuuming to reuse space after large purges.
