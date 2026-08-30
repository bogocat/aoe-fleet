"""Unit tests for handlers — targets listing + launch, without subprocess or host.

Mirrors tmq's tests/test_handlers.py shape: drive handlers directly with an
in-memory settings object and assert the reply / error classification. The
launch path is exercised with ``launch.launch`` mocked so no real aoe daemon
is spawned.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from aoe_fleet import handlers
from aoe_fleet.launch import LaunchError
from aoe_fleet.registry import TargetEntry


def _settings(registry_path: str = "") -> handlers.Settings:
    return handlers.Settings(registry_path=registry_path)


def _local_target(**overrides) -> TargetEntry:
    base = {"name": "home-portal", "host": "local", "dir": "/root/projects/home-portal", "harness": "pi", "model": "", "opening_skill": ""}
    base.update(overrides)
    return TargetEntry(**base)


def test_targets_human_format_lists_columns():
    result = handlers.handle_targets({"args": {}}, settings=_settings())
    assert result["count"] >= 20
    text = result["text"]
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


# ── launch ──────────────────────────────────────────────────────────────


def test_launch_unknown_target_is_user_error():
    with pytest.raises(handlers.FleetCommandError) as excinfo:
        handlers.handle_launch({"args": {"target": "no-such-target"}}, settings=_settings())
    assert "no-such-target" in str(excinfo.value)


def test_launch_missing_target_is_user_error():
    with pytest.raises(handlers.FleetCommandError):
        handlers.handle_launch({"args": {}}, settings=_settings())


def test_launch_nonlocal_host_is_user_error():
    with mock.patch.object(handlers, "load_registry", return_value={"remote": _local_target(name="remote", host="10.89.97.50")}):
        with pytest.raises(handlers.FleetCommandError) as excinfo:
            handlers.handle_launch({"args": {"target": "remote"}}, settings=_settings())
        assert "blocked on upstream" in str(excinfo.value)


def test_launch_success_returns_reply_shape():
    fake = mock.Mock()
    fake.to_reply.return_value = {"session_name": "home-portal", "action": "created"}
    with mock.patch.object(handlers, "load_registry", return_value={"home-portal": _local_target()}):
        with mock.patch.object(handlers.launch_mod, "launch", return_value=fake):
            result = handlers.handle_launch({"args": {"target": "home-portal"}}, settings=_settings())
    assert result["session_name"] == "home-portal"
    assert result["action"] == "created"


def test_launch_subprocess_failure_is_external_error():
    with mock.patch.object(handlers, "load_registry", return_value={"home-portal": _local_target()}):
        with mock.patch.object(handlers.launch_mod, "launch", side_effect=LaunchError("aoe add failed")):
            with pytest.raises(handlers.FleetExternalError) as excinfo:
                handlers.handle_launch({"args": {"target": "home-portal"}}, settings=_settings())
    assert "aoe add failed" in str(excinfo.value)
