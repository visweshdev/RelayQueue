# Clean installation and worker recovery

[RelayQueue](../README.md) / Clean installation and worker recovery

You will build a local stack, run a sales CSV report, kill the worker executing a file checksum,
verify the retried result, and reproduce the core tests.

## Start with a clean clone

Install Git and Docker Desktop (Linux containers) or Docker Engine with the Compose plugin.
Confirm that `docker version` lists a server and that `docker compose version` works. The first
build downloads container images and Python packages. The commands below reserve loopback ports
18000, 13000, and 19090 so they can run alongside the default stack. Use unused ports if these
are occupied, and run subsequent Compose commands in the same shell.

```sh
git clone https://github.com/visweshdev/RelayQueue.git
cd RelayQueue
export RELAYQUEUE_API_PORT=18000 RELAYQUEUE_GRAFANA_PORT=13000 RELAYQUEUE_PROMETHEUS_PORT=19090
export RELAYQUEUE_IMAGE=relayqueue:release-check
export LEASE_MS=10000 HEARTBEAT_MS=2000 REAPER_INTERVAL_MS=1000
docker compose -p relayqueue-release-check up -d --build --wait --wait-timeout 240
docker compose -p relayqueue-release-check --profile demo run --rm demo
```

PowerShell uses these assignments instead of the three `export` lines:

```powershell
$env:RELAYQUEUE_API_PORT = '18000'
$env:RELAYQUEUE_GRAFANA_PORT = '13000'
$env:RELAYQUEUE_PROMETHEUS_PORT = '19090'
$env:RELAYQUEUE_IMAGE = 'relayqueue:release-check'
$env:LEASE_MS = '10000'
$env:HEARTBEAT_MS = '2000'
$env:REAPER_INTERVAL_MS = '1000'
```

For the published source, add `--branch v0.1.0` to the clone command. Compose applies the database
schema during startup. If startup fails, inspect `docker compose -p relayqueue-release-check ps -a`
and `docker compose -p relayqueue-release-check logs --tail 100`.

Open the [dashboard](http://127.0.0.1:18000/) and select **Try local demo**. The terminal demo
reports **3 rows, 6 units, and revenue 50.10** for the valid CSV, the same job ID on duplicate
submission, and a dead letter with two failed attempts for the deliberately invalid CSV. The
development API key is `dev-key-1`. Grafana uses `admin` and `relayqueue-local` locally.

## Recover an interrupted checksum

A worker can verify the integrity of a file after upload without blocking the request that queued
it. Here the existing `cpu_hash` handler runs repeated SHA-256 rounds over the sample file bytes
so there is time to interrupt it. The checksum is deterministic and has no external side effects.

Install Python 3.12 for the drill and test commands. Run these commands from the repository root.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m bench.checksum_recovery --project relayqueue-release-check
```

On Windows, replace the first two lines with `py -3.12 -m venv .venv` and
`.\.venv\Scripts\Activate.ps1`, or use `.venv\Scripts\python.exe` for the remaining commands
without activating the environment.

The drill discovers the API and monitoring ports from the named project. It submits the file,
waits for a worker to claim it, and sends that worker SIGKILL. The reaper then records
`lease_expired` and requeues the job. The script requires a successful second attempt, compares
the returned digest against a local computation, and waits for Prometheus to observe an increase
in `fq_lease_expired_total`. Use this fault injection only in the disposable project.

In the November 22 Windows Docker Desktop run, the same job ID went from an expired attempt to
a successful retry in **15.813 s** from submission to observed success. Prometheus recorded the
counter moving from **0 to 1**. The restarted container used a new worker ID. The command prints
its job ID for lookup in the dashboard. Inspect lease expirations in
[Grafana](http://127.0.0.1:13000/) or query `sum(fq_lease_expired_total)` in
[Prometheus](http://127.0.0.1:19090/).

[Recorded checksum result and attempt timestamps](../bench/results/checksum-recovery.json) ·
[Recorded dashboard walkthrough](../output/playwright/dashboard-demo.webm)

The observed delay uses a 10-second lease and a one-second reaper interval. Recovery under
other settings or failure conditions can take longer. The checksum depends on file bytes,
including CRLF versus LF line endings.

## Reproduce the core checks

Run the following from the same Python 3.12 environment. Testcontainers creates its own
PostgreSQL and Redis instances.

```sh
REQUIRE_DOCKER=1 python -m pytest tests/unit tests/integration --cov=relayqueue --cov-fail-under=85
python -m ruff check src tests bench migrations
python -m ruff format --check src tests bench migrations
python -m mypy --strict src
```

For PowerShell, run `$env:REQUIRE_DOCKER = '1'` before the pytest command and omit the inline
assignment. Testcontainers uses the default Docker endpoint. If Windows uses a separate Docker
Desktop Linux endpoint, set `DOCKER_HOST` as described in the [Windows testing notes](testing.md#windows-local-tooling).

When done, `docker compose -p relayqueue-release-check down` stops the drill stack and keeps
its volumes. Add `--volumes` only to intentionally erase this disposable project's data.

## Share independent install feedback

If you are trying RelayQueue for the first time, please record your release tag, OS, Docker and
Compose versions, and whether the CSV demo, checksum drill, and core tests passed. For any
failure, include the exact command and relevant output with secrets and payloads redacted.
[Open a feedback issue](https://github.com/visweshdev/RelayQueue/issues/new).
