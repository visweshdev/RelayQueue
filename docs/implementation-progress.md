# RelayQueue progress

Updated November 10, 2026. Approved package rename completed: relayqueue imports, packaging, entry points, API and dashboard. Docker volumes reuse the existing storage names to preserve data.

Corrected sustained P3: 300 seconds, 100.000 RPS, p95 35 ms, p99 50 ms, zero failures. Old Locust startup jitter was cancelled by its pacing clock, causing synchronized bursts. Old P3/P5 measurements remain historical burst-load evidence. Uvicorn standard runtime and async repository dependency are enabled; durability unchanged.

157 Linux unit/integration tests pass, 90.28% coverage. Lint, format, strict types and relayqueue wheel pass. Remote CI remains unrun without a repository. See final-report.md and bench/results/latency-relayqueue-p3.json.
