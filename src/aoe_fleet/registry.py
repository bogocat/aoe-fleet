"""Target registry: pinned launch targets.

A target is the record the fleet re-types by hand today::

    target = (name, host, dir, harness, model, opening-skill)

The shipped defaults live at ``aoe_fleet/data/default_targets.json`` (frozen by
the package). A user file shadows them; user wins on key collision. The
operator's default overlay path is ``DEFAULT_USER_PATH``
(``~/.config/aoe-fleet/targets.json``) — the CLI/worker resolve that path when
no explicit override is configured; ``load("")`` means "no overlay".

Unlike tmq's registry (which raises on a bad overlay so a typo is loud), the
fleet AC requires a *missing or malformed* user file to fall back to defaults
instead of crashing the worker. So the user overlay is best-effort: an
unreadable/unparseable file falls back to defaults entirely, and an invalid
entry is skipped (with a warning) while valid entries still apply. Only the
shipped defaults are validated strictly — a bad entry there is a package bug
and raises.

Validation rejects unknown keys, non-string fields, missing required fields
(``dir``, ``harness``), and empty/whitespace-only ``dir``/``harness``. ``host``
defaults to ``"local"`` (whitespace-trimmed); ``model`` and ``opening-skill``
default to ``""``. A non-local ``host`` is *accepted and stored* here —
rejection happens at launch (Child D, blocked on upstream #3545/#3546).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("aoe_fleet.registry")

# The operator's default overlay path, per the issue: a user file here shadows
# the shipped defaults. Callers (CLI/worker) resolve this when no explicit
# path is configured; `load("")` itself means "no overlay".
DEFAULT_USER_PATH = str(Path.home() / ".config" / "aoe-fleet" / "targets.json")

# The only host values that count as local. Anything else (an IP, hostname,
# ssh alias) is a remote target and rejected at launch until upstream lands.
# Deliberately strict: "localhost"/"127.0.0.1" are NOT in the whitelist — a
# target should say "local", and a stray hostname should fail loudly, not
# silently launch something whose status will never resolve.
LOCAL_HOSTS: frozenset[str] = frozenset({"", "local"})


class TargetRegistryError(ValueError):
    """Bad target entry: unknown name, missing required field, or invalid shape."""


@dataclass(frozen=True)
class TargetEntry:
    name: str
    host: str
    dir: str
    harness: str
    model: str
    opening_skill: str

    @property
    def is_local(self) -> bool:
        return (self.host or "").strip().lower() in LOCAL_HOSTS


def _str_field(name: str, raw: dict[str, Any], field: str, default: str) -> str:
    """Extract a required-string field, rejecting non-string values.

    A missing or explicit ``null`` value yields ``default``; any present
    non-string (int, bool, list, object) raises — silently ``str()``-coercing
    ``null``→``"None"`` or ``[1,2]``→``"[1, 2]"`` would land a bogus path in
    the registry and explode at launch with no breadcrumb back to the overlay.
    """
    if field not in raw or raw[field] is None:
        return default
    val = raw[field]
    if not isinstance(val, str):
        raise TargetRegistryError(f"{name!r}: {field} must be a string, got {type(val).__name__}")
    return val


def _entry_from(name: str, raw: dict[str, Any]) -> TargetEntry:
    if not isinstance(raw, dict):
        raise TargetRegistryError(f"{name!r}: entry must be an object, got {type(raw).__name__}")
    if not name or not name.strip():
        raise TargetRegistryError("target name must not be empty")
    missing = {"dir", "harness"} - raw.keys()
    if missing:
        raise TargetRegistryError(f"{name!r}: missing required field(s): {', '.join(sorted(missing))}")

    dir_ = _str_field(name, raw, "dir", "")
    harness = _str_field(name, raw, "harness", "")
    host = _str_field(name, raw, "host", "local").strip() or "local"
    model = _str_field(name, raw, "model", "")
    opening_skill = _str_field(name, raw, "opening-skill", "").strip()

    if not dir_.strip():
        raise TargetRegistryError(f"{name!r}: dir is empty")
    if not harness.strip():
        raise TargetRegistryError(f"{name!r}: harness is empty")

    # Drop unknown keys loudly: a stale field here is almost always a typo
    # the operator wanted us to act on. The user overlay catches this
    # per-entry and skips instead of raising (see _user_overlay).
    allowed = {"host", "dir", "harness", "model", "opening-skill"}
    extras = set(raw.keys()) - allowed
    if extras:
        raise TargetRegistryError(f"{name!r}: unknown field(s): {', '.join(sorted(extras))}")
    return TargetEntry(name=name, host=host, dir=dir_, harness=harness, model=model, opening_skill=opening_skill)


def _shipped_default() -> dict[str, TargetEntry]:
    """Read the frozen default set shipped with the package."""
    raw = resources.files("aoe_fleet.data").joinpath("default_targets.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TargetRegistryError(f"shipped targets must be an object, got {type(parsed).__name__}")
    return {name: _entry_from(name, entry) for name, entry in parsed.items()}


def _try_entry(name: str, raw: Any) -> TargetEntry | None:
    """Build one overlay entry; return None (with a warning) on validation failure."""
    try:
        return _entry_from(name, raw)
    except TargetRegistryError as exc:
        LOGGER.warning("skipping invalid target entry: %s", exc)
        return None


def _user_overlay(path: str) -> dict[str, TargetEntry]:
    """Read the user overlay, best-effort: never raise on a bad file.

    - missing / empty path -> no overlay
    - unreadable (missing, permission, is-a-directory, non-UTF-8) -> full
      fallback to defaults
    - unparseable JSON or non-object -> full fallback to defaults
    - an invalid entry -> skipped (warning), other valid entries still apply
    """
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            body = f.read().strip()
    except (OSError, ValueError) as exc:
        LOGGER.warning("user targets file %r unreadable (%s); falling back to shipped defaults", path, exc)
        return {}
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except ValueError as exc:
        LOGGER.warning("user targets file %r is not valid JSON (%s); falling back to shipped defaults", path, exc)
        return {}
    if not isinstance(parsed, dict):
        LOGGER.warning(
            "user targets file %r must be a JSON object, got %s; falling back to shipped defaults",
            path,
            type(parsed).__name__,
        )
        return {}
    overlay: dict[str, TargetEntry] = {}
    for name, entry in parsed.items():
        built = _try_entry(name, entry)
        if built is not None:
            overlay[name] = built
    return overlay


def load(registry_path: str = "") -> dict[str, TargetEntry]:
    """Compose shipped defaults + user overlay. User wins on key collision.

    ``registry_path=""`` means "no user overlay" (shipped defaults only). The
    CLI/worker resolve the operator's default overlay path themselves via
    ``DEFAULT_USER_PATH`` when no explicit path is configured.
    """
    targets = _shipped_default()
    targets.update(_user_overlay(registry_path))
    return targets


def get(targets: dict[str, TargetEntry], name: str) -> TargetEntry:
    """Look up by target name; raise TargetRegistryError for unknown."""
    try:
        return targets[name]
    except KeyError as exc:
        raise TargetRegistryError(f"unknown target {name!r}; known: {', '.join(sorted(targets))}") from exc


def machine_summary(targets: dict[str, TargetEntry]) -> list[dict[str, Any]]:
    """Stable, machine-readable dump for `fleet targets --machine`.

    Deliberately five fields (name, host, dir, harness, model) — the AC's
    listing columns. ``opening_skill`` is stored on the entry but not a listing
    column, so it is omitted here rather than round-tripped.
    """
    return [
        {"name": t.name, "host": t.host, "dir": t.dir, "harness": t.harness, "model": t.model}
        for t in (targets[k] for k in sorted(targets))
    ]
