# Local HTTPS rehearsal

This separate Compose project binds only `127.0.0.1:8443`. It does not publish the
application to the internet or modify the ordinary development database.

Verified locally on November 12, 2026: 184 unit/integration tests passed, 88.60%
coverage, Ruff lint/format and strict mypy passed. Trusted TLS, tenant isolation,
desktop/mobile CSV submission and both firing/resolved outage alerts were exercised.
The [restore report](../bench/results/restore-verification.json) records 374,075 jobs
and 374,213 attempts restored successfully. Three detached pre-migration volumes
were archived under private `backups/`, their archives checked, then removed. Current
RelayQueue volumes remain. This verification does not claim a new GitHub Actions run.

## Dashboard

Run `docker compose up -d --build --wait`, open <http://localhost:8000/>, and connect
with `dev-key-1`, or select **Try local demo**. Open **Create report**, choose **Use
sample data** or upload `examples/sales.csv`, then select **Create report**: the result
is 6 units and 50.10 revenue. Job details open immediately in a dialog. Jobs, report
creation, the API guide and interactive API documentation navigate in the same tab.
Search and status filtering apply to loaded jobs. Loading older jobs pauses automatic
list refresh so pagination stays intact; Refresh returns to the newest jobs.
Live polling runs every five seconds while the tab is visible. A focused job-list
control also pauses background list replacement so keyboard navigation stays stable.
Open the URL rather than double-clicking `src/relayqueue/ui/index.html`; a file preview
cannot call the API. The dashboard keeps the access key in memory and clears it on reload.

[Recorded browser demo](../output/playwright/dashboard-demo.webm) |
[Desktop screenshot](../output/playwright/dashboard.png) |
[Mobile screenshot](../output/playwright/dashboard-mobile.png)

The **Try local demo** shortcut appears only on `localhost:8000` or `127.0.0.1:8000`.
For the isolated HTTPS deployment, enter the appropriate workspace key instead.

## Start the isolated deployment

From the repository root, with Python development dependencies installed:

```sh
python scripts/init_local_secrets.py
docker compose -f deploy/compose.hardened.yaml up -d --build --wait
docker compose -f deploy/compose.hardened.yaml cp gateway:/data/caddy/pki/authorities/local/root.crt .secrets/local-ca.crt
python scripts/verify_secure.py
```

Secret generation refuses to overwrite existing credentials. Skip that first command
on subsequent starts. Caddy uses a private local certificate authority. The verifier
explicitly trusts its exported public certificate and checks the hostname; it does not
disable TLS validation or install a system-wide trust root. A browser will require
explicit trust configuration to use <https://localhost:8443/> without a certificate warning.

The `.secrets/alpha.key` and `.secrets/beta.key` files contain separate workspace keys.
The server stores their SHA-256 digests mapped to queues. Reads, submissions, cancellation,
retry, listings and queue statistics are scoped to that queue. Worker inventory and public
diagnostics are blocked. This is application authorization over shared infrastructure:
tenants still share PostgreSQL, Redis and workers, without per-tenant fairness or hard
resource isolation. Anyone with container/database administrator access can access all data.

Compose mounts credentials as files; this is not a cloud secret manager. Protect `.secrets`
with host filesystem permissions (on Windows, use an account-restricted NTFS ACL; chmod
alone does not implement Unix permissions). Never commit or send this directory. For a
public host, use its managed secret backend to populate the same file paths.

To rotate a workspace key, generate a fresh random token, add its SHA-256 digest and queue
to `auth_policy.json`, recreate API containers, update the client, then remove the old
digest and recreate the API again. Database/Redis passwords additionally require changing
the live service credential and corresponding connection URL together during maintenance;
rerunning the initializer is not a rotation procedure.

## Retention and backup

The rehearsal prunes at most 1,000 succeeded/cancelled jobs older than 30 days per day.
Active and dead-letter jobs remain. Attempt history and the original idempotency record
are deleted with the job: submitting its key after retention may create a new job.
The batch cap bounds each deletion; monitor growth and adjust scheduling to the workload.
This policy does not prune the ordinary development stack.

```sh
docker compose -f deploy/compose.hardened.yaml exec api python -m relayqueue.retention --days 30 --limit 1000
python scripts/backup_restore.py --compose deploy/compose.hardened.yaml
```

Retention defaults to dry-run unless `--apply` is supplied. Backup creates a private
custom-format PostgreSQL dump, restores it into a disposable network-isolated container,
and compares job, attempt and effect counts. Pause submissions and allow active work to
drain for this count-based verification; concurrent writes cause it to refuse verification.
The restore does not replace the live database. It checks restore validity and row counts,
not byte-for-byte equality of every row or a full recovery-time objective.

Schedule the backup command with the host scheduler and monitor failures. Scheduling,
encrypted off-host storage, backup expiry and a real disaster recovery exercise remain
operator responsibilities; local dumps alone do not protect against host loss. Redis is
coordination state, rebuilt from PostgreSQL by the reaper. Preserve Grafana configuration
and dashboards separately if customized. Stop writers before a disaster restore into a
fresh database, run migrations, restart with empty Redis and verify jobs before resuming.

## Alerts

Prometheus evaluates unavailable targets, dead jobs and persistent backlog. Alertmanager
sends to a local receiver stored in the `alert-events` volume; no emails or external
messages are sent. Inspect it with:

```sh
docker compose -f deploy/compose.hardened.yaml exec alert-receiver cat /events/alerts.jsonl
```

To rehearse, stop the isolated reaper for over 90 seconds, inspect the firing event,
restart it, and inspect the resolved event. Configure an authenticated operator destination
before public use. Protect monitoring, add resource limits and capacity alerts, choose a
domain/public certificate, test provider backups and document rollback before deployment.

Stop this project with `docker compose -f deploy/compose.hardened.yaml down`.
Do not add `-v` unless deliberately discarding its data.

## Measured CSV workload

November 12, 2026; four local workers, 1,000 jobs each, concurrency 16, zero retries,
all results validated. Times include HTTP submission and result polling.

| CSV rows/job | Jobs/min | Submission p95 | Raw evidence |
| --- | ---: | ---: | --- |
| 3 | 2,249 | 936 ms | [JSON](../bench/results/sales-3-rows.json) |
| 1,000 | 1,899 | 1,120 ms | [JSON](../bench/results/sales-1000-rows.json) |

Reproduce with `python -m bench.sales_workload --help`. These single shared-machine runs
are not sustained-rate latency tests and do not establish the earlier 100-RPS latency SLO
for CSV workloads. Existing noop measurements remain separately labeled.
