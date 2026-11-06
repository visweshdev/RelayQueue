# Tests and reproducible experiments

Use Python 3.12 and Docker Engine/Compose v2 for real-service tests. No SQLite, fake Redis, queue
framework or in-memory broker substitutes are used. Testcontainers starts PostgreSQL 16 and
Redis 7, applies Alembic migrations, and resets only its isolated test database between tests.
If `TEST_DATABASE_URL` and `TEST_REDIS_URL` are supplied, **they must point to disposable test
instances**: tables and Redis indexes are cleared by the integration fixtures.

```sh
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m ruff check src tests bench migrations
python -m ruff format --check src tests bench migrations
python -m mypy --strict src
python -m pytest tests/unit -q
python -m pytest tests/unit tests/integration --cov=forgequeue --cov-report=term-missing --cov-report=xml --cov-fail-under=85
```

Without Docker, integration tests explicitly skip. Set `REQUIRE_DOCKER=1` to fail instead; CI
does this. The 85% gate remains active and is not waived because dependencies are unavailable.
Coverage includes branches, making the combined gate stricter than line-only coverage.

Real process chaos tests use an isolated random Compose project and port 18800. They kill real
workers, restart Redis with persistence disabled, stop/start PostgreSQL, drain with SIGTERM,
and compare actual leases with Redis TIME. Their fixtures tear down only that project.

```sh
RUN_CHAOS=1 python -m pytest tests/chaos -v
```

PowerShell: `$env:RUN_CHAOS='1'; python -m pytest tests/chaos -v`.
The repeated-crash test runs for two minutes and has bounded drain/cleanup deadlines.

## Benchmarks

Start a dedicated local Compose demo stack before these commands. Chaos/reliability benchmarks
intentionally disrupt its workers/Redis; do not point them at shared infrastructure.

| ID | Command | Evidence |
|---|---|---|
| P1 | `python -m bench.throughput --jobs 20000 --workers 4` | JSON successful jobs/min, logical submit latency, outcomes |
| P2 | `python -m bench.scaling --jobs 20000` | 1/2/4/8-worker JSON files and measured PNG chart |
| P3 | `python -m bench.latency --rates 100 --seconds 300` | Locust CSV and p95/p99 JSON |
| P4 | `python -m bench.latency --idle-samples 100` | Sequential, initially idle pickup samples |
| P5 | `python -m bench.latency --rates 25,50,100,150,200 --seconds 300` | First observed p95 crossing 100 ms, actual achieved RPS and failures |
| R1-R3 | `python -m bench.chaos_kill --jobs 10000 --duration 120 --interval 5` | Missing/terminal counts, lease-to-ready samples, observed duplicate lower bound |
| R4 | `python -m bench.reliability redis --jobs 100` | Restart + explicit index loss and final accounting |
| R5 | `python -m bench.reliability retry --jobs 100` | 50% flaky workload reaches succeeded/dead |
| R6 | `python -m bench.reliability graceful --jobs 100` | Stop/drain, no running rows, restart and final accounting |
| Monitoring | `python -m bench.monitoring` | All worker scrape targets up; provisioned dashboard loaded |

All scripts write real measurements under `bench/results/`; saved JSON files contain the observed performance measurements. CPU/RAM/OS/Python/Docker version accompanies benchmark results.
Record Docker Desktop CPU/RAM allocation separately when it differs from host specs. Throughput
includes submission and polling overhead; noop success is the numerator. Under-load pickup in P1
is not the idle P4 experiment. Latency runs use one request/second per Locust user and report actual
RPS; setting 100 users does not establish an achieved rate of 100 under saturation. Above the default
200/s rate limit, 429s indicate admission control, not worker capacity. Adjust RATE_LIMIT_PER_S and
record it before using higher P5 loads. Keep failures alongside latency percentiles.

