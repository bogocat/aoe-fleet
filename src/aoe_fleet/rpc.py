"""JSON-RPC error code + the MethodNotFoundError sentinel.

The worker maps ``MethodNotFoundError`` to ``-32601``; the user/external/internal
taxonomy (``-32001``/``-32002``/``-32603``) lives in ``handlers.py`` where the
corresponding exceptions are defined. No response builders live here — the
worker emits its envelopes inline so the error mapping stays in one place.
"""

from __future__ import annotations

ERR_METHOD_NOT_FOUND = -32601


class MethodNotFoundError(LookupError):
    """Raised when the worker has no handler for a requested method."""
