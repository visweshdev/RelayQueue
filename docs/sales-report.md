# CSV sales reports

A small retailer can submit a sales export and retrieve a durable per-product summary without
holding an HTTP request open while it runs. This is a working reference use case, not a claim
of production adoption. The worker reads the uploaded CSV content, validates every row, and
returns exact decimal revenue totals. No external service or paid account is required.

## Run the demonstration

Prerequisites: Docker with Compose v2, an internet connection for the first image build, and
free local ports 8000, 3000 and 9090. From the repository root:

```sh
docker compose up -d --build --wait --wait-timeout 180
docker compose --profile demo run --rm demo
```

The first build downloads dependencies; later runs reuse the image. The demo should finish in
under two minutes after the stack is ready. It prints real job states and attempt counts, then:

- Produces a report for `examples/sales.csv`: **3 rows, 6 units, revenue 50.10**.
- Submits the same content again and verifies that it returns the same job ID.
- Submits an intentionally invalid CSV, waits for two failed attempts, and verifies dead-letter
  status and both attempt-history records. This is a real validation failure, not random fault injection.

The dead-letter job is expected: the command exits successfully only after checking this outcome.
Every demo rerun creates one new invalid-file job; the valid report is reused by content hash.
Inspect either printed ID at `/v1/jobs/{id}` using `X-API-Key: dev-key-1`, or use the
[interactive API documentation](http://localhost:8000/docs).

Stop with `docker compose down` to retain data. Use `docker compose down --volumes` only to
deliberately erase the current stack's data. Nightly CI runs this demo on a fresh stack.

## Submit your own file

CSV columns, in order, are `sku,quantity,unit_price`. Example:

```csv
sku,quantity,unit_price
COFFEE,2,12.50
TEA,3,4.20
COFFEE,1,12.50
```

With the Python development environment installed:

```sh
python -m relayqueue.examples.sales_report examples/sales.csv --output report.json
```

For Docker-only usage, mount a file into the demo container (replace the absolute host path):

```sh
docker compose --profile demo run --rm -v /absolute/path/sales.csv:/input.csv:ro demo /input.csv
```

The client uploads UTF-8 file content in the existing JSON job payload; it does not expose a
multipart-upload endpoint or accept arbitrary filesystem paths on workers. Use `--url` and the
`API_KEY` environment variable for another deployment. If `API_KEYS` is customized in Compose,
set `API_KEY` to one matching key for the demo client.

Submit directly through the existing API with task `sales_report` and payload
`{"content":"sku,quantity,unit_price\nA,1,0.10\n"}`. Results include the source SHA-256, row and
unit counts, total revenue, and sorted per-product aggregates. Revenue is a decimal string;
all rows must use the same currency, with no conversion, tax, refunds, or discount logic.

## Guarantees and limits

- Maximum file size in the client: 48,000 bytes; maximum 1,000 data rows and 100 distinct SKUs.
  The API's independent 65,536-byte encoded JSON limit still applies (escaping can expand data).
- SKUs contain 1–64 ASCII letters, digits, underscores or hyphens. Quantities are integers
  1–999999; prices are 0.00–99999999.99 with exactly two decimal places. A single invalid row
  fails the entire report. Fix the source and submit again; errors intentionally do not echo rows.
- Progress means observed queue state and attempt history. There is no row-level percentage,
  resumable parsing checkpoint, or streaming download. Small reports can finish between polls.
- The client uses `sales-report:v1:<sha256>` as its submission key. Identical content in the same
  queue returns the existing job. Changing formatting changes the hash. A dead or cancelled job
  with the same key is not reset by resubmission. Only dead jobs can be manually retried;
  creating a replacement for a cancelled job requires a new idempotency key.
- Execution is at least once. This handler is deterministic and has no external side effects,
  so replay computes the same report. Job completion is still guarded by the queue's lease token.
  Adding email, payment, or object-store writes requires downstream idempotency or an outbox;
  the submission key alone does not make those effects exactly once.
- All handler failures currently consume the configured retry budget, including invalid input.
  The demo intentionally shows this limitation. Production adapters should distinguish permanent
  validation errors from transient failures before adding expensive side effects.
- Files and reports are stored in PostgreSQL job payloads/results and returned to any valid API
  key holder. There is no tenant isolation, retention scheduler, encryption-at-rest setup, or
  per-user authorization. Do not submit sensitive customer exports to a shared/public demo.

For larger files, store immutable content in object storage, enqueue a content-addressed reference,
stream batches, and persist checkpoint progress with ownership checks. That requires a separate
storage, authentication, retention and retry design; it is not implemented here.
