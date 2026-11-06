# Design decisions and reliability limits

## Durable database, repairable broker

PostgreSQL is authoritative because acceptance requires a committed job, independent of Redis
availability. Redis makes small multi-key queue operations atomic and keeps polling cheap.
Payloads and results never live exclusively in Redis. A failed post-commit publish is logged and
reconciled; the API may still return 201 because PostgreSQL has accepted responsibility.
If the client disconnects after commit, the caller should retry with the same idempotency key.
The unique partial index covers `(queue, idempotency_key)` even for concurrent submissions.

The implementation relies on the documented [Redis script atomicity](https://redis.io/docs/latest/develop/programmability/eval-intro/)
and [PostgreSQL concurrency controls](https://www.postgresql.org/docs/16/mvcc.html).
Redis 7 effects replication permits Redis TIME inside these write scripts. Queue keys target
one Redis server, not Redis Cluster; dynamic lease keys deliberately do not claim cluster support.

## Claims, fencing and partial transactions

A Lua claim removes the oldest ready ID, installs a unique worker/claim token with TTL, and
updates the lease sorted set using Redis TIME. It refuses any ID with a live owner, including
one accidentally reintroduced into a ready set. The PostgreSQL claim then locks the job row,
validates queued/due/not-cancelled state and renews that exact token before recording the attempt.

Completion also locks the row and checks both the durable token and Redis ownership. Reaper
recovery and manual operations take the same lock. A stale worker cannot overwrite a successor's
durable outcome, even if Redis restarts between an ownership check and a database commit.
There is still no atomic commit across stores: a lease can expire after the validation point,
and a handler can have completed an external side effect before its result is recorded. The
row lock serializes durable decisions, not arbitrary effects. Late results are discarded.

| Failure window | Recovery |
|---|---|
| Before database commit | No accepted job; transaction rolls back |
| Commit, before Redis publish | Queued/scheduled row is rediscovered by reconciliation |
| Redis claim, before database attempt | Queued row survives; after TTL expiry reaper republishes it |
| Durable attempt, before handler start | Lease expiry closes attempt and schedules retry or DLQ |
| During handler | Same recovery; side effects may already exist |
| Handler finished, before result commit | Handler may run again; durable effect keys help |
| Result commit, before lease cleanup | Terminal row prevents another attempt; reconciliation removes indexes |
| Redis loses all indexes | Running rows without matching owner recover; ready/scheduled rows republish |

Reconciliation reads bounded UUID-keyset batches, then re-reads each row under lock before acting.
It never publishes from an old snapshot after a concurrent cancellation or completion. Concurrent
reapers serialize on rows, and duplicate ZADDs do not create duplicate valid owners. Scheduled
promotion is driven by PostgreSQL time and `FOR UPDATE SKIP LOCKED`, with Redis as its repairable
index; this avoids promoting an ID before its durable state is queued. Lua atomically switches
the scheduled/ready indexes. All multi-key Redis writes are Lua.

## Guarantees and assumptions

At-least-once execution assumes PostgreSQL durable commits and storage survive, services eventually
recover, an API/reaper/worker deployment continues operating, and job retention is not manually
deleted. Jobs remain discoverable until terminal. Exhausted jobs become dead; at-least-once does
not mean successful execution is inevitable. Redis-only loss is recoverable; losing PostgreSQL's
durable data is outside the guarantee. No local test establishes production readiness.

Exactly-once external side effects are not promised. `apply_once(session, key, callback)` runs a
database effect and its deduplication record in the same caller transaction. A callback using a
different connection, sending email, writing a file or calling HTTP breaks that atomicity. Use
the downstream service's idempotency key or a transactional outbox for such effects. An outbox
alone still does not make an arbitrary external operation exactly-once.

## Schema additions

- `jobs.claim_token`: per-claim fencing, stronger than reusing a worker ID.
- `jobs.attempt_seq`: monotonic lifetime sequence. `attempts` resets on manual retry; the unique
  `(job_id, attempt_no)` history never resets and all prior errors survive.
- `jobs.cancel_requested`: durable running cancellation intent, not a premature terminal state.
- `job_attempts.handler_finished_at`: independent audit written after handler success, before
  result commit; helps count observed duplicate completions after lease loss.
- `job_attempts.requeued_at`: first durable timestamp after a confirmed Redis ready publish for
  that completed attempt; supports measured recovery latency.
- Attempt outcome `cancelled`: distinguishes explicit cancellation from failure and timeout.
- `side_effects`: transactionally deduplicated effect results.

There is a unique Redis claim-count key per worker (24-hour TTL). A notification channel named
`fq:{queue}:ready:0:notify` carries best-effort wakeups after ready inserts; polling remains the
recovery mechanism if notifications are lost. API keys are hashed before
being used in rate-limit key names; neither API keys nor payloads appear in logs/metric labels.

## Timeouts, cancellation and shutdown

Async handlers are cancelled and awaited. CPU work runs in a child process that is killed and
joined on timeout/cancellation; Linux also sets a parent-death SIGKILL to stop it if the worker
dies. An independent watchdog bounds CPU subprocess lifetime on Windows. No unbounded executor
thread continues CPU work after a timeout is reported. HTTP has an explicit trusted-origin
allowlist, disabled environment proxies, no redirects, bounded response bytes and a timeout.
Allowlisted domains and their DNS are operator-controlled trust boundaries.

Queued/scheduled/retrying cancellation commits terminal cancellation before Redis cleanup; any
stray claimant must revalidate PostgreSQL. Running cancellation returns 202 with `status=running`
and `cancel_requested=true`; the worker checks durable intent at each heartbeat, stops execution,
then commits cancellation. A reaper can acknowledge a lost-owner cancellation. Signals in Redis
are hints; losing them does not lose the durable request. External effects cannot be undone.

SIGTERM stops new claims, marks draining, and waits up to SHUTDOWN_GRACE_S. At grace expiry,
active handlers are stopped and an owned attempt records failure; if storage is unavailable,
lease recovery remains responsible. SIGKILL cannot run cleanup and is recovered after lease expiry.

## Timing trade-offs

The specification combines a 5-second reaper scan, retry backoff, a 1-second scheduler scan, and
an R2 target of ready within 5 seconds after expiry. Applying all three delays cannot satisfy the
intended recovery bound. **Explicit resolution:** handler failures and timeouts retain full-jitter
backoff; lost leases consume an attempt but, when budget remains, validate running -> failed_retrying
-> queued in one recovery transaction and immediately republish. This avoids both extra delays.
Reaper scan phase plus database/broker work still prevents a hard real-time guarantee under load.
R2 is a measurement target, not an unconditional bound. The benchmark records actual ready timing.

Redis TIME is authoritative for lease deadlines and rate buckets; PostgreSQL time drives durable
scheduling. Python wall-clock changes cannot extend another worker's lease. Cross-store benchmark
timestamp subtraction assumes synchronized Redis/PostgreSQL host clocks. Poll/reconnect timers
use monotonic clocks. Idle polling retains the required 50 ms to 1 second backoff. To reconcile
this with the P4 <200 ms idle pickup target, atomic ready insertion also publishes a wakeup.
Each worker maintains a Redis subscription that wakes its execution slots. Notifications carry
no durable responsibility: if a connection drops or a notification is missed, fallback polling
still discovers work. P4 measured p95 71.645 ms over 100 samples; outage latency can reach the polling cap.

## Observability accuracy

Prometheus scrapes each worker process independently, avoiding API-only counters masquerading as
global metrics. Reaper-owned queue depth and live-worker gauges come from durable state. Labels
contain configured queue names, registered tasks, bounded priorities/outcomes and route templates.
Events are structured JSON with available job/worker/attempt/queue/task context and sanitized errors.
Counters are operational estimates: process restarts, a crash before scrape, or a transaction
rollback after an emitted metric can change their accounting. PostgreSQL supplies benchmark and
acceptance accounting. Duplicate completion audit is a lower bound: a worker can die between
handler return and audit commit. Missing audit evidence must never be called zero actual duplicates.

## Scaling and deployment limits

At 10x load, per-job database transactions and the scheduler/reconciler's row-by-row broker
round trips become likely bottlenecks. Batch publication/outbox dispatch and carefully tuned
connection pools would help. At 100x, partition durable history, shard queues and ownership,
separate metrics/admin queries from the write path, and benchmark hot-queue contention.
Redis Cluster, multi-region, DAGs, public tenancy and retention/archival are intentionally absent.

The local compose network has loopback-only published API/monitoring ports and no published database
ports. Its static credentials are demo values. A real deployment needs secret management, TLS,
network controls, backup/restore exercises, resource budgets, retention, monitoring alerts,
load-tested failover, and an explicit review of external side effects. Compose and dashboard runtime have been verified locally. Remote CI still requires a configured
GitHub repository.

## Independent maintenance loops

Scheduler, lease recovery, reconciliation and gauge refresh run as independent asynchronous
loops with separate retries. A slow reconstruction pass therefore cannot block expiry recovery
or delayed-job promotion. Each loop measures its interval from the start of the preceding pass.
Reconciliation scans nonterminal PostgreSQL rows and then Redis index members for stale terminal
or orphan entries; completed database history does not become an ever-growing recovery backlog.
All repairs still lock and reread the current job before mutation.

## API process capacity and shared metrics

The initial single API process reached about 95% CPU during the 100-RPS experiment. The
Compose API now starts two Uvicorn processes by default (`API_WORKERS=2`). Each has its own
database pool; authentication and rate limiting remain shared through Redis.

The launcher creates a fresh Linux-native temporary metrics directory before starting Uvicorn
and exports `PROMETHEUS_MULTIPROC_DIR` to both children. `/metrics` uses a fresh collector
registry to aggregate process files; a regression test verifies counters from two independent
processes. Standalone single-process runs keep the normal registry. This follows the
[Prometheus Python multiprocess guidance](https://prometheus.github.io/client_python/multiprocess/).
Worker and reaper services retain their independent scrape endpoints.

Locust users now stagger their initial phases over one second, with seed 42, so the sustained
rate test does not create an artificial synchronized request burst every second. The earlier
single-process/burst results are preserved under `bench/results/baseline-single-api/`.