R3 does not count every lease expiration as a duplicate. It counts lease-expired attempts with a
durable handler-completed audit, and explicitly reports the observation limit. R2 excludes exhausted
dead attempts which are deliberately never requeued, and uses captured post-kill Redis deadlines.
Charts and screenshots must come from actual runs. No fabricated chart, Grafana screenshot or GIF
is included. `python -m bench.demo` supplies a terminal demo; use reduced, documented lease settings
or edit a real recording to fit a 20-second GIF.

## Windows local tooling

If Docker Desktop is installed per user but absent from the current shell PATH:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
$env:REQUIRE_DOCKER = '1'
.venv\Scripts\python.exe -m pytest tests/unit tests/integration --cov=forgequeue --cov-fail-under=85
```

`python -m bench.record_demo` captures actual stdout with monotonic timestamps into
`bench/results/demo-recording.json` and renders a time-compressed terminal GIF. It requires
Pillow (included through the locked matplotlib development dependencies). The demo checks an
actual killed owner's attempt history and final job counts before creating the GIF.
Use `--output latency-p3.json` and `--output latency-p5.json` to preserve separate latency runs.

## Container load generator

The final P1/P2/P3/P5 measurements use a Linux load-generator container on the same Docker
network as the services. On this Windows host, batches of 32 health requests took roughly
0.5 seconds even with reused connections; host client overhead limited an initial throughput
run. Those preliminary runs were interrupted and are not reported as complete benchmarks.

```sh
docker build -f deploy/Dockerfile.bench -t forgequeue-bench:local .
python -m bench.scaling --jobs 20000 --container-client
python -m bench.latency --rates 100 --seconds 300 --output latency-p3.json --container-client
python -m bench.latency --rates 25,50,150,200 --seconds 60 --output latency-p5.json --container-client
```

Scaling runs the same P1 workload at 1/2/4/8 workers; `scaling-4.json` is the four-worker P1
measurement. The generator uses the pinned development dependencies, calls `http://api:8000`,
and mounts only the results directory. Docker control remains on the host. Results retain host
CPU/RAM, Docker allocation, runtime image ID, source digest, and the load-generator OS/Python.
The default network is `forgequeue_default`; override `BENCH_DOCKER_NETWORK` for another name.
Rebuild the benchmark image after editing its Python files. Host-mode commands remain available.
P3 is a full five-minute run; P5 uses sixty-second steps and reports actual achieved rates and errors.

## Resumable acceptance campaign

After starting Compose and building the benchmark image, run:

```sh
python -m bench.acceptance --resume
```

This performs the real demo, monitoring, R4/R5/R6, the 10,000-job crash campaign, idle pickup,
five-minute P3, step-load P5 and 20,000-job scaling at 1/2/4/8 workers. It may take around an
hour on a laptop. `bench/results/campaign.json` records each completed stage and the source/image
fingerprint; `tmp/acceptance-*.log` contains progress. Resuming reuses completed stages only when
the runtime fingerprint matches. Successful process exit means the experiment ran, not that
every numerical performance target passed. Read the measurements and acceptance report.

## Linux verification on Docker Desktop

The same 157 unit/integration tests also passed inside the Linux Python 3.12.16 benchmark
image, with 90.28% combined coverage and no skips. This is a local test run, not a remote
GitHub Actions result. The fixture starts isolated PostgreSQL/Redis containers through the
Docker socket; it does not truncate the application database.

```powershell
docker run --rm --mount "type=bind,source=$($PWD.Path),target=/workspace" --mount "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock" --workdir /workspace --env PYTHONPATH=/workspace/src --env REQUIRE_DOCKER=1 --env TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal forgequeue-bench:local python -m pytest tests/unit tests/integration -q --cov=forgequeue --cov-report=json:tmp/linux-coverage.json --junitxml=tmp/linux-test-results.xml --cov-fail-under=85
```

On native Linux, use the normal host test command above instead of the Docker Desktop
host override. Run performance experiments after tests finish to avoid resource contention.
