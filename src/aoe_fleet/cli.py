"""`fleet` CLI: argparse wrapper around the same handlers the worker uses.

Thin by design: the worker and the CLI both call the handler functions in
``aoe_fleet.handlers``, so there's exactly one implementation per command.
The CLI adds stdout formatting and exit codes; the worker adds JSON-RPC
envelopes.

Settings are sourced from environment variables when no setting override is
given (the worker gets them via inline ``params.settings``):

- FLEET_REGISTRY_PATH  — path to a user targets.json overriding shipped defaults
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from aoe_fleet.handlers import HANDLERS, FleetCommandError, FleetExternalError, Settings


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def settings_from_env() -> Settings:
    return Settings(registry_path=_env("FLEET_REGISTRY_PATH"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleet", description="bogocat.fleet — pinned launch targets over the aoe substrate")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("targets", help="List the target registry (name, host, dir, harness, model)")
    return p


def _emit(handler_key: str, params: dict[str, Any], settings: Settings) -> dict[str, Any]:
    handler = HANDLERS[handler_key]
    try:
        return handler(params, settings=settings)
    except FleetCommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    except FleetExternalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(3)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings_from_env()

    if args.command == "targets":
        result = _emit("targets", {"args": {"format": "human"}}, settings)
        print(result["text"])
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
