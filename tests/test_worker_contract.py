"""JSON-RPC worker contract tests — exercise the protocol surface without a plugin host.

Mirrors tmq's tests/test_worker_contract.py: drive ``python -m aoe_fleet.worker``
over stdin/stdout ndjson and assert the JSON-RPC 2.0 replies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")


def run_worker(requests):
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    env = {**os.environ, "PYTHONPATH": SRC}
    proc = subprocess.run(
        [sys.executable, "-m", "aoe_fleet.worker"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env=env,
    )
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_targets_returns_shipped_defaults():
    responses = run_worker([{"jsonrpc": "2.0", "id": 1, "method": "bogocat.fleet.targets", "params": {}}])
    assert len(responses) == 1
    assert responses[0]["id"] == 1
    result = responses[0]["result"]
    text = result.get("text") or ""
    assert "home-portal" in text
    assert "distillery" in text
    assert result["count"] >= 20


def test_unknown_method_errors():
    responses = run_worker([{"jsonrpc": "2.0", "id": 2, "method": "bogocat.fleet.nope"}])
    assert responses[0]["error"]["code"] == -32601
    assert "bogocat.fleet.nope" in responses[0]["error"]["message"]


def test_notification_has_no_response():
    responses = run_worker([{"jsonrpc": "2.0", "method": "bogocat.fleet.targets"}])
    assert responses == []
