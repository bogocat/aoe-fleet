"""Tests for the target registry — JSON loading, validation, override shadowing.

Mirrors tmq's test_registry.py shape. A target entry is the record the fleet
re-types by hand today::

    name -> (host, dir, harness, model, opening-skill)

The shipped defaults ship in the package; a user file shadows them. Unlike tmq
(which raises on a bad user overlay), the fleet AC requires a *missing or
malformed* user file to fall back to defaults instead of crashing the worker —
so the user overlay is best-effort: unreadable/unparseable files and invalid
entries are dropped with a warning, never a raise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from aoe_fleet.registry import DEFAULT_USER_PATH, TargetRegistryError, _entry_from, get, load, machine_summary


def test_loads_default_targets():
    targets = load()
    assert "home-portal" in targets
    assert targets["home-portal"].dir == "/root/projects/home-portal"
    assert targets["home-portal"].harness == "pi"
    assert targets["home-portal"].host == "local"
    assert targets["home-portal"].model == ""
    assert targets["home-portal"].opening_skill == ""


def test_name_lookup():
    targets = load()
    entry = get(targets, "home-portal")
    assert entry.name == "home-portal"
    assert entry.dir == "/root/projects/home-portal"


def test_unknown_target_raises():
    targets = load()
    with pytest.raises(TargetRegistryError) as excinfo:
        get(targets, "no-such-target")
    assert "no-such-target" in str(excinfo.value)


def test_user_overlay_shadows_default(tmp_path: Path):
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
    targets = load(str(overlay))
    assert targets["home-portal"].dir == "/custom/home-portal"
    assert targets["home-portal"].harness == "opencode"
    assert targets["home-portal"].model == "opus"
    # Other targets still ship.
    assert "distillery" in targets


def test_empty_user_overlay_is_noop(tmp_path: Path):
    overlay = tmp_path / "empty.json"
    overlay.write_text("", encoding="utf-8")
    targets = load(str(overlay))
    assert targets["home-portal"].dir == "/root/projects/home-portal"


def test_malformed_user_overlay_falls_back_to_defaults(tmp_path: Path):
    overlay = tmp_path / "bad.json"
    overlay.write_text("{ this is not json", encoding="utf-8")
    # Must NOT raise — the AC requires fall-back, not a crash.
    targets = load(str(overlay))
    assert targets["home-portal"].dir == "/root/projects/home-portal"
    assert targets["home-portal"].harness == "pi"


def test_non_object_overlay_falls_back(tmp_path: Path):
    overlay = tmp_path / "array.json"
    overlay.write_text(json.dumps([{"dir": "/x", "harness": "pi"}]), encoding="utf-8")
    targets = load(str(overlay))
    assert targets["home-portal"].harness == "pi"


def test_unreadable_overlay_falls_back(tmp_path: Path):
    # A directory at the overlay path must not crash the worker (OSError path).
    targets = load(str(tmp_path))
    assert targets["home-portal"].dir == "/root/projects/home-portal"


def test_invalid_entry_is_skipped_not_fatal(tmp_path: Path):
    overlay = tmp_path / "mixed.json"
    overlay.write_text(
        json.dumps(
            {
                "broken": {"host": "local", "dir": "/x"},  # missing harness
                "not-an-object": "nope",
                "good": {
                    "host": "local",
                    "dir": "/custom/good",
                    "harness": "pi",
                },
            }
        ),
        encoding="utf-8",
    )
    targets = load(str(overlay))
    assert "broken" not in targets
    assert "not-an-object" not in targets
    assert targets["good"].dir == "/custom/good"


def test_invalid_entry_logs_warning(tmp_path: Path, caplog):
    overlay = tmp_path / "bad.json"
    overlay.write_text(json.dumps({"bad": {"host": "local", "dir": "/x"}}), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="aoe_fleet.registry"):
        load(str(overlay))
    assert any("skipping invalid target entry" in r.message for r in caplog.records)


def test_nonlocal_host_is_accepted_and_stored(tmp_path: Path):
    overlay = tmp_path / "remote.json"
    overlay.write_text(
        json.dumps({"remote-build": {"host": "10.89.97.50", "dir": "/srv/build", "harness": "pi"}}),
        encoding="utf-8",
    )
    targets = load(str(overlay))
    assert targets["remote-build"].host == "10.89.97.50"
    assert targets["remote-build"].is_local is False


def test_whitespace_host_normalized_to_local():
    entry = _entry_from("x", {"dir": "/p", "harness": "pi", "host": "  local  "})
    assert entry.host == "local"
    assert entry.is_local is True


def test_unknown_field_is_rejected():
    with pytest.raises(TargetRegistryError) as excinfo:
        _entry_from("x", {"host": "local", "dir": "/p", "harness": "pi", "active": True})
    assert "active" in str(excinfo.value)


def test_nonstring_dir_is_rejected():
    with pytest.raises(TargetRegistryError) as excinfo:
        _entry_from("x", {"dir": None, "harness": "pi"})
    assert "dir" in str(excinfo.value)


def test_nonstring_int_dir_is_rejected():
    with pytest.raises(TargetRegistryError) as excinfo:
        _entry_from("x", {"dir": 42, "harness": "pi"})
    assert "dir" in str(excinfo.value)


def test_nonstring_harness_is_rejected():
    with pytest.raises(TargetRegistryError) as excinfo:
        _entry_from("x", {"dir": "/p", "harness": ["pi"]})
    assert "harness" in str(excinfo.value)


def test_empty_name_is_rejected():
    with pytest.raises(TargetRegistryError):
        _entry_from("  ", {"dir": "/p", "harness": "pi"})


def test_machine_summary_shape():
    targets = load()
    summary = machine_summary(targets)
    assert isinstance(summary, list)
    first = summary[0]
    assert set(first.keys()) == {"name", "host", "dir", "harness", "model"}


def test_default_user_path_matches_issue():
    assert str(Path.home() / ".config" / "aoe-fleet" / "targets.json") == DEFAULT_USER_PATH
