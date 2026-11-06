from prometheus_client import Counter, Gauge, Histogram

SUBMITTED = Counter("fq_jobs_submitted", "Durably accepted jobs", ["queue", "task", "priority"])
COMPLETED = Counter("fq_jobs_completed", "Attempt outcomes", ["queue", "task", "outcome"])
DURATION = Histogram("fq_job_duration_seconds", "Attempt duration", ["queue", "task"])
PICKUP = Histogram(
    "fq_pickup_latency_seconds",
    "Creation to execution",
    ["queue", "priority"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 5, 30, 60),
)
DEPTH = Gauge("fq_queue_depth", "Durable queue depth", ["queue", "priority", "state"])
EXPIRED = Counter("fq_lease_expired", "Expired execution leases", ["queue"])
DUPLICATES = Counter(
    "fq_duplicate_executions", "Discarded stale completion attempts", ["queue", "task"]
)
ACTIVE = Gauge("fq_workers_active", "Workers with recent heartbeat")
HTTP = Histogram("http_request_duration_seconds", "HTTP duration", ["route", "method", "status"])
