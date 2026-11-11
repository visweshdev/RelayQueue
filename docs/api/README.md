# API and job examples

[RelayQueue](../../README.md) / API and job examples

[API reference](#api-reference) | [Example submissions and results](#example-submissions-and-results)

## API reference

All `/v1` routes require `X-API-Key`. Errors have `code` and `message`; validation errors do not echo
payloads or secrets. Missing keys return 401. Unknown job IDs return 404.

| Method / path | Behavior |
|---|---|
| POST `/v1/jobs` | 201 for new jobs, 200 for an existing queue/idempotency key |
| GET `/v1/jobs/{id}` | Full job and ordered `history` of attempts |
| GET `/v1/jobs` | Filter by status, queue and task; newest-first cursor pagination |
| POST `/v1/jobs/{id}/cancel` | 202 accepted, 409 if already terminal |
| POST `/v1/jobs/{id}/retry` | 202 for a dead job, 409 otherwise |
| GET `/v1/queues/stats` | Counts by status/priority and oldest ready age |
| GET `/v1/workers` | Worker records, heartbeat, completed attempts and computed liveness |
| GET `/health` | Unauthenticated liveness |
| GET `/ready` | 200 if both stores respond; otherwise 503 |
| GET `/metrics` | Unauthenticated Prometheus exposition; intended for internal access |

`limit` is 1-100. Cursor ordering uses both creation timestamp and UUID, so timestamp ties do not
repeat rows. Invalid list arguments/cursors return 400. Unknown task/payload schema errors return
422, oversized payloads return 413, unconfigured queues return 400, and rate limiting returns
429 with `Retry-After: 1`. The default per-key bucket holds 200 tokens and refills at 200/second.

## Example submissions and results

```sh
curl -X POST http://localhost:8000/v1/jobs -H "X-API-Key: dev-key-1" -H "Content-Type: application/json" -d '{"task":"sleep","payload":{"seconds":2},"priority":0,"timeout_s":10,"idempotency_key":"demo-sleep-1"}'
curl http://localhost:8000/v1/jobs/JOB_ID -H "X-API-Key: dev-key-1"
curl 'http://localhost:8000/v1/jobs?status=dead&limit=10' -H "X-API-Key: dev-key-1"
curl -X POST http://localhost:8000/v1/jobs/JOB_ID/retry -H "X-API-Key: dev-key-1"
```

Replace JOB_ID with the returned UUID. A completed sleep result is `{"slept":2.0}`. Add an
offset-aware ISO-8601 `run_at` for delayed execution. Payloads/results are limited to 65,536 UTF-8
serialized JSON bytes. Request metadata is separately bounded by a 512 KiB streaming body cap.

| Handler | Payload |
|---|---|
| noop | `{}` |
| sleep | `{"seconds":2}` |
| flaky | `{"fail_rate":0.5}` |
| cpu_hash | `{"buffer":"abc","iterations":10000}` |
| http_call | `{"url":"http://test-server:8080/","timeout_s":5}` |

HTTP calls require an exact origin in `HTTP_ALLOWED_ORIGINS`; default outbound HTTP is disabled.
Redirects and environment proxies are disabled. Tests use a local HTTP mock service.
