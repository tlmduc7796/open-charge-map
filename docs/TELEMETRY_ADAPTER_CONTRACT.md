# Telemetry adapter contract

This contract defines the boundary between a future aggregator integration and
the backend's existing complete-snapshot ingest API. It is provider-neutral;
the aggregator has not been selected and all telemetry currently generated in
the workspace is simulated. Simulated payloads are rejected when
`DEMO_MODE=false` and must never be promoted to operational observations.

## Flow

An adapter may poll an aggregator, receive its webhook, or consume its MQTT
feed. It authenticates to the provider using secrets held outside the browser,
maps provider station/port identifiers to the reviewed release catalog, and
sends one normalized snapshot per station to:

```text
PUT /api/realtime/stations/{station_id}/telemetry
X-Telemetry-API-Key: <secret>
Content-Type: application/json
```

The adapter is responsible for provider authentication, webhook signature
validation (when applicable), reconnect/backoff, secret rotation, metrics, and
dead-letter handling. It must not write directly to PostgreSQL or Redis.

## Normalized snapshot

```json
{
  "station_id": "STATION_ID_FROM_RELEASE_CATALOG",
  "observed_at": "2026-10-10T08:30:00Z",
  "data_source": "station_api",
  "avg_session_duration_min": 32.0,
  "ports": [
    {
      "port_id": "stable-provider-port-id",
      "connector_types": ["CCS2"],
      "state": "charging",
      "session_id": "stable-session-id",
      "reported_remaining_port_release_min": 18.0
    },
    {
      "port_id": "another-provider-port-id",
      "connector_types": ["CCS2"],
      "state": "available"
    }
  ],
  "queue": []
}
```

The sample is illustrative only; connector and port rows must match the
approved catalog exactly. `data_source` describes the underlying observation
method, not the transport or vendor: use `station_api` for aggregator data
derived from charger/operator APIs, `camera_vision` for camera-derived
observations, and `combined` only when the snapshot genuinely combines those
observation methods. Never label simulated observations as operational data.

## Mapping and validity rules

- `station_id` must identify an active, non-synthetic release catalog station.
  Provider station IDs need an explicit, reviewed mapping; do not infer an
  identity from a nearby name or coordinate.
- `observed_at` is the provider's observation time, in ISO-8601 with timezone.
  It is not adapter receipt/send time. Preserve it unchanged across retries.
- Every catalog port appears exactly once. The normalized `port_id` must match
  that port's reviewed `ports.external_id`, when present, or its stable
  `ports.label` otherwise. The backend checks both the full ID set and each
  port's connector code against PostgreSQL on release ingest. Map aggregator
  IDs to these reviewed identifiers in the adapter; never derive a match from
  port order or connector totals alone.
- Map provider states to `available`, `charging`, `out_of_service`, or
  `unknown`. Use `unknown` when the provider did not observe state; do not
  convert missing data to `available` or `out_of_service`.
- A `charging` port requires `session_id`; include
  `reported_remaining_port_release_min` only when the provider reports it.
  Do not fabricate a remaining duration. The release DES wait path cannot
  resolve a charging port without provider duration or an approved model.
- `queue: []` means an observed empty queue. `queue: null` or an omitted queue
  means queue state is unknown. Include only physically confirmed vehicles;
  app intentions and planned arrivals are not a confirmed queue.
- Queue entries need unique IDs and positions, timezone-aware entry times,
  compatible connector types, and a positive expected charge duration. If the
  provider cannot support these fields reliably, send `queue: null`.
- `avg_session_duration_min` must be a positive provider-derived value for
  recommendation wait estimation. Missing duration causes the candidate to be
  excluded with `WAIT_INPUT_UNAVAILABLE`; do not substitute a demo default.
- A snapshot may contain at most 1,000 ports and 2,000 queue entries. Keep the
  HTTP request body below the release proxy's 1 MiB limit.

## Delivery, retries, and monitoring

The backend accepts an identical retry for the same station and
`observed_at`. Reusing that timestamp with a different payload conflicts.
Retry 429 and transient 5xx/network failures with bounded exponential backoff
and jitter; honor `Retry-After` where supplied. Treat 401/403 as credential or
configuration failures, 404 as an unresolved catalog mapping, 409 as a
payload/timestamp conflict, and 422 as a schema or observation-time problem;
these require correction rather than blind retry. Do not send an older
observation after a newer one has been accepted.

Track provider polling/webhook lag, per-station last observed time, accepted,
rejected, retried, and dead-lettered snapshots, and freshness against
`REALTIME_TELEMETRY_MAX_AGE_S`. Keep station IDs out of unbounded metric labels;
put per-station diagnostics in access-controlled logs or the adapter's bounded
operations view. Alert on sustained lack of fresh eligible stations and
reconcile adapter health with backend `/health/ready` and Prometheus freshness
metrics.

Before enabling a provider in release, retain its API/webhook/MQTT specification
and a dated sample payload, document every field mapping and null/unknown
policy, verify station and port identity against the approved catalog, test
replay/idempotency and out-of-order delivery, rotate credentials, and collect
at least 12 consecutive observed five-minute occupancy buckets for each station
expected to use occupancy forecasting. The current simulator is suitable for
exercising the API path in demo mode only; it cannot satisfy these release
checks.
