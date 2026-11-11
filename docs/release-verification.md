# Delivery verification — November 11, 2026

## Implemented use case

The [CSV sales-report demo](sales-report.md) uses real asynchronous jobs and persistent results.
It ran against the rebuilt local Docker stack and produced 3 rows, 6 units and revenue `50.10`.
Submitting the same file returned the same job ID. An invalid file recorded two failed attempts
and reached the dead-letter queue. No synthetic success result or production-user claim is used.

## Validation

- 178 unit/integration tests passed locally, with 88.78% branch-inclusive coverage (85% required).
- All 21 new sales-report tests passed; the handler has 100% measured coverage.
- Ruff lint/format and strict mypy passed; the runtime Docker image built and started successfully.
- GitHub CI passed for sales-report commit `918a5b4`:
  [CI run](https://github.com/visweshdev/RelayQueue/actions/runs/42970911948).
- The preceding six-test reliability suite and full nightly workflow passed on `c0efe99`:
  [nightly run](https://github.com/visweshdev/RelayQueue/actions/runs/42969147032).
- Nightly now includes the CSV demo. Current runs are available in
  [GitHub Actions](https://github.com/visweshdev/RelayQueue/actions).

## Local deployment cleanup

Before and after copying the stopped database to the new volume, PostgreSQL contained exactly
372,073 jobs. The demo subsequently added its own jobs. PostgreSQL, Redis and Grafana now use
RelayQueue-named volumes; their original volumes remain as offline rollback copies. The Grafana
database was backed up, its existing dashboard UID was migrated, and the local demo password
was aligned with configuration. The live monitoring check verified six healthy scrape targets,
four workers and dashboard UID `relayqueue`.

The retained copies are not a continuous backup solution. See the
[migration/rollback guidance](operations/README.md#compose-volume-migration) before removing them.

## Scope of evidence

Historical throughput/latency charts retain their original workload, machine and source
fingerprints. These application additions have not been rerun through the full scaling campaign.
The local deployment is not a public hosted service. Shared keys, single-node storage and lack
of retention/tenant isolation remain explicit [production limitations](production-readiness.md).
