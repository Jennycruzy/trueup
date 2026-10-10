"""What the fake sends back for one request, plus the facts the truth log keeps."""

from __future__ import annotations

import itertools
import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Reply:
    status: int
    body: bytes
    content_type: str = "application/json"
    # Write the body, then drop the connection before the declared length.
    cut: bool = False
    # Truth facts about this reply.
    response_id: str | None = None
    outcome: str = "complete"  # complete, failed, incomplete, error_event, cut, http_error
    usage: dict[str, int] | None = None  # None means the fake sent no usage
    finish: list[str | None] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)

    def facts(self) -> dict[str, Any]:
        return {
            "status_code": self.status,
            "response_id": self.response_id,
            "outcome": self.outcome,
            "usage": dict(self.usage) if self.usage is not None else None,
            "usage_sent": self.usage is not None,
            "finish": list(self.finish),
            "tool_calls": [dict(t) for t in self.tool_calls],
            "text": list(self.text),
        }


class Ids:
    """Ids unique per call and per server instance.

    Reusing a response id across calls makes some libraries treat the second
    span as a duplicate and drop it, so every id carries a per-server token and
    a counter.
    """

    def __init__(self) -> None:
        self._token = secrets.token_hex(4)
        self._count = itertools.count(1)
        self._lock = threading.Lock()

    def new(self, prefix: str) -> str:
        with self._lock:
            n = next(self._count)
        return f"{prefix}{self._token}{n:04d}"


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


def json_reply(status: int, obj: Any, **kw: Any) -> Reply:
    return Reply(status=status, body=dumps(obj), **kw)


def sse(data: Any, event: str | None = None) -> bytes:
    head = f"event: {event}\n" if event else ""
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    return f"{head}data: {payload}\n\n".encode()


def stream_reply(parts: list[bytes], **kw: Any) -> Reply:
    return Reply(status=200, body=b"".join(parts), content_type="text/event-stream", **kw)
