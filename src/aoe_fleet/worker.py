"""Tier 1 worker — JSON-RPC 2.0 over ndjson on stdio.

The plugin host (aoe daemon) spawns this process and pipes one JSON-RPC
request per line on stdin; we answer one reply per line on stdout. The worker
is long-lived: each command is a request/response.

Method names. The host namespacing is ``plugin.<id>.<command>``; the handler
dispatches on the trailing segment so we accept both
``plugin.bogocat.fleet.targets`` and ``bogocat.fleet.targets``.

Settings. The worker reads its settings either inline in the first request's
``params.settings``, or via the ``FLEET_REGISTRY_PATH`` env var. A real host
pushes a ``config.get`` call (per the plugin-github contract); we read inline
settings because the fleet worker doesn't poll and doesn't need the outbound
RPC yet.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from aoe_fleet.handlers import (
    ERR_EXTERNAL,
    ERR_INTERNAL,
    ERR_USER,
    HANDLERS,
    FleetCommandError,
    FleetExternalError,
    Settings,
)
from aoe_fleet.registry import DEFAULT_USER_PATH
from aoe_fleet.rpc import MethodNotFoundError


class Worker:
    """The worker itself; ``stdin``/``stdout`` are injectable for tests."""

    def __init__(self, *, stdin: Any, stdout: Any, settings: Settings) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.settings = settings
        self._settings_applied = False

    def _send_result(self, msg_id: Any, result: Any) -> None:
        self.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
        self.stdout.flush()

    def _send_error(self, msg_id: Any, code: int, message: str) -> None:
        self.stdout.write(
            json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}) + "\n"
        )
        self.stdout.flush()

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Call the matching handler or raise a typed error."""
        command = method.rsplit(".", 1)[-1]
        handler = HANDLERS.get(command)
        if handler is None:
            raise MethodNotFoundError(method)
        return handler(params, settings=self.settings)

    def process_line(self, line: str) -> None:
        """Read one request, dispatch, write one response."""
        line = (line or "").strip()
        if not line:
            return
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(request, dict):
            return
        msg_id = request.get("id")
        if msg_id is None:
            return  # notification: don't reply
        method = str(request.get("method", ""))
        params = request.get("params") or {}
        # Bootstrap: first request may carry inline settings.
        if isinstance(params, dict) and params.get("settings") and not self._settings_applied:
            inline = params["settings"]
            if isinstance(inline, dict):
                self.settings = Settings.from_dict(inline)
                self._settings_applied = True
        try:
            result = self.dispatch(method, params)
        except MethodNotFoundError as exc:
            self._send_error(msg_id, -32601, f"unknown method {exc!s}")
            return
        except FleetCommandError as exc:
            self._send_error(msg_id, ERR_USER, str(exc))
            return
        except FleetExternalError as exc:
            self._send_error(msg_id, ERR_EXTERNAL, str(exc))
            return
        except Exception as exc:
            self._send_error(msg_id, ERR_INTERNAL, str(exc))
            return
        self._send_result(msg_id, result)

    def run(self) -> None:
        """Drive the loop until EOF."""
        for raw in self.stdin:
            self.process_line(raw)


def _bootstrap_settings() -> Settings:
    return Settings(
        registry_path=os.environ.get("FLEET_REGISTRY_PATH", DEFAULT_USER_PATH) or DEFAULT_USER_PATH
    )


def main(stdin: Any = None, stdout: Any = None) -> None:
    """Entry point: spawn a Worker and run it until EOF."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    Worker(stdin=stdin, stdout=stdout, settings=_bootstrap_settings()).run()


if __name__ == "__main__":
    main()
