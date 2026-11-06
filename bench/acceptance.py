"""Run and resume the full local acceptance experiments without fabricating SLO passes."""

import argparse
import json
import os
import subprocess
import sys
import time

from bench.common import ROOT, machine

STEPS = [
    ("demo", ["-m", "bench.record_demo"]),
    ("monitoring", ["-m", "bench.monitoring"]),
    ("redis", ["-m", "bench.reliability", "redis", "--jobs", "100"]),
    ("retry", ["-m", "bench.reliability", "retry", "--jobs", "100"]),
    ("graceful", ["-m", "bench.reliability", "graceful", "--jobs", "100"]),
    ("crashes", ["-m", "bench.chaos_kill", "--jobs", "10000", "--duration", "120"]),
    ("pickup", ["-m", "bench.latency", "--idle-samples", "100"]),
    (
        "latency-p3",
        [
            "-m",
            "bench.latency",
            "--rates",
            "100",
            "--seconds",
            "300",
            "--output",
            "latency-p3.json",
            "--container-client",
        ],
    ),
    (
        "latency-p5",
        [
            "-m",
            "bench.latency",
            "--rates",
            "25,50,150,200",
            "--seconds",
            "60",
            "--output",
            "latency-p5.json",
            "--container-client",
        ],
    ),
    ("scaling", ["-m", "bench.scaling", "--jobs", "20000", "--container-client", "--resume"]),
]


def main(resume):
    metadata = machine()
    if not metadata["runtime_image_id"]:
        raise SystemExit("Start Docker and the local Compose stack before acceptance experiments")
    path = ROOT / "bench/results/campaign.json"
    fingerprint = [metadata["source_sha256"], metadata["runtime_image_id"]]
    progress = {
        "fingerprint": fingerprint,
        "machine": metadata,
        "completed": [],
        "state": "running",
    }
    if resume and path.exists():
        previous = json.loads(path.read_text())
        if previous["fingerprint"] == fingerprint:
            progress["completed"] = previous["completed"]
    done = {row["stage"] for row in progress["completed"] if row["exit_code"] == 0}
    logs = ROOT / "tmp"
    logs.mkdir(exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, arguments in STEPS:
        if name in done:
            print(f"Reusing completed experiment: {name}", flush=True)
            continue
        progress["current"] = name
        path.write_text(json.dumps(progress, indent=2) + "\n")
        print(f"START {name}", flush=True)
        started = time.monotonic()
        with (logs / f"acceptance-{name}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, "-u", *arguments],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        progress["completed"].append(
            {
                "stage": name,
                "exit_code": result.returncode,
                "duration_s": time.monotonic() - started,
            }
        )
        print(f"END {name}: exit {result.returncode}", flush=True)
        if result.returncode:
            progress["state"] = "failed"
            path.write_text(json.dumps(progress, indent=2) + "\n")
            raise SystemExit(result.returncode)
    progress["state"] = "completed"
    progress["note"] = (
        "Experiments completed; exit code zero is not proof that numerical SLOs passed."
    )
    path.write_text(json.dumps(progress, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    main(parser.parse_args().resume)
