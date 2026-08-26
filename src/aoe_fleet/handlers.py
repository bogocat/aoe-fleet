"""Worker handlers — the ``plugin.bogocat.fleet.<cmd>`` methods.

Each handler returns a dict that the worker wraps in a JSON-RPC ``result``
reply. Failure modes raise one of:

- ``FleetCommandError`` for user-facing input errors (unknown target, non-local
  host). The worker translates these to JSON-RPC ``error`` replies with a
  stable code (``-32001``) so the UI can render the actionable hint.
- ``FleetExternalError`` for subprocess failures (aoe add/start/show). Code
  ``-32002``; the operator should consult stderr.

Settings (``registry_path``) are passed in by the worker via the ``settings``
dict; tests construct this directly. The registry_path setting points at the
user overlay file; empty/unset = shipped defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aoe_fleet.registry import load as load_registry
from aoe_fleet.registry import machine_summary

ERR_USER = -32001
ERR_EXTERNAL = -32002
ERR_INTERNAL = -32603


class FleetCommandError(Exception):
    """Bad input from the operator (unknown target, non-local host)."""


class FleetExternalError(Exception):
    """A subprocess call failed in a way the operator should see."""


@dataclass(frozen=True)
class Settings:
    registry_path: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        v = raw.get("registry_path", "")
        return cls(registry_path=str(v) if v is not None else "")


def handle_targets(params: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    targets = load_registry(settings.registry_path)
    fmt = str((params.get("args") or {}).get("format", "human"))
    if fmt == "machine":
        return {"targets": machine_summary(targets)}
    lines = ["name host dir harness model"]
    lines.extend(f"{t.name} {t.host} {t.dir} {t.harness} {t.model}" for t in (targets[k] for k in sorted(targets)))
    return {"text": "\n".join(lines), "count": len(targets)}


HANDLERS: dict[str, Any] = {
    "targets": handle_targets,
}


def register_handlers() -> dict[str, Any]:
    """Public accessor for the worker; tests can drive this directly."""
    return HANDLERS
