# Architecture and ownership

```mermaid
flowchart LR
    C[Client] -->|REST, API key| A[FastAPI]
    A -->|commit job first| P[(PostgreSQL 16)]
    A -->|publish ID after commit| R[(Redis 7)]
    R -->|Lua claim + unique lease token| W[Independent workers x4]
    W -->|row lock + attempt token| P
    W --> H[Async handlers / isolated CPU process]
    W -->|Lua heartbeat + compare-delete| R
    S[Scheduler / Reaper] -->|due jobs + durable reconciliation| P
    S -->|repair ready/scheduled/lease indexes| R
    M[Prometheus] -->|scrape API, each worker, reaper| A
    M --> W
    M --> S
    G[Grafana] --> M
```

PostgreSQL owns definitions, lifecycle and attempts. Redis contains IDs, priority indexes,
scheduled timestamps, cancellation hints, liveness hints and lease tokens. There is no
cross-store transaction. All durable state decisions lock the job row, validate the central
transition graph, and use the current attempt token. Handler execution holds no database lock.

```mermaid
stateDiagram-v2
    [*] --> queued
    [*] --> scheduled
    scheduled --> queued: due
    queued --> running: valid lease + durable claim
    running --> succeeded: result committed
    running --> failed_retrying: error / timeout / expired lease
    failed_retrying --> queued: backoff elapsed
    running --> dead: retry budget exhausted
    dead --> queued: explicit manual retry
    queued --> cancelled
    scheduled --> cancelled
    failed_retrying --> cancelled
    running --> cancelled: stop acknowledged / ownership recovered
```

Workers discover configured queues in rotating order; claims within a queue prioritize 0, 1, 2.
Every tenth successful claim for a worker reverses this to 2, 1, 0. Redis owns this counter, so
concurrent slots cannot independently drift from the starvation guard. Empty polls do not count.

Each worker has its own metrics HTTP server on container port 9100. Prometheus DNS discovery
resolves all `worker` replicas, retaining one target per IP. The API serves its own metrics on
8000, and the reaper owns system gauges. The dashboard sums event counters across targets.
