# Acceptance gates

Evaluated 2026-11-06. PASS means executed, NOT RUN means unexecuted, FAIL means an observed
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
| P1-P5 / R1-R6 targets | FAIL | All executed; P3 misses targets; details below |
| README/design/matrix/architecture | PASS | Files present and reviewed |
| Actual dashboard screenshot | PASS | output/playwright/grafana.png; visually inspected |
| Actual demo GIF | PASS | Actual recorded 20-second GIF and timestamped event log |

## Measured performance

| Experiment | Target | Observed result |
|---|---|---|
| P1: 20,000 noop jobs / four workers | >=1,000 jobs/min | PASS: 4,521.405 jobs/min; all succeeded |
| P2: 1/2/4/8 workers | Close to linear from 1 to 4 | PASS (measurement): 3.26x speedup, 81.4% of ideal; qualitative target has no tolerance |
| P3: 100 requests/s for 300 s | p95 <50 ms; p99 <100 ms | FAIL: 99.856 RPS, p95 630 ms, p99 910 ms; zero failures |
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

P3 requires performance improvements and repeat measurements. Remote CI requires an actual
GitHub repository. See [final report](final-report.md) for evidence and limitations.
