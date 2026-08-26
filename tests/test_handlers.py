"""Unit tests for handlers — the ``targets`` listing without subprocess or host.

Mirrors tmq's tests/test_handlers.py shape: drive ``handle_targets`` directly
with a small in-memory settings object and assert the reply shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from aoe_fleet import handlers


def _settings(registry_path: str = "") -> handlers.Settings:
    return handlers.Settings(registry_path=registry_path)


def test_targets_human_format_lists_columns():
    result = handlers.handle_targets({"args": {}}, settings=_settings())
    assert result["count"] >= 20
    text = result["text"]
    # header row + one line per target
    lines = text.splitlines()
    assert lines[0].split() == ["name", "host", "dir", "harness", "model"]
    assert any("home-portal" in line for line in lines[1:])


def test_targets_machine_format_returns_summary_list():
    result = handlers.handle_targets({"args": {"format": "machine"}}, settings=_settings())
    targets = result["targets"]
    assert isinstance(targets, list)
    assert len(targets) >= 20
    first = targets[0]
    assert set(first.keys()) == {"name", "host", "dir", "harness", "model"}


def test_targets_respects_user_override(tmp_path: Path):
    overlay = tmp_path / "targets.json"
    overlay.write_text(
        json.dumps(
            {
                "home-portal": {
                    "host": "local",
                    "dir": "/custom/home-portal",
                    "harness": "opencode",
                    "model": "opus",
                },
            }
        ),
        encoding="utf-8",
    )
    result = handlers.handle_targets(
        {"args": {"format": "machine"}},
        settings=_settings(registry_path=str(overlay)),
    )
    by_name = {t["name"]: t for t in result["targets"]}
    assert by_name["home-portal"]["harness"] == "opencode"
    assert by_name["home-portal"]["dir"] == "/custom/home-portal"
