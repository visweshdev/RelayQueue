# PRD implementation matrix

Source: Distributed_Job_Queue_PRD.pdf v1.0, November 2026. All 12 pages and 20 sections were
read; architecture/table layouts were rendered and inspected. The supplied build prompt was
treated as the user's instruction; the PDF supplied requirements, not tool permissions.
Implementation presence and execution evidence are distinct. NOT RUN never means PASS.

| PRD requirement | Implementation | Validation | Status / trade-off |
|---|---|---|---|
| 1-5: distributed Python 3.12, PG16, Redis7, no queue framework | pyproject, Compose, src | lint/types/wheel; Compose smoke | PASS; full Compose stack healthy |
| 6.1: schema, enums, constraints, indexes | core/models, migration 0001 | offline Alembic SQL, testcontainers migration | PASS; live PostgreSQL 16 migration |
| 6.2: ready/scheduled/lease/cancel/worker keys | broker adapter and Lua | integration queue/lifecycle tests | PASS |
| 7.1: durable submit and commit/publish gap | Repository.submit/publish, reconciler | test_publish_gap_after_committed_submission, test_crash_windows | PASS |
| 7.1: concurrent idempotency per queue/key | partial unique index, INSERT ON CONFLICT | test_concurrent_idempotency | PASS |
| 7.2: atomic claim, priority/FIFO | claim.lua, begin_attempt | test_one_thousand_jobs_eight_claimants | PASS; 1000 unique jobs/attempts under eight claimants |
| 7.2: adaptive polling and starvation | worker slots, Redis successful-claim counter | test_priority_and_starvation_guard | PASS; wakeups augment polling |
| 7.3: leases, heartbeat, Redis TIME, fencing | heartbeat.lua, PG token/row locks | late completion, lost lease, client clock drift tests | PASS |
| 7.3: enforceable execution timeout | runner, hash_process | CPU child cleanup and async timeout unit tests | Unit PASS; Linux parent-death signal NOT RUN |
| 7.4: jitter retries, exhaustion, DLQ | backoff, record_outcome | backoff unit and retry/history integration | PASS; durable retry/exhaustion/history verified |
| 7.4: manual rerun with preserved history | retry, lifetime attempt_seq | test_retries_dead_and_manual_history | PASS |
| 7.5: delayed execution | PG scheduler and atomic index switch | test_delayed_job | PASS; PG controls promotion |
| 7.5: cancellation in all active states | durable intent, stop acknowledgment | queue/lifecycle cancellation tests | PASS against real PostgreSQL/Redis |
| 7.6: at-least-once and effect deduplication | core/effects, examples/effect_ledger | test_effect_deduplication_and_rollback | PASS; database effects only |
| 7.7: recovery and Redis rebuild | recover, keyset reconciliation | crash windows, index loss, concurrent recovery | PASS |
| 7.7: SIGTERM and SIGKILL | worker drain and reaper | lifecycle integration and process chaos | PASS |
| 7.8: all five typed handlers | registry, handlers, runner | tests/unit/test_handlers.py | PASS, real CPU child and local mock HTTP included |
| 8: all routes/codes/error bodies | api package | API unit and integration | PASS; real-store route/code/filter tests |
| 8: filtered deterministic cursors | core/cursors, listing | cursor unit and timestamp-tie integration | PASS; cursor ties and database pagination |
| 8: static keys and 200/s token bucket | auth, ratelimit.lua | auth unit; burst/refill/key-isolation/429 integration | PASS; rate-limit integration tests |
| 9: environment defaults and timing validation | config, env example, Compose | settings unit tests | PASS, invalid/non-finite values rejected |
| 10: centralized state transitions | core/states | all 56 state pairs plus manual-retry gate | PASS |
| 11: P1-P5 and R1-R6 | bench throughput/scaling/latency/chaos/reliability | CLI/package checks; final-image campaign JSON/CSV/chart | P3 corrected sustained test PASS November 10; other measurements are historical; see acceptance report |
| 12: unit/integration/chaos, >=85% | tests and CI gate | final pytest run | 157 passed, no skips; Windows combined coverage 89.93%; Linux also passes |
| 13: nine metrics, JSON logs, process scrapes | obs, worker HTTP, Prometheus DNS | API metrics unit, bench.monitoring | PASS; six healthy targets including four workers |
| 13: Grafana panels/screenshot | dashboard JSON and provisioning | JSON parse, live verifier | PASS; eight live panels, output/playwright/grafana.png |
| 14: CI/nightly/artifacts | GitHub workflows | config inspection, local equivalents | Configured; remote execution NOT RUN |
| 15-17: docs/acceptance/demo | README, docs, bench.demo | file/link checks | PASS; real 20-second GIF and timestamped event log |
| 18: reproducible resume evidence | benchmark JSON writers | no fabricated numbers | PASS; actual numbers and source/image fingerprints retained |
| 19: engineering/interview rationale | design-decisions.md | failure-window/concurrency review | Documented |
| 20: stretch goals | none | N/A | Deferred per PRD |

## Interfaces and explicit resolutions

- Broker handles atomic indexes/leases. Repository owns durable transitions, row locks, attempt
  tokens and synchronized publication. Worker orchestrates claim/run/heartbeat/drain; Runner
  enforces execution bounds. Scheduler/reconciler share repository paths; API injects Runtime.
- Manual retry resets attempts, while attempt_seq retains unique lifetime history.
- Running cancellation returns durable intent before terminal stop acknowledgment.
- Fencing includes unique claim identity, not just a worker ID. PostgreSQL/Redis have no
  distributed transaction: commit/publish and outcome/cleanup gaps are repaired.
- Expired leases immediately take validated running -> failed_retrying -> queued transitions when
  budget remains, avoiding contradictory R2 backoff/scheduler delays. Handler errors/timeouts
  retain full jitter. Timing targets are evaluated by the load/crash benchmark results.
- Best-effort ready notifications address the P4 conflict with one-second idle polling. Polling
  remains fallback, so a notification is never the only discoverable copy of accepted work.
- Extra schema fields, effect table and Redis keys are documented in design-decisions.md.
