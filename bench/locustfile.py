"""100 users at one request/second each targets 100 RPS; verify achieved rate in CSV."""

import os
from random import Random
from time import perf_counter
from uuid import uuid4

import gevent
from locust import HttpUser, task

phases = Random(42)


class Submitter(HttpUser):
    def wait_time(self):
        now = perf_counter()
        self.next_start = max(self.next_start + 1, now)
        return self.next_start - now

    def on_start(self):
        # Spread initial phases across a second instead of synchronizing every
        # user into a single recurring burst. P3 specifies a sustained rate.
        gevent.sleep(phases.random())
        self.next_start = perf_counter()

    @task
    def submit(self):
        self.client.post(
            "/v1/jobs",
            headers={"X-API-Key": os.getenv("API_KEY", "dev-key-1")},
            json={"task": "noop", "idempotency_key": uuid4().hex},
            name="POST /v1/jobs",
        )
