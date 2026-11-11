# RelayQueue progress

Updated November 11, 2026. Approved package rename completed: relayqueue imports, packaging, entry points, API and dashboard. Docker volumes now use RelayQueue names. Local data migration is complete; originals remain available for rollback.

Corrected sustained P3: 300 seconds, 100.000 RPS, p95 35 ms, p99 50 ms, zero failures. Old Locust startup jitter was cancelled by its pacing clock, causing synchronized bursts. Old P3/P5 measurements remain historical burst-load evidence. Uvicorn standard runtime and async repository dependency are enabled; durability unchanged.

157 Linux unit/integration tests pass, 90.28% coverage. Lint, format, strict types and relayqueue wheel pass. Remote CI and Nightly reliability passed on commit `c0efe99` on November 11, 2026. See final-report.md and bench/results/latency-relayqueue-p3.json.

Sales-report delivery: 178 unit/integration tests pass with 88.78% coverage. The Docker CSV demo verifies totals, duplicate submissions and two failed attempts before dead-lettering. See [verification](release-verification.md).
