# Tradeoffs and production boundaries

RelayQueue is a single-host reference system. The reliability evidence covers the specific
failures exercised in the test suite and local rehearsals.

## Deployment-readiness matrix

| Area | Default development Compose | Hardened local Compose rehearsal | Before a public deployment |
| --- | --- | --- | --- |
| Network and TLS | Loopback HTTP API, Prometheus, and Grafana. PostgreSQL and Redis use the Compose network. | Only the loopback Caddy HTTPS gateway is published. It uses a local CA. | Use a public DNS name and trusted certificates. Keep backing stores and monitoring on private networks. |
| Credentials and access | Shared development API key with access to all queues. Demo database and Grafana credentials. | File-mounted credentials, Redis authentication, and queue-scoped API permissions. | Provision and rotate managed secrets. Validate authorization and limit access to the intended users. |
| Data lifecycle | Persistent named volumes. No scheduled pruning or backup in this stack. | Daily 30-day retention for terminal jobs, plus an on-demand PostgreSQL backup and verified isolated restore. | Schedule encrypted off-host backups, test restores against recovery objectives, and set a retention policy. |
| Monitoring and alerts | Prometheus and a provisioned Grafana dashboard. | Prometheus rules and Alertmanager deliver to a local receiver. | Route alerts to an external on-call destination and test delivery. |
| Availability and rollout | Single-host PostgreSQL and Redis. Container restart policies and a one-shot migration. | Same single-host dependency. Restart recovery was exercised locally. | Set CPU, memory, disk, and connection budgets. Rehearse rollback and database recovery on the target infrastructure. |

[Hardened configuration and recorded verification](local-rehearsal.md).

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
recorded source and machine. The CSV worker comparison covers 1,000 sales reports per run. The
20,000-job campaign uses noop handlers. [CSV worker scaling](benchmarks/README.md#csv-worker-scaling).

## Failure boundaries

Worker leases cover abandoned execution. A lost host or disk requires restoring PostgreSQL from
a backup and rebuilding Redis indexes. Cancellation cannot undo completed side effects.

See [the CSV demo](sales-report.md), [architecture](architecture/README.md), and
[operations](operations/README.md) for the implemented behavior and reproduction commands.
