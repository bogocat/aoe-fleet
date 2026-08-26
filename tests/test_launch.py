"""Tests for the launch path: aoe argv, host guard, idempotence, duplicate surfacing.

Mirrors tmq's test_spawn.py shape: drive ``launch()`` with the ``_run``
subprocess boundary mocked so no real aoe daemon or agent is spawned.
"""

from __future__ import annotations

from unittest import mock

import pytest

from aoe_fleet import launch
from aoe_fleet.launch import HostBlockedError, LaunchError, TargetEntry, build_add_argv
from aoe_fleet.launch import launch as launch_top


def _entry(**overrides) -> TargetEntry:
    base = {"name": "home-portal", "host": "local", "dir": "/root/projects/home-portal", "harness": "pi", "model": "", "opening_skill": ""}
    base.update(overrides)
    return TargetEntry(**base)


# ── build_add_argv ──────────────────────────────────────────────────────


def test_build_add_argv_no_model():
    argv = build_add_argv(_entry())
    assert argv == ["aoe", "add", "/root/projects/home-portal", "-t", "home-portal", "--tool", "pi"]


def test_build_add_argv_forwards_model():
    argv = build_add_argv(_entry(model="kimi-k3"))
    assert argv == [
        "aoe",
        "add",
        "/root/projects/home-portal",
        "-t",
        "home-portal",
        "--tool",
        "pi",
        "--model",
        "kimi-k3",
    ]


def test_build_add_argv_never_uses_cmd_override():
    # The issue forbids --cmd-override; the harness is the wrapper surface.
    argv = build_add_argv(_entry(harness="pi-k3", model="kimi-k3"))
    assert "--cmd-override" not in argv
    assert argv[argv.index("--tool") + 1] == "pi-k3"


# ── host guard ──────────────────────────────────────────────────────────


def test_nonlocal_host_is_blocked():
    with pytest.raises(HostBlockedError) as excinfo:
        launch_top(_entry(host="10.89.97.50"))
    msg = str(excinfo.value)
    assert "blocked on upstream" in msg
    assert "#3545" in msg or "3545" in msg


def test_local_host_passes_guard():
    # "local" and "" are both local; neither should raise HostBlockedError.
    with mock.patch.object(launch, "session_exists", return_value=None):
        with mock.patch.object(launch, "_run", return_value=""):
            result = launch_top(_entry(host="local"))
            assert result.action == "created"


# ── fresh launch ────────────────────────────────────────────────────────


def test_fresh_launch_adds_then_starts():
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return ""

    with mock.patch.object(launch, "session_exists", return_value=None):
        with mock.patch.object(launch, "_run", side_effect=fake_run):
            result = launch_top(_entry(model="kimi-k3"))
    assert result.action == "created"
    assert result.session_name == "home-portal"
    assert result.cwd == "/root/projects/home-portal"
    assert result.harness == "pi"
    assert result.model == "kimi-k3"
    add_calls = [c for c in calls if c[:2] == ["aoe", "add"]]
    assert len(add_calls) == 1
    assert add_calls[0] == build_add_argv(_entry(model="kimi-k3"))
    assert ["aoe", "session", "start", "home-portal"] in calls


# ── idempotence ─────────────────────────────────────────────────────────


def test_existing_running_session_attaches_without_add():
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return ""

    with mock.patch.object(
        launch,
        "session_exists",
        return_value={"id": "abc", "status": "running", "state": "live"},
    ):
        with mock.patch.object(launch, "_run", side_effect=fake_run):
            result = launch_top(_entry())
    assert result.action == "attached"
    assert result.status == "running"
    assert not any(c[:2] == ["aoe", "add"] for c in calls), "existing session must not be re-added"


def test_stopped_session_is_started_not_readded():
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return ""

    with mock.patch.object(
        launch,
        "session_exists",
        return_value={"id": "abc", "status": "stopped", "state": "live"},
    ):
        with mock.patch.object(launch, "_run", side_effect=fake_run):
            result = launch_top(_entry())
    assert result.action == "started"
    assert ["aoe", "session", "start", "home-portal"] in calls
    assert not any(c[:2] == ["aoe", "add"] for c in calls)


# ── duplicate surfacing ─────────────────────────────────────────────────


def test_duplicate_add_is_surfaced_cleanly():
    def fake_run(argv, **kwargs):
        if argv[:2] == ["aoe", "add"]:
            raise LaunchError("aoe add failed: Session already exists with same title and path: home-portal")
        return ""

    with mock.patch.object(launch, "session_exists", return_value=None):
        with mock.patch.object(launch, "_run", side_effect=fake_run):
            with pytest.raises(LaunchError) as excinfo:
                launch_top(_entry())
    msg = str(excinfo.value)
    assert "already exists" in msg
    assert "home-portal" in msg
    assert "attach" in msg  # actionable hint, not the raw aoe error
