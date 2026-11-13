# Dashboard regression checks

The browser suite uses pinned Playwright Chromium and the real development API, database,
and workers. It checks delayed sample selection, refresh during polling, CSV submission and
results, pagination preservation, search, same-tab navigation, mobile overflow, network-error
recovery, and disconnect behavior.

From the repository root, with Node.js 22 or newer and Docker running:

```sh
npm ci
npx playwright install chromium
docker compose up -d --build --wait --wait-timeout 180
npm run test:browser
```

On Linux CI, use `npx playwright install --with-deps chromium` to install browser system
libraries too. The default URL is `http://localhost:8000`; `RELAYQUEUE_URL` can override it.
The checks use the development key `dev-key-1` and create 13 noop fixtures plus a CSV report.
Run them on a development/test stack, not a tenant deployment or customer dataset.

Only the sample-response and request-failure cases intercept requests. Successful job
processing uses the real API and workers. The two race tests deliberately control response
ordering rather than relying on a naturally slow network.

Screenshots and a Playwright trace are saved under ignored `output/browser-checks/`.
On failure, `failure.png` captures the current page. Inspect the trace with:

```sh
npx playwright show-trace output/browser-checks/trace.zip
```

GitHub CI runs a separate `browser` job, uploads the `browser-checks` artifact (including
container logs), and removes only that runner's disposable stack after the run. The existing
`verify` job continues to enforce Python checks, coverage and image building.

## Infrastructure restart checks

`tests/unit/test_deployment_config.py` checks that every long-running hardened service uses
`unless-stopped`, migrations remain one-shot, and only the loopback gateway publishes a port.
Explicitly stopped services stay stopped; use Compose to start them again.

A local November 13, 2026 rehearsal exited Redis using its authenticated shutdown command.
Docker reported restart count 1 and a running container; the HTTPS verification script then
passed tenant-boundary and CSV-result checks. This verifies Redis process recovery, not a
full host reboot or high-availability failover.

The same local validation run passed 186 Python unit/integration tests with 88.54% coverage.
