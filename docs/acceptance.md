# Acceptance gates

Updated 2026-11-10. PASS means executed, NOT RUN means unexecuted, FAIL means an observed
failure, INCOMPLETE means a missing deliverable. The project is not acceptance-complete.

| Gate | Result | Evidence |
|---|---|---|
| Complete PRD reviewed | PASS | 12 pages extracted/rendered; 20-section matrix |
| Python 3.12 package builds | PASS | Local 3.12.14; wheel includes six Lua scripts |
| No prohibited queue framework | PASS | Source/dependencies inspected |
| Ruff lint and formatting | PASS | Source, tests, benchmarks and migrations |
| Strict mypy | PASS | 36 source files |
| Unit tests | PASS | 123 cases |
| Central state machine | PASS | Exhaustive state pairs and manual gate |
| Typed handlers, bounded HTTP, async/CPU timeout | PASS | Actual child process and local HTTP server tests |
| Offline Alembic SQL | PASS | upgrade head --sql |
| Migration applied to PostgreSQL 16 | PASS | Testcontainers and Compose migration succeeded |
| Compose starts all services / four workers | PASS | All services healthy; Docker 29.9.2 / WSL 2.7.14 |
| API CRUD/history/stats and all codes | PASS | Real-service API integration tests |
| Durable submission and idempotency | PASS | Concurrent submissions and publish-outage recovery |
| Atomic claims: 1000 jobs / 8 claimants | PASS | 1000 unique attempts and successful jobs |
| Priority/starvation/delay | PASS | Real Redis/PostgreSQL tests |
| Retry/DLQ/manual rerun | PASS | Real execution and preserved attempt history |
| Durable cancellation/acknowledgment | PASS | Pending and running cancellation tests |
| Heartbeat/recovery/fencing | PASS | Expiry, stale completion and clock-drift tests |
| Redis restart / index reconstruction | PASS | Real restart and index-loss tests |
| SIGKILL/SIGTERM/PostgreSQL outage | PASS | Six chaos tests, 210.73 seconds; recovery build |
| Coverage >=85% | PASS | 89.93% Windows; Linux 90.28% |
| CI actually green | NOT RUN | Configured; no remote run |
| Live Prometheus and Grafana | PASS | Six healthy scrape targets including four workers |
| Benchmark CLIs/package | PASS | Help commands loaded |
| P1-P5 / R1-R6 experiments | PASS | P3 rerun November 10 passes; other evidence is historical and identified below |
| README/design/matrix/architecture | PASS | Files present and reviewed |
| Dashboard illustration | Updated | output/playwright/grafana.png; historical capture AI-edited for branding |
| Actual demo GIF | PASS | Actual recorded 20-second GIF and timestamped event log |

## Measured performance

| Experiment | Target | Observed result |
|---|---|---|
| P1: 20,000 noop jobs / four workers | >=1,000 jobs/min | PASS: 4,521.405 jobs/min; all succeeded |
| P2: 1/2/4/8 workers | Close to linear from 1 to 4 | PASS (measurement): 3.26x speedup, 81.4% of ideal; qualitative target has no tolerance |
| P3: 100 requests/s for 300 s | p95 <50 ms; p99 <100 ms | PASS: 100.000 RPS, p95 35 ms, p99 50 ms; zero failures (November 10) |
| P4: 100 idle samples | p95 <200 ms | PASS: p95 10.721 ms |
| P5: step load | Report first p95 >100 ms | PASS (measurement): already exceeded at 25 target RPS; threshold <=25 RPS |

## Measured reliability

| Experiment | Result | Evidence |
|---|---|---|
| R1: repeated SIGKILL | PASS: 10,000 succeeded, zero missing/nonterminal | chaos.json; 120 s crash window, five-second cadence |
| R2: expiry to ready <5 s | PASS: maximum 2.9945 s over 21 observations | chaos.json |
| R3: measure duplicate executions | PASS (measurement): observed 0.01% | One audited completed attempt later expired; lower bound only |
| R4: Redis restart/rebuild <60 s | PASS: 100 succeeded, zero missing; 31.360 s | reliability-redis.json; includes forced index loss and drain |
| R5: 50% flaky workload terminates | PASS: 96 succeeded, four dead; zero missing | reliability-retry.json |
| R6: graceful shutdown | PASS: 100 succeeded; no stranded running rows | reliability-graceful.json |

## Linux validation

Linux Python 3.12.16: 157 passed, 0 skipped, 108.84 s; combined coverage 90.28%.

## Remaining acceptance work

P3 now passes the corrected sustained-rate test. Remote CI requires an actual
GitHub repository. See [final report](final-report.md) for evidence and limitations.


## RelayQueue update — November 10

The package, imports, entry points, API title and dashboard title now use RelayQueue/`relayqueue`.
Docker project/image/network identifiers and dashboard UID use `relayqueue`.
The renamed Compose project uses RelayQueue-named volumes. Existing deployment volumes remain intact but must be migrated before starting with existing data. Database tables and migration IDs are unchanged. Historical
charts and demo recordings are rendered from the original data with RelayQueue branding. The historical dashboard image was AI-edited for RelayQueue branding and is illustrative; use the raw benchmark results for exact measurements and source fingerprints.

The final 300-second corrected P3 run achieved 100.000 RPS, p95 35 ms, p99 50 ms, zero failures.
See [raw result](../bench/results/latency-relayqueue-p3.json).
The earlier Locust pacing initialized its clock before startup jitter, cancelling that jitter
and synchronizing clients on later requests. The corrected per-client monotonic schedule keeps
phases spread, includes request time, and avoids catch-up bursts after overruns. Earlier 630 ms
P3 and P5 results describe burst-shaped load; they are retained, not relabeled as sustained tests.
The API also uses Uvicorn standard runtime dependencies and an async repository dependency.
No synchronous-commit, fsync, ownership or durability guarantees were weakened. Default API
process count remains two. The benchmark correction is the main observed improvement; the
35 ms result must not be represented as a 630-to-35 ms server-only optimization.

Remaining external gate: execute the configured workflow in a real GitHub repository.
