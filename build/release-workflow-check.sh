python scripts/preflight_release.py
docker compose --env-file .env.release -f compose.release.yaml build api web
docker run --rm --entrypoint python smart-ev-backend:release -c \
  "from backend.app.config import load_settings; s=load_settings(); assert s.app_env == 'production' and not s.demo_mode"
docker compose --env-file .env.release -f compose.release.yaml up -d postgres
docker compose --env-file .env.release -f compose.release.yaml run --rm migrate
revision=$(docker compose --env-file .env.release -f compose.release.yaml \
  exec -T postgres psql -U smart_ev -d smart_ev_data -Atc \
  "SELECT version_num FROM alembic_version")
test "$revision" = "0020_path_safe_ids"
docker compose --env-file .env.release -f compose.release.yaml \
  run --rm --no-deps migrate python -m alembic check
docker compose --env-file .env.release -f compose.release.yaml \
  exec -T postgres psql -U smart_ev -d smart_ev_data -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE release_backup_roundtrip (marker text PRIMARY KEY); INSERT INTO release_backup_roundtrip VALUES ('backup-restore-ok');"
backup_identity_path="$RUNNER_TEMP/smart-ev-backup.agekey"
backup_output_dir="$RUNNER_TEMP/smart-ev-backups"
age-keygen -o "$backup_identity_path" 2>/dev/null
backup_recipient=$(age-keygen -y "$backup_identity_path")
python data_platform/scripts/backup_database.py create \
  --output-dir "$backup_output_dir" \
  --age-recipient "$backup_recipient" \
  --age-identity-file "$backup_identity_path"
backup_archive=$(find "$backup_output_dir" -maxdepth 1 -name '*.dump.age' -print -quit)
test -n "$backup_archive"
python data_platform/scripts/backup_database.py verify "$backup_archive" \
  --age-identity-file "$backup_identity_path"
python data_platform/scripts/restore_database.py "$backup_archive" \
  --target-database smart_ev_restore_check \
  --age-identity-file "$backup_identity_path"
restored_revision=$(docker compose --env-file .env.release -f compose.release.yaml \
  exec -T postgres psql -U smart_ev -d smart_ev_restore_check -Atc \
  "SELECT version_num FROM alembic_version")
test "$restored_revision" = "0020_path_safe_ids"
restored_marker=$(docker compose --env-file .env.release -f compose.release.yaml \
  exec -T postgres psql -U smart_ev -d smart_ev_restore_check -Atc \
  "SELECT marker FROM release_backup_roundtrip")
test "$restored_marker" = "backup-restore-ok"
docker compose --env-file .env.release -f compose.release.yaml \
  run --rm --no-deps api python -c \
  "from backend.app.main import app, settings; assert app.title == 'Smart EV Journey API'; assert settings.app_env == 'production' and not settings.demo_mode"
docker compose --env-file .env.release -f compose.release.yaml up -d api web
web_container=$(docker compose --env-file .env.release -f compose.release.yaml ps -q web)
test -n "$web_container"
web_uid=$(docker exec "$web_container" id -u)
test "$web_uid" != "0"
docker inspect "$web_container" | python -c "import json,sys; c=json.load(sys.stdin)[0]; h=c['HostConfig']; assert h['ReadonlyRootfs'] is True; assert 'ALL' in h['CapDrop']; assert 'no-new-privileges:true' in h['SecurityOpt']; assert '/tmp' in h['Tmpfs']"
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8080/health/live >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent http://127.0.0.1:8080/health/live >/dev/null
curl --fail --silent http://127.0.0.1:8080/ >/tmp/smart-ev-release-index.html
grep -qi '<html' /tmp/smart-ev-release-index.html
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8080/api/health/live >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent http://127.0.0.1:8080/api/health/live >/dev/null
telemetry_key=$(python -c "from pathlib import Path; print(next(line.split('=', 1)[1] for line in Path('.env.release').read_text().splitlines() if line.startswith('TELEMETRY_INGEST_API_KEY=')))")
simulated_payload=$(python -c "import json; from datetime import UTC,datetime; print(json.dumps({'station_id':'ST_CI_SIMULATED','observed_at':datetime.now(UTC).isoformat(),'ports':[{'port_id':'SIM-CI-1','connector_types':['CCS2'],'state':'available'}],'queue':[],'avg_session_duration_min':30,'data_source':'simulated'}))")
unauthenticated_telemetry_status=$(curl --silent --show-error \
  --output /tmp/smart-ev-release-telemetry-auth.json --write-out '%{http_code}' \
  --request PUT http://127.0.0.1:8080/api/realtime/stations/ST_CI_SIMULATED/telemetry \
  --header 'Content-Type: application/json' --data "$simulated_payload")
