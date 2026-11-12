# Tradeoffs and production boundaries

RelayQueue is a runnable, tested reference system. Passing reliability tests establishes behavior
under the tested failures, not a production SLA or real-user adoption.

| Decision | Benefit | Cost or limitation |
| --- | --- | --- |
| PostgreSQL owns lifecycle and results | Recovery can reconstruct Redis indexes | Durable writes, row locks and connection pools limit throughput |
| Redis leases plus fencing at completion | Stale workers cannot commit a newer owner's result | An external side effect can still happen twice before completion is recorded |
| At-least-once execution | Work can recover after worker loss | Handlers must tolerate replay; submission deduplication is not effect deduplication |
| Full payloads/results in PostgreSQL | Simple durable small-file demo | Storage/WAL/backups grow with jobs; bounded retention is enabled in the isolated rehearsal |
| Periodic reconciliation | Repairs cross-store publication gaps | Database scans and per-job checks increase cost with backlog/history |
| Separate workers and monitoring | Failure isolation and observable ownership | More containers, memory, network connections and operational work than an in-process queue |

## Duplicate effects

An external request can succeed immediately before a worker crashes. The queue then retries
because it never received a durable completion record. Use an effect-specific idempotency key at
the downstream service, or commit a transactional outbox entry alongside application state and
deliver it with downstream deduplication. `core/effects.py` protects effects only when they use
the same PostgreSQL transaction; it cannot atomically cover an arbitrary HTTP request.

The sales-report example deliberately performs only deterministic computation. It demonstrates a
safe replay strategy without claiming to solve external exactly-once delivery.

## Operating costs

The default local deployment runs an API, four worker containers, a reaper, PostgreSQL, Redis,
Prometheus and Grafana, plus a short-lived migration service. Reducing workers saves memory and
connections but reduces available execution concurrency. Costs include database disk and WAL,
backup storage, metrics retention, container memory/CPU, network traffic and on-call maintenance.
No cloud bill estimate is claimed without a provider, workload and retention policy.

Measure accepted/drained throughput, queue age, database pool pressure, CPU/RAM and storage growth
under your actual handlers. Published noop throughput includes load-client overhead and is not a
capacity promise for file parsing or external APIs. Existing benchmark data remains tied to its
recorded source and machine. [CSV measurements](local-rehearsal.md#measured-csv-workload)
now cover 1,000 jobs per run; the 20,000-job campaign remains a noop workload.

## Before exposing it publicly

The [isolated local rehearsal](local-rehearsal.md) implements TLS, file-mounted secrets,
queue-scoped tenant authorization, retention, backup/restore verification and local alerts.
Before public use, configure managed secrets, off-host backup scheduling, resource limits,
external alert routing and a deployment rollback procedure. The included shared API keys and local
passwords are development defaults. PostgreSQL/Redis are single-node in Compose; a host or disk
failure requires backups, not just queue retries. Cancellation cannot undo completed side effects.

See [the CSV demo](sales-report.md), [architecture](architecture/README.md), and
[operations](operations/README.md) for the implemented behavior and reproduction commands.
