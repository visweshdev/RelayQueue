"""Create a PostgreSQL custom-format backup and prove it restores in an isolated container."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=300, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="compose.yaml")
    parser.add_argument("--output", type=Path, default=Path("backups"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.output / f"relayqueue-{stamp}.dump"
    prefix = ["docker", "compose", "-f", args.compose, "exec", "-T", "postgres"]
    sql = (
        "SELECT json_build_object('jobs',(SELECT count(*) FROM jobs),"
        "'attempts',(SELECT count(*) FROM job_attempts),"
        "'effects',(SELECT count(*) FROM side_effects))"
    )

    def counts():
        # Environment is read inside the container, never printed or copied into host arguments.
        result = command(
            [
                *prefix,
                "sh",
                "-ec",
                'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
                "--",
                sql,
            ]
        )
        return json.loads(result.stdout)

    before = counts()
    dump = command(
        [
            *prefix,
            "sh",
            "-ec",
            'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl',
        ]
    )
    with target.open("xb") as stream:
        stream.write(dump.stdout)
    target.chmod(0o600)
    after = counts()
    if before != after:
        raise SystemExit(
            "Source changed during backup. Backup retained; pause submissions and rerun validation."
        )
    name = f"relayqueue-restore-{uuid4().hex[:10]}"
    started = time.monotonic()
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "postgres:16-alpine",
            ]
        )
        for _ in range(60):
            probe = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Restore container did not become ready")
        command(
            [
                "docker",
                "exec",
                "-i",
                name,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
            ],
            input=dump.stdout,
        )
        restored = json.loads(
            command(
                ["docker", "exec", name, "psql", "-U", "postgres", "-d", "postgres", "-Atc", sql]
            ).stdout
        )
        if restored != before:
            raise RuntimeError("Restored counts differ from the stopped/quiescent source")
        report = {
            "verified_at": stamp,
            "backup_file": target.name,
            "sha256": hashlib.sha256(dump.stdout).hexdigest(),
            "bytes": len(dump.stdout),
            "source_counts": before,
            "restored_counts": restored,
            "restore_seconds": round(time.monotonic() - started, 2),
            "verified": True,
        }
        target.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


if __name__ == "__main__":
    main()