test "$unauthenticated_telemetry_status" = "401"
python -c "import json; d=json.load(open('/tmp/smart-ev-release-telemetry-auth.json')); assert d['detail']=='invalid telemetry API key' and d['error_code']=='AUTHENTICATION_REQUIRED'"
simulated_status=$(curl --silent --show-error \
  --output /tmp/smart-ev-release-simulated-telemetry.json --write-out '%{http_code}' \
  --request PUT http://127.0.0.1:8080/api/realtime/stations/ST_CI_SIMULATED/telemetry \
  --header "X-Telemetry-API-Key: $telemetry_key" \
  --header 'Content-Type: application/json' --data "$simulated_payload")
test "$simulated_status" = "422"
python -c "import json; d=json.load(open('/tmp/smart-ev-release-simulated-telemetry.json')); assert d['detail']=='simulated telemetry is disabled' and d['error_code']=='VALIDATION_FAILED'"
ready_status=$(curl --silent --show-error \
  --output /tmp/smart-ev-release-ready.json --write-out '%{http_code}' \
  http://127.0.0.1:8080/api/health/ready)
test "$ready_status" = "503"
python -c "import json; d=json.load(open('/tmp/smart-ev-release-ready.json')); assert d['detail']['checks']['identity']['status']=='unavailable'"
gated_api_status=$(curl --silent --show-error \
  --output /tmp/smart-ev-release-gated-api.json --write-out '%{http_code}' \
  http://127.0.0.1:8080/api/stations)
test "$gated_api_status" = "503"
python -c "import json; d=json.load(open('/tmp/smart-ev-release-gated-api.json')); assert d['detail']=='API is not ready' and d['error_code']=='DEPENDENCY_UNAVAILABLE'"
docker compose --env-file .env.release -f compose.release.yaml down --volumes
docker run --rm --entrypoint amtool \
  -v "$PWD/deploy/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
  -v "$PWD/.secrets/alertmanager-webhook-url:/run/secrets/alertmanager_webhook_url:ro" \
  prom/alertmanager:v0.34.1 \
  check-config /etc/alertmanager/alertmanager.yml
docker run --rm --entrypoint promtool \
  -v "$PWD/deploy/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/deploy/prometheus-alerts.yml:/etc/prometheus/prometheus-alerts.yml:ro" \
  prom/prometheus:v3.5.0 \
  check config /etc/prometheus/prometheus.yml
docker run --detach --rm --name smart-ev-grafana-check \
  --publish 127.0.0.1:13000:3000 \
  --env GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_admin_password \
  --env GF_USERS_ALLOW_SIGN_UP=false \
  --env GF_AUTH_ANONYMOUS_ENABLED=false \
  --volume "$PWD/deploy/grafana/provisioning:/etc/grafana/provisioning:ro" \
  --volume "$PWD/deploy/grafana/dashboards:/etc/grafana/dashboards:ro" \
  --volume "$PWD/.secrets/grafana-admin-password:/run/secrets/grafana_admin_password:ro" \
  grafana/grafana:12.4.3
trap 'docker stop smart-ev-grafana-check >/dev/null 2>&1 || true' EXIT
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:13000/api/health >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent --show-error \
  --user "admin:$(cat .secrets/grafana-admin-password)" \
  http://127.0.0.1:13000/api/dashboards/uid/smart-ev-release-ops \
  | python -c "import json,sys; d=json.load(sys.stdin); assert d['dashboard']['title']=='Smart EV Release Operations'"
docker stop smart-ev-grafana-check
