# Implementation progress

Updated 2026-11-06. Local implementation, tests, all benchmark experiments, chart, screenshot and
recorded GIF are delivered. **Acceptance remains FAIL for P3; remote CI is NOT RUN.**

Windows: 157 tests passed, 89.93% coverage. Linux Python 3.12.16: 157 passed, 0 skipped, 108.84 s; combined coverage 90.28%.
R1: 10,000 succeeded, zero missing. P1: 4,521.405 jobs/min. P2: 3.26x
one-to-four-worker speedup. P3: p95 630 ms/p99 910 ms at 99.856 RPS, zero failures.
R2-R6 and P4/P5 evidence are summarized in [final report](final-report.md).

## Resume information

Use Python 3.12 (`.venv\Scripts\python.exe`), not global Python 3.14. Docker is under
`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`. The complete campaign command is
`python -m bench.acceptance --resume`; state is `bench/results/campaign.json` and logs are
`tmp/acceptance-*.log`. Cache reuse requires matching source/image fingerprints. Old temporary
orchestrator scripts are obsolete. See [testing](testing.md) for testcontainers environment.

Source: `4576bdd376a2bc9d9d9ba4ad0d075263ae5a146a0729c0e9cbbb049944d220cf`.
Image: `sha256:802e9d4ccbf6de78d5ea6538e7351e9f54d91d63679a62b82057db9a641b80b7`.

## Remaining actions

Profile transaction/coordination latency and shared-host contention, improve measured bottlenecks,
then rerun P3 and scaling. Run GitHub CI once a repository exists. Preserve durability and explicit
at-least-once limitations. Never replace observed failures with claims based on code presence.
No acceptance experiment remains unexecuted. The local Linux check is not a remote CI run.

Docker startup was repaired by preserving its stale IPC directory at
`%LOCALAPPDATA%/docker-secrets-engine.stale-20261105`; no volumes or database contents were removed.
