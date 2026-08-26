"""Target launch: turn one registry entry into a running aoe session.

``fleet launch <name>``:

1. Resolve the target (handler does this; ``launch`` receives the entry).
2. Reject a non-local ``host`` — remote targets are gated on upstream
   agent-of-empires#3545/#3546 (transport works, but turn-completion detection
   and session-id discovery are host-local). Fail loudly, never launch a
   session whose status will never resolve.
3. Idempotence: if ``aoe session show <name> --json`` already resolves, the
   session exists — report it (attach), or start it if stopped, instead of
   re-adding. A race that slips past the pre-check is caught by the
   ``already exists`` marker on ``aoe add`` and surfaced cleanly.
4. ``aoe add <dir> -t <name> --tool <harness> [--model <model>]`` then
   ``aoe session start <name>``.

Harness maps to aoe's agent registry: a built-in tool (``pi``/``claude``/
``opencode``/``codex``) or a custom agent defined under
``[session.custom_agents]``. A target that needs a model/account/host wrapper
names that custom agent as its harness (with ``[session.agent_detect_as]`` for
status detection) — we never use ``--cmd-override``. ``model`` is forwarded via
``--model`` (meaningful for the structured view; inert for the terminal view).

The module is pure-Python with ``_run`` as the only subprocess boundary, so the
handlers can test the whole launch path without spawning a real aoe daemon.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from aoe_fleet.registry import TargetEntry

# agent-of-empires#3224: `aoe add` over a duplicate (title, path) prints
# "Session already exists..." and exits non-zero. This marker is how we detect
# the race that slipped past the pre-check.
DUPLICATE_MARKER = "already exists"


class LaunchError(RuntimeError):
    """Launch failed; the handler decides whether to surface as user or external."""


class HostBlockedError(LaunchError):
    """A non-local host was requested; remote launch is gated on upstream."""


@dataclass(frozen=True)
class LaunchResult:
    session_name: str
    cwd: str
    harness: str
    model: str
    action: str  # "created" | "attached" | "started"
    status: str  # aoe runtime status ("running"/"idle"/"stopped"/"waiting"), "" if unknown

    def to_reply(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "cwd": self.cwd,
            "harness": self.harness,
            "model": self.model,
            "action": self.action,
            "status": self.status,
        }


def _run(argv: list[str], *, check: bool = True, timeout: float = 30.0) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)
    except FileNotFoundError as exc:
        raise LaunchError(f"{argv[0]!r} not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LaunchError(f"`{' '.join(argv)}` timed out after {timeout}s") from exc
    if check and proc.returncode != 0:
        snippet = proc.stderr.strip().splitlines()[:3] or [proc.stdout[:200]]
        raise LaunchError(f"`{' '.join(argv)}` exited {proc.returncode}: {' | '.join(snippet)}")
    return proc.stdout


def build_add_argv(entry: TargetEntry) -> list[str]:
    """Construct the ``aoe add`` argv for a target. Never ``--cmd-override``."""
    argv = ["aoe", "add", entry.dir, "-t", entry.name, "--tool", entry.harness]
    if entry.model:
        argv += ["--model", entry.model]
    return argv


def session_exists(name: str) -> dict[str, Any] | None:
    """Return the session record if it exists, else None.

    None means "no session" — ``aoe session show`` failed or returned
    unparseable output. A non-None dict means the session is registered and we
    must not re-add it.
    """
    try:
        out = _run(["aoe", "session", "show", name, "--json"])
    except LaunchError:
        return None
    try:
        parsed = json.loads(out)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _surface_duplicate(name: str, exc: LaunchError) -> LaunchError:
    if DUPLICATE_MARKER in str(exc):
        return LaunchError(
            f"session {name!r} already exists (aoe reported a duplicate title/path); "
            f"attach with `aoe session attach {name}` or remove with `aoe remove {name}` first"
        )
    return exc


def launch(entry: TargetEntry) -> LaunchResult:
    if not entry.is_local:
        raise HostBlockedError(
            f"target {entry.name!r} has non-local host {entry.host!r}; remote launch is "
            "blocked on upstream agent-of-empires#3545/#3546"
        )

    existing = session_exists(entry.name)
    if existing is not None:
        status = str(existing.get("status") or existing.get("state") or "")
        if status == "stopped":
            _run(["aoe", "session", "start", entry.name])
            return LaunchResult(
                session_name=entry.name,
                cwd=entry.dir,
                harness=entry.harness,
                model=entry.model,
                action="started",
                status=status,
            )
        return LaunchResult(
            session_name=entry.name,
            cwd=entry.dir,
            harness=entry.harness,
            model=entry.model,
            action="attached",
            status=status,
        )

    add_argv = build_add_argv(entry)
    try:
        _run(add_argv)
    except LaunchError as exc:
        raise _surface_duplicate(entry.name, exc) from exc
    _run(["aoe", "session", "start", entry.name])
    return LaunchResult(
        session_name=entry.name,
        cwd=entry.dir,
        harness=entry.harness,
        model=entry.model,
        action="created",
        status="running",
    )


def aoe_available() -> bool:
    return shutil.which("aoe") is not None
