"""Deployment invariants for the isolated local HTTPS stack."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_long_running_hardened_services_restart_but_migrations_do_not():
    config = yaml.safe_load((ROOT / "deploy/compose.hardened.yaml").read_text())
    services = config["services"]
    assert services["migrate"]["restart"] == "no"
    for name, service in services.items():
        if name != "migrate":
            assert service.get("restart") == "unless-stopped", name


def test_hardened_stack_only_publishes_loopback_gateway():
    config = yaml.safe_load((ROOT / "deploy/compose.hardened.yaml").read_text())
    published = {
        name: service["ports"]
        for name, service in config["services"].items()
        if service.get("ports")
    }
    assert published == {"gateway": ["127.0.0.1:8443:443"]}
