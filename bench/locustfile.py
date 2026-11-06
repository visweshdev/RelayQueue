"""100 users at one request/second each targets 100 RPS; verify achieved rate in CSV."""

import os
from random import Random
from uuid import uuid4

import gevent
from locust import HttpUser, constant_throughput, task

phases = Random(42)


class Submitter(HttpUser):
    wait_time = constant_throughput(1)

    def on_start(self):
        # Spread initial phases across a second instead of synchronizing every
        # user into a single recurring burst. P3 specifies a sustained rate.
        gevent.sleep(phases.random())

    @task
    def submit(self):
        self.client.post(
            "/v1/jobs",
            headers={"X-API-Key": os.getenv("API_KEY", "dev-key-1")},
            json={"task": "noop", "idempotency_key": uuid4().hex},
            name="POST /v1/jobs",
        )
